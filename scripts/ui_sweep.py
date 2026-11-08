r"""UI sweep: walk every GET route in headless Chrome at several widths.

This is the visual regression net that the test suite does not provide. The
pytest suite asserts text contracts; it cannot see layout, overflow, broken
images, or console errors. Run this before and after a UI/UX pass and diff the
screenshots / report.

Usage (from the repo root):

    .\.venv\Scripts\python.exe scripts\ui_sweep.py
    .\.venv\Scripts\python.exe scripts\ui_sweep.py --widths 390,1440 --preset all
    .\.venv\Scripts\python.exe scripts\ui_sweep.py --matrix
    .\.venv\Scripts\python.exe scripts\ui_sweep.py --site-matrix --public-only --widths 390,768,1440
    .\.venv\Scripts\python.exe scripts\ui_sweep.py --headed --only /admin/calendar

What it does:

  1. Builds an isolated SQLite database in the run folder (never touches dev data)
     and seeds predictable demo records: long names, quoted requests, appointments,
     recurring work, staff, gallery items.
  2. Serves the app from that database on a random loopback port.
  3. Logs in through the real login form (CSRF included).
  4. Visits every GET route at each width and records status, horizontal overflow
     with the offending elements, broken images, missing alt text, heading order,
     console errors, page errors and failed requests.
  5. Saves a full-page screenshot per route per width, plus report.json and
     summary.md.

Exit code is 1 when anything at error severity was found, so it can gate a commit.

Requires: pip install playwright  (browsers come from installed Chrome via
--browser chrome, or `playwright install chromium` for the bundled build).
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import logging
import re
import shutil
import sys
import threading
import traceback
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SWEEP_EMAIL = "sweep@example.test"
SWEEP_PASSWORD = "sweep-password-123"

# Feature-flag presets. "all" is the default because most work happens with every
# optional module switched on; the others prove the template still holds together
# when a customer turns modules off.
PRESETS: dict[str, dict[str, bool]] = {
    "all": {
        "ENABLE_SERVICES": True,
        "ENABLE_GALLERY": True,
        "ENABLE_SCHEDULING": True,
        "ENABLE_STAFF_MANAGEMENT": True,
        "ENABLE_CUSTOMER_RECORDS": True,
        "ENABLE_CALENDAR": True,
        "ENABLE_RECURRING_WORK": True,
    },
    "core": {
        "ENABLE_SERVICES": True,
        "ENABLE_GALLERY": False,
        "ENABLE_SCHEDULING": False,
        "ENABLE_STAFF_MANAGEMENT": False,
        "ENABLE_CUSTOMER_RECORDS": False,
        "ENABLE_CALENDAR": False,
        "ENABLE_RECURRING_WORK": False,
    },
    "off": {
        "ENABLE_SERVICES": False,
        "ENABLE_GALLERY": False,
        "ENABLE_SCHEDULING": False,
        "ENABLE_STAFF_MANAGEMENT": False,
        "ENABLE_CUSTOMER_RECORDS": False,
        "ENABLE_CALENDAR": False,
        "ENABLE_RECURRING_WORK": False,
    },
    "scheduling": {
        "ENABLE_SERVICES": True,
        "ENABLE_GALLERY": False,
        "ENABLE_SCHEDULING": True,
        "ENABLE_STAFF_MANAGEMENT": True,
        "ENABLE_CUSTOMER_RECORDS": True,
        "ENABLE_CALENDAR": True,
        "ENABLE_RECURRING_WORK": False,
    },
    "content": {
        "ENABLE_SERVICES": True,
        "ENABLE_GALLERY": True,
        "ENABLE_SCHEDULING": False,
        "ENABLE_STAFF_MANAGEMENT": False,
        "ENABLE_CUSTOMER_RECORDS": False,
        "ENABLE_CALENDAR": False,
        "ENABLE_RECURRING_WORK": False,
    },
}

# Pages that exist only as redirects or that we intentionally exercise elsewhere.
SKIP_ENDPOINTS = {
    "static",
    "auth.login",  # covered by the login step itself
    "auth.logout",  # POST-only
    "legacy_login_redirect",
    "legacy_dashboard_login_redirect",
    "admin.download_import_template",  # triggers a file download, not a page
}

# Route parameters that we can satisfy from seeded rows, keyed by converter+name.
PARAM_ALIASES = {
    "request_id": "quote_request",
    "quote_request_id": "quote_request",
    "appointment_id": "appointment",
    "customer_id": "customer",
    "staff_member_id": "staff_member",
    "recurring_work_id": "recurring_work",
    "quote_id": "request_quote",
    "note_id": "request_note",
    "item_id": "gallery_item",
    "service_id": "service_option",
    "address_id": "customer_address",
    "availability_id": "staff_availability",
    "customer_note_id": "customer_note",
}

SITECONFIG_PLACEHOLDER = "Sweep Sweep Sweep"

SITE_PRESETS = ("local_service_business", "specialty_contractor", "minimal_quote_funnel")
PUBLIC_PAGE_ENDPOINTS = {
    "main.index": "home", "main.services_page": "services", "main.gallery_page": "gallery",
    "main.service_area_page": "service_area", "main.about_page": "about",
    "main.contact_page": "contact", "main.faq_page": "faq",
    "main.quote_request": "quote_request", "main.schedule_work": "schedule_work",
}


def sweep_manifest(site_preset: str) -> dict:
    """Keep kit defaults, adding a hidden structured page to exercise custom discovery."""
    presets = json.loads((REPO_ROOT / "app/data/site_presets.json").read_text(encoding="utf-8"))
    return {"custom_pages": [*presets[site_preset].get("custom_pages", []), {
        "slug": "sweep-content", "title": "Project planning guide", "show_in_nav": False,
        "sections": [
            {"type": "text", "title": "Plan your project", "paragraphs": ["Share the work, location, and timing."]},
            {"type": "feature_cards", "title": "What to prepare", "items": [
                {"title": "Project details", "text": "A clear description helps us plan."}]},
            {"type": "checklist", "title": "Before you start", "checklist": ["Describe the scope.", "Gather photos."]},
            {"type": "faq", "title": "Common questions", "items": [
                {"question": "What happens next?", "answer": "We review your details and follow up."}]},
            {"type": "quote_cta", "title": "Discuss your project"},
        ],
    }]}


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def seed_demo_data(ids_out: dict[str, int]) -> dict[str, int]:
    """Insert predictable demo records. Returns a map of name -> primary key."""

    from app.extensions import db
    from app.models import (
        Appointment,
        AppointmentStaffAssignment,
        Customer,
        CustomerAddress,
        CustomerField,
        CustomerNote,
        GalleryItem,
        QuoteRequest,
        RecurringWork,
        RequestNote,
        RequestQuote,
        ServiceOption,
        StaffAvailability,
        StaffMember,
        User,
    )

    user = User(email=SWEEP_EMAIL)
    user.set_password(SWEEP_PASSWORD)
    db.session.add(user)
    db.session.flush()

    services = {
        "windows": ServiceOption(
            name="Window Cleaning",
            description="Interior and exterior glass, frames and sills.",
            is_active=True,
            display_order=1,
        ),
        "pressure": ServiceOption(
            name="Pressure Washing",
            description="Driveways, walkways and siding soft wash.",
            is_active=True,
            display_order=2,
        ),
        "gutters": ServiceOption(
            name="Gutter Clearing",
            description="Seasonal debris removal and downspout flush.",
            is_active=False,
            display_order=3,
        ),
    }
    db.session.add_all(services.values())

    staff_lead = StaffMember(
        display_name="Example Crew Lead",
        phone="(555) 010-0142",
        email="crew.lead@example.test",
        role_title="Lead Technician",
        worker_type="employee",
        status="active",
        compensation_amount=Decimal("22.50"),
        compensation_frequency="hourly",
        notes="Primary technician for scheduled work.",
        services=[services["windows"], services["pressure"]],
    )
    staff_long = StaffMember(
        display_name="Second Technician With A Deliberately Long Display Name",
        phone="(555) 010-0199",
        email="second.technician@example.test",
        role_title="Technician",
        worker_type="contractor",
        status="active",
        compensation_amount=Decimal("180.00"),
        compensation_frequency="daily",
        services=[services["pressure"]],
    )
    staff_inactive = StaffMember(
        display_name="Inactive Helper",
        worker_type="employee",
        status="inactive",
        services=[services["windows"]],
    )
    db.session.add_all([staff_lead, staff_long, staff_inactive])
    db.session.flush()

    db.session.add_all(
        [
            StaffAvailability(
                staff_member_id=staff_lead.id,
                day_of_week=day,
                start_time=time(8, 0),
                end_time=time(16, 30),
                notes="Standard shift",
            )
            for day in range(0, 5)
        ]
    )

    customer = Customer(
        primary_name="Example Residential Customer",
        individual_name="Example Residential Customer",
        display_name_preference="individual",
        primary_email="example.customer@example.test",
        primary_phone="(555) 010-0110",
        primary_city="Daytona Beach",
        billing_amount=Decimal("185.00"),
        billing_frequency="monthly",
    )
    customer_long = Customer(
        primary_name="Coastal Property Management Group of Greater Daytona Beach",
        business_name="Coastal Property Management Group of Greater Daytona Beach",
        display_name_preference="business",
        primary_email="accounts@coastal.example.test",
        primary_phone="(555) 010-0188",
        primary_city="Ormond Beach",
    )
    customer_empty = Customer(primary_name="Minimal Record Customer")
    db.session.add_all([customer, customer_long, customer_empty])
    db.session.flush()

    for value in ["example.customer@example.test", "(555) 010-0110"]:
        db.session.add(
            CustomerField(
                customer_id=customer.id,
                kind="email" if "@" in value else "phone",
                value=value,
                is_primary=True,
            )
        )
    db.session.add(
        CustomerAddress(
            customer_id=customer.id,
            address_line_1="123 Example Lane",
            address_line_2="Unit 4",
            state="FL",
            zip_code="32114",
            is_billing=True,
        )
    )
    db.session.add(
        CustomerNote(
            customer_id=customer.id,
            note_text="Customer prefers morning appointments and texts before arrival.",
            created_by=user.id,
        )
    )

    quote_request = QuoteRequest(
        request_number=0,
        full_name="Example Residential Customer",
        phone="(555) 010-0110",
        email="example.customer@example.test",
        city="Daytona Beach",
        status="New",
        additional_notes=(
            "Two story home with hard water stains on the north-facing windows. "
            "Would like a recurring schedule if the first visit goes well."
        ),
        customer=customer,
        services=[services["windows"], services["pressure"]],
        draft_quote_amount=Decimal("240.00"),
        draft_quote_billing_frequency="monthly",
        draft_quote_description="Exterior glass plus driveway wash, monthly.",
    )
    quoted_request = QuoteRequest(
        request_number=0,
        full_name="Coastal Property Management Group",
        phone="(555) 010-0188",
        email="accounts@coastal.example.test",
        city="Ormond Beach",
        status="Quoted",
        customer=customer_long,
        services=[services["pressure"]],
    )
    empty_request = QuoteRequest(
        request_number=0,
        full_name="Walk In Customer",
        city="Port Orange",
        status="Viewed",
    )
    db.session.add(quote_request)
    db.session.flush()  # request_number is assigned by a before_insert hook per row
    db.session.add(quoted_request)
    db.session.flush()
    db.session.add(empty_request)
    db.session.flush()

    db.session.add(
        RequestNote(
            quote_request_id=quote_request.id,
            note_text="Called back, left voicemail about the recurring option.",
            created_by=user.id,
        )
    )

    accepted_quote = RequestQuote(
        quote_request_id=quoted_request.id,
        amount=Decimal("1250.00"),
        description="Quarterly pressure wash for six buildings.",
        billing_frequency="quarterly",
        decision="Accepted",
    )
    pending_quote = RequestQuote(
        quote_request_id=quoted_request.id,
        amount=Decimal("400.00"),
        description="One time sidewalk wash.",
        billing_frequency="one_time",
        decision="Pending",
    )
    db.session.add_all([accepted_quote, pending_quote])

    appointment = Appointment(
        customer=customer,
        quote_request=quote_request,
        title="Window Cleaning - Example Residential Customer",
        scheduled_date=date.today(),
        start_time=time(9, 0),
        end_time=time(10, 30),
        status="Scheduled",
        services=[services["windows"]],
        customer_notes="Gate code 4412.",
        internal_notes="Bring the tall ladder for the second story.",
    )
    second_appointment = Appointment(
        customer=customer_long,
        title="Pressure Washing - Coastal Property Management",
        scheduled_date=date.today() + timedelta(days=1),
        start_time=time(13, 0),
        end_time=time(15, 0),
        status="Requested",
        services=[services["pressure"]],
    )
    db.session.add_all([appointment, second_appointment])
    db.session.flush()

    db.session.add(
        AppointmentStaffAssignment(
            appointment_id=appointment.id,
            staff_member_id=staff_lead.id,
            assignment_role="Lead",
        )
    )

    recurring = RecurringWork(
        customer=customer,
        quote_request=quote_request,
        title="Monthly Window Cleaning",
        frequency="monthly",
        day_of_month=1,
        starts_on=date.today(),
        start_time=time(9, 0),
        end_time=time(11, 0),
        billing_amount=Decimal("185.00"),
        billing_frequency="monthly",
        status="active",
        notes="Skip December per customer request.",
    )
    db.session.add(recurring)
    db.session.flush()

    for index, title in enumerate(
        ["Lobby glass after hours", "Driveway soft wash", "Storefront detail"]
    ):
        db.session.add(
            GalleryItem(
                image_path="assets/images/Logowhite.png",
                title=title,
                caption="Example gallery caption for layout testing.",
                service_id=services["windows"].id,
                featured=index == 0,
                is_active=True,
                display_order=index + 1,
            )
        )

    db.session.commit()

    ids_out.clear()
    ids_out.update(
        {
            "user": user.id,
            "service_option": services["windows"].id,
            "staff_member": staff_lead.id,
            "customer": customer.id,
            "customer_long": customer_long.id,
            "customer_empty": customer_empty.id,
            "quote_request": quote_request.id,
            "quote_request_quoted": quoted_request.id,
            "quote_request_empty": empty_request.id,
            "appointment": appointment.id,
            "recurring_work": recurring.id,
            "request_quote": accepted_quote.id,
            "gallery_item": 1,
        }
    )
    return ids_out


# ---------------------------------------------------------------------------
# App + server plumbing
# ---------------------------------------------------------------------------


def build_app(run_dir: Path, flags: dict[str, bool], db_path: Path,
              site_preset: str = "local_service_business"):
    """Override configuration before extension binding; never inherit operator state."""
    from functools import partial
    from unittest.mock import patch
    from flask import Flask
    import app as app_module

    instance = (run_dir / "instance").resolve()
    instance.mkdir(parents=True, exist_ok=True)
    overrides = {
        "SECRET_KEY": "ui-sweep-secret-key", "WTF_CSRF_ENABLED": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite+pysqlite:///{db_path.resolve().as_posix()}",
        "UPLOAD_FOLDER": str((run_dir / "uploads").resolve()),
        "TENANTS": None, "TENANTS_JSON": "", "TENANT_REGISTRY_FILE": "", "TENANT_ALLOW_DEFAULT": True,
        "SUPERADMIN_PASSWORD": "", "SUPERADMIN_HOST": "", "SUPERADMIN_PATH": "/platform/control",
        "SITE_THEME": "quite-clear", "SITE_PRESET": site_preset,
        "PUBLIC_PAGES_CONFIG": sweep_manifest(site_preset),
        "RECAPTCHA_ENABLED": False, "EMAIL_ENABLED": False, "RATE_LIMIT_ENABLED": False,
        "ERROR_WEBHOOK_URL": "", "TRUST_PROXY": False, "CANONICAL_ORIGIN": "",
        "BUSINESS_NAME": SITECONFIG_PLACEHOLDER, "TESTING": False, "DEBUG": False,
        **flags,
    }
    # Scope the constructor override to creation, as the isolated pytest fixtures do.
    with patch.object(app_module, "Flask", partial(Flask, instance_path=str(instance))):
        app = app_module.create_app("testing", overrides)

    @app.get("/favicon.ico")
    def sweep_favicon():
        return app.send_static_file("assets/images/Logowhite.png")

    return app


def assert_engine_matches(app, db_path: Path) -> None:
    """Fail loudly if the sweep is not actually pointed at the sweep database."""
    from app.extensions import db

    with app.app_context():
        actual = db.engine.url.database
    if not actual or Path(actual).resolve() != db_path.resolve():
        raise RuntimeError(
            "sweep app is not pointed at the sweep database "
            f"(expected {db_path}, got {actual!r})"
        )


def start_server(app):
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_port


@dataclass
class RouteTarget:
    path: str
    endpoint: str
    is_admin: bool
    expected_status: int = 200


# Which feature flag owns a route, by substring of the endpoint name. A route whose
# module is switched off is skipped rather than reported as a 404 - that is the
# behaviour a customer with that configuration expects to see.
ENDPOINT_FLAG_HINTS: tuple[tuple[str, str], ...] = (
    ("gallery", "ENABLE_GALLERY"),
    ("content_index", "ENABLE_GALLERY"),
    ("gallery_page", "ENABLE_GALLERY"),
    ("services", "ENABLE_SERVICES"),
    ("service_settings", "ENABLE_SERVICES"),
    ("services_page", "ENABLE_SERVICES"),
    ("calendar", "ENABLE_CALENDAR"),
    ("schedule_work", "ENABLE_SCHEDULING"),
    ("scheduled_work", "ENABLE_SCHEDULING"),
    ("appointment", "ENABLE_SCHEDULING"),
    ("staff", "ENABLE_STAFF_MANAGEMENT"),
    ("customer", "ENABLE_CUSTOMER_RECORDS"),
    ("recurring", "ENABLE_RECURRING_WORK"),
)


def route_flag(endpoint: str) -> str | None:
    for hint, flag in ENDPOINT_FLAG_HINTS:
        if hint in endpoint:
            return flag
    return None


def collect_routes(app, ids: dict[str, int], flags: dict[str, bool],
                   public_only: bool = False) -> list[RouteTarget]:
    """Turn the URL map into a concrete list of GET-able paths."""
    from app.services.public_pages import get_public_manifest, page_enabled

    with app.app_context():
        manifest = get_public_manifest()
        enabled = {endpoint: page_enabled(key) for endpoint, key in PUBLIC_PAGE_ENDPOINTS.items()}

    today = date.today()
    dynamic_fill = {
        "year": str(today.year),
        "month": str(today.month),
        "day": str(today.day),
        "file_format": "xlsx",
        "entity_type": "customers",
    }

    targets: list[RouteTarget] = []
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.endpoint in SKIP_ENDPOINTS:
            continue
        if rule.endpoint.startswith("superadmin."):
            continue  # Fleet control requires a separate operator/host fixture.
        if public_only and not rule.endpoint.startswith("main."):
            continue
        if rule.endpoint == "main.custom_page":
            for page in manifest["custom_pages"]:
                targets.append(RouteTarget(f"/p/{page['slug']}", rule.endpoint, False,
                                           200 if page["enabled"] else 404))
            continue
        expected = 200
        if rule.endpoint in enabled and not enabled[rule.endpoint]:
            key = PUBLIC_PAGE_ENDPOINTS[rule.endpoint]
            expected = (302 if key == "schedule_work" and manifest["pages"][key]["enabled"]
                        and not flags.get("ENABLE_SCHEDULING", False) else 404)
        elif not flags.get(route_flag(rule.endpoint) or "", True):
            continue
        path = str(rule)
        skip = False
        for match in re.finditer(r"<(?:\w+:)?(\w+)>", path):
            name = match.group(1)
            if name in dynamic_fill:
                path = path.replace(match.group(0), dynamic_fill[name], 1)
                continue
            alias = PARAM_ALIASES.get(name, name)
            if alias in ids:
                path = path.replace(match.group(0), str(ids[alias]), 1)
                continue
            skip = True
            break
        if skip:
            print(f"  [skip] could not build a URL for {rule.endpoint} ({rule})")
            continue
        targets.append(
            RouteTarget(
                path=path,
                endpoint=rule.endpoint,
                is_admin=path.startswith("/admin"),
                expected_status=expected,
            )
        )
    targets.sort(key=lambda item: (not item.is_admin, item.path))
    return targets


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

MEASURE_JS = r"""
() => {
  const vw = window.innerWidth;
  const doc = document.documentElement;
  const clipped = (el) => {
    // Content inside a scroll container is not page overflow - that is the
    // container doing its job. Walk ancestors looking for a clipping box.
    let node = el.parentElement;
    while (node && node !== document.body) {
      const style = getComputedStyle(node);
      if (['auto', 'scroll', 'hidden', 'clip'].includes(style.overflowX)) return true;
      node = node.parentElement;
    }
    return false;
  };
  const offenders = [];
  for (const el of document.querySelectorAll('body *')) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    if (rect.right > vw + 1 || rect.left < -1) {
      if (clipped(el)) continue;
      offenders.push({
        tag: el.tagName.toLowerCase(),
        cls: (typeof el.className === 'string' ? el.className : '').slice(0, 70),
        id: el.id || '',
        width: Math.round(rect.width),
        right: Math.round(rect.right),
      });
    }
  }
  offenders.sort((a, b) => b.width - a.width);
  const images = [...document.images];
  const controls = [...document.querySelectorAll('input, select, textarea')].filter(
    (el) => !['hidden', 'submit', 'button', 'checkbox', 'radio'].includes(el.type)
  );

  // ---- contrast audit -------------------------------------------------
  const parseColor = (value) => {
    const match = value && value.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
    if (!match) return null;
    return {
      r: Number(match[1]), g: Number(match[2]), b: Number(match[3]),
      a: match[4] === undefined ? 1 : Number(match[4]),
    };
  };
  const luminance = ({ r, g, b }) => {
    const channel = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const ratio = (first, second) => {
    const a = luminance(first);
    const b = luminance(second);
    const [high, low] = a > b ? [a, b] : [b, a];
    return (high + 0.05) / (low + 0.05);
  };
  const effectiveBackground = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const style = getComputedStyle(node);
      const parsed = parseColor(style.backgroundColor);
      if (parsed && parsed.a >= 0.85) return parsed;
      node = node.parentElement;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const composite = (foreground, background) => ({
    r: foreground.r * foreground.a + background.r * (1 - foreground.a),
    g: foreground.g * foreground.a + background.g * (1 - foreground.a),
    b: foreground.b * foreground.a + background.b * (1 - foreground.a),
    a: 1,
  });
  const contrastIssues = [];
  for (const el of document.querySelectorAll('body *')) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) < 0.5) continue;
    const ownText = [...el.childNodes]
      .filter((node) => node.nodeType === 3 && node.textContent.trim().length > 2)
      .map((node) => node.textContent.trim())
      .join(' ');
    if (!ownText) continue;
    const foreground = parseColor(style.color);
    if (!foreground) continue;
    if (foreground.a < 0.6) continue;
    const background = effectiveBackground(el);
    const fontSize = parseFloat(style.fontSize) || 16;
    const bold = Number(style.fontWeight) >= 700;
    const large = fontSize >= 24 || (bold && fontSize >= 18.66);
    const minimum = large ? 3 : 4.5;
    const value = ratio(composite(foreground, background), background);
    if (value < minimum) {
      contrastIssues.push({
        ratio: Math.round(value * 100) / 100,
        minimum,
        text: ownText.slice(0, 40),
        color: style.color,
        background: `rgb(${background.r}, ${background.g}, ${background.b})`,
        source: (el.tagName.toLowerCase() + '.' + (typeof el.className === 'string' ? el.className : '')).slice(0, 50),
      });
    }
  }
  contrastIssues.sort((a, b) => a.ratio - b.ratio);
  return {
    title: document.title,
    viewport: vw,
    scrollWidth: doc.scrollWidth,
    overflow: doc.scrollWidth > vw + 1,
    offenders: offenders.slice(0, 8),
    offenderCount: offenders.length,
    h1: [...document.querySelectorAll('h1')].map((el) => el.textContent.trim().slice(0, 90)),
    h2Count: document.querySelectorAll('h2').length,
    brokenImages: images
      .filter((img) => img.hasAttribute('src') || img.hasAttribute('srcset'))
      .filter((img) => !img.complete || img.naturalWidth === 0)
      .map((img) => img.currentSrc || img.src)
      .slice(0, 8),
    imagesWithoutAlt: images.filter((img) => !img.hasAttribute('alt')).length,
    unlabeledControls: controls
      .filter((el) => el.offsetParent !== null)
      .filter((el) => {
        if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
        if (el.labels && el.labels.length) return false;
        if (el.getAttribute('placeholder')) return false;
        return true;
      })
      .map((el) => `${el.tagName.toLowerCase()}[name=${el.name || '?'}]`)
      .slice(0, 8),
    buttonsWithoutName: [...document.querySelectorAll('button')]
      .filter((el) => !el.textContent.trim() && !el.getAttribute('aria-label') &&
                      !el.getAttribute('title') &&
                      !(el.querySelector('img[alt]') && el.querySelector('img[alt]').alt))
      .length,
    siteConfigLeak: document.body.innerText.includes('placeholder-business'),
    contrastIssues: contrastIssues.slice(0, 6),
    contrastIssueCount: contrastIssues.length,
    mainVisible: (() => {
      const main = document.querySelector('main');
      if (!main) return false;
      return main.getBoundingClientRect().height > 40;
    })(),
  };
}
"""


SLUG_OVERRIDES = {
    "/": "home",
    "/admin": "admin-login",
    "/admin/": "admin-dashboard",
}


def slug_for(path: str) -> str:
    if path in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[path]
    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    return slug or "root"


def unique_slug(base: str, used: dict[str, int]) -> str:
    """Keep /admin and /admin/ from writing over each other's screenshot."""

    count = used.get(base, 0) + 1
    used[base] = count
    return base if count == 1 else f"{base}-{count}"


