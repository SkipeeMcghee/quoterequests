"""Fast sweep-harness contracts: isolated storage and no real browser/server.

These tests deliberately use build_app rather than repairing its configuration in
the fixture: failures in sweep setup must remain visible as regressions.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from functools import partial
import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

from flask import Flask
from markupsafe import escape
import pytest

import app as app_module
from app.config import Config, DevelopmentConfig, ProductionConfig, TestingConfig
from app.extensions import db
from app.models import GalleryItem, ServiceOption
from app.services import public_pages, themes
from scripts import ui_sweep as sweep


HOME_ORDERS = {
    "local_service_business": ["hero", "services_preview", "service_area", "quote_cta"],
    "specialty_contractor": [
        "hero", "trust_highlights", "gallery_preview", "services_preview", "quote_cta",
    ],
    "minimal_quote_funnel": ["hero", "quote_cta"],
}


@pytest.fixture()
def sweep_app_factory(tmp_path):
    """Never seed the large demo graph or use the developer's instance/database."""
    apps = []

    def factory(site="local_service_business", flags=None):
        root = tmp_path / f"sweep-{len(apps)}"
        root.mkdir()
        database = root / "sweep.sqlite3"
        app = sweep.build_app(root, dict(sweep.PRESETS["all"] if flags is None else flags),
                              database, site)
        apps.append(app)
        sweep.assert_engine_matches(app, database)
        with app.app_context():
            db.create_all()
        return app, root, database

    yield factory
    for app in reversed(apps):
        with app.app_context():
            db.session.remove()
            engines = set(db.engines.values()) | set(app.extensions["tenancy"].engines.values())
            for engine in engines:
                engine.dispose()


def config_class_state():
    return {
        cls: deepcopy({key: value for key, value in vars(cls).items() if key.isupper()})
        for cls in (Config, DevelopmentConfig, TestingConfig, ProductionConfig)
    }


def test_build_app_overrides_hostile_operator_state_before_binding(
    sweep_app_factory, tmp_path, monkeypatch,
):
    operator = tmp_path / "operator-instance"
    operator.mkdir()
    theme_state = operator / "theme.json"
    theme_state.write_text('{"slug": "stormy-morning"}', encoding="utf-8")
    registry = operator / "registry.json"
    registry.write_text("not valid registry JSON", encoding="utf-8")
    operator_db = operator / "operator.sqlite3"
    operator_db.write_bytes(b"operator database must never be opened")
    original_files = {path: path.read_bytes() for path in operator.iterdir()}
    hostile = {
        "SQLALCHEMY_DATABASE_URI": f"sqlite+pysqlite:///{operator_db.as_posix()}",
        "UPLOAD_FOLDER": str(operator / "uploads"),
        "TENANTS": {"broken": {}}, "TENANTS_JSON": "not JSON",
        "TENANT_REGISTRY_FILE": str(registry), "TENANT_ALLOW_DEFAULT": False,
        "SUPERADMIN_PASSWORD": "operator-only", "SUPERADMIN_HOST": "operator.test",
        "SUPERADMIN_PATH": "/operator-only", "SITE_THEME": "stormy-morning",
        "SITE_PRESET": "invalid-kit", "PUBLIC_PAGES_CONFIG": {"unsupported": True},
        "SECRET_KEY": "operator-secret", "WTF_CSRF_ENABLED": False,
        "RECAPTCHA_ENABLED": True, "EMAIL_ENABLED": True, "RATE_LIMIT_ENABLED": True,
        "ERROR_WEBHOOK_URL": "https://operator.test/errors", "TRUST_PROXY": True,
        "CANONICAL_ORIGIN": "https://operator.test", "BUSINESS_NAME": "Operator business",
        "TESTING": True, "DEBUG": True,
        **sweep.PRESETS["off"],
    }
    for cls in (Config, TestingConfig):
        for key, value in hostile.items():
            monkeypatch.setattr(cls, key, deepcopy(value), raising=False)
    constructor = partial(Flask, instance_path=str(operator))
    monkeypatch.setattr(app_module, "Flask", constructor)
    before = config_class_state()

    app, root, database = sweep_app_factory(site="specialty_contractor")

    assert app_module.Flask is constructor
    assert config_class_state() == before
    assert Path(app.instance_path) == (root / "instance").resolve()
    assert Path(app.config["UPLOAD_FOLDER"]) == (root / "uploads").resolve()
    assert app.config["SQLALCHEMY_DATABASE_URI"] == f"sqlite+pysqlite:///{database.resolve().as_posix()}"
    assert app.config["SITE_PRESET"] == "specialty_contractor"
    assert app.config["SITE_THEME"] == themes.DEFAULT_SLUG
    assert app.config["PUBLIC_PAGES_CONFIG"] == sweep.sweep_manifest("specialty_contractor")
    assert app.config["SECRET_KEY"] == "ui-sweep-secret-key"
    assert app.config["WTF_CSRF_ENABLED"] is True
    assert app.config["TENANTS_JSON"] == app.config["TENANT_REGISTRY_FILE"] == ""
    assert app.config["TENANT_ALLOW_DEFAULT"] is True
    assert app.config["SUPERADMIN_PASSWORD"] == app.config["SUPERADMIN_HOST"] == ""
    assert app.config["SUPERADMIN_PATH"] == "/platform/control"
    assert app.config["ERROR_WEBHOOK_URL"] == app.config["CANONICAL_ORIGIN"] == ""
    assert app.config["BUSINESS_NAME"] == sweep.SITECONFIG_PLACEHOLDER
    for key in ("RECAPTCHA_ENABLED", "EMAIL_ENABLED", "RATE_LIMIT_ENABLED", "TRUST_PROXY",
                "TESTING", "DEBUG"):
        assert app.config[key] is False, key
    for key in sweep.PRESETS["all"]:
        assert app.config[key] is True, key
    assert set(app.extensions["tenancy"].tenants) == {"default"}
    with app.app_context():
        assert themes.get_active_slug(app) == themes.DEFAULT_SLUG
        assert Path(db.engine.url.database).resolve() == database.resolve()
    response = app.test_client().get("/", headers={"X-Forwarded-Host": "operator.test"})
    assert response.status_code == 200
    assert "Operator business" not in response.get_data(as_text=True)
    assert app.test_client().get("/platform/control").status_code == 404
    assert {path: path.read_bytes() for path in operator.iterdir()} == original_files
    assert config_class_state() == before


