# Deployment Checklist

This checklist is for deploying one customer site safely.

## What The Current `.env` Is

- The `.env` file in this repo is the local development config.
- The `SECRET_KEY` in that file should be treated as the local dev key.
- The reCAPTCHA keys in that file should be treated as local dev keys for `localhost` and `127.0.0.1` only.
- Do not reuse the local dev `SECRET_KEY` for customer production sites.
- Do not reuse the local dev reCAPTCHA keys for customer production sites.

## One Rule To Remember

- One customer deployment gets one unique `SECRET_KEY`.
- If one customer site uses multiple app servers, those servers should all use the same `SECRET_KEY` for that one customer.
- Different customers must not share the same `SECRET_KEY`.

## Per-Customer Deployment Steps

1. Create the customer's production environment settings or production `.env` file.
2. Generate a fresh `SECRET_KEY` for that customer.
3. Add that `SECRET_KEY` to that customer's production environment.
4. Set the customer's `DATABASE_URL`.
5. Set the customer's branding and business info.
6. Set the customer's feature flags.
7. Set the customer's social link settings.
8. Set the customer's reCAPTCHA settings if spam protection is enabled.
9. Deploy the app.
10. Verify the site loads and admin login works.

## Generate A Fresh `SECRET_KEY`

Use Python to generate a random key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Example output:

```text
2253773644027f486535c8cbd4471709c1093d8e18eef024775780ba5b869c3b
```

Use that generated value as the production `SECRET_KEY` for that customer.

## Required Production Settings

- `SECRET_KEY`
- `DATABASE_URL`

## Common Customer Settings

- `BUSINESS_NAME`
- `TAGLINE`
- `BUSINESS_PHONE`
- `BUSINESS_EMAIL`
- `SERVICE_AREA`
- `BUSINESS_ADDRESS`
- `SITE_LOGO_PATH`
- `SITE_LOGO_ALT`
- `ADMIN_NOTIFICATION_EMAIL`
- `DEFAULT_FROM_EMAIL`

## Feature Flags

- `ENABLE_SCHEDULING`
- `ENABLE_STAFF_MANAGEMENT`
- `ENABLE_CUSTOMER_RECORDS`
- `ENABLE_CALENDAR`
- `ENABLE_RECURRING_WORK`

## Spam Protection

- `RECAPTCHA_ENABLED`
- `RECAPTCHA_SITE_KEY`
- `RECAPTCHA_SECRET_KEY`
- `RECAPTCHA_MIN_SCORE`

## Local reCAPTCHA Dev Setup

- The local `.env` now contains a development reCAPTCHA v3 key pair.
- Those keys are for local development only.
- The allowed local hostnames should be `localhost` and `127.0.0.1`.
- Each customer production deployment should use its own separate reCAPTCHA v3 key pair.
- Put the production site key and secret key in that customer's production environment, not in the shared local `.env`.

## Social Links

- `SOCIAL_LINKS_PREVIEW`
- `SOCIAL_FACEBOOK_ENABLED`
- `SOCIAL_FACEBOOK_URL`
- `SOCIAL_INSTAGRAM_ENABLED`
- `SOCIAL_INSTAGRAM_URL`
- `SOCIAL_LINKEDIN_ENABLED`
- `SOCIAL_LINKEDIN_URL`
- `SOCIAL_YOUTUBE_ENABLED`
- `SOCIAL_YOUTUBE_URL`
- `SOCIAL_X_ENABLED`
- `SOCIAL_X_URL`
- `SOCIAL_TIKTOK_ENABLED`
- `SOCIAL_TIKTOK_URL`
- `SOCIAL_PINTEREST_ENABLED`
- `SOCIAL_PINTEREST_URL`
- `SOCIAL_WHATSAPP_ENABLED`
- `SOCIAL_WHATSAPP_URL`
- `SOCIAL_TELEGRAM_ENABLED`
- `SOCIAL_TELEGRAM_URL`
- `SOCIAL_SKYPE_ENABLED`
- `SOCIAL_SKYPE_URL`
- `SOCIAL_SNAPCHAT_ENABLED`
- `SOCIAL_SNAPCHAT_URL`
- `SOCIAL_SPOTIFY_ENABLED`
- `SOCIAL_SPOTIFY_URL`
- `SOCIAL_REDDIT_ENABLED`
- `SOCIAL_REDDIT_URL`
- `SOCIAL_GOOGLE_ENABLED`
- `SOCIAL_GOOGLE_URL`

## Production Sanity Checks

1. Confirm the customer site is using its own `SECRET_KEY`.
2. Confirm the site is pointing at the correct production database.
3. Confirm the correct logo, business name, and contact info are showing.
4. Confirm only the intended features are enabled.
5. Confirm the correct social links are enabled.
6. Confirm reCAPTCHA is working on public forms.
7. Confirm admin login works.
8. Confirm form submissions work.

## If A `SECRET_KEY` Is Ever Compromised

1. Generate a new `SECRET_KEY`.
2. Replace it in that customer's production environment.
3. Redeploy or restart the app.
4. Expect existing sessions to become invalid.

## What Not To Do

- Do not commit a real production `.env` file.
- Do not reuse one `SECRET_KEY` across all customers.
- Do not generate a new `SECRET_KEY` on every app startup.
- Do not copy the local development `.env` directly into production without reviewing it.