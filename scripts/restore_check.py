"""Verify a backup actually restores.

    python scripts/restore_check.py                  # newest backup in ./backups
    python scripts/restore_check.py backups/<stamp>   # a specific one

An untested backup is a rumour. This script:

  1. checks the manifest and re-computes checksums,
  2. reads the archive table of contents (pg_restore --list),
  3. restores the dump into a throwaway schema next to the live data,
  4. compares row counts against the manifest,
  5. drops the throwaway schema.

It never touches the existing schema. Creating the scratch schema is the only privilege
it needs beyond reading the dump, so it works with a normal application role.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCRATCH_SCHEMA = "restore_check"


def pg_tool(name: str) -> str:
    from scripts.backup import pg_tool as backup_tool

    return backup_tool(name)


def database_url() -> str:
    from scripts.backup import database_url as backup_url

    return backup_url()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def newest_backup(root: Path) -> Path:
    runs = sorted((path for path in root.iterdir() if path.is_dir()), reverse=True)
    if not runs:
        raise SystemExit(f"no backups in {root}")
    return runs[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore a backup into a scratch schema and verify it.")
    parser.add_argument("backup", nargs="?", help="backup directory (default: newest)")
    parser.add_argument("--keep", action="store_true", help="keep the scratch schema")
    args = parser.parse_args(argv)

    import psycopg

    backup_dir = Path(args.backup) if args.backup else newest_backup(REPO_ROOT / "backups")
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"no manifest in {backup_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dump_file = backup_dir / manifest["database"]["file"]
    uploads_file = backup_dir / manifest["uploads"]["file"]
    print(f"backup: {backup_dir}")

    failures: list[str] = []

    for label, path in (("database.dump", dump_file), ("uploads.tar.gz", uploads_file)):
        if not path.exists():
            failures.append(f"{label} missing")
            continue
        expected = manifest.get("uploads" if label.endswith("gz") else "database", {}).get("sha256")
        actual = sha256(path)
        status = "ok" if expected == actual else "CHECKSUM MISMATCH"
        print(f"  {label:15s} {path.stat().st_size / 1024:8.0f} KB  sha256 {status}")
        if expected != actual:
            failures.append(f"{label} checksum mismatch")

    toc = subprocess.run(
        [pg_tool("pg_restore"), "--list", str(dump_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if toc.returncode != 0:
        failures.append(f"pg_restore --list failed: {toc.stderr.strip()[:200]}")
        entries = 0
    else:
        entries = len([line for line in toc.stdout.splitlines() if line and not line.startswith(";")])
    print(f"  archive entries {entries}")

    url = database_url()
    with psycopg.connect(url, connect_timeout=10) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{SCRATCH_SCHEMA}"')

    plain = subprocess.run(
        [pg_tool("pg_restore"), "--no-owner", "--no-acl", "-f", "-", str(dump_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if plain.returncode != 0:
        failures.append(f"pg_restore -f failed: {plain.stderr.strip()[:200]}")
        sql = ""
    else:
        sql = rewrites_schema(plain.stdout, SCRATCH_SCHEMA)

    if sql:
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8") as handle:
            handle.write(sql)
            sql_path = Path(handle.name)
        try:
            restore = subprocess.run(
                [pg_tool("psql"), "--dbname", url, "--quiet", "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-f", str(sql_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if restore.returncode != 0:
                failures.append(f"psql restore failed: {restore.stderr.strip()[:300]}")
        finally:
            sql_path.unlink(missing_ok=True)

    if not failures:
        with psycopg.connect(url, connect_timeout=10) as conn, conn.cursor() as cur:
            print("  restored row counts:")
            for table, expected in manifest.get("row_counts", {}).items():
                if table == "alembic_version":
                    continue
                if not isinstance(expected, int):
                    continue
                cur.execute(f'select count(*) from "{SCRATCH_SCHEMA}"."{table}"')
                actual = cur.fetchone()[0]
                flag = "ok" if actual == expected else f"MISMATCH (backup had {expected})"
                print(f"    {table:22s} {actual:6d}  {flag}")
                if actual != expected:
                    failures.append(f"{table}: restored {actual} rows, backup had {expected}")

            cur.execute(f'select version_num from "{SCRATCH_SCHEMA}".alembic_version')
            revision = cur.fetchone()[0]
            print(f"  alembic revision {revision} (backup: {manifest.get('row_counts', {}).get('alembic_version')})")

    if args.keep:
        print(f"  scratch schema kept: {SCRATCH_SCHEMA}")
    else:
        with psycopg.connect(url, connect_timeout=10) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE')
        print("  scratch schema dropped")

    if failures:
        print("\nRESTORE CHECK FAILED")
        for failure in failures:
            print("  -", failure)
        return 1

    print("\nRESTORE CHECK PASSED")
    return 0


def rewrites_schema(sql: str, schema: str) -> str:
    """Re-point the dump at a scratch schema instead of public."""

    sql = re.sub(r"^CREATE SCHEMA public;.*$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"^ALTER SCHEMA public OWNER.*$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"^COMMENT ON SCHEMA public.*$", "", sql, flags=re.MULTILINE)
    sql = sql.replace("SET search_path = public", f"SET search_path = {schema}")
    sql = sql.replace("public.", f"{schema}.")
    header = f'SET search_path TO "{schema}";\n'
    return header + sql


if __name__ == "__main__":
    raise SystemExit(main())