def test_building_multiple_sweeps_does_not_mutate_config_classes_or_share_state(sweep_app_factory):
    before = config_class_state()
    first, first_root, first_db = sweep_app_factory(flags=sweep.PRESETS["off"])
    with first.app_context():
        themes.set_active_slug(first, "stormy-morning")
        db.session.add(ServiceOption(name="Only in first sweep", is_active=True))
        db.session.commit()
    second, second_root, second_db = sweep_app_factory(site="minimal_quote_funnel")
    assert first_root != second_root and first_db != second_db
    assert first.config["ENABLE_SERVICES"] is False
    assert second.config["ENABLE_SERVICES"] is True
    with second.app_context():
        assert themes.get_active_slug(second) == themes.DEFAULT_SLUG
        assert db.session.query(ServiceOption).count() == 0
    with first.app_context():
        assert themes.get_active_slug(first) == "stormy-morning"
        assert db.session.query(ServiceOption).count() == 1
    assert config_class_state() == before


def test_engine_guard_rejects_wrong_database(sweep_app_factory, tmp_path):
    app, _, database = sweep_app_factory()
    sweep.assert_engine_matches(app, database)
    with pytest.raises(RuntimeError, match="sweep app is not pointed at the sweep database"):
        sweep.assert_engine_matches(app, tmp_path / "wrong.sqlite3")


