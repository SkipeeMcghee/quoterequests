"""Back up one tenant's database, uploads and optional theme into a checked directory.

    python scripts/backup.py                    # back up to ./backups/<timestamp>/
    python scripts/backup.py --out D:\\backups   # choose a destination root
    python scripts/backup.py --keep 7           # prune all but the newest 7
    python scripts/backup.py --tenant alpha     # explicit registries require selection

A backup is only worth anything if it can be restored, so every run also writes a
manifest with checksums, the alembic revision and per-table row counts, and
`scripts/restore_check.py` verifies a directory independently.

PostgreSQL requires pg_dump (set PG_BIN if needed); SQLite uses its native backup API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from contextlib import closing, contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

UPLOADS_DIR = REPO_ROOT / "app" / "static" / "uploads"
COUNTED_TABLES = (
    "quote_requests",
    "customers",
    "appointments",
    "recurring_works",
    "gallery_items",
    "users",
)


def database_url() -> str:
    from app.config import DevelopmentConfig

    url = os.environ.get("DATABASE_URL") or DevelopmentConfig.SQLALCHEMY_DATABASE_URI
    url = url.replace("postgresql+psycopg", "postgresql").replace("postgresql+psycopg2", "postgresql")
    if not url.startswith("postgresql"):
        raise SystemExit("DATABASE_URL is not PostgreSQL; nothing to dump with pg_dump")
    return url


def pg_tool(name: str) -> str:
    override = os.environ.get("PG_BIN")
    # Windows needs the .exe suffix; shutil.which honours PATHEXT but these tools are
    # usually not on PATH, and Path.exists() is literal.
    names = [name, f"{name}.exe"] if os.name == "nt" else [name]
    candidates = []
    if override:
        candidates.extend(Path(override) / candidate for candidate in names)
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    for version in ("18", "17", "16", "15"):
        for candidate in names:
            candidates.append(Path(rf"C:\Program Files\PostgreSQL\{version}\bin") / candidate)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise SystemExit(
        f"{name} not found. Install the PostgreSQL client tools or set PG_BIN to the bin folder."
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_counts(engine) -> dict[str, int | str]:
    with engine.connect() as connection:
        return _row_counts(connection)


def _row_counts(connection) -> dict[str, int | str]:
    from sqlalchemy import inspect, text
    counts: dict[str, int | str] = {}
    tables = set(inspect(connection).get_table_names())
    for table in COUNTED_TABLES:
        counts[table] = connection.execute(text(f'select count(*) from "{table}"')).scalar_one() if table in tables else "missing"
    counts["alembic_version"] = connection.execute(text("select version_num from alembic_version")).scalar_one() if "alembic_version" in tables else "missing"
    return counts


def dump_database(url: str, target: Path, pg_dump: str, *, snapshot: str | None = None) -> None:
    arguments = [pg_dump, "--format=custom", "--schema=public", "--no-owner", "--no-acl", "--file", str(target)]
    if snapshot is not None:
        arguments.extend(["--snapshot", snapshot])
    arguments.append(url)
    result = subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"pg_dump failed: {result.stderr.strip()[:400]}")


def archive_uploads(target: Path, uploads_dir: Path = UPLOADS_DIR) -> tuple[int, int]:
    files = 0
    total_bytes = 0
    with tarfile.open(target, "w:gz") as archive:
        if uploads_dir.exists():
            for path in sorted(uploads_dir.rglob("*")):
                if path.is_symlink() or not path.resolve().is_relative_to(uploads_dir.resolve()):
                    raise SystemExit("Upload archives must not contain redirected paths.")
                if path.is_file():
                    archive.add(path, arcname=path.relative_to(uploads_dir).as_posix(), recursive=False)
                    files += 1
                    total_bytes += path.stat().st_size
    return files, total_bytes


def prune(root: Path, keep: int, tenant_slug: str = "default") -> list[str]:
    runs = sorted((
        path for path in root.iterdir()
        if path.is_dir() and not path.is_symlink()
        and re.fullmatch(r"\d{8}T\d{6}(?:\d{6})?Z", path.name)
        and (path / "manifest.json").is_file()
        and json.loads((path / "manifest.json").read_text(encoding="utf-8")).get("tenant", "default") == tenant_slug
    ), reverse=True)
    removed = []
    for path in runs[keep:]:
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def operations_app():
    from app import create_app
    return create_app()


@contextmanager
def operation_source(slug: str | None):
    from app.extensions import db
    from app.tenancy import get_registry, is_default_tenant, tenant_operation, tenant_upload_root

    app = operations_app()
    try:
        with app.app_context(), tenant_operation(slug) as tenant:
            root = tenant_upload_root()
            theme = Path(app.instance_path) / "theme.json" if is_default_tenant() else root.parent / "theme.json"
            yield tenant, get_registry().engine_for(tenant), root, theme
    finally:
        with app.app_context():
            db.session.remove()
            for engine in set(db.engines.values()) | set(get_registry().engines.values()):
                engine.dispose()


def postgres_url(engine) -> str:
    return engine.url.set(drivername="postgresql").render_as_string(hide_password=False)


def dump_sqlite(engine, target: Path) -> None:
    source = engine.raw_connection()
    try:
        with closing(sqlite3.connect(target)) as destination:
            source.driver_connection.backup(destination)
    finally:
        source.close()


def backup_tenant(root: Path, keep: int, tenant, engine, uploads_dir: Path, theme: Path) -> Path:
    backend = engine.url.get_backend_name()
    if backend not in ("postgresql", "sqlite"):
        raise SystemExit("Backups support PostgreSQL and SQLite only.")
    if root.resolve().is_relative_to(uploads_dir.resolve()):
        raise SystemExit("The backup destination must be outside the upload tree.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = root / stamp
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    db_file = target / ("database.sqlite3" if backend == "sqlite" else "database.dump")
    uploads_file = target / "uploads.tar.gz"
    print(f"backup: {target}")
    if backend == "sqlite":
        dump_sqlite(engine, db_file)
    else:
        from sqlalchemy import text
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            snapshot_id = connection.execute(text("select pg_export_snapshot()")).scalar_one()
            dump_database(postgres_url(engine), db_file, pg_tool("pg_dump"), snapshot=snapshot_id)
            counts = _row_counts(connection)
    files, upload_bytes = archive_uploads(uploads_file, uploads_dir)
    # Counts come from the snapshot, not a live SQLite DB that could change after copying.
    if backend == "sqlite":
        from sqlalchemy import create_engine
        from sqlalchemy.engine import URL
        snapshot = create_engine(URL.create("sqlite", database=str(db_file)))
        try:
            counts = row_counts(snapshot)
        finally:
            snapshot.dispose()
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tenant": tenant.slug, "hosts": list(tenant.hosts),
        "database": {"file": db_file.name, "bytes": db_file.stat().st_size,
                     "sha256": sha256(db_file), "format": "sqlite" if backend == "sqlite" else "pg_dump custom"},
        "uploads": {"file": uploads_file.name, "files": files, "bytes": uploads_file.stat().st_size,
                    "sha256": sha256(uploads_file)},
        "row_counts": counts,
    }
    if theme.exists():
        if theme.is_symlink() or theme.resolve() != theme.absolute():
            raise SystemExit("Theme backup must not redirect outside tenant storage.")
        copied = target / "theme.json"
        shutil.copyfile(theme, copied)
        manifest["theme"] = {"file": copied.name, "sha256": sha256(copied)}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  database: {db_file.name}; uploads: {files} files, {upload_bytes} bytes")
    if keep:
        prune(root, keep, tenant.slug)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the database and uploads.")
    parser.add_argument("--out", default=str(REPO_ROOT / "backups"))
    parser.add_argument("--keep", type=int, default=14, help="backups to retain (0 = keep all)")
    parser.add_argument("--tenant", help="Required for explicit tenant registries")
    args = parser.parse_args(argv)

    if args.keep < 0:
        parser.error("--keep cannot be negative.")
    root = Path(args.out).resolve()
    with operation_source(args.tenant) as (tenant, engine, uploads_dir, theme):
        if args.tenant:
            root /= tenant.slug
            if root.resolve() != root:
                raise SystemExit("Tenant backup roots must not redirect through symlinks.")
        backup_tenant(root, args.keep, tenant, engine, uploads_dir, theme)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