def sweep_preset(*args, **kwargs) -> dict:
    """Release every acquired resource even if a matrix member fails during setup."""
    with ExitStack() as cleanup:
        return _sweep_preset(*args, cleanup=cleanup, **kwargs)


def _sweep_preset(
    playwright,
    args,
    run_dir: Path,
    preset_name: str,
    flags: dict[str, bool],
    db_path: Path,
    seed_needed: bool,
    site_preset: str = "local_service_business",
    *, cleanup: ExitStack,
) -> dict:
    from app.extensions import db

    ids: dict[str, int] = {}
    app = build_app(run_dir, flags, db_path, site_preset)

    def dispose_engines():
        with app.app_context():
            db.session.remove()
            engines = set(db.engines.values()) | set(app.extensions["tenancy"].engines.values())
            # Each disposal is independent; ExitStack still closes the rest if one fails.
            with ExitStack() as engines_cleanup:
                for engine in engines:
                    engines_cleanup.callback(engine.dispose)

    cleanup.callback(dispose_engines)
    assert_engine_matches(app, db_path)

    with app.app_context():
        if seed_needed:
            db.drop_all()
            db.create_all()
            seed_demo_data(ids)
            Path(run_dir / "ids.json").write_text(json.dumps(ids, indent=2), encoding="utf-8")
        else:
            saved = run_dir / "ids.json"
            ids.update(json.loads(saved.read_text(encoding="utf-8")))

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.logger.setLevel(logging.WARNING)
    routes = collect_routes(app, ids, flags, args.public_only)

    results: list[dict] = []
    browser = launch_browser(playwright, args)
    cleanup.callback(browser.close)
    context = browser.new_context(
        viewport={"width": args.widths[0], "height": 900},
        device_scale_factor=1,
    )
    cleanup.callback(context.close)
    server, port = start_server(app)
    cleanup.callback(server.server_close)
    cleanup.callback(server.shutdown)
    base = f"http://127.0.0.1:{port}"

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[dict] = []
    context.on("requestfailed", lambda r: failed_requests.append(
        {"url": r.url, "failure": (r.failure or "")}
    ))
    context.on("response", lambda r: failed_requests.append(
        {"url": r.url, "status": r.status}
    ) if r.status >= 400 else None)

    page = context.new_page()
    page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type in ("error", "warning") else None)
    page.on("pageerror", lambda err: page_errors.append(str(err)))

    try:
        if not args.public_only:
            login(page, base)
        for width in args.widths:
            page.set_viewport_size({"width": width, "height": 900})
            row_dir = run_dir / "screenshots" / preset_name / str(width)
            row_dir.mkdir(parents=True, exist_ok=True)
            used_slugs: dict[str, int] = {}

            for target in routes:
                if args.only and not any(token in target.path for token in args.only):
                    continue
                console_errors.clear()
                page_errors.clear()
                failed_requests.clear()
                record = {
                    "preset": preset_name,
                    "width": width,
                    "path": target.path,
                    "endpoint": target.endpoint,
                    "is_admin": target.is_admin,
                    "expected_status": target.expected_status,
                    "site_preset": site_preset,
                }
                try:
                    if target.expected_status != 200:
                        # Probe gates without following redirects or treating intentional 404s as asset errors.
                        response = context.request.get(base + target.path, max_redirects=0)
                        record["status"] = response.status
                        if target.expected_status == 302:
                            record["location"] = response.headers.get("location", "")
                            record["expected_location"] = "/quote-request"
                            from urllib.parse import urljoin
                            record["redirect_valid"] = urljoin(base + target.path, record["location"]) == base + "/quote-request"
                        response.dispose()
                        record["gate_probe"] = True
                        results.append(record)
                        print(".", end="", flush=True)
                        continue
                    response = page.goto(base + target.path, wait_until="networkidle", timeout=30000)
                    record["status"] = response.status if response else None
                    record["final_url"] = page.url.replace(base, "")
                    # Full-page captures include below-the-fold lazy images. Request/decode
                    # them before measuring, without hiding genuine download failures.
                    page.evaluate("""async () => {
                        await Promise.all([...document.images]
                            .filter(img => img.hasAttribute('src') || img.hasAttribute('srcset'))
                            .map(async img => {
                                img.loading = 'eager';
                                try { await img.decode(); } catch (_) { /* reported by metrics */ }
                            }));
                    }""")
                    record["metrics"] = page.evaluate(MEASURE_JS)
                    record["console"] = list(console_errors)
                    record["pageErrors"] = list(page_errors)
                    record["failedRequests"] = [
                        item for item in failed_requests
                        if "/favicon" not in item["url"]
                    ]
                    screenshot = row_dir / f"{unique_slug(slug_for(target.path), used_slugs)}.png"
                    page.screenshot(path=str(screenshot), full_page=True)
                    record["screenshot"] = str(screenshot.relative_to(run_dir))
                except Exception as exc:  # noqa: BLE001 - sweep must keep going
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    record["traceback"] = traceback.format_exc(limit=3)
                results.append(record)
                print(".", end="", flush=True)
            print(f"  [{preset_name}] {width}px done")
    finally:
        pass  # The outer ExitStack covers setup failures as well as visit failures.

    return {"preset": preset_name, "site_preset": site_preset, "flags": flags, "base": base, "results": results}