@pytest.mark.parametrize("site", sweep.SITE_PRESETS)
def test_manifest_adds_hidden_page_without_replacing_kit_defaults(site, sweep_app_factory):
    presets_path = sweep.REPO_ROOT / "app/data/site_presets.json"
    original = presets_path.read_bytes()
    builtin = json.loads(original)[site]
    override = sweep.sweep_manifest(site)
    assert set(override) == {"custom_pages"}
    assert override["custom_pages"][:-1] == builtin["custom_pages"]
    hidden = override["custom_pages"][-1]
    assert hidden["slug"] == "sweep-content" and hidden["show_in_nav"] is False
    assert [section["type"] for section in hidden["sections"]] == [
        "text", "feature_cards", "checklist", "faq", "quote_cta",
    ]
    override["custom_pages"][-1]["sections"].clear()
    assert len(sweep.sweep_manifest(site)["custom_pages"][-1]["sections"]) == 5

    app, _, _ = sweep_app_factory(site=site)
    with app.app_context():
        db.session.add_all([
            ServiceOption(name="Sweep service", is_active=True),
            GalleryItem(title="Sweep project", image_path="assets/images/Logowhite.png", is_active=True),
        ])
        db.session.commit()
        manifest = public_pages.get_public_manifest()
        assert [block["type"] for block in manifest["home_blocks"]] == HOME_ORDERS[site]
    response = app.test_client().get("/")
    assert response.status_code == 200
    assert re.findall(r'data-public-block="([^"]+)"', response.get_data(as_text=True)) == HOME_ORDERS[site]
    targets = sweep.collect_routes(app, {}, sweep.PRESETS["all"], public_only=True)
    custom = {target.path: target.expected_status for target in targets
              if target.endpoint == "main.custom_page"}
    assert custom == {f"/p/{page['slug']}": 200 for page in sweep.sweep_manifest(site)["custom_pages"]}
    with app.test_request_context("/"):
        links = {link["url"] for link in public_pages.navigation_links()}
    assert "/p/sweep-content" not in links
    assert ("/p/our-process" in links) is (site == "specialty_contractor")
    assert app.test_client().get("/p/sweep-content").status_code == 200
    assert presets_path.read_bytes() == original


def test_custom_discovery_includes_disabled_and_hidden_pages(sweep_app_factory):
    app, _, _ = sweep_app_factory()
    app.config["PUBLIC_PAGES_CONFIG"] = {"custom_pages": [
        {"slug": "hidden-guide", "title": "Hidden guide", "show_in_nav": False},
        {"slug": "disabled-guide", "title": "Disabled guide", "enabled": False, "show_in_nav": True},
    ]}
    targets = sweep.collect_routes(app, {}, sweep.PRESETS["all"], public_only=True)
    custom = [target for target in targets if target.endpoint == "main.custom_page"]
    assert [(target.path, target.expected_status, target.is_admin) for target in custom] == [
        ("/p/disabled-guide", 404, False), ("/p/hidden-guide", 200, False),
    ]
    client = app.test_client()
    assert client.get("/p/hidden-guide").status_code == 200
    assert client.get("/p/disabled-guide").status_code == 404
    assert client.get("/p/unknown-guide").status_code == 404
    with app.test_request_context("/"):
        assert not any(link["url"].startswith("/p/") for link in public_pages.navigation_links())


@pytest.mark.parametrize("preset", sorted(sweep.PRESETS))
def test_public_only_and_admin_feature_flags(sweep_app_factory, preset):
    flags = sweep.PRESETS[preset]
    app, _, _ = sweep_app_factory(flags=flags)
    ids = {alias: 17 for alias in sweep.PARAM_ALIASES.values()}
    routes = sweep.collect_routes(app, ids, flags)
    public = sweep.collect_routes(app, ids, flags, public_only=True)
    assert public and all(target.endpoint.startswith("main.") and not target.is_admin for target in public)
    assert public == [target for target in routes if target.endpoint.startswith("main.")]
    assert not any(target.endpoint.startswith("superadmin.") for target in routes)
    assert not any(target.endpoint in sweep.SKIP_ENDPOINTS for target in routes)
    assert all("<" not in target.path and ">" not in target.path for target in routes)
    assert routes == sorted(routes, key=lambda target: (not target.is_admin, target.path))
    assert any(target.path == "/admin/" and target.is_admin for target in routes)
    for flag in flags:
        owned = [target for target in routes if target.is_admin and sweep.route_flag(target.endpoint) == flag]
        assert bool(owned) is flags[flag], flag
    expected = {target.path: target.expected_status for target in public}
    assert expected["/services"] == (200 if flags["ENABLE_SERVICES"] else 404)
    assert expected["/gallery"] == (200 if flags["ENABLE_GALLERY"] else 404)
    assert expected["/schedule-work"] == (200 if flags["ENABLE_SCHEDULING"] else 302)


