# Business owner guide

Your site has public pages for customers and a private dashboard for your team.
Only enabled features appear; your setup contact controls which modules are available.

## Start your day

1. Open **your business domain**, then add `/admin` to the address. Sign in with your
   own account. Never share passwords; ask your setup contact for help if access fails.
2. Open the **request queue**. Filter by status and open new requests. Review contact
   details, requested services, notes, and photos. Check the address and scope with the
   customer before committing to work.
3. Record your follow-up and keep statuses current. **New**, **Viewed**, **Contacted**,
   **Quoted**, **Accepted**, **Rejected**, and **Scheduled** help the team see what is next.

## Quote and schedule

- In the request details, prepare a quote with the amount, description, and appropriate
  billing frequency. Review the details before recording/sending it. Only promise
  delivery by email if your setup contact has verified notification email is enabled;
  otherwise share the agreed quote through your normal customer communication.
- Record the customer's decision. Acceptance alone does not confirm an appointment.
- With scheduling enabled, confirm the date/time and access arrangements, create or
  update the appointment, and assign available staff when that module is enabled.
  Update completed, cancelled, or rescheduled appointments promptly.

## Keep the business information useful

- **Customers:** keep contact details, addresses, notes, service history, and private
  photos accurate. Check carefully before merging duplicates.
- **Services:** maintain clear names/descriptions and ordering; deactivate services you
  no longer offer rather than advertising unavailable work.
- **Gallery:** upload approved examples with helpful titles/captions, choose featured
  items, and hide outdated images. Obtain permission before publishing identifiable
  customer photos. Request/customer photo uploads are private, not automatic gallery posts.
- **Appearance:** select a theme in the appearance screen, preview it, and save. This
  changes your site's theme, not another business's site.

## Public pages and presets

Ask the platform operator to choose **local_service_business** (the compatible default
with optional gallery/about/FAQ), **specialty_contractor** (project/trust content and
Our Process), or **minimal_quote_funnel** (home, contact and quote intake). Presets do
not change your theme or enable disabled business modules.

The operator's fleet dashboard has a preset selector and a **PUBLIC_PAGES_CONFIG**
JSON textarea for each tenant and for provisioning. It shows saved overrides, not
the complete merged preset. Blank or `{}` resets those overrides; omitted fields
preserve existing settings. `[]` clears home blocks, not all public pages. Validation
rejects invalid content before saving; a database outage does not hide these controls.

Content can arrange home blocks, change standard-page titles/navigation/visibility,
and add custom pages at `/p/<slug>`. Service area is at `/service-area` (also
`/directions`); quote intake also accepts `/request-quote`. All text is escaped:
even rich-text sections do not accept raw HTML or executable Markdown. CTA links must
be absolute local paths or HTTP(S) URLs. Module flags remain master gates.

For the exact manifest schema and merge/empty-list rules, see the
[public preset documentation](../README.md#public-presets-and-manifest). Preview all
navigation, service-area details, quote links, and custom-page copy on your own domain
before publishing. These are operator settings, not the tenant appearance picker.

## What the optional modules control

| Module | Purpose |
|---|---|
| Services | Public service list and service catalog management |
| Gallery | Public examples of work and gallery management |
| Scheduling | Work-request form and appointments |
| Staff management | Team profiles, availability, and job assignment |
| Customer records | Customer profiles, notes, addresses, photos, and history |
| Calendar | Calendar views of appointments |
| Recurring work | Recurring service plans and generated events |

Ask your setup contact to change modules, contact details, email settings, or account
access. Review your public Privacy Policy and Terms for your business practices before
publishing. Do not store unnecessary sensitive information in notes or photos.

**Before leaving:** check tomorrow's schedule and unresolved requests, then sign out on
shared devices. Report errors with the page, approximate time, and request ID if shown;
do not send customer photos or passwords with an error report. Backups and demo resets
are operator tasks: never reset a real customer site to demonstrate the software.
