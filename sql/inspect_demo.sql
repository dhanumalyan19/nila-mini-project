-- Read-only demonstration queries. Run after db upgrade and seed-demo.
USE nila;

SELECT code, name, is_synthetic FROM wards ORDER BY code;
SELECT COUNT(*) AS registered_buildings FROM buildings;

-- All quantities are grouped by scientific track, type AND unit.
SELECT track, measurement_type, unit, COUNT(*) AS record_count,
       SUM(value IS NULL) AS unknown_values
FROM measurements GROUP BY track, measurement_type, unit;

-- Nominal capacity arithmetic, not a generated assessment plan.
SELECT c.code, COUNT(cc.id) AS total_demand, c.available_slots AS available_capacity,
       GREATEST(COUNT(cc.id) - c.available_slots, 0) AS minimum_unmet_demand
FROM campaigns c JOIN campaign_candidates cc ON cc.campaign_id = c.id
WHERE c.code = 'NILA-DEMO-25-10'
GROUP BY c.id, c.code, c.available_slots;

-- Every one of the 25 cases remains visible with the original priority.
SELECT b.code, ac.priority_band, ac.evidence_status, ac.waiting_since,
       ac.required_by, o.display_name AS responsible_officer,
       ac.scheduling_status, ac.waiting_allowed, ac.next_action
FROM campaign_candidates cc
JOIN campaigns c ON c.id = cc.campaign_id
JOIN assessment_cases ac ON ac.id = cc.case_id
JOIN buildings b ON b.id = ac.building_id
LEFT JOIN officers o ON o.id = ac.responsible_officer_id
WHERE c.code = 'NILA-DEMO-25-10' ORDER BY b.code;

-- NULL is unknown; these records must not acquire zero defaults.
SELECT code, construction_year, ventilation, approximate_occupancy,
       hours_of_use_per_day, latitude, longitude
FROM buildings WHERE approximate_occupancy IS NULL ORDER BY code;

-- A multi-day detector assignment is still a booking tomorrow.
SELECT e.code, eb.starts_at, eb.ends_at, eb.status
FROM equipment_bookings eb JOIN equipment e ON e.id = eb.equipment_id;

-- A completion report and a reviewed follow-up are separate records.
SELECT a.code, a.status, a.reported_complete_at,
       ac.workflow_status, fr.decision AS follow_up_decision
FROM actions a JOIN assessment_cases ac ON ac.id = a.case_id
LEFT JOIN follow_up_reviews fr ON fr.action_id = a.id;

