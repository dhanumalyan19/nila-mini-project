# Phase 6 verification — fair planning and equipment booking

Date: 2026-09-16. Project: `C:\Users\dhanu\OneDrive\Desktop\nila`.

## Automated verification actually performed

`python -m pytest -q --mysql-integration`: **148 passed in 86.84 seconds**.
The suite ran against isolated loopback-only MySQL 8.0.44 instances and did not
read `.env`, use SQLite, or alter the user’s MySQL Windows service.

Phase 6 checks cover:

- Officer-only planner/equipment pages and CSRF on plan generation.
- The 25-demand/10-slot demo: 10 selected, 15 unmet, no duplicate selections,
  unchanged priorities/waiting/officer assignment, and an open deadline
  escalation.
- Reproducibility of exact waiting-time ties using the same recorded seed.
- Required follow-up selection before weighted queues, effective capacity from
  nominal/staff/equipment limits, and unused weighted capacity filling another
  eligible queue instead of being wasted.
- Campaign creation validation and the fact that candidates are explicit rather
  than automatically added.
- Audited officer replacement of a selection without changing plan capacity or
  screening priority.
- Equipment booking creation, interval-overlap rejection, and track/provenance
  mismatch rejection.

## Browser verification actually performed

Using headless Microsoft Edge and a temporary fictional MySQL database:

1. Signed in with a preview-only officer.
2. Opened the synthetic `NILA-DEMO-25-10` campaign and generated a plan with
   recorded seed `41025`.
3. Verified the plan page visibly showed 25 total demand, 10 effective capacity,
   10 selected, 15 unmet, an explicit capacity-shortfall statement, an open
   escalation, selection tie-break explanations, and the complete unmet list.
4. Opened the equipment-booking page and confirmed the track-matched selector,
   UTC interval fields and existing synthetic multi-day detector booking render.

Screenshots: `verification/phase-6-plan.png` and
`verification/phase-6-equipment.png` (ignored by Git). The preview server and
its temporary MySQL instance were stopped after testing.

## Phase boundary limits

- Campaign candidates must currently be added one at a time; no bulk selection,
  campaign editing, cancellation UI, calendar view or email notification exists.
- Equipment booking status changes (return/cancel) are not yet an officer UI.
  Active overlap prevention is implemented for new reservations.
- The planner consumes explicit candidate cases and local queue weights only. It
  does not produce validated risk scores, invent thresholds, or automate a
  qualified review decision.
- Phase 7 will add measurement review, guidance, action assignment, follow-up
  evidence and outcome-review workflow.
