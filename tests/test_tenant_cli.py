import json
from pathlib import Path
from io import BytesIO
import tarfile
from types import SimpleNamespace
from contextlib import contextmanager

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import make_url

from app import create_app
from app.cli import MIGRATIONS
from app.extensions import db
from app.models import Customer, User
from app.tenancy import tenant_operation, tenant_upload_root
from scripts import backup, restore_check


@pytest.fixture
def provision_app(tmp_path):
    path = tmp_path / "tenants.json"
    app = create_app("testing", {
        "TENANT_REGISTRY_FILE": str(path),
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "EMAIL_ENABLED": False,
    })
    app.instance_path = str(tmp_path / "instance")
    yield app
    with app.app_context():
        db.session.remove()
        for engine in set(db.engines.values()) | set(app.extensions["tenancy"].engines.values()):
            engine.dispose()


def provision(app, slug, admin=False):
    args = ["tenant", "create", slug, "--domain", f"{slug}.example.test",
            "--settings", json.dumps({"BUSINESS_NAME": slug.title(), "ENABLE_GALLERY": True})]
    if admin:
        args += ["--admin-email", "admin@example.test", "--admin-password", f"{slug}-password"]
    result = app.test_cli_runner().invoke(args=args)
    assert result.exit_code == 0, result.output + repr(result.exception)


def test_provisioning_migrates_two_tenants_and_admin_logins_are_isolated(provision_app):
    app = provision_app
    provision(app, "alpha", admin=True)
    provision(app, "beta")
    result = app.test_cli_runner().invoke(args=[
        "create-admin", "--tenant", "beta", "--email", "admin@example.test", "--password", "beta-password",
    ])
    assert result.exit_code == 0, result.output + repr(result.exception)
    head = ScriptDirectory(MIGRATIONS).get_current_head()
    for slug in ("alpha", "beta"):
        with app.app_context(), tenant_operation(slug):
            assert User.query.one().id == 1
            assert db.session.execute(text("select version_num from alembic_version")).scalar_one() == head
            assert set(db.metadata.tables) <= set(inspect(app.extensions["tenancy"].engines[slug]).get_table_names())
            inspector = inspect(app.extensions["tenancy"].engines[slug])
            for name, table in db.metadata.tables.items():
                assert set(table.columns.keys()) <= {column["name"] for column in inspector.get_columns(name)}
        root = Path(app.instance_path) / "tenants" / slug / "uploads"
        assert all((root / category).is_dir() for category in ("quote_requests", "customers", "gallery"))
    client = app.test_client()
    for slug in ("alpha", "beta", "alpha"):
        response = client.post("/auth/login", base_url=f"http://{slug}.example.test", data={
            "email": "admin@example.test", "password": f"{slug}-password",
        })
        assert response.status_code == 302
        with client.session_transaction(base_url=f"http://{slug}.example.test") as session:
            assert session["_user_id"] == f"{slug}:1"
    with client.session_transaction(base_url="http://beta.example.test") as session:
        session["_user_id"] = "alpha:1"
    assert client.get("/admin/", base_url="http://beta.example.test").status_code == 302
    listed = app.test_cli_runner().invoke(args=["tenant", "list"])
    assert "alpha.example.test" in listed.output and "beta.example.test" in listed.output
    assert "password" not in listed.output and "sqlite" not in listed.output


