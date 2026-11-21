"""Small, testable allocation algorithm. It never changes screening priority."""
from collections import defaultdict
from datetime import datetime, time
import random
import secrets

from sqlalchemy import and_, select

from ..extensions import db
from ..models import AssessmentCase, Campaign, CampaignCandidate, Equipment, EquipmentBooking, Escalation, PlanRun, PlanSelection, ScreeningRuleVersion
from ..models.common import utcnow

ALGORITHM_VERSION = "nila-planner-v1"
CATEGORIES = ("required_follow_up", "priority_screening", "coverage_gap")


class PlanningError(ValueError):
    pass


def effective_capacity(campaign):
    limits = [campaign.available_slots]
    if campaign.staff_slots is not None:
        limits.append(campaign.staff_slots)
    if campaign.equipment_slots is not None:
        limits.append(campaign.equipment_slots)
    return min(limits)


def category(case):
    if case.follow_up_required or case.workflow_status == "follow_up_pending":
        return "required_follow_up"
    if case.priority_band == "priority":
        return "priority_screening"
    return "coverage_gap"


def case_evidence(case):
    return {"case_id": case.id, "track": case.track, "priority_band": case.priority_band,
            "evidence_status": case.evidence_status, "workflow_status": case.workflow_status,
            "follow_up_required": case.follow_up_required, "waiting_since": case.waiting_since.isoformat(),
            "required_by": case.required_by.isoformat() if case.required_by else None,
            "evidence_snapshot": case.evidence_snapshot, "priority_reason": case.priority_reason}


def ordered(cases, rng):
    """Longest waiting comes first; exact time ties use recorded RNG ordering."""
    groups = defaultdict(list)
    for case in cases:
        groups[case.waiting_since].append(case)
    result = []
    for waiting_since in sorted(groups):
        group = sorted(groups[waiting_since], key=lambda item: item.id)
        if len(group) > 1:
            rng.shuffle(group)
        result.extend(group)
    return result


def allocations(campaign, queues, capacity):
    """Allocate remaining capacity by weights after follow-ups, with fair spare fill."""
    output = {name: 0 for name in CATEGORIES}
    output["required_follow_up"] = min(capacity, len(queues["required_follow_up"]))
    remaining = capacity - output["required_follow_up"]
    weighted = ("priority_screening", "coverage_gap")
    weights = campaign.queue_weights
    total_weight = sum(int(weights.get(name, 0)) for name in weighted if queues[name])
    if remaining and total_weight:
        fractions = []
        for name in weighted:
            desired = remaining * int(weights.get(name, 0)) / total_weight if queues[name] else 0
            output[name] = min(len(queues[name]), int(desired))
            fractions.append((desired - int(desired), name))
        spare = remaining - sum(output[name] for name in weighted)
        # Deterministic category order breaks fractional equality; people within
        # each category remain waiting-time/RNG ordered.
        for _, name in sorted(fractions, key=lambda item: (-item[0], item[1])):
            if spare and output[name] < len(queues[name]):
                output[name] += 1
                spare -= 1
        # A quota never wastes a slot while another eligible queue has cases.
        for name in weighted:
            while spare and output[name] < len(queues[name]):
                output[name] += 1
                spare -= 1
    return output


def planning_rule(case):
    if case.rule_version_id:
        rule = db.session.get(ScreeningRuleVersion, case.rule_version_id)
        if rule and rule.track == case.track:
            return rule, rule.key
    rule = db.session.scalar(select(ScreeningRuleVersion).where(ScreeningRuleVersion.track == case.track,
        ScreeningRuleVersion.validation_status != "retired").order_by(ScreeningRuleVersion.id.desc()))
    if not rule:
        raise PlanningError("This case has no available versioned planning rule. Add a reviewed rule before planning.")
    return rule, "coverage-gap planning queue; " + rule.key


