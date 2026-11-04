"""Back up the database and the uploads folder into one restorable directory.

    python scripts/backup.py                    # back up to ./backups/<timestamp>/
    python scripts/backup.py --out D:\\backups   # choose a destination root
    python scripts/backup.py --keep 7           # prune all but the newest 7

A backup is only worth anything if it can be restored, so every run also writes a
manifest with checksums, the alembic revision and per-table row counts, and
`scripts/restore_check.py` verifies a directory independently.

Requires PostgreSQL client tools (pg_dump). Set PG_BIN if they are not on PATH.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
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


def row_counts(url: str) -> dict[str, int | str]:
    import psycopg

    counts: dict[str, int | str] = {}
    try:
        with psycopg.connect(url, connect_timeout=10) as conn, conn.cursor() as cur:
            for table in COUNTED_TABLES:
                try:
                    cur.execute(f'select count(*) from "{table}"')
                    counts[table] = cur.fetchone()[0]
                except Exception:  # noqa: BLE001 - a missing table is data too
                    conn.rollback()
                    counts[table] = "missing"
            try:
                cur.execute("select version_num from alembic_version")
                counts["alembic_version"] = cur.fetchone()[0]
            except Exception:  # noqa: BLE001
                conn.rollback()
                counts["alembic_version"] = "missing"
    except Exception as exc:  # noqa: BLE001
        counts["error"] = f"{type(exc).__name__}: {exc}".splitlines()[0][:120]
    return counts


def dump_database(url: str, target: Path, pg_dump: str) -> None:
    result = subprocess.run(
        [pg_dump, "--format=custom", "--no-owner", "--no-acl", "--file", str(target), url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"pg_dump failed: {result.stderr.strip()[:400]}")


def archive_uploads(target: Path) -> tuple[int, int]:
    files = 0
    total_bytes = 0
    with tarfile.open(target, "w:gz") as archive:
        if UPLOADS_DIR.exists():
            for path in sorted(UPLOADS_DIR.rglob("*")):
                if path.is_file():
                    archive.add(path, arcname=path.relative_to(UPLOADS_DIR).as_posix())
                    files += 1
                    total_bytes += path.stat().st_size
    return files, total_bytes


def prune(root: Path, keep: int) -> list[str]:
    runs = sorted((path for path in root.iterdir() if path.is_dir()), reverse=True)
    removed = []
    for path in runs[keep:]:
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the database and uploads.")
    parser.add_argument("--out", default=str(REPO_ROOT / "backups"))
    parser.add_argument("--keep", type=int, default=14, help="backups to retain (0 = keep all)")
    args = parser.parse_args(argv)

    url = database_url()
    root = Path(args.out)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = root / stamp
    target.mkdir(parents=True, exist_ok=True)

    pg_dump = pg_tool("pg_dump")
    db_file = target / "database.dump"
    uploads_file = target / "uploads.tar.gz"

    print(f"backup: {target}")
    dump_database(url, db_file, pg_dump)
    print(f"  database.dump  {db_file.stat().st_size / 1024:.0f} KB")

    files, upload_bytes = archive_uploads(uploads_file)
    print(f"  uploads.tar.gz {files} files, {upload_bytes / 1024:.0f} KB")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database": {
            "file": db_file.name,
            "bytes": db_file.stat().st_size,
            "sha256": sha256(db_file),
            "format": "pg_dump custom",
            "pg_dump": pg_dump,
        },
        "uploads": {
            "file": uploads_file.name,
            "files": files,
            "bytes": uploads_file.stat().st_size,
            "sha256": sha256(uploads_file),
        },
        "row_counts": row_counts(url),
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  manifest.json  {manifest['row_counts']}")

    if args.keep:
        removed = prune(root, args.keep)
        if removed:
            print(f"  pruned {len(removed)} old backup(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