def launch_browser(playwright, args):
    attempts = [args.browser]
    for option in ("chrome", "chromium"):
        if option not in attempts:
            attempts.append(option)
    last_error: Exception | None = None
    for option in attempts:
        try:
            if option == "chrome":
                return playwright.chromium.launch(channel="chrome", headless=not args.headed)
            return playwright.chromium.launch(headless=not args.headed)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"could not launch a browser: {last_error}")


def login(page, base: str) -> None:
    page.goto(base + "/admin", wait_until="networkidle", timeout=30000)
    if page.locator('input[name="email"]').count() == 0:
        return  # already authenticated
    page.fill('input[name="email"]', SWEEP_EMAIL)
    page.fill('input[name="password"]', SWEEP_PASSWORD)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("networkidle")
    if page.locator('input[name="email"]').count() > 0:
        body = page.locator("body").inner_text()[:400]
        raise RuntimeError(f"login failed; page said: {body}")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def classify(record: dict) -> list[tuple[str, str]]:
    """Return (severity, message) pairs for one page visit."""

    issues: list[tuple[str, str]] = []
    if "error" in record:
        return [("error", f"navigation failed: {record['error']}")]

    status = record.get("status")
    metrics = record.get("metrics") or {}

    expected = record.get("expected_status", 200)
    if status != expected:
        issues.append(("error", f"HTTP {status}, expected {expected}"))
    if record.get("redirect_valid") is False:
        issues.append(("error", f"redirect {record.get('location')}, expected {record['expected_location']} on the sweep host"))
    if record.get("gate_probe"):
        return issues
    for err in record.get("pageErrors", []):
        issues.append(("error", f"JS exception: {err}"))
    if metrics.get("overflow"):
        offenders = ", ".join(
            f"{item['tag']}.{(item['cls'] or '').split(' ')[0]}[{item['width']}px]"
            for item in metrics.get("offenders", [])[:3]
        )
        issues.append(
            (
                "error",
                f"horizontal overflow: scrollWidth {metrics.get('scrollWidth')} "
                f"> viewport {metrics.get('viewport')} ({offenders})",
            )
        )
    for item in record.get("failedRequests", []):
        label = item.get("status") or item.get("failure")
        issues.append(("error", f"failed request {label}: {item['url']}"))
    for msg in record.get("console", []):
        if msg.startswith("error"):
            issues.append(("warn", f"console {msg[:160]}"))
    for url in metrics.get("brokenImages", []):
        issues.append(("warn", f"broken image: {url}"))
    if metrics.get("imagesWithoutAlt"):
        issues.append(("warn", f"{metrics['imagesWithoutAlt']} image(s) without alt attribute"))
    if metrics.get("unlabeledControls"):
        issues.append(
            ("warn", f"unlabeled control(s): {', '.join(metrics['unlabeledControls'])}")
        )
    if metrics.get("buttonsWithoutName"):
        issues.append(("warn", f"{metrics['buttonsWithoutName']} button(s) with no accessible name"))
    h1 = metrics.get("h1") or []
    if len(h1) != 1:
        issues.append(("warn", f"expected exactly 1 h1, found {len(h1)}"))
    if not metrics.get("mainVisible"):
        issues.append(("warn", "no visible <main> landmark"))
    if metrics.get("siteConfigLeak"):
        issues.append(("warn", "placeholder text leaked into the page"))
    for item in metrics.get("contrastIssues", []):
        issues.append(
            (
                "warn",
                f"contrast {item['ratio']}:1 below {item['minimum']} for "
                f"\"{item['text']}\" ({item['color']} on {item['background']}, {item['source']})",
            )
        )
    return issues