@pytest.mark.parametrize("scheduling,manifest_enabled,expected", [
    (True, True, 200), (False, True, 302), (True, False, 404), (False, False, 404),
])
def test_schedule_feature_redirect_is_distinct_from_explicit_manifest_gate(
    sweep_app_factory, scheduling, manifest_enabled, expected,
):
    flags = {**sweep.PRESETS["all"], "ENABLE_SCHEDULING": scheduling}
    app, _, _ = sweep_app_factory(flags=flags)
    app.config["PUBLIC_PAGES_CONFIG"] = {"pages": {"schedule_work": {"enabled": manifest_enabled}}}
    target = next(target for target in sweep.collect_routes(app, {}, flags, True)
                  if target.path == "/schedule-work")
    assert target.expected_status == expected
    response = app.test_client().get(target.path, follow_redirects=False)
    assert response.status_code == expected
    if expected == 302:
        assert response.headers["Location"].endswith("/quote-request")


@pytest.mark.parametrize("key", tuple(sweep.PUBLIC_PAGE_ENDPOINTS.values()))
def test_explicit_manifest_gates_are_collected_even_with_all_features_on(sweep_app_factory, key):
    app, _, _ = sweep_app_factory()
    app.config["PUBLIC_PAGES_CONFIG"] = {"pages": {key: {"enabled": False}}}
    targets = sweep.collect_routes(app, {}, sweep.PRESETS["all"], public_only=True)
    endpoint = next(endpoint for endpoint, page in sweep.PUBLIC_PAGE_ENDPOINTS.items() if page == key)
    gated = [target for target in targets if target.endpoint == endpoint]
    assert gated and all(target.expected_status == 404 for target in gated)
    for target in gated:
        assert app.test_client().get(target.path).status_code == 404
    if key == "quote_request":
        assert {target.path for target in gated} == {"/request-quote", "/quote-request"}
    if key == "service_area":
        assert {target.path for target in gated} == {"/service-area", "/directions"}


def test_route_parameters_aliases_dates_and_unknown_parameters(sweep_app_factory, capsys):
    app, _, _ = sweep_app_factory()
    app.add_url_rule("/admin/sweep/<int:request_id>/<int:year>/<int:month>/<int:day>/<file_format>/<entity_type>",
                     endpoint="admin.sweep_parameters", view_func=lambda **values: "ok")
    app.add_url_rule("/sweep/<unknown_value>", endpoint="main.sweep_unknown", view_func=lambda **values: "ok")
    app.add_url_rule("/sweep/post-only", endpoint="main.sweep_post", view_func=lambda: "ok", methods=["POST"])
    targets = sweep.collect_routes(app, {"quote_request": 23}, sweep.PRESETS["all"])
    today = date.today()
    target = next(target for target in targets if target.endpoint == "admin.sweep_parameters")
    assert target.path == f"/admin/sweep/23/{today.year}/{today.month}/{today.day}/xlsx/customers"
    assert target.is_admin and target.expected_status == 200
    assert not any(target.endpoint in ("main.sweep_unknown", "main.sweep_post") for target in targets)
    assert "could not build a URL for main.sweep_unknown" in capsys.readouterr().out


def test_minimal_kit_defaults_are_gates_not_skipped_feature_routes(sweep_app_factory):
    app, _, _ = sweep_app_factory(site="minimal_quote_funnel")
    targets = sweep.collect_routes(app, {}, sweep.PRESETS["all"], public_only=True)
    statuses = {target.path: target.expected_status for target in targets}
    for path in ("/services", "/gallery", "/service-area", "/directions", "/about", "/faq", "/schedule-work"):
        assert statuses[path] == 404, path
    for path in ("/", "/contact", "/quote-request", "/request-quote", "/p/sweep-content"):
        assert statuses[path] == 200, path


@pytest.mark.parametrize("expected", [302, 404])
@pytest.mark.parametrize("status", [200, 302, 404, 500, None])
def test_classify_gate_probes_only_checks_expected_status(expected, status):
    record = {
        "expected_status": expected, "status": status, "gate_probe": True,
        "metrics": {"overflow": True, "brokenImages": ["broken.png"]},
        "pageErrors": ["intentional gate page"], "console": ["error: gate"],
        "failedRequests": [{"url": "/gate", "status": 404}],
    }
    assert sweep.classify(record) == ([] if status == expected else [
        ("error", f"HTTP {status}, expected {expected}"),
    ])


