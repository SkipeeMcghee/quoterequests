# Page Inventory

The finish line for UI work on this template. Every page the app can render, what
gates it, and the states that have to look deliberate before a customer sees it.

How to use it: pick a page, walk its states at 390 / 768 / 1440, tick it off.
`scripts/ui_sweep.py` covers the mechanical part (layout overflow, broken images,
unlabeled controls, headings, JS errors) for resolvable GET routes and effective
custom pages. Unresolved media paths are reported as skips. Platform control needs
a separate operator fixture; this file covers interactions a snapshot can't see.

Last updated: 2026-11-07 (public preset/manifest and fleet-control inventory).

## States every page needs

| State | What "done" looks like |
|---|---|
| Default | Normal data volume, the thing the page is for is obvious in 3 seconds |
| Empty | A designed empty state that says what to do next — never a bare table header |
| One row | No layout that only works with lots of content |
| Many rows | 50+ rows or 20+ cards: scrolling, pagination or filtering still sane |
| Long text | A 60-character customer name, a 300-character note, a long service name |
| Validation error | Field-level message next to the field, form keeps what was typed |
| Success | Clear confirmation, and the page updates without a manual refresh |
| Narrow (390) | No horizontal scroll; tap targets >= 44px; nothing clipped |
| Keyboard | Every action reachable, visible focus ring, logical tab order |

## Public pages

| Route | Gated by | Notes / states to check |
|---|---|---|
| `/` | Manifest `home` | Ordered preset blocks, empty block list, services flag off, empty gallery teaser, long tagline. |
| `/services` | Manifest `services` + `ENABLE_SERVICES` | Empty catalogue, one service, 20 services, long description. |
| `/gallery` | Manifest `gallery` + `ENABLE_GALLERY` | Empty gallery, single item, 30 items, lightbox open/close, keyboard escape; empty gallery hidden in navigation. |
| `/service-area`, `/directions` | Manifest `service_area` | Coverage, hours, address, directions, optional sections, blank fields and long copy; alias parity. |
| `/about` | Manifest `about` | Optional compatible-default page, long body text, custom sections. |
| `/contact` | Manifest `contact` | Contact copy, mailto/tel links, custom sections. |
| `/faq` | Manifest `faq` | Optional compatible-default page, FAQ sections, long answers. |
| `/p/<slug>` | Enabled custom page with validated slug | Title/meta/nav label/order, hidden navigation, empty sections, hero/text/cards/checklist/FAQ/CTA; unknown or disabled slug 404. |
| `/quote-request`, `/request-quote` | Manifest `quote_request` | Empty form, validation errors, 20-photo limit, reCAPTCHA failure, success -> `/thank-you`; alias parity. |
| `/schedule-work` | Manifest `schedule_work` + `ENABLE_SCHEDULING` | Same as above plus preferred date/time; time selects when only hour is chosen. |
| `/thank-you` | — | Post-submit confirmation. |
| `/privacy-policy`, `/terms` | — | Placeholder legal copy per customer — replaced at deployment. |
| `/for-ai-systems` | — | Static. Headings now sentence case. |
| 404 | — | Branded page, link back home, admin paths redirect to login instead. |
| 500 | — | Branded page, never raises a second error, logs the traceback. |

