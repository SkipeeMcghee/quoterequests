"""Verify a tenant backup in scratch storage, never restore over live customer data."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backup import operation_source, pg_tool, postgres_url, sha256


def newest_backup(root: Path) -> Path:
    runs = sorted((path for path in root.iterdir() if path.is_dir() and (path / "manifest.json").is_file()), reverse=True)
    if not runs:
        raise SystemExit(f"no backups in {root}")
    return runs[0]


def manifest_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or name != Path(name).name or any(char in name for char in "\\/:"):
        raise ValueError("Invalid backup manifest filename.")
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Backup files must remain inside the backup directory.")
    return path


def restore_uploads(archive_path: Path, destination: Path, expected_files: int) -> None:
    """Extract only regular files/directories, rejecting aliases, links and traversal."""
    files = 0
    names = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            parts = member.name.split("/")
            if (
                not member.name or any(part in ("", ".", "..") or part.endswith((".", " ")) for part in parts)
                or "\\" in member.name or ":" in member.name
                or not (member.isfile() or member.isdir())
                or member.name.casefold() in names
            ):
                raise ValueError("Invalid or redirected path in upload archive.")
            names.add(member.name.casefold())
            path = destination.joinpath(*parts)
            if not path.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Upload archive escapes scratch storage.")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("Upload archive entry has no file content.")
                with source, path.open("wb") as target:
                    shutil.copyfileobj(source, target)
                files += 1
    if files != expected_files:
        raise ValueError("Upload archive file count differs from the manifest.")


def verify_counts(connection, counts: dict, schema: str | None = None) -> list[str]:
    from sqlalchemy import text
    from scripts.backup import COUNTED_TABLES
    if set(counts) != set(COUNTED_TABLES) | {"alembic_version"}:
        raise ValueError("Backup manifest must include all expected row counts and the migration revision.")
    failures = []
    prefix = f'"{schema}".' if schema else ""
    for table, expected in counts.items():
        if table == "alembic_version":
            if expected == "missing":
                continue
            actual = connection.execute(text(f'select version_num from {prefix}"alembic_version"')).scalar_one()
        else:
            if table not in COUNTED_TABLES:
                raise ValueError("Unknown table in backup row counts.")
            if expected == "missing":
                continue
            actual = connection.execute(text(f'select count(*) from {prefix}"{table}"')).scalar_one()
        if actual != expected:
            failures.append(f"{table}: restored {actual!r}, expected {expected!r}")
    return failures


def restore_sqlite(dump: Path, scratch: Path, counts: dict) -> list[str]:
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    restored = scratch / "database.sqlite3"
    with closing(sqlite3.connect(f"{dump.resolve().as_uri()}?mode=ro", uri=True)) as source, closing(sqlite3.connect(restored)) as target:
        source.backup(target)
        if target.execute("pragma integrity_check").fetchone()[0] != "ok":
            return ["SQLite integrity check failed"]
    engine = create_engine(URL.create("sqlite", database=str(restored)))
    try:
        with engine.connect() as connection:
            return verify_counts(connection, counts)
    finally:
        engine.dispose()


def run_pg(arguments: list[str]):
    result = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"PostgreSQL restore tool failed: {result.stderr.strip()[:300]}")
    return result


def restore_postgres(dump: Path, engine, scratch: Path, counts: dict, keep: bool) -> list[str]:
    from sqlalchemy import text
    schema = f"restore_check_{uuid4().hex}"
    url = postgres_url(engine)
    # Parse the dump before creating even scratch database objects.
    run_pg([pg_tool("pg_restore"), "--list", str(dump)])
    plain = run_pg([pg_tool("pg_restore"), "--no-owner", "--no-acl", "-f", "-", str(dump)])
    sql_file = scratch / "restore.sql"
    sql_file.write_text(rewrites_schema(plain.stdout, schema), encoding="utf-8")
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    verified = False
    try:
        run_pg([pg_tool("psql"), "--dbname", url, "--quiet", "--no-psqlrc",
                "-v", "ON_ERROR_STOP=1", "-f", str(sql_file)])
        with engine.connect() as connection:
            failures = verify_counts(connection, counts, schema)
        verified = not failures
        if keep and verified:
            print(f"scratch schema kept: {schema}")
        return failures
    finally:
        if not (keep and verified):
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", nargs="?", help="Backup directory (default: newest for the selected tenant)")
    parser.add_argument("--tenant")
    parser.add_argument("--root", default=str(REPO_ROOT / "backups"), help="Backup root used by backup.py --out")
    parser.add_argument("--keep", action="store_true", help="Keep successfully verified scratch data")
    args = parser.parse_args(argv)

    root = Path(args.root)
    # Validate selection before reading backups or using a slug as a filesystem path.
    with operation_source(args.tenant) as (tenant, _, _, _):
        selected_slug = tenant.slug
        if args.tenant:
            root /= tenant.slug
    backup_dir = Path(args.backup) if args.backup else newest_backup(root)
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("tenant", "default") != selected_slug:
        raise ValueError("Backup belongs to a different tenant; select its --tenant explicitly.")

    paths = {}
    for label in ("database", "uploads", "theme"):
        if label not in manifest:
            if label == "theme":
                continue
            raise ValueError(f"Backup manifest has no {label} entry.")
        entry = manifest[label]
        path = manifest_file(backup_dir, entry["file"])
        if not path.is_file() or sha256(path) != entry["sha256"]:
            print(f"RESTORE CHECK FAILED: {label} checksum mismatch or missing file")
            return 1
        paths[label] = path

    scratch = Path(tempfile.mkdtemp(prefix="tenant-restore-"))
    verified = False
    try:
        restore_uploads(paths["uploads"], scratch / "uploads", manifest["uploads"]["files"])
        if "theme" in paths:
            json.loads(paths["theme"].read_text(encoding="utf-8"))
            shutil.copyfile(paths["theme"], scratch / "theme.json")
        with operation_source(args.tenant) as (_, engine, _, _):
            backend = engine.url.get_backend_name()
            format_name = manifest["database"]["format"]
            if format_name == "sqlite" and backend == "sqlite":
                failures = restore_sqlite(paths["database"], scratch, manifest["row_counts"])
            elif format_name == "pg_dump custom" and backend == "postgresql":
                failures = restore_postgres(paths["database"], engine, scratch, manifest["row_counts"], args.keep)
            else:
                raise ValueError("Backup database format does not match the selected tenant.")
        if failures:
            print("RESTORE CHECK FAILED: " + "; ".join(failures))
            return 1
        verified = True
        print("RESTORE CHECK PASSED")
        if args.keep:
            print(f"scratch files kept: {scratch}")
        return 0
    finally:
        if not (args.keep and verified):
            shutil.rmtree(scratch)


def rewrites_schema(sql: str, schema: str) -> str:
    """Re-point a trusted public-schema pg_dump at a unique scratch schema."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", schema):
        raise ValueError("Invalid scratch schema name.")
    def rewrite_ddl(chunk: str) -> str:
        chunk = re.sub(r"^(?:CREATE SCHEMA public;|ALTER SCHEMA public OWNER|COMMENT ON SCHEMA public).*$", "", chunk, flags=re.MULTILINE)
        def rewrite_sql(value: str) -> str:
            value = value.replace("SET search_path = public", f"SET search_path = {schema}")
            return re.sub(r'(?<![\w$])(?:public|"public")\.', f'{schema}.', value)
        literals = re.compile(r"'(?:''|[^'])*'|\$\$.*?\$\$|\$(?P<tag>[a-zA-Z_]\w*)\$.*?\$(?P=tag)\$", re.DOTALL)
        rewritten = []
        position = 0
        for match in literals.finditer(chunk):
            rewritten.append(rewrite_sql(chunk[position:match.start()]))
            literal = match.group()
            # Sequence identities are SQL object references, not customer text.
            if (
                re.match(r"\s*::(?:pg_catalog\.)?regclass\b", chunk[match.end():])
                or re.search(r"\b(?:setval|nextval|currval)\(\s*$", chunk[:match.start()])
            ):
                literal = re.sub(r"""^'(?:public|"public")\.""", f"'{schema}.", literal)
            rewritten.append(literal)
            position = match.end()
        rewritten.append(rewrite_sql(chunk[position:]))
        return "".join(rewritten)

    output = [f'SET search_path TO "{schema}";\n']
    ddl = []
    copying = False
    for line in sql.splitlines(keepends=True):
        if copying:
            output.append(line)
            if line.rstrip("\r\n") == r"\.":
                copying = False
        else:
            ddl.append(line)
            if re.match(r"^COPY .* FROM stdin;\s*$", line):
                output.append(rewrite_ddl("".join(ddl)))
                ddl.clear()
                copying = True
    output.append(rewrite_ddl("".join(ddl)))
    return "".join(output)


if __name__ == "__main__":
    raise SystemExit(main())
