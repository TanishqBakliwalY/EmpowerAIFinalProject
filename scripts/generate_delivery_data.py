"""Generate the synthetic delivery dataset for Project Health (data/seed/delivery/projects.json).

    python scripts/generate_delivery_data.py

Active projects come from data/seed/assignments.csv (who works on what) and data/seed/scope_guard/sows.json (signed
contracts). This adds what a delivery tracker would hold: budget hours, effort booked to date, reported completion,
milestones and client/vendor dependencies. A few projects are deliberately seeded with problems (cost overrun, schedule
slip, staffing gap) and labelled in `seeded_risk`, so the risk detector can be evaluated for precision and recall.
Everything here is synthetic: no real Empower project, client or number.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"
OUT = SEED / "delivery" / "projects.json"
AS_OF = date(2026, 10, 26)

# How each project is doing, by design. pct_factor: reported completion vs time elapsed; burn_factor: hours booked vs
# plan to date. seeded_risk is the ground truth for evaluation, never shown to the agents.
SCENARIOS = {
    "A201": dict(pct_factor=0.93, burn_factor=1.00, late={"Card controls (S3) in UAT": 9}, deps=[("Card-processor sandbox keys", "vendor", -5, "late")], seeded_risk="schedule_slip"),
    "A202": dict(pct_factor=1.00, burn_factor=0.97, seeded_risk="none"),
    "A203": dict(pct_factor=0.80, burn_factor=1.05, late={"Meter data pipeline live": 18}, deps=[("Utility's historical meter export", "client", -12, "late")], seeded_risk="cost_overrun"),
    "A204": dict(pct_factor=1.02, burn_factor=0.98, seeded_risk="none"),
    "A205": dict(pct_factor=1.00, burn_factor=1.00, seeded_risk="none"),
    "A206": dict(pct_factor=0.90, burn_factor=1.06, late={"Regression suite signed off": 6}, seeded_risk="cost_overrun"),
    "A207": dict(pct_factor=0.78, burn_factor=0.96, late={"Agent hand-off flows": 21}, deps=[("Client's support ticket export", "client", -20, "late")], seeded_risk="schedule_slip"),
    "A209": dict(pct_factor=0.97, burn_factor=1.02, deps=[("Arabic content from client", "client", 10, "open")], seeded_risk="none"),
    "A210": dict(pct_factor=1.01, burn_factor=0.99, seeded_risk="none"),
    "A211": dict(pct_factor=0.0, burn_factor=0.0, planned_team=5, seeded_risk="staffing_gap"),
    "A212": dict(pct_factor=0.0, burn_factor=0.0, planned_team=4, seeded_risk="staffing_gap"),
}
MILESTONE_NAMES = {
    "A201": ["P2P transfers in UAT", "Savings pots v2 in UAT", "Card controls (S3) in UAT", "Dark mode + notifications", "App-store release"],
    "A203": ["Analytics design signed off", "Meter data pipeline live", "Dashboards beta", "Go-live"],
    "A206": ["Defect backlog triaged", "Regression suite signed off", "Performance fixes", "Handover"],
    "A207": ["Ingestion v2", "Retrieval evaluation passed", "Agent hand-off flows", "Go-live"],
}
RATES = {"USD": {"fixed": 31, "tm": 28}, "GBP": {"fixed": 26, "tm": 24}, "EUR": {"fixed": 29, "tm": 27}}


def d(s: str) -> date:
    return date.fromisoformat(s)


def main() -> None:
    sows = {s["project_code"]: s for s in json.loads((SEED / "scope_guard" / "sows.json").read_text(encoding="utf-8"))}
    clients = {r["client"]: r for r in csv.DictReader(open(SEED / "clients.csv", encoding="utf-8"))}
    rows = [r for r in csv.DictReader(open(SEED / "assignments.csv", encoding="utf-8")) if r["kind"] == "project"]
    by = defaultdict(list)
    for r in rows:
        by[r["project_code"]].append(r)

    projects = []
    for code, team in sorted(by.items()):
        if code not in SCENARIOS:  # internal work (A208) is not client delivery
            continue
        sc = SCENARIOS[code]
        first = team[0]
        start = min(d(r["start_date"]) for r in team)
        end = max(d(r["end_date"]) for r in team)
        if code in sows:
            start, end = d(sows[code]["start_date"]), d(sows[code]["end_date"])
        weeks = max(1, (end - start).days / 7)
        planned_hours = round(sum(int(r["allocation_pct"]) / 100 * 40 * ((d(r["end_date"]) - d(r["start_date"])).days / 7) for r in team))
        country = (clients.get(first["client"]) or {}).get("country", "US")
        currency = sows[code]["currency"] if code in sows else ("GBP" if country in ("UK", "GB") else "EUR" if country in ("DE", "BE", "FR", "NL") else "USD")
        contract = sows[code]["contract_type"] if code in sows else ("tm" if "retainer" in first["project_name"].lower() else "fixed")
        value = sows[code]["contract_value"] if code in sows else round(planned_hours * RATES[currency][contract], -3)
        elapsed = min(1.0, max(0.0, (AS_OF - start).days / max(1, (end - start).days)))
        pct = round(min(0.99, elapsed * sc["pct_factor"]), 2) if elapsed > 0 else 0.0
        booked = round(planned_hours * elapsed * sc["burn_factor"]) if elapsed > 0 else 0

        names = MILESTONE_NAMES.get(code) or ["Design signed off", "Build complete", "UAT complete", "Go-live"]
        milestones = []
        for i, name in enumerate(names):
            planned = start + timedelta(days=round((end - start).days * (i + 1) / len(names)))
            late = sc.get("late", {}).get(name)
            if late is not None:
                forecast = planned + timedelta(days=late)
                if planned > AS_OF:
                    status, actual = "at_risk", None  # not due yet, but forecast to slip
                elif forecast > AS_OF:
                    status, actual = "late", None  # overdue and not done
                else:
                    status, actual = "done_late", forecast
            elif planned <= AS_OF:
                status, actual, forecast = "done", planned, planned
            else:
                status, actual, forecast = "upcoming", None, planned
            milestones.append({"name": name, "planned": planned.isoformat(), "forecast": forecast.isoformat(),
                               "actual": actual.isoformat() if actual else None, "status": status})
        deps = [{"item": item, "owner": owner, "due": (AS_OF + timedelta(days=days)).isoformat(), "status": st}
                for item, owner, days, st in sc.get("deps", [])]
        projects.append({
            "code": code, "name": first["project_name"], "client": first["client"], "country": country,
            "sow_id": sows[code]["sow_id"] if code in sows else None, "contract_type": contract, "currency": currency,
            "contract_value": value, "start": start.isoformat(), "end": end.isoformat(),
            "status": "active" if start <= AS_OF else "starting", "budget_hours": planned_hours,
            "hours_booked": booked, "pct_complete": pct, "planned_team_size": sc.get("planned_team", len(team)),
            "milestones": milestones, "dependencies": deps, "seeded_risk": sc["seeded_risk"],
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"as_of": AS_OF.isoformat(), "synthetic": True,
                               "note": "Synthetic delivery tracker data for the demo; not real Empower projects.",
                               "projects": projects}, indent=2), encoding="utf-8")
    print(f"wrote {OUT} with {len(projects)} projects")


if __name__ == "__main__":
    main()
