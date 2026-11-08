"""Public engine contracts, using isolated storage and the real HTTP/operator APIs."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from functools import partial
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3

from alembic.script import ScriptDirectory
from flask import Flask
from markupsafe import escape
import pytest
from werkzeug.exceptions import NotFound

from app import create_app
from app.cli import MIGRATIONS
from app.extensions import db
from app.models import GalleryItem, ServiceOption
from app.services import public_pages, rate_limit
from app.tenancy import current_tenant_settings, tenant_context


CONTROL_URL = "http://control.engine.test"
CONTROL_PATH = "/platform/control"
PASSWORD = "public-engine-test-password"
PRESETS = ("local_service_business", "specialty_contractor", "minimal_quote_funnel")
ROUTES = {
    "home": ("/",), "services": ("/services",), "gallery": ("/gallery",),
    "service_area": ("/service-area", "/directions"), "about": ("/about",),
    "contact": ("/contact",), "faq": ("/faq",),
    "quote_request": ("/quote-request", "/request-quote"),
    "schedule_work": ("/schedule-work",),
}


class PrimaryNavigation(HTMLParser):
    """Read only the primary nav, excluding footer and separate quote buttons."""

    def __init__(self, body):
        super().__init__()
        self.active = False
        self.links = []
        self.found = False
        self.feed(body)
        assert self.found, "Expected the real primary navigation element"

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav" and attrs.get("aria-label") == "Primary navigation":
            self.active = self.found = True
        elif self.active and tag == "a":
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "nav":
            self.active = False


@pytest.fixture()
def engine_factory(tmp_path, monkeypatch):
    apps = []
    rate_limit.reset_all()

    def factory(records=None, **overrides):
        root = tmp_path / f"factory-{len(apps)}"
        root.mkdir()
        instance = root / "instance"
        instance.mkdir()
        registry = root / "registry.json"
        # Runtime registry edits deliberately go through this file, not app.config.
        registry.write_text(json.dumps(records or {}), encoding="utf-8")
        monkeypatch.setattr("app.Flask", partial(Flask, instance_path=str(instance)))
        config = {
            "SECRET_KEY": "public-engine-independent-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite+pysqlite:///{root / 'default.sqlite3'}",
            "TENANTS": {}, "TENANTS_JSON": "", "TENANT_ALLOW_DEFAULT": False,
            "TENANT_REGISTRY_FILE": str(registry),
            "SUPERADMIN_HOST": "control.engine.test", "SUPERADMIN_PATH": CONTROL_PATH,
            "SUPERADMIN_PASSWORD": PASSWORD, "WTF_CSRF_ENABLED": False,
            "WTF_CSRF_SSL_STRICT": False, "TRUST_PROXY": False,
            "RATE_LIMIT_ENABLED": False, "EMAIL_ENABLED": False,
            "ERROR_WEBHOOK_URL": "", "RECAPTCHA_ENABLED": False,
            "RECAPTCHA_SITE_KEY": "", "RECAPTCHA_SECRET_KEY": "",
            "CANONICAL_ORIGIN": "", "UPLOAD_FOLDER": str(root / "uploads"),
            "SITE_PRESET": "local_service_business", "PUBLIC_PAGES_CONFIG": {},
            "ENABLE_SERVICES": True, "ENABLE_GALLERY": True, "ENABLE_SCHEDULING": True,
            "BUSINESS_NAME": "Engine Default", "BUSINESS_EMAIL": "default@engine.test",
            "BUSINESS_PHONE": "555-0100", "BUSINESS_ADDRESS": "Default Street",
            "SERVICE_AREA": "Default County", "TAGLINE": "Engine test tagline",
        }
        config.update(overrides)
        app = create_app("testing", config)
        apps.append(app)
        with app.app_context():
            # Context processors can inspect the maintenance/default metadata too.
            db.metadata.create_all(bind=db.engine)
            for engine in app.extensions["tenancy"].engines.values():
                db.metadata.create_all(bind=engine)
        return app

    yield factory
    for app in reversed(apps):
        with app.app_context():
            db.session.remove()
            engines = set(db.engines.values()) | set(app.extensions["tenancy"].engines.values())
            for engine in engines:
                engine.dispose()
    rate_limit.reset_all()


@pytest.fixture()
def engine_app(engine_factory, tmp_path):
    records = {
        slug: {
            "hosts": [f"{slug}.engine.test"],
            "database_uri": f"sqlite+pysqlite:///{tmp_path / (slug + '.sqlite3')}",
            "settings": {
                "SITE_PRESET": preset, "PUBLIC_PAGES_CONFIG": {},
                "BUSINESS_NAME": f"{slug.title()} Engine", "BUSINESS_EMAIL": f"{slug}@engine.test",
                "SERVICE_AREA": f"{slug.title()} County", "ENABLE_SERVICES": True,
                "ENABLE_GALLERY": True, "ENABLE_SCHEDULING": True,
            },
        }
        for slug, preset in zip(("alpha", "beta"), PRESETS)
    }
    app = engine_factory(records)
    for slug in records:
        with app.app_context(), tenant_context(slug):
            db.session.add_all([
                ServiceOption(name=f"{slug.title()} Service", is_active=True, display_order=0),
                GalleryItem(title=f"{slug.title()} Project", image_path="assets/images/Logowhite.png",
                            is_active=True, display_order=0),
            ])
            db.session.commit()
    return app


def get(app, route="/", slug="alpha"):
    return app.test_client().get(route, base_url=f"http://{slug}.engine.test")


def body(app, route="/", slug="alpha"):
    response = get(app, route, slug)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_data(as_text=True)


def nav(app, slug="alpha"):
    return PrimaryNavigation(body(app, slug=slug)).links


def blocks(app, slug="alpha"):
    return re.findall(r'data-public-block="([^"]+)"', body(app, slug=slug))


def saved(app):
    return json.loads(Path(app.config["TENANT_REGISTRY_FILE"]).read_text(encoding="utf-8"))


def edit_registry(app, slug="alpha", **settings):
    records = saved(app)
    records[slug]["settings"].update(settings)
    Path(app.config["TENANT_REGISTRY_FILE"]).write_text(json.dumps(records), encoding="utf-8")


def manifest(app, slug="alpha"):
    with app.app_context(), tenant_context(slug):
        return public_pages.get_public_manifest()


def login(app):
    client = app.test_client()
    response = client.post(CONTROL_PATH, base_url=CONTROL_URL,
                           data={"action": "login", "password": PASSWORD})
    assert response.status_code == 302
    return client


def operator_post(client, action, **fields):
    return client.post(CONTROL_PATH, base_url=CONTROL_URL, data={"action": action, **fields})


def checksum(app):
    return hashlib.sha256(Path(app.config["TENANT_REGISTRY_FILE"]).read_bytes()).hexdigest()


def assert_migrated(app, slug):
    path = Path(app.instance_path) / "tenants" / slug / "tenant.sqlite3"
    assert path.is_file()
    with sqlite3.connect(path) as connection:
        heads = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert heads == set(ScriptDirectory(MIGRATIONS).get_heads())
    assert {"users", "service_options", "gallery_items", "quote_requests"} <= tables


def test_presets_have_distinct_home_nav_and_tenant_content(engine_app):
    assert public_pages.preset_names() == list(PRESETS)
    assert blocks(engine_app) == ["hero", "services_preview", "service_area", "quote_cta"]
    assert blocks(engine_app, "beta") == [
        "hero", "trust_highlights", "gallery_preview", "services_preview", "quote_cta",
    ]
    assert nav(engine_app) == ["/", "/services", "/gallery", "/about", "/contact"]
    assert nav(engine_app, "beta") == [
        "/", "/gallery", "/services", "/directions", "/about", "/contact", "/p/our-process",
    ]
    assert get(engine_app, "/p/our-process").status_code == 404
    assert "Helpful project details" in body(engine_app, "/p/our-process", "beta")
    for slug, other in (("alpha", "Beta"), ("beta", "Alpha")):
        page = body(engine_app, slug=slug)
        assert f"{slug.title()} Engine" in page
        assert f"{other} Engine" not in page
        gallery = body(engine_app, "/gallery", slug)
        assert f"{slug.title()} Project" in gallery and f"{other} Project" not in gallery
        assert '/static/assets/images/Logowhite.png' in gallery


def test_effective_manifest_is_deeply_immutable_and_fresh(engine_app):
    first = manifest(engine_app, "beta")
    assert isinstance(first, Mapping)
    assert isinstance(first["home_blocks"], tuple)
    trust = first["home_blocks"][1]
    assert isinstance(trust["items"], tuple)
    sections = first["custom_pages"][0]["sections"]
    assert isinstance(sections, tuple) and isinstance(sections[0]["paragraphs"], tuple)
    for target, key in ((first, "pages"), (first["pages"], "contact"),
                        (trust["items"][0], "title"), (sections[0], "paragraphs")):
        with pytest.raises(TypeError):
            target[key] = "mutated"
    with pytest.raises(TypeError):
        sections[0]["paragraphs"][0] = "mutated"
    with pytest.raises(AttributeError):
        first["home_blocks"].append({"type": "hero"})
    assert manifest(engine_app, "beta") == first
    assert manifest(engine_app, "alpha")["custom_pages"] == ()
    edit_registry(engine_app, "beta", PUBLIC_PAGES_CONFIG={"pages": {"contact": {"title": "Fresh beta"}}})
    assert "Fresh beta" in body(engine_app, "/contact", "beta")
    assert manifest(engine_app, "beta")["pages"]["contact"]["title"] == "Fresh beta"
    assert first["pages"]["contact"]["title"] == "Contact"
    assert manifest(engine_app)["pages"]["contact"]["title"] == "Contact"


@pytest.mark.parametrize("key", tuple(ROUTES))
def test_registry_refresh_disables_routes_and_aliases_then_restores(engine_app, key):
    for route in ROUTES[key]:
        assert get(engine_app, route).status_code == 200
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"pages": {key: {"enabled": False}}})
    for route in ROUTES[key]:
        assert get(engine_app, route).status_code == 404
        assert get(engine_app, route, "beta").status_code == 200
    if key != "home":
        assert ROUTES[key][0] not in nav(engine_app)
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"pages": {key: {"enabled": True}}})
    for route in ROUTES[key]:
        assert get(engine_app, route).status_code == 200


@pytest.mark.parametrize("override", [
    ["quote_cta", "hero"],
    {"home_blocks": ["quote_cta", {"type": "trust_highlights", "enabled": False}, "hero"]},
])
def test_home_override_replaces_preset_and_skips_disabled_blocks(engine_app, override):
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG=override)
    assert blocks(engine_app) == ["quote_cta", "hero"]
    assert "trust_highlights" not in blocks(engine_app)
    assert "trust_highlights" in blocks(engine_app, "beta")


@pytest.mark.parametrize(("key", "flag", "block"), [
    ("services", "ENABLE_SERVICES", "services_preview"),
    ("gallery", "ENABLE_GALLERY", "gallery_preview"),
    ("schedule_work", "ENABLE_SCHEDULING", None),
])
def test_master_flags_override_explicit_page_nav_and_blocks(engine_app, key, flag, block):
    override = {"home_blocks": ["hero", "services_preview", "gallery_preview"],
                "pages": {key: {"enabled": True, "show_in_nav": True}}}
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG=override, **{flag: True})
    assert ROUTES[key][0] in nav(engine_app)
    if block:
        assert block in blocks(engine_app)
    edit_registry(engine_app, **{flag: False})
    # Preserve the pre-engine scheduling feature-off redirect contract.
    assert get(engine_app, ROUTES[key][0]).status_code == (302 if key == "schedule_work" else 404)
    assert ROUTES[key][0] not in nav(engine_app)
    if block:
        assert block not in blocks(engine_app)
    assert get(engine_app, ROUTES[key][0], "beta").status_code == 200


def test_empty_gallery_hides_teaser_nav_and_page_without_affecting_other_tenant(engine_app):
    with engine_app.app_context(), tenant_context("beta"):
        GalleryItem.query.update({GalleryItem.is_active: False})
        db.session.commit()
    assert "gallery_preview" not in blocks(engine_app, "beta")
    assert "/gallery" not in nav(engine_app, "beta")
    assert get(engine_app, "/gallery", "beta").status_code == 404
    assert get(engine_app, "/gallery").status_code == 200


@pytest.mark.parametrize("route,key", [("/contact", "contact"), ("/service-area", "service_area"),
                                        ("/directions", "service_area")])
def test_standard_copy_details_and_meta_are_escaped(engine_app, route, key):
    copy = {
        "title": 'Visit <b>Alpha</b>', "text": '<script>alert("copy")</script>',
        "hours": "Weekdays <9-5>\nSaturday & Sunday", "coverage": "North <County>",
        "address": "12 <Main> Street", "directions": 'Use <west> entrance & ring "bell"',
        "meta_description": '\"/><script>alert("meta")</script>',
    }
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"pages": {key: copy}})
    page = body(engine_app, route)
    assert f"<h1>{escape(copy['title'])}</h1>" in page
    assert f"<title>{escape(copy['title'])} | Alpha Engine</title>" in page
    assert f'<meta name="description" content="{escape(copy["meta_description"])}">' in page
    for field in ("text", "hours", "coverage", "address", "directions"):
        for line in copy[field].splitlines():
            assert str(escape(line)) in page
    assert '<script>alert("copy")</script>' not in page
    assert "Visit &lt;b&gt;Alpha&lt;/b&gt;" not in body(engine_app, route, "beta")


def test_standard_pages_direct_list_reorders_nav_and_disables_omissions(engine_app):
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"pages": [
        {"key": "contact", "show_in_nav": True},
        {"key": "services", "show_in_nav": True},
        {"key": "home", "show_in_nav": True},
    ]})
    body(engine_app)
    for key in ("gallery", "service_area", "about", "faq", "quote_request", "schedule_work"):
        for route in ROUTES[key]:
            assert get(engine_app, route).status_code == 404
    assert nav(engine_app) == ["/contact", "/services", "/"]


def test_explicit_nav_order_and_stable_ties(engine_app):
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={
        "pages": [{"key": "contact", "order": -10}, {"key": "services", "order": -10},
                  {"key": "home", "order": 20}],
        "custom_pages": [{"slug": "one", "title": "One", "show_in_nav": True, "order": -10},
                         {"slug": "two", "title": "Two", "show_in_nav": True, "order": -10}],
    })
    assert nav(engine_app) == ["/contact", "/services", "/p/one", "/p/two", "/"]


def test_custom_sections_render_all_kinds_in_order_without_safe_html(engine_app):
    dangerous = '<img src=x onerror="alert(1)">'
    sections = [
        {"type": "hero", "title": "Hero heading", "subtitle": dangerous, "cta_url": "/contact"},
        {"type": "paragraphs", "paragraphs": ["First paragraph", dangerous]},
        {"type": "custom_richtext", "body": dangerous},
        {"type": "feature_cards", "items": [{"title": "Feature heading", "text": dangerous,
                                                "label": "Feature link", "url": "https://example.test/info"}]},
        {"type": "checklist", "checklist": ["Checklist entry", dangerous]},
        {"type": "faq_accordion", "items": [{"question": "FAQ question", "answer": dangerous}]},
        {"type": "cta_banner", "title": "CTA heading", "text": dangerous,
         "cta_label": "Next step", "cta_url": "http://example.test/next"},
        {"type": "text", "enabled": False, "text": "Invisible section"},
    ]
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"custom_pages": [{
        "slug": "our-process", "title": "Our <Process>", "show_in_nav": True,
        "meta_description": dangerous, "sections": sections,
    }]})
    page = body(engine_app, "/p/our-process")
    assert re.findall(r'data-public-section="([^"]+)"', page) == [
        "hero", "text", "custom_richtext", "feature_cards", "checklist", "faq", "cta",
    ]
    for text in ("Hero heading", "First paragraph", "Feature heading", "Checklist entry",
                 "FAQ question", "CTA heading", "Next step"):
        assert text in page
    assert page.count(str(escape(dangerous))) >= 7
    assert dangerous not in page and "Invisible section" not in page
    for url in ("/contact", "https://example.test/info", "http://example.test/next"):
        assert f'href="{url}"' in page
    assert "/p/our-process" in nav(engine_app)
    assert "Our &lt;Process&gt;" not in body(engine_app, "/p/our-process", "beta")
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"custom_pages": [{
        "slug": "our-process", "title": "Hidden", "enabled": False, "show_in_nav": True,
    }]})
    assert get(engine_app, "/p/our-process").status_code == 404
    assert "/p/our-process" not in nav(engine_app)


@pytest.mark.parametrize("route", ["/p/missing", "/p/Admin", "/p/caf%C3%A9", "/p/contact"])
def test_invalid_or_unknown_runtime_custom_slug_is_404(engine_app, route):
    assert get(engine_app, route).status_code == 404


def test_unknown_engine_page_apis_fail_closed(engine_app):
    with engine_app.app_context(), tenant_context("alpha"):
        assert not public_pages.page_enabled("missing")
        assert not public_pages.page_enabled(None)
        for function in (public_pages.page_config, public_pages.require_page, public_pages.custom_page):
            with pytest.raises(NotFound):
                function("missing")


@pytest.mark.parametrize("override", [{"home_blocks": []}, []])
def test_empty_home_lists_clear_only_home_content(engine_app, override):
    edit_registry(engine_app, "beta", PUBLIC_PAGES_CONFIG=override)
    assert blocks(engine_app, "beta") == []
    assert manifest(engine_app, "beta")["home_blocks"] == ()
    assert get(engine_app, "/p/our-process", "beta").status_code == 200
    assert "/gallery" in nav(engine_app, "beta")


def test_deep_map_merge_preserves_settings_and_lists_replace_without_preset_contamination(engine_app):
    original = manifest(engine_app, "beta")
    override = {"pages": {"contact": {"title": "Only beta contact", "sections": [
        {"type": "text", "paragraphs": ["Replacement paragraph"]},
    ]}}, "home_blocks": ["hero"], "custom_pages": [
        {"slug": "replacement", "title": "Replacement", "sections": []},
    ]}
    untouched_input = deepcopy(override)
    edit_registry(engine_app, "beta", PUBLIC_PAGES_CONFIG=override)
    body(engine_app, slug="beta")  # Execute before_request to refresh the file source.
    effective = manifest(engine_app, "beta")
    assert override == untouched_input
    assert effective["pages"]["contact"]["title"] == "Only beta contact"
    for field in ("enabled", "show_in_nav", "order", "nav_label"):
        assert effective["pages"]["contact"][field] == original["pages"]["contact"][field]
    assert effective["pages"]["gallery"] == original["pages"]["gallery"]
    assert [item["type"] for item in effective["home_blocks"]] == ["hero"]
    assert [item["slug"] for item in effective["custom_pages"]] == ["replacement"]
    with engine_app.app_context(), tenant_context("beta"):
        settings = current_tenant_settings()
        assert settings["BUSINESS_NAME"] == "Beta Engine" and settings["ENABLE_GALLERY"] is True
    assert manifest(engine_app)["pages"]["contact"]["title"] == "Contact"
    edit_registry(engine_app, "beta", PUBLIC_PAGES_CONFIG={"custom_pages": [], "home_blocks": [],
                                                         "pages": {"contact": {"sections": []}}})
    assert blocks(engine_app, "beta") == []
    cleared = manifest(engine_app, "beta")
    assert cleared["custom_pages"] == () and cleared["pages"]["contact"]["sections"] == ()
    assert get(engine_app, "/p/our-process", "beta").status_code == 404
    edit_registry(engine_app, "beta", PUBLIC_PAGES_CONFIG={})
    body(engine_app, slug="beta")
    assert manifest(engine_app, "beta") == original


def test_empty_page_selection_keeps_implicit_home_and_retargets_generated_cta(engine_app):
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"pages": []})
    assert nav(engine_app) == ["/"]
    assert manifest(engine_app)["pages"]["home"]["enabled"] is True
    for key in ROUTES:
        if key != "home":
            assert get(engine_app, ROUTES[key][0]).status_code == 404
    assert 'href="/quote-request"' not in body(engine_app)
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"pages": {"quote_request": {"enabled": False}},
                                                  "home_blocks": ["hero", {"type": "quote_cta", "cta_url": ""}]})
    body(engine_app)
    current = manifest(engine_app)
    assert current["home_blocks"][0]["cta_url"] == "/contact"
    assert current["home_blocks"][1]["cta_url"] == ""


INVALID_SLUGS = ["admin", "contact", "service-area", "directions", "request-quote", "static",
                 "../escape", "a/b", "a\\b", "Our-process", "café", "école", "", "1start",
                 "a--b", "a-", "a" * 81]


@pytest.mark.parametrize("slug", INVALID_SLUGS)
def test_invalid_custom_slugs_rejected_at_startup(engine_factory, slug):
    with pytest.raises(ValueError):
        engine_factory(PUBLIC_PAGES_CONFIG={"custom_pages": [{"slug": slug, "title": "Invalid"}]})


UNSAFE_URLS = ["javascript:alert(1)", "data:text/html,test", "//evil.test/path", "relative/path",
               "https://user:password@example.test", "/\\evil.test", "/%2fevil.test", "/%252fevil.test",
               "https://example.test/%0a", "https://example.test:bad/path", "https://", "/bad%zz",
               "https://example.test/a b"]


@pytest.mark.parametrize("url", UNSAFE_URLS)
@pytest.mark.parametrize("item_link", [False, True], ids=["cta", "feature-item"])
def test_unsafe_links_rejected_at_startup(engine_factory, url, item_link):
    section = ({"type": "feature_cards", "items": [{"url": url}]} if item_link
               else {"type": "cta", "cta_url": url})
    with pytest.raises(ValueError):
        engine_factory(PUBLIC_PAGES_CONFIG={"custom_pages": [{
            "slug": "safe-slug", "title": "Links", "sections": [section],
        }]})


@pytest.mark.parametrize("url", ["http://example.test/info", "https://example.test/info?q=yes&n=2",
                                 "/contact", "/p/our-process#details", ""])
def test_current_safe_links_accepted_and_rendered(engine_app, url):
    override = {"custom_pages": [{"slug": "links", "title": "Links", "sections": [
        {"type": "cta", "cta_url": url, "cta_label": "Safe CTA"},
        {"type": "feature_cards", "items": [{"url": url, "label": "Safe item"}]},
    ]}]}
    public_pages.validate_public_settings(PRESETS[0], override)
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG=override)
    page = body(engine_app, "/p/links")
    if url:
        assert page.count(f'href="{escape(url)}"') >= 2
        assert "Safe CTA" in page and "Safe item" in page
    else:
        assert "Safe CTA" not in page and "Safe item" not in page


@pytest.mark.parametrize("route", ["/about", "/faq", "/schedule-work", "/thank-you"])
def test_legacy_pages_do_not_link_disabled_quote_or_contact(engine_app, route):
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"pages": {
        "quote_request": {"enabled": False}, "contact": {"enabled": False},
    }})
    page = body(engine_app, route)
    assert 'href="/quote-request"' not in page
    assert 'href="/request-quote"' not in page
    assert 'href="/contact"' not in page


def test_explicit_empty_trust_items_do_not_restore_default_claims(engine_app):
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"home_blocks": [
        {"type": "trust_highlights", "items": []},
    ]})
    page = body(engine_app)
    assert "Clear next steps" not in page
    assert "Photo-friendly intake" not in page


def test_request_snapshot_reuses_manifest_without_cross_request_staleness(engine_app, monkeypatch):
    original = public_pages._manifest
    calls = []

    def tracked(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(public_pages, "_manifest", tracked)
    body(engine_app)
    # Presets are already cached by startup; dozens of helpers share one override parse.
    assert len(calls) == 1
    edit_registry(engine_app, PUBLIC_PAGES_CONFIG={"home_blocks": ["quote_cta"]})
    assert blocks(engine_app) == ["quote_cta"]


INVALID_MANIFESTS = [
    None, "{}", 1, {"unknown": []}, {"home_blocks": "hero"},
    {"home_blocks": ["unknown"]}, {"home_blocks": [{"type": "hero", "enabled": "false"}]},
    {"pages": {"unknown": {}}}, {"pages": {"home": {"title": 123}}},
    {"pages": {"home": {"enabled": 1}}}, {"pages": {"home": {"show_in_nav": "yes"}}},
    {"pages": {"home": {"order": True}}}, {"pages": {"home": {"order": 1.5}}},
    {"pages": {"home": {"order": 1000001}}}, {"pages": {"home": {"order": -1000001}}},
    {"pages": [{"key": "contact"}, {"key": "contact"}]},
    {"pages": {"home": {"title": "x" * 241}}},
    {"pages": {"home": {"meta_description": "x" * 501}}},
    {"pages": {"home": {"title": "control\x00text"}}},
    {"pages": {"home": {"title": "surrogate\ud800"}}},
    {"custom_pages": [{"slug": "duplicate", "title": "One"}, {"slug": "duplicate", "title": "Two"}]},
    {"custom_pages": [{"slug": "empty-title", "title": " "}]},
    {"custom_pages": [{"slug": "unknown-section", "title": "Unknown", "sections": [{"type": "script"}]}]},
    {"pages": {"contact": {"sections": ["text"]}}},
    {"pages": {"contact": {"sections": [{"type": "text", "paragraphs": [1]}]}}},
    {"pages": {"contact": {"sections": [{"type": "feature_cards", "items": [{"html": "no"}]}]}}},
    {"home_blocks": ["hero"] * 31},
    {"custom_pages": [{"slug": f"page-{i}", "title": "Page"} for i in range(31)]},
    {"pages": {"contact": {"sections": [{"type": "text"}] * 51}}},
    {"home_blocks": [{"type": "custom_richtext", "paragraphs": ["p"] * 51}]},
    {"home_blocks": [{"type": "trust_highlights", "items": [{"title": "x"}] * 51}]},
    {"home_blocks": [{"type": "custom_richtext", "body": "x" * 10001}]},
]


@pytest.mark.parametrize("override", INVALID_MANIFESTS, ids=[f"invalid-{i}" for i in range(len(INVALID_MANIFESTS))])
def test_invalid_types_fields_duplicates_and_bounds_rejected_at_startup(engine_factory, override):
    with pytest.raises(ValueError):
        engine_factory(PUBLIC_PAGES_CONFIG=override)


@pytest.mark.parametrize("preset", ["unknown", "SPECIALTY_CONTRACTOR", "", None])
def test_unknown_preset_rejected_at_startup(engine_factory, preset):
    with pytest.raises(ValueError):
        engine_factory(SITE_PRESET=preset)


@pytest.mark.parametrize("shape", ["depth", "nodes", "total-text", "object-fields", "object-key", "cycle"])
def test_manifest_complexity_is_bounded_at_startup(engine_factory, shape):
    if shape == "depth":
        override = {}
        for _ in range(14):
            override = {"nested": override}
    elif shape == "nodes":
        # Individually legal string/list lengths, but over the global node budget.
        override = {"home_blocks": [{"type": "trust_highlights", "items": [
            {"title": "t", "text": "t", "question": "q", "answer": "a", "label": "l", "url": ""}
            for _ in range(50)
        ]} for _ in range(30)]}
    elif shape == "total-text":
        override = {"home_blocks": [{"type": "custom_richtext", "body": "x" * 10000}
                                     for _ in range(11)]}
    elif shape == "object-fields":
        override = {f"field-{index}": "" for index in range(65)}
    elif shape == "object-key":
        override = {"x" * 81: ""}
    else:
        override = {}
        override["cycle"] = override
    with pytest.raises(ValueError, match="PUBLIC_PAGES_CONFIG"):
        engine_factory(PUBLIC_PAGES_CONFIG=override)


def test_validation_does_not_mutate_caller_lists_and_rejects_non_json_objects():
    override = {"home_blocks": ["hero"], "custom_pages": [{
        "slug": "typed", "title": "Typed", "sections": [{"type": "paragraphs", "paragraphs": ["Text"]}],
    }]}
    before = deepcopy(override)
    public_pages.validate_public_settings(PRESETS[0], override)
    assert override == before
    for invalid in ({"home_blocks": ("hero",)}, {"home_blocks": {"hero"}}, {"pages": {"home": {"title": object()}}}):
        with pytest.raises(ValueError):
            public_pages.validate_public_settings(PRESETS[0], invalid)


def test_invalid_tenant_manifest_is_validated_at_startup(engine_factory, tmp_path):
    with pytest.raises(ValueError):
        engine_factory({"broken": {"hosts": ["broken.engine.test"],
                                   "database_uri": f"sqlite:///{tmp_path / 'never.sqlite3'}",
                                   "settings": {"PUBLIC_PAGES_CONFIG": {"home_blocks": ["unknown"]}}}})
    assert not (tmp_path / "never.sqlite3").exists()


@pytest.mark.parametrize("preset", PRESETS)
def test_cli_preset_provisions_real_migrations_and_immediate_domain(engine_factory, preset):
    app = engine_factory()
    result = app.test_cli_runner().invoke(args=[
        "tenant", "create", "created", "--domain", "created.engine.test", "--preset", preset,
        "--settings", json.dumps({"BUSINESS_NAME": "Created Engine", "ENABLE_SERVICES": True}),
    ])
    assert result.exit_code == 0, result.output + repr(result.exception)
    assert saved(app)["created"]["settings"]["SITE_PRESET"] == preset
    assert_migrated(app, "created")
    assert "Created Engine" in body(app, slug="created")
    expected = 200 if preset == "specialty_contractor" else 404
    assert get(app, "/p/our-process", "created").status_code == expected


def test_cli_unknown_preset_has_no_database_storage_or_registry_side_effect(engine_factory):
    app = engine_factory()
    before = checksum(app)
    result = app.test_cli_runner().invoke(args=[
        "tenant", "create", "rejected", "--domain", "rejected.engine.test", "--preset", "unknown",
    ])
    assert result.exit_code != 0 and "Invalid value" in result.output
    assert checksum(app) == before and "rejected" not in saved(app)
    assert "rejected" not in app.extensions["tenancy"].tenants
    assert not (Path(app.instance_path) / "tenants" / "rejected").exists()
    assert get(app, slug="rejected").status_code == 404


def test_superadmin_controls_and_provisioned_uppercase_public_fields(engine_factory):
    app = engine_factory()
    client = login(app)
    dashboard = client.get(CONTROL_PATH, base_url=CONTROL_URL).get_data(as_text=True)
    assert '<select name="SITE_PRESET">' in dashboard
    assert '<textarea name="PUBLIC_PAGES_CONFIG"' in dashboard
    for preset in PRESETS:
        assert f'<option value="{preset}"' in dashboard
    override = {"pages": {"contact": {"title": "Created contact"}}}
    response = operator_post(client, "create", slug="created", domains="created.engine.test",
                             BUSINESS_NAME="Created Engine", SITE_PRESET="specialty_contractor",
                             PUBLIC_PAGES_CONFIG=json.dumps(override), ENABLE_SERVICES="on", ENABLE_GALLERY="on")
    assert response.status_code == 302
    assert saved(app)["created"]["settings"]["PUBLIC_PAGES_CONFIG"] == override
    assert saved(app)["created"]["settings"]["SITE_PRESET"] == "specialty_contractor"
    assert_migrated(app, "created")
    assert "Created contact" in body(app, "/contact", "created")
    assert get(app, "/p/our-process", "created").status_code == 200
    dashboard = client.get(CONTROL_PATH, base_url=CONTROL_URL).get_data(as_text=True)
    row = re.search(r'<tr id="tenant-created">(.*?)</tr>', dashboard, re.S).group(1)
    assert '<option value="specialty_contractor" selected' in row
    textarea = re.search(r'<textarea name="PUBLIC_PAGES_CONFIG"[^>]*>(.*?)</textarea>', row, re.S).group(1)
    assert json.loads(textarea) == override
    assert "home_blocks" not in textarea  # Persisted overrides, never an expanded preset.


def test_superadmin_edits_apply_immediately_and_preserve_absent_public_fields(engine_app):
    client = login(engine_app)
    fields = {"slug": "alpha", "ENABLE_SERVICES": "on", "ENABLE_GALLERY": "on", "ENABLE_SCHEDULING": "on"}
    override = {"pages": {"contact": {"title": "Operator contact"}}, "home_blocks": ["hero"]}
    assert operator_post(client, "edit", **fields, SITE_PRESET="specialty_contractor",
                         PUBLIC_PAGES_CONFIG=json.dumps(override)).status_code == 302
    assert "Operator contact" in body(engine_app, "/contact")
    assert blocks(engine_app) == ["hero"]
    assert get(engine_app, "/p/our-process").status_code == 200
    assert operator_post(client, "edit", **fields, BUSINESS_NAME="Renamed Engine").status_code == 302
    settings = saved(engine_app)["alpha"]["settings"]
    assert settings["SITE_PRESET"] == "specialty_contractor" and settings["PUBLIC_PAGES_CONFIG"] == override
    assert settings["BUSINESS_EMAIL"] == "alpha@engine.test"
    assert "Renamed Engine" in body(engine_app) and "Operator contact" in body(engine_app, "/contact")
    assert operator_post(client, "edit", **fields, SITE_PRESET="minimal_quote_funnel").status_code == 302
    assert saved(engine_app)["alpha"]["settings"]["PUBLIC_PAGES_CONFIG"] == override
    assert get(engine_app, "/p/our-process").status_code == 404
    assert get(engine_app, "/services").status_code == 404
    assert operator_post(client, "edit", **fields, PUBLIC_PAGES_CONFIG="{}").status_code == 302
    assert saved(engine_app)["alpha"]["settings"]["SITE_PRESET"] == "minimal_quote_funnel"
    assert "Operator contact" not in body(engine_app, "/contact")
    assert get(engine_app, "/p/our-process", "beta").status_code == 200


@pytest.mark.parametrize("raw", ["", "{}", "[]"])
def test_superadmin_empty_public_override_reset_semantics(engine_app, raw):
    client = login(engine_app)
    fields = {"slug": "beta", "ENABLE_SERVICES": "on", "ENABLE_GALLERY": "on", "ENABLE_SCHEDULING": "on"}
    override = {"custom_pages": [], "home_blocks": ["quote_cta"],
                "pages": {"contact": {"title": "Temporary title"}}}
    assert operator_post(client, "edit", **fields, PUBLIC_PAGES_CONFIG=json.dumps(override)).status_code == 302
    assert "Temporary title" in body(engine_app, "/contact", "beta")
    assert operator_post(client, "edit", **fields, PUBLIC_PAGES_CONFIG=raw).status_code == 302
    assert saved(engine_app)["beta"]["settings"]["PUBLIC_PAGES_CONFIG"] == ([] if raw == "[]" else {})
    assert "Temporary title" not in body(engine_app, "/contact", "beta")
    assert get(engine_app, "/p/our-process", "beta").status_code == 200
    assert blocks(engine_app, "beta") == ([] if raw == "[]" else [
        "hero", "trust_highlights", "gallery_preview", "services_preview", "quote_cta",
    ])


@pytest.mark.parametrize("fields", [
    {"SITE_PRESET": "unknown"}, {"PUBLIC_PAGES_CONFIG": "{"},
    {"PUBLIC_PAGES_CONFIG": '{"pages": {}, "pages": {}}'},
    {"PUBLIC_PAGES_CONFIG": '{"pages": {"home": {"order": NaN}}}'},
    {"PUBLIC_PAGES_CONFIG": '{"home_blocks": ["unknown"]}'},
])
@pytest.mark.parametrize("action", ["edit", "create"])
def test_superadmin_invalid_public_settings_leave_registry_checksum_unchanged(engine_app, fields, action):
    client = login(engine_app)
    before = checksum(engine_app)
    settings = saved(engine_app)
    response = operator_post(client, action, slug="alpha" if action == "edit" else "rejected",
                             domains="alpha.engine.test" if action == "edit" else "rejected.engine.test",
                             BUSINESS_NAME="Must not persist", **fields)
    assert response.status_code == 302
    assert checksum(engine_app) == before and saved(engine_app) == settings
    dashboard = client.get(CONTROL_PATH, base_url=CONTROL_URL).get_data(as_text=True)
    assert "flash-error" in dashboard
    assert "Alpha Engine" in body(engine_app)
    assert not (Path(engine_app.instance_path) / "tenants" / "rejected").exists()