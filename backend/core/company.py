"""Empower's company data: people, assignments, past projects, rates and policies.

Loaded once from DATA_DIR (CSV + JSON files). Every module reads the company through this one
object, so swapping the synthetic demo data for real exports is a folder change, not a code change.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from statistics import mean

from .config import DATA_DIR

REQUIRED_FILES = (
    "meta.json", "employees.csv", "assignments.csv", "projects.csv", "project_modules.csv", "clients.csv",
    "lost_deals.csv", "module_catalog.json", "rate_card.json", "compliance.json", "company_profile.md",
)


@dataclass(frozen=True)
class Employee:
    emp_id: str
    name: str
    role: str
    title: str
    level: str
    office: str
    years_exp: int
    skills: tuple[str, ...]
    monthly_cost_inr: int  # internal only -- never leaves the server in client-facing output


@dataclass(frozen=True)
class Assignment:
    emp_id: str
    project_code: str
    project_name: str
    client: str
    allocation_pct: int
    start: date
    end: date
    kind: str  # "project" | "leave"


@dataclass
class CompanyData:
    data_dir: Path
    meta: dict
    as_of: date
    employees: dict[str, Employee]
    assignments: list[Assignment]
    projects: dict[str, dict]
    project_modules: list[dict]
    clients: list[dict]
    lost_deals: list[dict]
    module_catalog: dict[str, dict]
    complexity_multipliers: dict[str, float]
    rate_card: dict
    compliance_rules: list[dict]
    company_profile: str
    role_cost_inr_per_hour: dict[str, float] = field(default_factory=dict)

    @property
    def policy(self) -> dict:
        return self.rate_card["policy"]

    @property
    def roles(self) -> dict[str, str]:
        return self.rate_card["roles"]

    def is_synthetic(self) -> bool:
        return self.meta.get("dataset") == "synthetic-demo"

    def sensitive_numbers(self) -> set[str]:
        """Internal figures that must never appear in a client-facing document (leak check)."""
        out: set[str] = set()
        for e in self.employees.values():
            out.add(f"{e.monthly_cost_inr:,}")
            out.add(str(e.monthly_cost_inr))
        return out


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_company(data_dir: Path = DATA_DIR) -> CompanyData:
    missing = [f for f in REQUIRED_FILES if not (data_dir / f).exists()]
    if missing:
        raise FileNotFoundError(f"Data folder {data_dir} is missing: {', '.join(missing)}")

    meta = json.loads((data_dir / "meta.json").read_text(encoding="utf-8"))
    as_of = date.fromisoformat(meta.get("as_of") or date.today().isoformat())

    employees = {
        r["emp_id"]: Employee(
            emp_id=r["emp_id"], name=r["name"], role=r["role"], title=r["title"], level=r["level"],
            office=r["office"], years_exp=int(r["years_exp"]),
            skills=tuple(s.strip() for s in r["skills"].split(";") if s.strip()),
            monthly_cost_inr=int(r["monthly_cost_inr"]),
        )
        for r in _read_csv(data_dir / "employees.csv")
    }
    assignments = [
        Assignment(
            emp_id=r["emp_id"], project_code=r["project_code"], project_name=r["project_name"], client=r["client"],
            allocation_pct=int(r["allocation_pct"]), start=date.fromisoformat(r["start_date"]),
            end=date.fromisoformat(r["end_date"]), kind=r.get("kind") or "project",
        )
        for r in _read_csv(data_dir / "assignments.csv")
    ]
    projects = {}
    for r in _read_csv(data_dir / "projects.csv"):
        for k in ("price", "est_hours", "actual_hours", "team_size"):
            r[k] = int(float(r[k]))
        r["modules"] = [m for m in r["modules"].split(";") if m]
        projects[r["project_id"]] = r
    project_modules = _read_csv(data_dir / "project_modules.csv")
    for r in project_modules:
        r["est_hours"] = float(r["est_hours"])
        r["actual_hours"] = float(r["actual_hours"])
    catalog = json.loads((data_dir / "module_catalog.json").read_text(encoding="utf-8"))
    rate_card = json.loads((data_dir / "rate_card.json").read_text(encoding="utf-8"))
    compliance = json.loads((data_dir / "compliance.json").read_text(encoding="utf-8"))

    company = CompanyData(
        data_dir=data_dir, meta=meta, as_of=as_of, employees=employees, assignments=assignments,
        projects=projects, project_modules=project_modules, clients=_read_csv(data_dir / "clients.csv"),
        lost_deals=_read_csv(data_dir / "lost_deals.csv"), module_catalog=catalog["modules"],
        complexity_multipliers=catalog["complexity_multipliers"], rate_card=rate_card,
        compliance_rules=compliance["rules"],
        company_profile=(data_dir / "company_profile.md").read_text(encoding="utf-8"),
    )
    # Internal cost per productive hour by role: average loaded monthly cost x overhead / monthly hours.
    pol = rate_card["policy"]
    for role in rate_card["roles"]:
        costs = [e.monthly_cost_inr for e in employees.values() if e.role == role]
        if costs:
            company.role_cost_inr_per_hour[role] = round(
                mean(costs) * pol["cost_overhead_multiplier"] / pol["monthly_working_hours"], 1
            )
    return company


@lru_cache(maxsize=1)
def company() -> CompanyData:
    return load_company()