@pytest.mark.parametrize("status", [302, 404, 500, None])
def test_classify_normal_pages_rejects_unexpected_status(status):
    assert sweep.classify({"status": status, "metrics": {"h1": ["Title"], "mainVisible": True}}) == [
        ("error", f"HTTP {status}, expected 200"),
    ]


def test_classify_setup_or_navigation_error_takes_precedence():
    assert sweep.classify({"error": "RuntimeError: setup failed", "status": 500, "gate_probe": True}) == [
        ("error", "navigation failed: RuntimeError: setup failed"),
    ]
    assert sweep.classify({"status": 200, "metrics": {"h1": ["Title"], "mainVisible": True}}) == []
    assert sweep.classify({"status": 200}) == [
        ("warn", "expected exactly 1 h1, found 0"), ("warn", "no visible <main> landmark"),
    ]


def test_classify_normal_visits_keeps_layout_errors_and_accessibility_warnings():
    record = {
        "status": 200, "pageErrors": ["script exploded"],
        "failedRequests": [{"url": "/missing.css", "status": 404},
                           {"url": "/offline.js", "failure": "net::ERR_FAILED"}],
        "console": ["error: console failure", "warning: ignored warning"],
        "metrics": {
            "overflow": True, "viewport": 390, "scrollWidth": 500,
            "offenders": [{"tag": "div", "cls": "wide panel", "width": 500}],
            "brokenImages": ["/broken.png"], "imagesWithoutAlt": 2,
            "unlabeledControls": ["input[name=email]"], "buttonsWithoutName": 1,
            "h1": ["First", "Second"], "mainVisible": False, "siteConfigLeak": True,
            "contrastIssues": [{"ratio": 2, "minimum": 4.5, "text": "Faint text",
                                "color": "gray", "background": "white", "source": "p.muted"}],
        },
    }
    assert sweep.classify(record) == [
        ("error", "JS exception: script exploded"),
        ("error", "horizontal overflow: scrollWidth 500 > viewport 390 (div.wide[500px])"),
        ("error", "failed request 404: /missing.css"),
        ("error", "failed request net::ERR_FAILED: /offline.js"),
        ("warn", "console error: console failure"),
        ("warn", "broken image: /broken.png"),
        ("warn", "2 image(s) without alt attribute"),
        ("warn", "unlabeled control(s): input[name=email]"),
        ("warn", "1 button(s) with no accessible name"),
        ("warn", "expected exactly 1 h1, found 2"),
        ("warn", "no visible <main> landmark"),
        ("warn", "placeholder text leaked into the page"),
        ("warn", 'contrast 2:1 below 4.5 for "Faint text" (gray on white, p.muted)'),
    ]


def test_report_preserves_gates_and_failures_removes_tracebacks_and_groups_widths(tmp_path):
    records = [
        {"preset": "kit--all", "path": "/disabled", "width": 390,
         "status": 404, "expected_status": 404, "gate_probe": True},
        *[{"preset": "kit--all", "path": "/", "width": width, "status": 200,
           "metrics": {"h1": [], "mainVisible": True}} for width in (390, 768)],
        {"preset": "kit--off", "path": "<setup>", "width": 0,
         "error": "RuntimeError: fixture unavailable", "traceback": "private stack detail"},
    ]
    runs = [
        {"preset": "kit--all", "site_preset": "specialty_contractor", "flags": {"enabled": True}, "results": records[:3]},
        {"preset": "kit--off", "site_preset": "minimal_quote_funnel", "flags": {"enabled": False}, "results": records[3:]},
    ]
    before = deepcopy(runs)
    assert sweep.write_report(tmp_path, runs) == (1, 2)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["generated"] == date.today().isoformat()
    assert [run["site_preset"] for run in report["runs"]] == ["specialty_contractor", "minimal_quote_funnel"]
    assert [len(run["results"]) for run in report["runs"]] == [3, 1]
    assert report["runs"][0]["results"][0]["issues"] == []
    failure = report["runs"][1]["results"][0]
    assert "traceback" not in failure
    assert failure["error"] == "RuntimeError: fixture unavailable"
    assert failure["issues"] == [["error", "navigation failed: RuntimeError: fixture unavailable"]]
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "4 page visits, 1 errors, 2 warnings." in summary
    assert summary.count("expected exactly 1 h1") == 1
    assert "@ 390,768px" in summary and "<setup> @ 0px" in summary
    assert runs == before


