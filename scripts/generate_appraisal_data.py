"""Generate the synthetic appraisal-cycle data in data/seed/appraisals/ (Appraisal & Hike Planner).

Reads the existing synthetic company (employees, assignments) so people, roles, offices and costs match
the rest of the app. Everything is made up and deterministic (fixed seed).

    python scripts/generate_appraisal_data.py

Two fairness problems are planted on purpose, for the Fairness Auditor to find:
  1. One tech lead rates the women on their team about one point lower than their evidence supports.
  2. The Bhopal market moved up (new IT parks), so Bhopal staff now sit well below their market band.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.company import company  # noqa: E402
from backend.core.config import DATA_DIR  # noqa: E402

OUT = DATA_DIR / "appraisals"
rng = random.Random(2627)

FEMALE = {"Priya", "Sneha", "Ananya", "Kavya", "Neha", "Pooja", "Isha", "Meera", "Riya", "Tanvi", "Shruti", "Divya",
          "Kriti", "Nidhi", "Pallavi", "Simran", "Vaishali", "Bhavna", "Deepika", "Hema", "Komal", "Mansi", "Prachi",
          "Sakshi", "Varsha", "Zoya", "Swati", "Ritika"}
PM_MANAGERS = ["E001", "E003", "E004"]
LEAD_MANAGERS = ["E051", "E052", "E053", "E054"]
HEAD = "E002"  # Lead Project Manager: managers report here; E002 reports to the delivery director (not in the data)
DEV_ROLES = {"fe", "be", "mobile", "devops", "data", "ml"}
CITY_FACTOR = {"Indore": 1.00, "Pune": 1.02, "Bhopal": 1.15}  # planted: Bhopal market moved up sharply in 2026

NOTES = {
    5: ["Exceptional year: led the {proj} release and mentored two juniors.", "Client asked for them by name on {proj}; consistently ahead of plan.",
        "Owned the hardest module on {proj} and raised the team's bar."],
    4: ["Strong delivery on {proj}; reliable under deadline pressure.", "Good technical depth; took ownership of releases on {proj}.",
        "Solid year, positive client feedback, ready for more scope."],
    3: ["Met expectations on {proj}; steady and dependable.", "Delivered assigned work on {proj}; should push for more ownership.",
        "Good team player; growth area is estimation and planning."],
    2: ["Missed several sprint commitments on {proj}; needs closer support.", "Quality issues in two releases; improvement plan agreed.",
        "Below expectations this cycle; communication with client was a concern."],
    1: ["Did not meet core expectations; performance plan in place.", "Repeated missed deadlines and rework on {proj}."],
}
INCONSISTENT = [  # notes that contradict the numbers, for the Calibration Analyst to catch
    (5, "Outstanding year, client loved every delivery."),            # but feedback will be low
    (2, "Struggled with deadlines and needs closer supervision."),     # but evidence will be strong
    (3, "Average year; nothing special to report."),                   # but promotion is recommended
]


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def utilization(c, emp_id: str) -> float:
    """Average project allocation over the past 26 weeks (from assignments), blended with a historical figure."""
    weeks = [c.as_of - timedelta(weeks=i) for i in range(1, 27)]
    alloc = []
    for ws in weeks:
        we = ws + timedelta(days=6)
        alloc.append(min(100, sum(a.allocation_pct for a in c.assignments
                                  if a.emp_id == emp_id and a.kind == "project" and a.start <= we and a.end >= ws)))
    recent = sum(alloc) / len(alloc)
    historical = rng.uniform(58, 94)
    return round(0.6 * historical + 0.4 * recent, 1)


def main() -> None:
    c = company()
    joined = {r["emp_id"]: date.fromisoformat(r["joined"]) for r in csv.DictReader((DATA_DIR / "employees.csv").open(encoding="utf-8"))}
    projects = [a.project_name for a in c.assignments if a.kind == "project"] or ["client work"]
    emps = sorted(c.employees.values(), key=lambda e: e.emp_id)
    gender = {e.emp_id: ("F" if e.name.split()[0] in FEMALE else "M") for e in emps}

    # reporting lines
    manager: dict[str, str] = {}
    lead_i = pm_i = 0
    for e in emps:
        if e.emp_id == HEAD:
            manager[e.emp_id] = ""
        elif e.emp_id in PM_MANAGERS or e.emp_id in LEAD_MANAGERS:
            manager[e.emp_id] = HEAD
        elif e.role in DEV_ROLES:
            manager[e.emp_id] = LEAD_MANAGERS[lead_i % len(LEAD_MANAGERS)]
            lead_i += 1
        else:
            manager[e.emp_id] = PM_MANAGERS[pm_i % len(PM_MANAGERS)]
            pm_i += 1
    # the planted biased manager: the tech lead with the most women on the team
    women_by_lead = {m: sum(1 for e in emps if manager[e.emp_id] == m and gender[e.emp_id] == "F") for m in LEAD_MANAGERS}
    biased = max(LEAD_MANAGERS, key=lambda m: (women_by_lead[m], m))

    rows = []
    for e in emps:
        util = utilization(c, e.emp_id)
        feedback = int(clamp(round(rng.gauss(3.6, 0.8)), 1, 5))
        skills = rng.choices([0, 1, 2, 3], weights=[3, 4, 2, 1])[0]
        if manager[e.emp_id] == biased and gender[e.emp_id] == "F":  # make their evidence clearly solid
            feedback = max(feedback, 4)
            util = max(util, 82.0)
            skills = max(skills, 1)
        util_score = clamp(1 + (util - 40) / 13.75, 1, 5)          # 40% -> 1, 95% -> 5
        skill_score = 2.5 + skills * (2.5 / 3)
        evidence = 0.45 * feedback + 0.35 * util_score + 0.20 * skill_score
        rating = int(clamp(round(evidence + rng.gauss(0, 0.45)), 1, 5))
        if manager[e.emp_id] == biased:                                 # planted bias: men at evidence, women a point below
            rating = int(clamp(round(evidence + 0.25), 1, 5)) if gender[e.emp_id] == "M" else max(2, int(round(evidence)) - 1)
        tenure = round((c.as_of - joined[e.emp_id]).days / 365.25, 1)
        promo = rating >= 4 and tenure >= 1.5 and e.level in ("Junior", "Mid", "Senior") and rng.random() < 0.35
        notes = rng.choice(NOTES[rating]).format(proj=rng.choice(projects))
        rows.append({
            "emp_id": e.emp_id, "review_cycle": "FY2026-27", "manager_emp_id": manager[e.emp_id], "rating": rating,
            "manager_notes": notes, "promotion_recommended": int(promo), "client_feedback_score": feedback,
            "utilization_12m_pct": util, "certifications_or_skills_added": skills,
            "current_annual_ctc_inr": e.monthly_cost_inr * 12, "gender": gender[e.emp_id], "tenure_years": tenure,
            "last_hike_pct": round(clamp(rng.gauss(6 + rating, 2.0), 0, 18), 1),
            "months_since_last_hike": rng.choice([10, 12, 12, 12, 14, 18, 24]),
        })

    # plant three notes that contradict the evidence (not on the biased manager's team, to keep signals separate)
    others = [r for r in rows if r["manager_emp_id"] not in ("", biased) and r["emp_id"] not in LEAD_MANAGERS + PM_MANAGERS]
    rng.shuffle(others)
    a, b, d = others[:3]
    a.update(rating=5, manager_notes=INCONSISTENT[0][1], client_feedback_score=2, utilization_12m_pct=61.0)
    b.update(rating=2, manager_notes=INCONSISTENT[1][1], client_feedback_score=5, utilization_12m_pct=93.0,
             certifications_or_skills_added=2)
    d.update(rating=3, manager_notes=INCONSISTENT[2][1], promotion_recommended=1)

    # market bands: role x level medians of current pay, moved up 4% this year, then a city factor
    groups: dict[tuple[str, str], list[int]] = {}
    for e in emps:
        groups.setdefault((e.role, e.level), []).append(e.monthly_cost_inr * 12)
    bands = []
    for (role, level), ctcs in sorted(groups.items()):
        base = median(ctcs) * 1.04
        for city, f in CITY_FACTOR.items():
            p50 = round(base * f, -3)
            bands.append({"role": role, "level": level, "city": city, "p25": round(p50 * 0.88, -3), "p50": p50,
                          "p75": round(p50 * 1.14, -3), "source": "Synthetic 2026 salary survey"})

    policy = {
        "cycle": "FY2026-27",
        "effective_date": "2027-04-01",
        "currency": "INR",
        "pool_pct_of_payroll": 9.0,
        "guideline_hike_pct": {"5": [12, 18], "4": [8, 12], "3": [5, 8], "2": [0, 3], "1": [0, 0]},
        "promotion_addon_pct": [5, 10],
        "min_hike_pct": 0.0,
        "max_hike_pct": 25.0,
        "guideline_slack_pp": 3.0,
        "compa_ratio": {"floor": 0.88, "target": 1.0, "ceiling": 1.15, "market_gap_factor": 0.5,
                        "market_component_bounds_pct": [-3, 10]},
        "retention": {"high_risk_bonus_pct": 3.0, "medium_risk_bonus_pct": 1.5},
        "strategy_bounds": {"performance_weight": [0.4, 0.8], "market_weight": [0.1, 0.5], "retention_weight": [0.0, 0.3],
                            "promotion_share_pct": [5, 25]},
        "default_strategy": {"performance_weight": 0.6, "market_weight": 0.3, "retention_weight": 0.1, "promotion_share_pct": 12},
        "fairness": {"gender_gap_pp_within_rating": 1.0, "manager_rating_gap_vs_evidence": 0.5,
                     "office_compa_gap": 0.06, "tenure_gap_pp_within_rating": 1.5, "compa_outlier_low": 0.85,
                     "compa_outlier_high": 1.2, "min_group_size": 2},
        "max_adjustment_pp": [-3.0, 5.0],
        "notes": "Demo policy. HR edits this file; agents never invent pay rules.",
    }

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "appraisal_inputs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with (OUT / "market_bands.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(bands[0].keys()))
        w.writeheader()
        w.writerows(bands)
    (OUT / "hike_policy.json").write_text(json.dumps(policy, indent=2), encoding="utf-8")
    (OUT / "README.md").write_text(
        "# Appraisal demo data (synthetic)\n\nGenerated by `scripts/generate_appraisal_data.py`. No real people or pay.\n\n"
        f"Planted for the Fairness Auditor: manager {biased} rates women about one point below their evidence; "
        "the Bhopal market band moved up 15% so Bhopal staff sit below band.\n", encoding="utf-8")
    print(f"{len(rows)} employees, {len(bands)} bands, biased manager {biased} "
          f"({women_by_lead[biased]} women) -> {OUT}")


if __name__ == "__main__":
    main()
