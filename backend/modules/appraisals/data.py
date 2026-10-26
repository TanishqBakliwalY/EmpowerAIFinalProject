"""Appraisal-cycle inputs: ratings and evidence per person, market bands, and HR's hike policy.

Loaded once from DATA_DIR/appraisals (synthetic demo data by default; point EMPOWER_DATA_DIR at a folder
with the same files to use real exports). Derived numbers (evidence score, compa-ratio, retention risk)
are computed here in code so every agent sees the same facts.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ...core.company import CompanyData, company
from ...core.config import DATA_DIR

FILES = ("appraisal_inputs.csv", "market_bands.csv", "hike_policy.json")


@dataclass(frozen=True)
class Person:
    emp_id: str
    name: str
    role: str
    title: str
    level: str
    office: str
    manager_emp_id: str
    rating: int
    manager_notes: str
    promotion_recommended: bool
    client_feedback_score: int
    utilization_12m_pct: float
    skills_added: int
    ctc: int  # current annual CTC, INR (internal, HR/director only)
    gender: str  # used ONLY in aggregate by the fairness audit
    tenure_years: float
    last_hike_pct: float
    months_since_last_hike: int
    band_p25: float
    band_p50: float
    band_p75: float
    evidence_score: float  # 1-5 from client feedback, utilisation and skills added
    compa_ratio: float  # ctc / market p50 for role, level and city
    retention_risk: str  # low | medium | high


@dataclass
class AppraisalData:
    policy: dict
    people: dict[str, Person]
    managers: dict[str, str]  # manager emp_id -> name
    data_dir: Path

    @property
    def payroll(self) -> int:
        return sum(p.ctc for p in self.people.values())

    def team(self, manager_emp_id: str) -> list[Person]:
        return [p for p in self.people.values() if p.manager_emp_id == manager_emp_id]


def evidence_score(feedback: float, util: float, skills: int) -> float:
    util_score = max(1.0, min(5.0, 1 + (util - 40) / 13.75))
    skill_score = 2.5 + min(skills, 3) * (2.5 / 3)
    return round(0.45 * feedback + 0.35 * util_score + 0.20 * skill_score, 2)


def retention_risk(compa: float, rating: int, months: int) -> str:
    if compa < 0.9 and rating >= 4:
        return "high"
    if (compa < 0.95 and months >= 15) or (rating >= 4 and compa < 1.0):
        return "medium"
    return "low"


def load(data_dir: Path, c: CompanyData) -> AppraisalData:
    folder = data_dir / "appraisals"
    missing = [f for f in FILES if not (folder / f).exists()]
    if missing:
        raise FileNotFoundError(f"{folder} is missing {', '.join(missing)}. Run scripts/generate_appraisal_data.py.")
    policy = json.loads((folder / "hike_policy.json").read_text(encoding="utf-8"))
    bands = {(r["role"], r["level"], r["city"]): (float(r["p25"]), float(r["p50"]), float(r["p75"]))
             for r in csv.DictReader((folder / "market_bands.csv").open(encoding="utf-8"))}
    people: dict[str, Person] = {}
    for r in csv.DictReader((folder / "appraisal_inputs.csv").open(encoding="utf-8")):
        e = c.employees.get(r["emp_id"])
        if not e:
            continue
        ctc = int(float(r["current_annual_ctc_inr"]))
        p25, p50, p75 = bands.get((e.role, e.level, e.office), (ctc * 0.88, float(ctc), ctc * 1.14))
        rating = int(r["rating"])
        feedback, util, skills = int(r["client_feedback_score"]), float(r["utilization_12m_pct"]), int(r["certifications_or_skills_added"])
        compa = round(ctc / p50, 3) if p50 else 1.0
        months = int(r["months_since_last_hike"])
        people[e.emp_id] = Person(
            emp_id=e.emp_id, name=e.name, role=e.role, title=e.title, level=e.level, office=e.office,
            manager_emp_id=r["manager_emp_id"], rating=rating, manager_notes=r["manager_notes"],
            promotion_recommended=r["promotion_recommended"] in ("1", "true", "True"), client_feedback_score=feedback,
            utilization_12m_pct=util, skills_added=skills, ctc=ctc, gender=r["gender"], tenure_years=float(r["tenure_years"]),
            last_hike_pct=float(r["last_hike_pct"]), months_since_last_hike=months, band_p25=p25, band_p50=p50, band_p75=p75,
            evidence_score=evidence_score(feedback, util, skills), compa_ratio=compa,
            retention_risk=retention_risk(compa, rating, months),
        )
    managers = {m: (people[m].name if m in people else m) for m in sorted({p.manager_emp_id for p in people.values()} - {""})}
    return AppraisalData(policy=policy, people=people, managers=managers, data_dir=folder)


@lru_cache(maxsize=1)
def appraisal_data() -> AppraisalData:
    return load(DATA_DIR, company())