def test_sweep_probes_gates_without_navigation_login_or_screenshots(sweep_app_factory, monkeypatch):
    app, root, database = sweep_app_factory()
    (root / "ids.json").write_text("{}", encoding="utf-8")
    targets = [sweep.RouteTarget("/disabled", "main.about_page", False, 404),
               sweep.RouteTarget("/schedule-work", "main.schedule_work", False, 302)]
    page = Mock()
    responses = [Mock(status=404), Mock(status=302)]
    responses[1].headers = {"location": "/quote-request"}
    context = Mock()
    context.new_page.return_value = page
    context.request.get.side_effect = responses
    browser = Mock()
    browser.new_context.return_value = context
    server = Mock()
    monkeypatch.setattr(sweep, "build_app", lambda *args: app)
    monkeypatch.setattr(sweep, "collect_routes", Mock(return_value=targets))
    monkeypatch.setattr(sweep, "start_server", lambda app: (server, 8765))
    monkeypatch.setattr(sweep, "launch_browser", lambda *args: browser)
    login = Mock(side_effect=AssertionError("public sweeps must not log in"))
    monkeypatch.setattr(sweep, "login", login)
    args = SimpleNamespace(public_only=True, widths=[390], only=None)

    run = sweep.sweep_preset(object(), args, root, "kit--all", sweep.PRESETS["all"], database, False)

    assert [record["status"] for record in run["results"]] == [404, 302]
    assert all(record["gate_probe"] and sweep.classify(record) == [] for record in run["results"])
    assert all("metrics" not in record and "screenshot" not in record for record in run["results"])
    assert context.request.get.call_args_list == [
        (("http://127.0.0.1:8765/disabled",), {"max_redirects": 0}),
        (("http://127.0.0.1:8765/schedule-work",), {"max_redirects": 0}),
    ]
    for response in responses:
        response.dispose.assert_called_once_with()
    page.goto.assert_not_called()
    page.evaluate.assert_not_called()
    page.screenshot.assert_not_called()
    login.assert_not_called()
    context.close.assert_called_once_with()
    browser.close.assert_called_once_with()
    server.shutdown.assert_called_once_with()
    server.server_close.assert_called_once_with()


