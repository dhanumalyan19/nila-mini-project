# Phase 6 — assessment planner guide

Nila’s planner is a transparent capacity-allocation tool for qualified officers.
It does not diagnose a health condition, apply an official radiation threshold,
or certify that any building is safe.

## Planning flow

1. After officer sign-in, open **Assessment planner**.
2. Create a campaign or open an existing campaign. Record the assessment track,
   planning period, nominal capacity and known staff/equipment limits.
3. Add explicit eligible assessment cases. Adding a candidate does not schedule
   it or change its screening priority.
4. Set the priority-screening and coverage-gap weights and generate a plan with
   a reason. Required follow-ups always take precedence; its displayed policy
   value is recorded with the campaign rather than used to displace a follow-up.
   You may supply a random seed; otherwise Nila generates and records one.
5. Read both the selected opportunities and the unmet-demand list. Arrange more
   capacity or qualified review where required.

The algorithm is in `app/planner/service.py`. `generate()` computes the lowest
of nominal, staff and equipment capacity. It first fills capacity from the
required-follow-up queue. It then uses the campaign’s priority-screening and
coverage-gap weights for the remaining capacity. If a weighted queue runs out of
cases, its unused share can fill another eligible queue; a slot is not left empty
only to preserve a quota.

Within each queue, cases waiting longest are first. Exact waiting-time ties are
shuffled with the recorded seed, making the result reproducible. Each selection
stores the category, rule/version, evidence snapshot and tie-break explanation.
The algorithm does not modify a case’s screening priority or evidence quality.

## The 25 / 10 demo

`seed-demo` creates the clearly synthetic campaign `NILA-DEMO-25-10`. It has 25
equal-priority indoor-radon assessment cases, 10 nominal slots, identical waiting
time, and a shared deadline. Generating a plan displays:

- Total demand: 25
- Effective capacity: 10
- Selected: 10
- Unmet demand: 15

All 25 keep their priority. The 15 remaining cases stay visible with waiting
time, responsible officer, scheduling status and next action. Because the common
deadline cannot be met with 10 slots, Nila creates an open escalation record.
Selecting 10 is never presented as resolving all 25 needs.

## Overrides and equipment

An officer may replace one selection with another explicit eligible candidate.
The replacement requires a reason, retains the fixed plan capacity, leaves
screening priority unchanged, and creates both an `OfficerOverride` and an audit
event.

**Equipment bookings** use UTC start/end times. Nila locks the selected resource
and rejects overlapping `reserved` or `in_use` intervals for it. Returned and
cancelled historical bookings do not block a new interval. The resource, case
track and synthetic/real provenance must match. Nila does not infer that a
detector is available the next day.

## Try it with fictional data

```powershell
.\.venv\Scripts\python.exe scripts\preview_officer_flow.py
```

Use the temporary credentials printed in the terminal, then open **Assessment
planner** → **Fictional equal-attention exercise: 25 buildings / 10 slots**.
Generate a plan with a reason and inspect the selected/unmet tables plus the
escalation. All records in that preview are fictional and the temporary database
does not use your `.env` settings.
