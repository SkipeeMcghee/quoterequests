# Page Inventory

The finish line for UI work on this template. Every page the app can render, what
gates it, and the states that have to look deliberate before a customer sees it.

How to use it: pick a page, walk its states at 390 / 768 / 1440, tick it off.
`scripts/ui_sweep.py` covers the mechanical part (layout overflow, broken images,
unlabeled controls, heading order, JS errors) for every route automatically —
this file covers the part a script can't see.

Last updated: 2026-11-04 (baseline `550baa1` + Phase 1 polish).

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
| `/` | — | Home. Services list empty (services flag off), gallery teaser empty, long tagline. |
| `/services` | `ENABLE_SERVICES` | Empty catalogue, one service, 20 services, long description. |
| `/gallery` | `ENABLE_GALLERY` | Empty gallery, single item, 30 items, lightbox open/close, keyboard escape. |
| `/about` | — | Static copy, long body text. |
| `/contact` | — | Static copy, mailto/tel links. |
| `/faq` | — | Static copy; check disclosure widgets if added later. |
| `/quote-request` | — | Empty form, validation errors, 20-photo limit, reCAPTCHA failure, success -> `/thank-you`. |
| `/schedule-work` | `ENABLE_SCHEDULING` | Same as above plus preferred date/time; time selects when only hour is chosen. |
| `/thank-you` | — | Post-submit confirmation. |
| `/privacy-policy`, `/terms` | — | Placeholder legal copy per customer — replaced at deployment. |
| `/for-ai-systems` | — | Static. Headings now sentence case. |
| 404 | — | Branded page, link back home, admin paths redirect to login instead. |
| 500 | — | Branded page, never raises a second error, logs the traceback. |

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

## Known gaps logged here, not yet fixed

- `QuoteRequestForm` defines `preferred_time` fields but `quote_request.html` never
  renders them — either surface them or delete the fields.
- The theme library is light-UI only: several rules hard-code `rgba(255,255,255,…)`
  surfaces, so dark palettes are deliberately lightened rather than rendered dark.
  A true dark mode needs those surfaces converted to tokens first.
- 42 lines of inline JS remain in `admin/customer_merge.html` (it builds a JSON map
  with a Jinja loop); every other page's JS now lives in `app/static/js/`.
- 12 hidden/JS-generated controls are labelled now, but the availability editor is
  mouse-first: keyboard reordering of time windows has no equivalent.
- Contrast has not been measured against WCAG AA; the sweep only checks structure.
- `/admin/content` only exists as a gallery wrapper — worth revisiting if a second
  content type lands.
