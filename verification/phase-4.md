# Phase 4 verification — officer access and building records

Date: 2026-09-14. Project: `C:\Users\dhanu\OneDrive\Desktop\nila`.

## Automated verification actually performed

`python -m pytest -q --mysql-integration -x`: **75 passed in 44.41 seconds**
in the final full run. This includes 16 foundation tests and 59 test cases
using actual isolated MySQL 8.0.44. `python -m pip check` reports no broken
requirements. Python is 3.12.10; existing locked dependencies were sufficient.

The tests use a freshly initialized loopback-only MySQL instance with a random
temporary database password. Separate schemas isolate access tests, existing
data tests and the migration-preservation test. The user's regular MySQL service
and `.env` credentials are not used or altered. No SQLite substitute is used.

New checks exercised through actual Flask HTTP requests with CSRF enabled:

- Anonymous users cannot view building lists, details, creation or edit pages.
- An anonymous POST with a valid CSRF token still cannot create a building.
- Officer CLI creation stores a salted scrypt hash and never echoes passwords.
- Successful login rotates the client session and creates an expiring server
  session containing only a token hash; cookies have HttpOnly and SameSite=Lax.
- Invalid, absent and disabled demo usernames receive a generic error.
- Supplied external `next` URLs cannot redirect a successful login off-site.
- Expired sessions and disabled officers cannot read private pages.
- Logout is POST-only, requires CSRF and revokes the server session. Replaying
  its old signed cookie does not restore access.
- Missing CSRF tokens block login, logout, building creation/edit and assignment.
- New buildings persist with NULL unknowns and two distinct unknown-priority
  assessment cases. Record and audit changes share a database transaction.
- Invalid coordinates, coordinate pairs, negative counts, future years,
  out-of-range/non-finite hours, invalid wards, blank reasons and real records
  in fictional wards are rejected without writes while form values are retained.
- Duplicate building IDs are rejected. Stale edits return HTTP 409 and preserve
  the newer record; update history records the reason and previous values.
- Search, empty results, pagination and HTML escaping operate correctly.
- Assignments update the officer/next action and audit reason without changing
  priority or review status, including when extra forged fields are posted.
- Private evidence shows individual units and officer notes, while anonymous
  pages expose neither those private notes nor building details.
- Login submissions are limited to 20 per peer address per 10 minutes, backed
  by MySQL. The next attempt receives HTTP 429 with a Retry-After header.
- Duplicate officer usernames are rejected without replacing the account.
- A newly registered building can be read from a fresh Flask app/connection.

The existing Phase 3 migration, seed, measurement constraints, 25/10 shortfall,
provenance and data-preservation tests also pass. Migration 0002 was additionally
applied to a schema containing an existing Phase 3 building: its data remained
intact and the edit version initialized to 1. Migration/metadata comparison
and the empty-schema downgrade/upgrade round-trip passed through the new head.

## Actual browser journey

Used agent-browser 0.37.1 and the installed Microsoft Edge executable in headless
mode, against `scripts/preview_officer_flow.py` on port 5012. This was a separate
real MySQL preview containing fictional data and a random temporary login.

Performed the following in the browser:

1. Opened the sign-in page, filled the temporary username/password and signed in.
2. Opened the 50-building register, searched for `NILA-DEMO-B026` and followed
   the result to its evidence detail page.
3. Inspected separate indoor-measurement history and regional survey context,
   including quantity/unit, source, times, quality and synthetic labels.
4. Registered `BROWSER-DEMO-001` with optional numeric fields left unknown and
   the synthetic checkbox selected.
5. Opened its edit form, changed its name to `Browser building edited`, supplied
   a reason and saved. Search subsequently displayed the changed name.
6. Signed out, requested `/buildings/51` directly and confirmed redirection to
   `/auth/login`.

Captured and visually inspected the desktop register/detail and mobile
register/form. Mobile detail width was also checked: document width and viewport
width both measured 390 px. The table has its own horizontal scrolling region
on narrow screens. Browser console and page-error checks returned no entries.
Desktop viewport: 1440 × 1000; mobile: 390 × 844.

Screenshots in this directory:

- `phase-4-register-desktop.png`
- `phase-4-detail-desktop.png`
- `phase-4-form-mobile.png`
- `phase-4-detail-mobile.png`
- `phase-4-register-mobile.png`
- `phase-4-login-mobile.png`

The browser happy path used the preview process started before the final
validation-only fixes. Those fixed validation paths were exercised by the final
automated suite. A later explanatory sentence about coordinate changes was
added to the edit form after its screenshot. No final whole-app browser audit
or formal accessibility certification is claimed.

## Issues found and fixed

- Flask-WTF's CSRF timeout needed integer seconds rather than a timedelta for
  the installed dependency versions. Valid form submission exposed this issue.
- Optional field validation skipped a missing longitude; coordinate-pair
  validation now runs at form level.
- Stripped whitespace in required text needed a minimum-length check, ensuring
  a blank audit reason is rejected by the form before reaching MySQL.
- Duplicate creation must redisplay a creation form rather than render edit
  links for an unsaved object; that error path was corrected and tested.
- Test request contexts were isolated to match real request lifetimes, and
  inspector transactions are ended before reading HTTP commits under MySQL's
  REPEATABLE READ isolation.

## Scope and handover limits

The user's persistent Nila database/account is still unconfigured in `.env`;
the regular service has not been migrated or populated on the user's behalf.
`docs/officer-guide.md` includes both immediate fictional preview instructions
and persistent setup/account-creation steps. The user's original port-5001
server is left unchanged and must be restarted to load the new application.

The temporary verification browser and preview servers were stopped afterward.
Ignored test data/logs remain in `.test-artifacts/`; cleanup was not retried
after the earlier phase's policy rejection.

Map/import workflows, allocation algorithms, equipment overlap prevention,
full measurement/action review transitions and public locality/request pages
remain later phases. This phase has a shared officer register, not per-ward
permissions or MFA. Session expiry and login throttling are local defaults.
The preview starts fresh on each run and must not hold real records.