@pytest.mark.parametrize("failure_stage", [
    "launch_browser", "new_context", "new_page", "context_close",
])
def test_sweep_outer_cleanup_covers_setup_and_context_close_failures(
    sweep_app_factory, monkeypatch, failure_stage,
):
    app, root, database = sweep_app_factory()
    (root / "ids.json").write_text("{}", encoding="utf-8")
    with app.app_context():
        db.session.add(ServiceOption(name="Preserved sweep service", is_active=True))
        db.session.commit()
        engines = set(db.engines.values()) | set(app.extensions["tenancy"].engines.values())
    disposals = []
    for engine in engines:
        dispose = Mock(wraps=engine.dispose)
        monkeypatch.setattr(engine, "dispose", dispose)
        disposals.append(dispose)

    failure = RuntimeError(f"{failure_stage} failed")
    context = Mock()
    browser = Mock()
    browser.new_context.return_value = context
    launch = Mock(return_value=browser)
    server = Mock()
    start = Mock(return_value=(server, 8765))
    failing_call = {
        "launch_browser": launch,
        "new_context": browser.new_context,
        "new_page": context.new_page,
        "context_close": context.close,
    }[failure_stage]
    failing_call.side_effect = failure
    monkeypatch.setattr(sweep, "build_app", Mock(return_value=app))
    monkeypatch.setattr(sweep, "collect_routes", Mock(return_value=[]))
    monkeypatch.setattr(sweep, "start_server", start)
    monkeypatch.setattr(sweep, "launch_browser", launch)
    args = SimpleNamespace(public_only=True, widths=[390], only=None)

    with pytest.raises(RuntimeError) as exc:
        sweep.sweep_preset(object(), args, root, "kit--all", sweep.PRESETS["all"], database, False)

    assert exc.value is failure
    launch.assert_called_once()
    if failure_stage == "launch_browser":
        browser.new_context.assert_not_called()
        browser.close.assert_not_called()
    else:
        browser.new_context.assert_called_once_with(
            viewport={"width": 390, "height": 900}, device_scale_factor=1,
        )
        browser.close.assert_called_once_with()
    if failure_stage in ("launch_browser", "new_context"):
        context.new_page.assert_not_called()
        context.close.assert_not_called()
        start.assert_not_called()
        server.shutdown.assert_not_called()
        server.server_close.assert_not_called()
    else:
        context.new_page.assert_called_once_with()
        context.close.assert_called_once_with()
        start.assert_called_once_with(app)
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
    for dispose in disposals:
        dispose.assert_called_once_with()
    sweep.assert_engine_matches(app, database)
    with app.app_context():
        assert [service.name for service in db.session.query(ServiceOption).all()] == [
            "Preserved sweep service",
        ]
    assert (root / "ids.json").read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize("location,valid", [
    pytest.param("/quote-request", True, id="good-relative"),
    pytest.param("http://127.0.0.1:8765/quote-request", True, id="good-absolute"),
    pytest.param("//127.0.0.1:8765/quote-request", True, id="good-scheme-relative"),
    pytest.param("https://external.test/quote-request", False, id="bad-external"),
    pytest.param("//external.test/quote-request", False, id="bad-external-scheme-relative"),
    pytest.param("/request-quote", False, id="bad-wrong-relative-path"),
    pytest.param("http://127.0.0.1:8765/contact", False, id="bad-wrong-absolute-path"),
    pytest.param("http://127.0.0.1:9999/quote-request", False, id="bad-wrong-port"),
    pytest.param("", False, id="bad-missing-location"),
])
def test_classify_good_and_bad_redirects_from_mocked_gate_response(
    sweep_app_factory, monkeypatch, location, valid,
):
    app, root, database = sweep_app_factory()
    (root / "ids.json").write_text("{}", encoding="utf-8")
    target = sweep.RouteTarget("/schedule-work", "main.schedule_work", False, 302)
    response = Mock(status=302, headers={"location": location} if location else {})
    page = Mock()
    context = Mock()
    context.new_page.return_value = page
    context.request.get.return_value = response
    browser = Mock()
    browser.new_context.return_value = context
    server = Mock()
    monkeypatch.setattr(sweep, "build_app", Mock(return_value=app))
    monkeypatch.setattr(sweep, "collect_routes", Mock(return_value=[target]))
    monkeypatch.setattr(sweep, "start_server", Mock(return_value=(server, 8765)))
    monkeypatch.setattr(sweep, "launch_browser", Mock(return_value=browser))
    login = Mock(side_effect=AssertionError("gate probes must not log in"))
    monkeypatch.setattr(sweep, "login", login)
    args = SimpleNamespace(public_only=True, widths=[390], only=None)

    run = sweep.sweep_preset(object(), args, root, "kit--all", sweep.PRESETS["all"], database, False)

    assert len(run["results"]) == 1
    record = run["results"][0]
    assert record["status"] == record["expected_status"] == 302
    assert record["gate_probe"] is True
    assert record["location"] == location
    assert record["expected_location"] == "/quote-request"
    assert record["redirect_valid"] is valid
    assert sweep.classify(record) == ([] if valid else [
        ("error", f"redirect {location}, expected /quote-request on the sweep host"),
    ])
    context.request.get.assert_called_once_with(
        "http://127.0.0.1:8765/schedule-work", max_redirects=0,
    )
    response.dispose.assert_called_once_with()
    page.goto.assert_not_called()
    page.evaluate.assert_not_called()
    page.screenshot.assert_not_called()
    login.assert_not_called()
    assert "metrics" not in record and "screenshot" not in record
    context.close.assert_called_once_with()
    browser.close.assert_called_once_with()
    server.shutdown.assert_called_once_with()
    server.server_close.assert_called_once_with()


@pytest.mark.parametrize("site", sweep.SITE_PRESETS)
def test_cli_site_selection_is_independent_of_feature_preset(site):
    args = sweep.parse_args(["--site-preset", site, "--preset", "off", "--public-only", "--widths", "390, 768"])
    assert args.site_preset == site and args.preset == "off"
    assert args.widths == [390, 768] and args.public_only
    assert not args.matrix and not args.site_matrix
    matrix = sweep.parse_args(["--site-matrix", "--matrix"])
    assert matrix.site_matrix and matrix.matrix