def write_report(run_dir: Path, runs: list[dict]) -> tuple[int, int]:
    rows = []
    errors = 0
    warnings = 0
    for run in runs:
        for record in run["results"]:
            issues = classify(record)
            errors += sum(1 for sev, _ in issues if sev == "error")
            warnings += sum(1 for sev, _ in issues if sev == "warn")
            rows.append({**record, "issues": issues})

    (run_dir / "report.json").write_text(
        json.dumps({"generated": date.today().isoformat(), "runs": [
            {"preset": r["preset"], "site_preset": r.get("site_preset"), "flags": r["flags"], "results": [
                {k: v for k, v in row.items() if k != "traceback"} for row in rows
                if row["preset"] == r["preset"]
            ]} for r in runs
        ]}, indent=2),
        encoding="utf-8",
    )

    # Collapse the same finding at several widths into one line - a page that
    # overflows at 390 and 768 is one bug, not two.
    lines = ["# UI sweep summary", ""]
    lines.append(f"{len(rows)} page visits, {errors} errors, {warnings} warnings.")
    lines.append("")
    for preset in dict.fromkeys(row["preset"] for row in rows):
        preset_rows = [row for row in rows if row["preset"] == preset]
        grouped: dict[tuple[str, str, str], set[int]] = {}
        for row in preset_rows:
            for severity, message in row["issues"]:
                key = (severity, row["path"], message)
                grouped.setdefault(key, set()).add(row["width"])
        lines.append(
            f"## preset: {preset} ({len(preset_rows)} visits, "
            f"{len(grouped)} unique findings)"
        )
        lines.append("")
        if not grouped:
            lines.extend(["- clean", ""])
            continue
        ordered = sorted(grouped.items(), key=lambda item: (item[0][0] != "error", item[0][1]))
        for (severity, path, message), widths in ordered:
            marker = "ERROR" if severity == "error" else "warn "
            width_label = ",".join(str(w) for w in sorted(widths))
            lines.append(f"- `{marker}` {path} @ {width_label}px - {message}")
        lines.append("")
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return errors, warnings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screenshot + layout sweep over every GET route.")
    parser.add_argument("--widths", default="390,768,1440",
                        help="comma separated viewport widths (default 390,768,1440)")
    parser.add_argument("--preset", default="all", choices=sorted(PRESETS),
                        help="feature-flag preset to sweep (default all)")
    parser.add_argument("--matrix", action="store_true",
                        help="sweep every preset instead of one")
    parser.add_argument("--site-preset", default=SITE_PRESETS[0], choices=SITE_PRESETS,
                        help="public blueprint (independent of the feature-flag preset)")
    parser.add_argument("--site-matrix", action="store_true", help="sweep all three public blueprints")
    parser.add_argument("--public-only", action="store_true", help="anonymous public routes only")
    parser.add_argument("--out", default="artifacts/ui-sweep", help="output root folder")
    parser.add_argument("--browser", default="chrome", choices=["chrome", "chromium"])
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--only", nargs="*", default=None,
                        help="limit to paths containing any of these substrings")
    parser.add_argument("--keep", action="store_true", help="keep previous runs (default: keep)")
    args = parser.parse_args(argv)
    args.widths = [int(w) for w in args.widths.split(",") if w.strip()]
    if not args.widths:
        parser.error("--widths must contain at least one number")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed. Run: .\\.venv\\Scripts\\python.exe -m pip install playwright")
        return 2

    from datetime import datetime

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = (REPO_ROOT / args.out / stamp).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"run folder: {run_dir}")

    presets = sorted(PRESETS) if args.matrix else [args.preset]
    sites = SITE_PRESETS if args.site_matrix else [args.site_preset]
    runs: list[dict] = []

    for site in sites:
        for preset in presets:
            name = f"{site}--{preset}"
            fixture_dir = run_dir / name
            fixture_dir.mkdir()
            print(f"preset {name}: {PRESETS[preset]}")
            try:
                # A crashed browser driver must not poison the remaining matrix members.
                with sync_playwright() as playwright:
                    runs.append(sweep_preset(playwright, args, fixture_dir, name,
                                             PRESETS[preset], fixture_dir / "sweep.db", True, site))
            except Exception as exc:  # noqa: BLE001 - keep failures in the report/exit status
                print(f"  preset {name} failed: {type(exc).__name__}: {exc}")
                runs.append({"preset": name, "site_preset": site, "flags": PRESETS[preset], "results": [
                    {"preset": name, "path": "<setup>", "width": 0,
                     "error": f"{type(exc).__name__}: {exc}"}]})

    for run in runs:
        for record in run["results"]:
            if "screenshot" in record:
                record["screenshot"] = f"{run['preset']}/{record['screenshot']}"

    if not runs:
        print("nothing was swept")
        return 2

    errors, warnings = write_report(run_dir, runs)
    print()
    print(f"errors:   {errors}")
    print(f"warnings: {warnings}")
    print(f"report:   {run_dir / 'summary.md'}")
    print(f"json:     {run_dir / 'report.json'}")
    print(f"shots:    {run_dir / 'screenshots'}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