def generate(campaign_id, officer_id, reason, seed=None):
    campaign = db.session.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
    if not campaign:
        raise PlanningError("Campaign not found.")
    candidate_rows = list(db.session.scalars(select(CampaignCandidate).where(CampaignCandidate.campaign_id == campaign.id).with_for_update()))
    candidate_ids = [row.case_id for row in candidate_rows]
    cases = list(db.session.scalars(select(AssessmentCase).where(AssessmentCase.id.in_(candidate_ids)).with_for_update())) if candidate_ids else []
    cases = [case for case in cases if case.track == campaign.track and case.workflow_status != "outcome_reviewed"]
    if not cases:
        raise PlanningError("This campaign has no eligible cases. Add candidates before generating a plan.")
    if any(case.is_synthetic != campaign.is_synthetic for case in cases):
        raise PlanningError("Campaign and candidate provenance must match.")
    seed = secrets.randbelow(2**63) if seed is None else seed
    rng = random.Random(seed)
    queues = {name: [] for name in CATEGORIES}
    for case in cases:
        queues[category(case)].append(case)
    for name in queues:
        queues[name] = ordered(queues[name], rng)
    capacity = effective_capacity(campaign)
    counts = allocations(campaign, queues, capacity)
    selected = []
    for name in CATEGORIES:
        selected.extend((name, case) for case in queues[name][:counts[name]])
    selected_ids = {case.id for _, case in selected}
    unselected = [case for case in cases if case.id not in selected_ids]
    deadline_cases = [case for case in unselected if case.required_by and case.required_by <= datetime.combine(campaign.ends_on, time.max)]
    deadline_feasible = not deadline_cases
    inputs = {"candidate_case_ids": sorted(candidate_ids), "eligible_case_ids": sorted(case.id for case in cases),
              "queue_case_ids": {name: [case.id for case in queues[name]] for name in CATEGORIES},
              "capacity_limits": {"available_slots": campaign.available_slots, "staff_slots": campaign.staff_slots, "equipment_slots": campaign.equipment_slots},
              "generated_at": utcnow().isoformat()}
    rule_snapshot = {"algorithm_version": ALGORITHM_VERSION, "queue_weights": campaign.queue_weights,
                     "allocation": counts, "follow_up_rule": "Required follow-up is selected before weighted queues.",
                     "tie_break_rule": "Longest waiting time first; exact ties use recorded seeded random order.",
                     "deadline_rule": "Unselected cases due by campaign end create an escalation."}
    plan = PlanRun(campaign_id=campaign.id, generated_by_id=officer_id, random_seed=seed, algorithm_version=ALGORITHM_VERSION,
        input_snapshot=inputs, rule_snapshot=rule_snapshot, total_demand=len(cases), effective_capacity=capacity,
        selected_count=len(selected), unmet_demand=len(cases) - len(selected), deadline_feasible=deadline_feasible,
        is_synthetic=campaign.is_synthetic)
    db.session.add(plan)
    db.session.flush()
    for position, (name, case) in enumerate(selected, 1):
        rule, applicable_rule = planning_rule(case)
        tie = "Longest waiting time in its queue."
        equal = [item for item in queues[name] if item.waiting_since == case.waiting_since]
        if len(equal) > 1:
            tie = f"Exact waiting-time tie resolved with recorded random seed {seed}; queue position is reproducible."
        db.session.add(PlanSelection(plan_run_id=plan.id, case_id=case.id, category=name, applicable_rule=applicable_rule,
            rule_version_id=rule.id, evidence_used=case_evidence(case), tie_break_reason=tie, selection_order=position,
            is_synthetic=plan.is_synthetic))
        case.scheduling_status = "planned"
    for case in unselected:
        # Do not lower priority or imply unmet cases have been resolved.
        case.scheduling_status = "waiting"
    if deadline_cases:
        db.session.add(Escalation(plan_run_id=plan.id, responsible_officer_id=officer_id,
            reason="Campaign capacity cannot meet one or more required assessment deadlines. Qualified officer review is required; priorities remain unchanged.",
            affected_case_ids=[case.id for case in deadline_cases], status="open", is_synthetic=plan.is_synthetic))
    return plan, selected, unselected


def active_overlap(equipment_id, starts_at, ends_at):
    return db.session.scalar(select(EquipmentBooking.id).where(EquipmentBooking.equipment_id == equipment_id,
        EquipmentBooking.status.in_(("reserved", "in_use")), EquipmentBooking.starts_at < ends_at,
        EquipmentBooking.ends_at > starts_at).limit(1))