@pytest.mark.parametrize("argv", [["--site-preset", "missing-kit"], ["--widths", ", ,"]])
def test_cli_rejects_invalid_site_or_empty_widths(argv):
    with pytest.raises(SystemExit) as exc:
        sweep.parse_args(argv)
    assert exc.value.code == 2


@pytest.mark.parametrize("matrix", [False, True])
def test_main_reports_partial_matrix_setup_failures_and_returns_one(tmp_path, monkeypatch, matrix):
    """Exercise the real main/report code even when Playwright is not installed."""
    token = object()
    lifecycle = []

    @contextmanager
    def fake_playwright():
        lifecycle.append("enter")
        try:
            yield token
        finally:
            lifecycle.append("exit")

    package = ModuleType("playwright")
    package.__path__ = []
    api = ModuleType("playwright.sync_api")
    api.sync_playwright = fake_playwright
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    monkeypatch.setattr(sweep, "launch_browser", Mock(side_effect=AssertionError("no browser launch")))
    calls = []

    def fake_sweep(playwright, args, root, name, flags, database, seed_needed, site):
        assert playwright is token and args.public_only
        assert root.is_dir() and database == root / "sweep.db" and seed_needed is True
        assert name == f"{site}--{name.split('--')[1]}"
        assert flags == sweep.PRESETS[name.split("--")[1]]
        calls.append((site, name))
        if site == "specialty_contractor":
            raise RuntimeError("isolated fixture setup failed")
        return {"preset": name, "site_preset": site, "flags": flags, "results": [
            {"preset": name, "site_preset": site, "path": "/", "width": 390, "status": 200,
             "metrics": {"h1": ["Title"], "mainVisible": True}, "screenshot": "screenshots/home.png"},
        ]}

    monkeypatch.setattr(sweep, "sweep_preset", fake_sweep)
    argv = ["--site-matrix", "--public-only", "--out", str(tmp_path), "--widths", "390", "--preset", "core"]
    if matrix:
        argv.append("--matrix")
    assert sweep.main(argv) == 1
    presets = sorted(sweep.PRESETS) if matrix else ["core"]
    assert calls == [(site, f"{site}--{preset}") for site in sweep.SITE_PRESETS for preset in presets]
    assert lifecycle == ["enter", "exit"] * len(calls)
    sweep.launch_browser.assert_not_called()
    reports = list(tmp_path.glob("*/report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert len(report["runs"]) == len(calls)
    failures = [run for run in report["runs"] if run["site_preset"] == "specialty_contractor"]
    assert len(failures) == len(presets)
    for run in failures:
        record = run["results"][0]
        assert record["path"] == "<setup>" and record["width"] == 0
        assert record["error"] == "RuntimeError: isolated fixture setup failed"
        assert record["issues"] == [["error", "navigation failed: RuntimeError: isolated fixture setup failed"]]
    successes = [run for run in report["runs"] if run["site_preset"] != "specialty_contractor"]
    for run in successes:
        assert run["results"][0]["issues"] == []
        assert run["results"][0]["screenshot"] == f"{run['preset']}/screenshots/home.png"
    assert "isolated fixture setup failed" in reports[0].with_name("summary.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("route", ["/quote-request", "/request-quote"])
@pytest.mark.parametrize("title", ["Get a Quote", "Plan your custom project", "Project <details> & estimates"])
def test_quote_heading_keeps_default_copy_and_honors_configured_title(app, client, monkeypatch, tmp_path, route, title):
    monkeypatch.setattr(app, "instance_path", str(tmp_path / "quote-instance"))
    app.config["SITE_PRESET"] = "local_service_business"
    app.config["PUBLIC_PAGES_CONFIG"] = {"pages": {"quote_request": {"title": title}}}
    response = client.get(route)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert re.findall(r"<h1[^>]*>(.*?)</h1>", body, re.DOTALL) == [str(escape(title))]
    assert '<h2 id="quote-form-heading">Tell us about your project</h2>' in body
    assert 'aria-labelledby="quote-form-heading"' in body
    assert f"<title>{escape(title)} | " in body