Public review matrix: `local_service_business` (compatible default, optional
gallery/about/FAQ retained), `specialty_contractor`, `minimal_quote_funnel`.
Verify map deep-merges, list replacement, empty-list clearing, stable navigation
ordering, master feature gates and disabled-page 404s. Copy must remain escaped plain
text (no raw HTML/executable Markdown); CTA links accept only absolute local or HTTP(S)
URLs. See [manifest schema](README.md#public-presets-and-manifest).

Automated public baseline: run the sweep with `--site-matrix --public-only
--widths 390,768,1440`. Add `--matrix` to cross all three kits with the five
feature-flag presets. `--site-preset` chooses one kit; `--preset` still chooses a
feature-flag preset. Each combination uses its own database, instance/theme state,
and uploads without inheriting the operator registry or changing configuration
classes. Specialty's `/p/our-process` and a hidden `/p/sweep-content` structured
page are discovered even when absent from navigation. Disabled standard/custom
pages are expected-status probes, not layout failures. Setup failures remain in
the report and force a nonzero exit. Lazy images are decoded before measurement.
Accessibility findings remain warnings requiring review, not a full WCAG audit.

## Admin pages (all require login)

| Route | Gated by | Notes / states to check |
|---|---|---|
| `/admin` | — | Login: bad credentials, empty fields, CSRF expiry message. |
| `/admin/` | — | Dashboard queue: empty, 1 request, 200 requests, filters with no matches. |
| `/admin/requests/<id>` | — | Long notes, no customer linked, customer linked, quote draft autosave, delete last quote, photos. |
| `/admin/customers` | `ENABLE_CUSTOMER_RECORDS` | Empty list, 400 customers, city filter with no matches, import panel. |
| `/admin/customers/<id>` | `ENABLE_CUSTOMER_RECORDS` | Minimal record (name only), full record, many addresses/notes/photos, merge view. |
| `/admin/customers/<id>/merge` | `ENABLE_CUSTOMER_RECORDS` | Two records with overlapping fields; confirm dialog. |
| `/admin/calendar` | `ENABLE_CALENDAR` | Empty month, dense month, day view with no events. |
| `/admin/staff` | `ENABLE_STAFF_MANAGEMENT` | Empty, inactive staff only, long display name. |
| `/admin/staff/<id>` | `ENABLE_STAFF_MANAGEMENT` | No availability, full week, drag handles, range preset, manual time entry. |
| `/admin/staff/new`, `/edit` | `ENABLE_STAFF_MANAGEMENT` | Validation errors, compensation fields blank. |
| `/admin/recurring-work` | `ENABLE_RECURRING_WORK` | Empty, archived plans, many plans. |
| `/admin/recurring-work/<id>` | `ENABLE_RECURRING_WORK` | Autosave, generated-events dialog, archive confirm (long label wraps), impact preview. |
| `/admin/appointments/<id>` | `ENABLE_SCHEDULING` | Reschedule, status change, staff assignment, no staff. |
| `/admin/scheduled-work/new` | `ENABLE_SCHEDULING` | Customer required, time validation, staff optional. |
| `/admin/content` | `ENABLE_GALLERY` | Index when only gallery is on. |
| `/admin/content/gallery` | `ENABLE_GALLERY` | Empty, 30 items, reorder mode, upload errors, lightbox. |
| `/admin/settings/services` | `ENABLE_SERVICES` | Empty, archived services, reorder mode. |
| `/admin/imports/<type>/template.xlsx` | — | File download, not a page (sweep skips it). |
| `/admin/settings/appearance` | — | Internal theme library: dropdown of 100 palettes, swatch grid, applied server-side to every page. Check: long option list, active swatch highlight, applying then reloading. |

## Platform operator page (independent master authentication)

| Route | Gated by | Notes / states to check |
|---|---|---|
| `/platform/control` (configurable) | `SUPERADMIN_PASSWORD`, optional `SUPERADMIN_HOST`, master session | Login remains independent of tenant context; authenticated-only three-preset choices. Provision/edit preset and pretty-JSON saved overrides; blank resets to {}; absent optional fields preserve values. Invalid JSON/schema/URLs fail safely before persistence. Fleet shows effective preset/settings even for broken databases. Existing maintenance, demo-reset, handoff and identity/flag controls unchanged. |

## Known gaps logged here, not yet fixed
- `QuoteRequestForm` defines `preferred_time` fields but `quote_request.html` never
  renders them — either surface them or delete the fields.
- The theme library is light-UI only: several rules hard-code `rgba(255,255,255,…)`
  surfaces, so dark palettes are deliberately lightened rather than rendered dark.
  A true dark mode needs those surfaces converted to tokens first.

## Review log

Pass of 2026-11-04: all 102 screenshots (34 routes × 390/768/1440) reviewed via
contact sheets, plus contrast and keyboard probes.

Fixed in that pass:
- Home hero stayed two-column at phone width (heading squeezed into half the screen).
- Schedule toolbar: view toggle, month nav and action buttons collided at 390px; the
  month heading is now on its own row and the buttons stack.
- Customers table: percentage columns collapsed to slivers; it now keeps a 44rem
  minimum and scrolls inside its card.
- Muted text (`--muted`) was 0.72 alpha — 3.42:1 on the page background. Raised to
  0.88, which clears 4.5:1 while staying visibly lighter than body text.
- Theme accent had only a 3:1 target, but it is used for link text and for button
  backgrounds carrying white text; raised to 4.5:1 in both directions, verified
  across all 100 palettes.

Not defects (found and dismissed): gallery thumbnails look blank because the seeded
demo data points every item at the white logo file, not because images fail.
- 42 lines of inline JS remain in `admin/customer_merge.html` (it builds a JSON map
  with a Jinja loop); every other page's JS now lives in `app/static/js/`.
- 12 hidden/JS-generated controls are labelled now, but the availability editor is
  mouse-first: keyboard reordering of time windows has no equivalent.
- The sweep includes a heuristic rendered contrast check, reported as warnings;
  it does not replace a full WCAG AA audit or the 100-palette unit tests.
- `/admin/content` only exists as a gallery wrapper — worth revisiting if a second
  content type lands.
