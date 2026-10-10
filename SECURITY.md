# Security policy

## Reporting a vulnerability

Do not open a public issue for a security problem.  Send a private report to the
security contact configured for this repository (replace `<security-contact>` below
before publishing) with:

- the affected endpoint or component and the version or commit,
- steps to reproduce, and the impact you observed,
- whether tenant data or payments could be affected.

Acknowledgement target: 2 business days.  Triage target: 5 business days.
Please allow time for a fix before public disclosure.

## Supported versions

Only the `main` branch and the most recent tagged release receive security fixes.

## Session model

- **Refresh token:** HttpOnly, Secure (production), SameSite=Strict cookie scoped to
  `/api/v1/auth`.  Browsers never see it in JSON.  Cookie-based refresh requires the
  `X-Requested-With: qentry` header that a cross-site form cannot send.
- **Access token:** short-lived.  The admin console keeps it in memory only.  The
  field PWA keeps it in `sessionStorage` because offline device sessions must be
  restored after a reload.  This is a deliberate trade-off: an XSS in the field PWA
  can read a token that expires within the hour, but it cannot read the refresh token.
- **Native client (`field-expo`):** opts in with `X-Refresh-Transport: body`.

## Tenant isolation

- Enforced in PostgreSQL by row-level security (migrations v61–v66).  Tenant
  requests run as `qentry_app` (no BYPASSRLS).  The application checks at startup
  that the roles are configured this way and refuses to run in production otherwise.
- Operating providers may read and write rows of events they operate.  They never
  receive another tenant's full data set.
- Two narrow, table-backed exceptions, not client-controlled: a tenant may notify
  the counterparty of an active booking/operation, and a linked organizer/institution
  workspace pair shares usage, subscription and seat data as one billing unit
  (migration v62 — see the runbook's RLS section for the exact scope per table).
- Routes without a tenant context use the privileged session explicitly.  The list is
  reviewed in `tests/test_database_access_policy.py`.
- Billing: subscriptions are reviewed manually by platform staff, not charged
  through an online gateway (the Link integration code path is disabled).
  At most one pending request may exist per billing tenant at a time --
  enforced by a unique index (migration v68 for `provider='manual'`, v64 for
  the disabled `provider='link'` path), not just the route's own
  check-then-insert, which a double-click or two browser tabs can race.

## Known accepted risks

| Advisory | Component | Status | Plan |
|---|---|---|---|
| ~~PYSEC-2026-1325 / CVE-2026-85394~~ | ~~`ecdsa` / `python-jose`~~ | **Resolved.** `python-jose` (and its `ecdsa` dependency) removed entirely; JWT verification in `app/auth.py` now uses PyJWT, which was already installed. Covered by `tests/test_auth_jwks_verification.py` (RS256/ES256 via real generated keypairs) and `tests/test_auth_security.py`. | — |
| Field PWA access token in `sessionStorage` | Required for offline restore; the token is short-lived and the refresh token is cookie-only. | Revisit when the field app restores sessions through a cookie refresh at startup. |
| Expo / React Native transitive advisories | `field-expo` (native mobile app, not part of the API image) | No fix within the installed major (expo 57.0.26 is the latest patch). The npm suggestion is a downgrade and is rejected. | Plan the Expo SDK upgrade. Until then the mobile app is not a CI gate. |

## Secrets

- Production secrets are never stored in the repository.  They live in
  `/etc/qentry/*.env` on the host (see `deploy/env/*.example`).
- CI runs gitleaks against the full git history on every push.
- Rotate a secret immediately if it appears in a commit, log, screenshot or chat.
