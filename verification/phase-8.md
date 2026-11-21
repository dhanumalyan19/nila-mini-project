# Phase 8 verification — public information and requests

Date: 2026-09-17. Project: `C:\Users\dhanu\OneDrive\Desktop\nila`.

`python -m pytest -q --mysql-integration tests/test_public.py`: **2 passed in
21.69 seconds** against an isolated loopback-only MySQL instance. Tests verify
that public locality search returns aggregate coverage but not a building ID,
address or officer-only note; officer request intake stays protected; requests
require CSRF; and a browser-session cooldown blocks immediate repeat requests.

Browser verification used the temporary fictional preview database. A public
search for the fictional demo locality showed public ward information, regional
context, coverage and the request form without sign-in. Screenshot:
`verification/phase-8-public.png` (ignored by Git). The preview server and
temporary MySQL instance were stopped afterwards.