def test_registry_survives_a_fresh_app_and_unknown_hosts_stay_closed(provision_app):
    provision(provision_app, "alpha", admin=True)
    restarted = create_app("testing", {
        "TENANT_REGISTRY_FILE": provision_app.config["TENANT_REGISTRY_FILE"],
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    restarted.instance_path = provision_app.instance_path
    try:
        client = restarted.test_client()
        assert client.get("/", base_url="http://alpha.example.test").status_code == 200
        assert client.get("/", base_url="http://unknown.example.test").status_code == 404
        response = client.post("/auth/login", base_url="http://alpha.example.test", data={
            "email": "admin@example.test", "password": "alpha-password",
        })
        assert response.status_code == 302
        with client.session_transaction(base_url="http://alpha.example.test") as session:
            assert session["_user_id"] == "alpha:1"
    finally:
        with restarted.app_context():
            for engine in set(db.engines.values()) | set(restarted.extensions["tenancy"].engines.values()):
                engine.dispose()


def test_targeted_commands_and_migrations_leave_beta_unchanged(provision_app):
    app = provision_app
    provision(app, "alpha", admin=True)
    provision(app, "beta", admin=True)
    beta = app.extensions["tenancy"].engines["beta"]
    statements = []
    event.listen(beta, "before_cursor_execute", lambda *args: statements.append(args[2]))
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-dev-admin", "--tenant", "alpha", "--email", "dev@alpha.test"])
    assert result.exit_code == 0, result.output + repr(result.exception)
    # A real downgrade/upgrade, not a no-op, proves Alembic selected alpha.
    result = runner.invoke(args=["db", "-x", "tenant=alpha", "downgrade", "t3u4v5w6x7y8"])
    assert result.exit_code == 0, result.output + repr(result.exception)
    with app.app_context(), tenant_operation("alpha"):
        columns = {column["name"] for column in inspect(db.session.get_bind()).get_columns("quote_requests")}
        assert "draft_quote_amount" not in columns
    result = runner.invoke(args=["tenant", "upgrade", "alpha"])
    assert result.exit_code == 0, result.output + repr(result.exception)
    assert statements == []
    with app.app_context(), tenant_operation("alpha"):
        assert User.query.count() == 2
    with app.app_context(), tenant_operation("beta"):
        assert User.query.count() == 1
        assert db.session.execute(text("select version_num from alembic_version")).scalar_one() == ScriptDirectory(MIGRATIONS).get_current_head()
        assert "draft_quote_amount" in {column["name"] for column in inspect(beta).get_columns("quote_requests")}


@pytest.mark.parametrize("arguments", [
    ["create-admin", "--email", "admin@test.example", "--password", "password"],
    ["create-dev-admin"],
    ["db", "upgrade"],
    ["db", "-x", "tenant=unknown", "upgrade"],
    ["tenant", "upgrade", "unknown"],
])
def test_unscoped_or_unknown_tenant_commands_fail_closed(provision_app, arguments):
    result = provision_app.test_cli_runner().invoke(args=arguments)
    assert result.exit_code != 0
    assert provision_app.extensions["tenancy"].tenants == {}


@pytest.mark.parametrize("arguments", [
    ["alpha", "--domain", "another.example.test"],
    ["beta", "--domain", "www.alpha.example.test"],
    ["../escape", "--domain", "escape.example.test"],
    ["beta", "--domain", "beta.example.test", "--settings", '{"ENABLE_GALLERY":"false"}'],
    ["beta", "--domain", "beta.example.test", "--database-uri", "sqlite:///:memory:"],
])
def test_invalid_provisioning_does_not_publish_or_modify_existing_tenant(provision_app, arguments):
    provision(provision_app, "alpha", admin=True)
    path = Path(provision_app.config["TENANT_REGISTRY_FILE"])
    before = path.read_bytes()
    result = provision_app.test_cli_runner().invoke(args=["tenant", "create", *arguments])
    assert result.exit_code != 0
    assert path.read_bytes() == before
    assert set(provision_app.extensions["tenancy"].tenants) == {"alpha"}
    assert not path.with_name(path.name + ".lock").exists()
    with provision_app.app_context(), tenant_operation("alpha"):
        assert User.query.count() == 1


def test_provisioning_cannot_reuse_another_tenants_database(provision_app):
    provision(provision_app, "alpha", admin=True)
    uri = provision_app.extensions["tenancy"].tenants["alpha"].database_uri
    result = provision_app.test_cli_runner().invoke(args=[
        "tenant", "create", "beta", "--domain", "beta.example.test", "--database-uri", uri,
    ])
    assert result.exit_code != 0 and "dedicated database" in result.output
    assert set(provision_app.extensions["tenancy"].tenants) == {"alpha"}


def test_failed_migration_does_not_publish_a_tenant(provision_app, monkeypatch):
    from app import cli
    def fail_migration(**kwargs):
        raise RuntimeError("simulated migration failure")
    monkeypatch.setattr(cli, "upgrade", fail_migration)
    result = provision_app.test_cli_runner().invoke(args=[
        "tenant", "create", "alpha", "--domain", "alpha.example.test",
    ])
    assert result.exit_code != 0
    assert provision_app.extensions["tenancy"].tenants == {}
    assert not Path(provision_app.config["TENANT_REGISTRY_FILE"]).exists()
    assert provision_app.test_client().get("/", base_url="http://alpha.example.test").status_code == 404


def test_registry_lock_is_not_overwritten(provision_app):
    path = Path(provision_app.config["TENANT_REGISTRY_FILE"])
    lock = path.with_name(path.name + ".lock")
    lock.write_text("another provisioning process", encoding="utf-8")
    result = provision_app.test_cli_runner().invoke(args=[
        "tenant", "create", "alpha", "--domain", "alpha.example.test",
    ])
    assert result.exit_code != 0 and "locked" in result.output
    assert lock.read_text(encoding="utf-8") == "another provisioning process"


def test_tenant_backup_restore_and_retention_are_isolated(provision_app, tmp_path, monkeypatch):
    app = provision_app
    for slug in ("alpha", "beta"):
        provision(app, slug, admin=True)
        with app.app_context(), tenant_operation(slug):
            db.session.add(Customer(primary_name=slug))
            db.session.commit()
            photo = tenant_upload_root() / "customers" / "1" / "same.png"
            photo.parent.mkdir()
            photo.write_bytes(slug.encode())
            (tenant_upload_root().parent / "theme.json").write_text(json.dumps({"slug": slug}), encoding="utf-8")
    monkeypatch.setattr(backup, "operations_app", lambda: app)
    beta_engine = app.extensions["tenancy"].engines["beta"]
    beta_db = Path(beta_engine.url.database)
    before = backup.sha256(beta_db)
    statements = []
    event.listen(beta_engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    output = tmp_path / "backups"
    assert backup.main(["--tenant", "alpha", "--out", str(output), "--keep", "1"]) == 0
    first = restore_check.newest_backup(output / "alpha")
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tenant"] == "alpha" and manifest["row_counts"]["customers"] == 1
    assert (first / "theme.json").read_text(encoding="utf-8") == '{"slug": "alpha"}'
    with tarfile.open(first / "uploads.tar.gz") as archive:
        assert archive.getnames() == ["customers/1/same.png"]
        assert archive.extractfile("customers/1/same.png").read() == b"alpha"
    assert restore_check.main([str(first), "--tenant", "alpha"]) == 0
    assert backup.main(["--tenant", "alpha", "--out", str(output), "--keep", "1"]) == 0
    assert not first.exists()
    assert len(list((output / "alpha").iterdir())) == 1
    assert not (output / "beta").exists()
    assert statements == [] and backup.sha256(beta_db) == before
    beta_root = Path(app.instance_path) / "tenants" / "beta"
    assert (beta_root / "uploads" / "customers" / "1" / "same.png").read_bytes() == b"beta"
    assert (beta_root / "theme.json").read_text(encoding="utf-8") == '{"slug": "beta"}'


def test_wrong_tenant_or_corrupt_backup_is_rejected_before_restore(provision_app, tmp_path, monkeypatch):
    for slug in ("alpha", "beta"):
        provision(provision_app, slug)
    monkeypatch.setattr(backup, "operations_app", lambda: provision_app)
    output = tmp_path / "backups"
    backup.main(["--tenant", "alpha", "--out", str(output)])
    directory = restore_check.newest_backup(output / "alpha")
    with pytest.raises(ValueError, match="different tenant"):
        restore_check.main([str(directory), "--tenant", "beta"])
    (directory / "database.sqlite3").write_bytes(b"corrupt")
    assert restore_check.main([str(directory), "--tenant", "alpha"]) == 1


@pytest.mark.parametrize("name", ["../escape", "/absolute", r"C:\escape", "customers/../escape", "file."])
def test_upload_restore_rejects_malicious_archive_paths(tmp_path, name):
    archive = tmp_path / "uploads.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        member = tarfile.TarInfo(name)
        member.size = 4
        handle.addfile(member, BytesIO(b"data"))
    with pytest.raises(ValueError):
        restore_check.restore_uploads(archive, tmp_path / "scratch", 1)


def test_legacy_default_admin_command_still_targets_the_default_database(app):
    result = app.test_cli_runner().invoke(args=[
        "create-admin", "--email", "legacy@example.test", "--password", "legacy-password",
    ])
    assert result.exit_code == 0, result.output + repr(result.exception)
    with app.app_context():
        assert User.query.filter_by(email="legacy@example.test").one().check_password("legacy-password")


@pytest.mark.parametrize("command", [backup.main, restore_check.main])
def test_backup_helpers_require_tenant_selection_for_explicit_registry(provision_app, monkeypatch, command):
    monkeypatch.setattr(backup, "operations_app", lambda: provision_app)
    with pytest.raises(ValueError, match="--tenant"):
        command([])


def test_postgres_dump_targets_selected_database_and_exported_snapshot(tmp_path, monkeypatch):
    calls = []
    def run(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(backup.subprocess, "run", run)
    backup.dump_database("postgresql://localhost/alpha", tmp_path / "database.dump", "pg_dump", snapshot="snapshot-alpha")
    assert calls[0][-1] == "postgresql://localhost/alpha"
    assert calls[0][calls[0].index("--snapshot") + 1] == "snapshot-alpha"
    assert "--schema=public" in calls[0]


def test_postgres_schema_rewrite_preserves_copy_data_and_string_literals():
    original = (
        "CREATE SCHEMA public;\n"
        "CREATE TABLE public.notes (body text DEFAULT 'public.literal');\n"
        'COPY "public".notes (body) FROM stdin;\n'
        "public.customer-data\n"
        "\\.\n"
        "INSERT INTO public.notes VALUES ('another public.value');\n"
        "SELECT pg_catalog.setval('public.notes_id_seq', 1, true);\n"
        "ALTER TABLE public.notes ALTER COLUMN id SET DEFAULT nextval('public.notes_id_seq'::regclass);\n"
        "INSERT INTO public.notes VALUES ('SET search_path = public');\n"
    )
    rewritten = restore_check.rewrites_schema(original, "restore_check_alpha")
    assert "CREATE SCHEMA public" not in rewritten
    assert "CREATE TABLE restore_check_alpha.notes" in rewritten
    assert "COPY restore_check_alpha.notes" in rewritten
    assert "'public.literal'" in rewritten and "public.customer-data\n" in rewritten
    assert "'another public.value'" in rewritten
    assert "setval('restore_check_alpha.notes_id_seq'" in rewritten
    assert "nextval('restore_check_alpha.notes_id_seq'::regclass)" in rewritten
    assert "'SET search_path = public'" in rewritten


def test_default_backup_and_restore_still_work_without_tenant_flag(app, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "instance_path", str(tmp_path / "instance"))
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(backup, "operations_app", lambda: app)
    output = tmp_path / "backups"
    assert backup.main(["--out", str(output)]) == 0
    directory = restore_check.newest_backup(output)
    assert json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["tenant"] == "default"
    assert restore_check.main([str(directory)]) == 0


@pytest.mark.parametrize("fail_restore", [False, True])
def test_postgres_restore_targets_alpha_and_cleans_only_its_unique_scratch_schema(tmp_path, monkeypatch, fail_restore):
    statements = []
    commands = []
    class ScratchEngine:
        url = make_url("postgresql+psycopg://localhost/alpha")
        @contextmanager
        def begin(self):
            yield self
        def connect(self):
            return self.begin()
        def execute(self, statement):
            sql = str(statement)
            statements.append(sql)
            return SimpleNamespace(scalar_one=lambda: "head" if "version_num" in sql else 1)
    def run(arguments):
        commands.append(arguments)
        if arguments[0] == "psql" and fail_restore:
            raise RuntimeError("simulated PostgreSQL restore failure")
        return SimpleNamespace(stdout="CREATE TABLE public.users (id integer);\n")
    monkeypatch.setattr(restore_check, "run_pg", run)
    monkeypatch.setattr(restore_check, "pg_tool", lambda name: name)
    counts = dict.fromkeys(backup.COUNTED_TABLES, 1) | {"alembic_version": "head"}
    arguments = (tmp_path / "database.dump", ScratchEngine(), tmp_path, counts, fail_restore)
    if fail_restore:
        with pytest.raises(RuntimeError, match="simulated PostgreSQL"):
            restore_check.restore_postgres(*arguments)
    else:
        assert restore_check.restore_postgres(*arguments) == []
    created = next(sql for sql in statements if sql.startswith("CREATE SCHEMA"))
    schema = created.split('"')[1]
    assert schema.startswith("restore_check_") and schema != "public"
    assert f'DROP SCHEMA "{schema}" CASCADE' in statements
    command = next(command for command in commands if command[0] == "psql")
    assert command[command.index("--dbname") + 1] == "postgresql://localhost/alpha"
    assert all("beta" not in sql for sql in statements)


def test_provisioning_checks_redirected_storage_before_running_migrations(provision_app, monkeypatch, tmp_path):
    from app import cli
    original = Path.resolve
    root = Path(provision_app.instance_path) / "tenants" / "alpha" / "uploads"
    called = []
    def redirected(path, *args, **kwargs):
        return tmp_path / "other-tenant" if path == root else original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", redirected)
    monkeypatch.setattr(cli, "upgrade", lambda **kwargs: called.append(True))
    result = provision_app.test_cli_runner().invoke(args=[
        "tenant", "create", "alpha", "--domain", "alpha.example.test",
    ])
    assert result.exit_code != 0 and called == []
    assert not (root.parent / "tenant.sqlite3").exists()
    assert provision_app.extensions["tenancy"].tenants == {}


@pytest.mark.parametrize("arguments", [
    ["create-dev-admin", "--tenant", ""],
    ["db", "-x", "tenant=", "upgrade"],
])
def test_empty_explicit_tenant_does_not_fall_back_to_the_default(app, arguments):
    result = app.test_cli_runner().invoke(args=arguments)
    assert result.exit_code != 0
    with app.app_context():
        assert User.query.count() == 0
