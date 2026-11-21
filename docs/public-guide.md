# Phase 8 — public locality information guide

The public page at `/public/localities` (with `/public/` as an alias) is deliberately
separate from officer tools. It accepts a locality search and returns only
curated locality labels, regional context and aggregate indoor-radon measurement coverage. It never
renders building IDs, household addresses, coordinates, private notes,
individual readings, screening priorities, plans, actions or officer records.

Coverage means that a reviewed, submitted measurement record exists. It is not
a safety statement and does not turn an unmeasured building into a safe or
unsafe result. Regional context remains separate from indoor radon evidence.

Residents may submit a request with an optional contact field. Requests are
private officer intake records. Forms require CSRF validation, contain a hidden
honeypot field, and limit a browser session to one request per five minutes.
An officer can view submitted requests at `/public/requests` or the **Review &
actions** queue after sign-in.
