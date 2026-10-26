"""Deterministic Bench Optimizer math. Agents propose matches and courses; this code checks and counts.

Definitions (all over a horizon of N weeks starting at the dataset's as-of date):
- free %      100 - project allocation that week (planned leave is tracked separately, not as bench).
- bench FTE   sum over people of free % / 100 in a week, excluding people on leave that week.
- bench cost  bench hours x the role's loaded internal cost per hour (company.role_cost_inr_per_hour), INR.
              Internal-only: it is built from salary data, so the API is restricted to Directors and HR.
- roll-off    someone whose free capacity reaches `min_free_pct` at some week in the horizon.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any

from ...core.company import CompanyData, Employee
from ..staffing import availability as av

WIN_PROBABILITY = {"approved": 1.0, "ready": 0.5, "changes_requested": 0.3}
_REACT_NATIVE = re.compile(r"\breact\s+native\b", re.I)


def r1(x: float) -> float:
    return round(x, 1)


def week_hours(c: CompanyData) -> float:
    return float(c.policy["hours_per_week"])


def role_cost(c: CompanyData, role: str) -> float:
    return float(c.role_cost_inr_per_hour.get(role, 0.0))


def _leave_flags(c: CompanyData, emp_id: str, start: date, weeks: int) -> list[bool]:
    mine = [a for a in c.assignments if a.emp_id == emp_id and a.kind == "leave"]
    return [any(a.start <= ws + timedelta(days=6) and a.end >= ws for a in mine) for ws in av.week_starts(c, start, weeks)]


def weekly_free(c: CompanyData, emp_id: str, start: date, weeks: int) -> list[dict]:
    """Per week: project allocation, free %, leave flag and the bench fraction (0 when on leave)."""
    alloc = av.weekly_allocation(c, emp_id, start, weeks, include_leave=False)
    leave = _leave_flags(c, emp_id, start, weeks)
    out = []
    for ws, a, lv in zip(av.week_starts(c, start, weeks), alloc, leave):
        free = max(0, min(100, 100 - a))
        out.append({"week": ws.isoformat(), "alloc_pct": a, "free_pct": free, "leave": lv,
                    "bench_frac": 0.0 if lv else free / 100})
    return out


# =========================================================================== roll-offs and forecast


def _ending_project(c: CompanyData, emp_id: str, free_from: date) -> dict | None:
    """The project assignment that ends just before the person frees up (the reason they roll off)."""
    ended = [a for a in c.assignments if a.emp_id == emp_id and a.kind == "project" and a.end < free_from
             and a.end >= free_from - timedelta(days=14)]
    if not ended:
        return None
    a = max(ended, key=lambda x: x.end)
    return {"project": a.project_name, "code": a.project_code, "client": a.client, "ends": a.end.isoformat(),
            "allocation_pct": a.allocation_pct}


def _next_project(c: CompanyData, emp_id: str, after: date) -> dict | None:
    later = [a for a in c.assignments if a.emp_id == emp_id and a.kind == "project" and a.start > after]
    if not later:
        return None
    a = min(later, key=lambda x: x.start)
    return {"project": a.project_name, "starts": a.start.isoformat(), "allocation_pct": a.allocation_pct}


def person_rolloff(c: CompanyData, e: Employee, start: date, horizon: int, min_free_pct: int) -> dict | None:
    wk = weekly_free(c, e.emp_id, start, horizon)
    idx = next((i for i, w in enumerate(wk) if w["free_pct"] >= min_free_pct), None)
    if idx is None:
        return None
    hours = sum(w["bench_frac"] for w in wk) * week_hours(c)
    free_from = date.fromisoformat(wk[idx]["week"])
    free_after = [w["free_pct"] for w in wk[idx:idx + 4]]
    return {
        "emp_id": e.emp_id, "name": e.name, "role": e.role, "title": e.title, "level": e.level, "office": e.office,
        "skills": list(e.skills),
        "free_from": free_from.isoformat(), "weeks_until_free": idx,
        "free_pct": min(free_after) if free_after else wk[idx]["free_pct"],
        "status": "on_bench_now" if idx == 0 else "rolling_off",
        "fully_free": wk[idx]["free_pct"] >= 100,
        "weekly_free_pct": [w["free_pct"] for w in wk],
        "leave_weeks": sum(1 for w in wk if w["leave"]),
        "bench_hours": r1(hours),
        "bench_cost_inr": round(hours * role_cost(c, e.role)),
        "ending_project": _ending_project(c, e.emp_id, free_from) if idx > 0 else None,
        "next_project": _next_project(c, e.emp_id, free_from),
    }


def rolloffs(c: CompanyData, horizon: int = 12, min_free_pct: int = 50, start: date | None = None) -> list[dict]:
    start = start or c.as_of
    rows = [r for e in c.employees.values() if (r := person_rolloff(c, e, start, horizon, min_free_pct))]
    rows.sort(key=lambda r: (r["free_from"], -r["bench_hours"]))
    return rows


def weekly_forecast(c: CompanyData, horizon: int = 12, start: date | None = None) -> list[dict]:
    """Bench FTE and bench cost per week across everyone (anyone with unallocated time counts)."""
    start = start or c.as_of
    weeks = av.week_starts(c, start, horizon)
    rows = [{"week": w.isoformat(), "bench_fte": 0.0, "bench_cost_inr": 0.0, "fully_free": 0, "on_leave": 0} for w in weeks]
    for e in c.employees.values():
        rate = role_cost(c, e.role) * week_hours(c)
        for i, w in enumerate(weekly_free(c, e.emp_id, start, horizon)):
            rows[i]["bench_fte"] += w["bench_frac"]
            rows[i]["bench_cost_inr"] += w["bench_frac"] * rate
            rows[i]["fully_free"] += int(w["free_pct"] >= 100 and not w["leave"])
            rows[i]["on_leave"] += int(w["leave"])
    for r in rows:
        r["bench_fte"] = r1(r["bench_fte"])
        r["bench_cost_inr"] = round(r["bench_cost_inr"])
    return rows


# =========================================================================== demand: Deal Desk pipeline + internal work


def deal_demand(c: CompanyData, deal_states: list[dict]) -> list[dict]:
    """Staffing demand from Deal Desk deals that are approved or awaiting a decision."""
    pol = c.policy
    weekly_cap = pol["hours_per_week"] * pol["productive_utilization"]
    out = []
    for d in deal_states:
        status = d.get("status")
        if status not in WIN_PROBABILITY:
            continue
        r = d.get("results") or {}
        est, sch = r.get("estimate"), r.get("schedule")
        if not est or not sch:
            continue
        design, spec = r.get("design") or {}, r.get("spec") or {}
        total_w = max(1.0, float(sch.get("total_weeks") or 1))
        build_w = max(1.0, float(sch.get("build_weeks") or total_w))
        team = sch.get("team") or []
        roles = []
        for role, hours in sorted((est.get("hours_by_role") or {}).items(), key=lambda kv: -kv[1]):
            if hours <= 0:
                continue
            weeks = total_w if role in ("pm", "lead") else build_w
            roles.append({
                "role": role, "hours": r1(hours), "fte_needed": round(hours / (weeks * weekly_cap) * 4) / 4 or 0.25,
                "planned": [{"emp_id": m["emp_id"], "name": m.get("name"), "allocation_pct": m.get("allocation_pct")}
                            for m in team if m.get("role") == role],
                "uncovered": role in (sch.get("uncovered_roles") or []),
            })
        stack = [s.get("technology", "") for s in design.get("recommended_stack") or []]
        stack += (spec.get("constraints") or {}).get("preferred_stack") or []
        out.append({
            "deal_id": d["id"], "title": d.get("title"), "client": spec.get("client_name"), "status": status,
            "win_probability": WIN_PROBABILITY[status], "start": sch.get("start_date"), "end": sch.get("end_date"),
            "weeks": sch.get("total_weeks"), "roles": roles, "stack": [s for s in stack if s][:12],
            "capability_gaps": design.get("capability_gaps") or [], "link": f"#/deals/{d['id']}",
        })
    out.sort(key=lambda x: (-x["win_probability"], x["start"] or ""))
    return out


def internal_demand(work: list[dict]) -> list[dict]:
    return [{**w, "target_type": "internal"} for w in work]


# =========================================================================== skills: demand vs supply


def _phrase_in(term: str, text: str) -> bool:
    t, s = term.lower().strip(), text.lower()
    if not t:
        return False
    if t == "react" and _REACT_NATIVE.search(s) and not re.search(r"\breact\b(?!\s+native)", s):
        return False
    return re.search(r"(?<![\w.])" + re.escape(t) + r"(?![\w])", s) is not None


def skills_gap(c: CompanyData, deals: list[dict], rolls: list[dict], course_list: list[dict]) -> list[dict]:
    """Which skills the pipeline asks for, how many people have them, and how many of those are coming free."""
    inventory = av.skill_inventory(c)
    vocab = sorted(set(inventory) | {x["skill"] for x in course_list}, key=len, reverse=True)
    demand: dict[str, dict[str, Any]] = {}
    for d in deals:
        texts = d["stack"] + d["capability_gaps"]
        hit: set[str] = set()
        for term in vocab:
            if any(_phrase_in(term, t) for t in texts):
                hit.add(term)
        for term in hit:
            row = demand.setdefault(term, {"skill": term, "demand_score": 0.0, "deals": []})
            row["demand_score"] += d["win_probability"]
            row["deals"].append(d["title"])
    free_ids = {r["emp_id"] for r in rolls}
    out = []
    for term, row in demand.items():
        people = [e for e in c.employees.values() if any(av.skill_matches(term, s) for s in e.skills)]
        free = [e for e in people if e.emp_id in free_ids]
        out.append({**row, "demand_score": r1(row["demand_score"]), "people_with_skill": len(people),
                    "coming_free_with_skill": len(free), "gap": len(free) == 0,
                    "courses": [x["id"] for x in course_list if av.skill_matches(term, x["skill"]) or av.skill_matches(x["skill"], term)]})
    out.sort(key=lambda r: (-int(r["gap"]), -r["demand_score"], r["skill"]))
    return out


# =========================================================================== validation of the agents' proposals


def _target(target_type: str, target_id: str, deals_by_id: dict, internal_by_id: dict) -> dict | None:
    return (deals_by_id if target_type == "deal" else internal_by_id).get(target_id)


def _target_roles(t: dict, target_type: str) -> list[str]:
    return [x["role"] for x in t["roles"]] if target_type == "deal" else list(t["roles"])


def _target_skills(t: dict, target_type: str) -> list[str]:
    return t["stack"] if target_type == "deal" else list(t["skills"])


def skill_fit(e: Employee, wanted: list[str]) -> tuple[str, list[str]]:
    matched = sorted({s for s in e.skills for w in wanted if av.skill_matches(s, w) or _phrase_in(s, w)})
    if not wanted:
        return "partial", matched
    label = "strong" if len(matched) >= 2 else "partial" if matched else "weak"
    return label, matched


def hours_in_window(c: CompanyData, emp_id: str, start: date, weeks: int, alloc_pct: int, horizon_end: date) -> float:
    """Hours this assignment would fill inside the horizon, never more than the person's free time."""
    n = max(0, min(weeks, math.ceil((horizon_end - start).days / 7)))
    if n == 0:
        return 0.0
    total = 0.0
    for w in weekly_free(c, emp_id, start, n):
        total += min(alloc_pct / 100, w["bench_frac"]) * week_hours(c)
    return r1(total)


def validate_match(c: CompanyData, m: dict, deals_by_id: dict, internal_by_id: dict, rolls_by_id: dict,
                   horizon_end: date, already_pct: int = 0) -> dict:
    """Check one proposed match. Returns it enriched with status ok / flagged / rejected and the reasons."""
    issues: list[str] = []
    e = c.employees.get(str(m.get("emp_id", "")).strip().upper())
    ttype, tid = m.get("target_type"), str(m.get("target_id", "")).strip()
    base = {**m, "issues": issues, "status": "rejected"}
    if not e:
        issues.append(f"{m.get('emp_id')} is not an Empower employee.")
        return base
    t = _target(ttype, tid, deals_by_id, internal_by_id)
    if not t:
        issues.append(f"Unknown {ttype} '{tid}'.")
        return {**base, "name": e.name}
    if e.role not in _target_roles(t, ttype):
        issues.append(f"{e.name} is a {e.title}; {t.get('title') or t.get('name')} does not need that role.")
        return {**base, "name": e.name}
    try:
        start = date.fromisoformat(str(m.get("start_date")))
    except ValueError:
        start = c.as_of
        issues.append("Start date unreadable; using today.")
    if start < c.as_of:
        start = c.as_of
    weeks = max(1, min(int(m.get("weeks") or 4), 26))
    want = max(25, min(int(m.get("allocation_pct") or 100), 100))
    window = max(2, min(weeks, 8))
    free = av.free_pct(c, e.emp_id, start, window)
    roll = rolls_by_id.get(e.emp_id)
    if free < 25 and roll and date.fromisoformat(roll["free_from"]) > start:
        moved = date.fromisoformat(roll["free_from"])
        if av.free_pct(c, e.emp_id, moved, window) >= 25:
            issues.append(f"Start moved from {start.isoformat()} to {moved.isoformat()}, when {e.name} is free.")
            start, free = moved, av.free_pct(c, e.emp_id, moved, window)
    free_left = max(0, free - already_pct)
    if free_left < 25:
        issues.append(f"{e.name} is not free enough then ({free}% free, {already_pct}% already planned).")
        return {**base, "name": e.name}
    alloc = want
    if free_left < want:
        alloc = max(25, (free_left // 25) * 25)
        issues.append(f"Allocation cut from {want}% to {alloc}% (only {free_left}% free).")
    if ttype == "deal" and t.get("end") and start > date.fromisoformat(t["end"]):
        issues.append("Starts after the deal is planned to finish.")
        return {**base, "name": e.name}
    fit, matched = skill_fit(e, _target_skills(t, ttype))
    if fit == "weak":
        issues.append("No matching skills for the stack; plan a ramp-up.")
    if ttype == "internal" and t.get("max_weeks") and weeks > t["max_weeks"]:
        issues.append(f"Shortened to {t['max_weeks']} weeks, the most this initiative usefully takes.")
        weeks = t["max_weeks"]
    hours = hours_in_window(c, e.emp_id, start, weeks, alloc, horizon_end)
    win = t.get("win_probability", 1.0) if ttype == "deal" else 1.0
    return {
        **m, "emp_id": e.emp_id, "name": e.name, "title": e.title, "role": e.role, "office": e.office,
        "target_type": ttype, "target_id": tid, "target_name": t.get("title") or t.get("name"),
        "link": t.get("link"), "start_date": start.isoformat(), "weeks": weeks, "allocation_pct": alloc,
        "fit": fit, "matched_skills": matched, "win_probability": win, "hours_in_horizon": hours,
        "cost_covered_inr": round(hours * role_cost(c, e.role)), "status": "flagged" if issues else "ok", "issues": issues,
    }


def validate_matches(c: CompanyData, matches: list[dict], deals: list[dict], internal: list[dict], rolls: list[dict],
                     horizon_end: date) -> tuple[list[dict], list[dict]]:
    """Validate all matches in order, tracking how much of each person and initiative is already planned."""
    deals_by_id = {d["deal_id"]: d for d in deals}
    internal_by_id = {w["id"]: w for w in internal}
    rolls_by_id = {r["emp_id"]: r for r in rolls}
    planned: dict[str, int] = {}
    capacity_used: dict[str, float] = {}
    kept, rejected = [], []
    for m in matches:
        v = validate_match(c, m, deals_by_id, internal_by_id, rolls_by_id, horizon_end, planned.get(str(m.get("emp_id", "")).upper(), 0))
        if v["status"] == "rejected":
            rejected.append(v)
            continue
        if v["target_type"] == "internal":
            w = internal_by_id[v["target_id"]]
            used = capacity_used.get(w["id"], 0.0) + v["allocation_pct"] / 100
            if used > w["capacity_fte"] + 1e-9:
                v["issues"].append(f"{w['name']} only takes {w['capacity_fte']} FTE; this pushes it to {used:.2f}.")
                v["status"] = "flagged"
            capacity_used[w["id"]] = used
        planned[v["emp_id"]] = planned.get(v["emp_id"], 0) + v["allocation_pct"]
        kept.append(v)
    return kept, rejected


def validate_upskilling(c: CompanyData, items: list[dict], course_list: list[dict], rolls: list[dict],
                        matches: list[dict], horizon_end: date) -> tuple[list[dict], list[dict]]:
    by_course = {x["id"]: x for x in course_list}
    rolls_by_id = {r["emp_id"]: r for r in rolls}
    matched_pct: dict[str, int] = {}
    for m in matches:
        matched_pct[m["emp_id"]] = matched_pct.get(m["emp_id"], 0) + m["allocation_pct"]
    kept, rejected = [], []
    for it in items:
        e = c.employees.get(str(it.get("emp_id", "")).strip().upper())
        course = by_course.get(str(it.get("course_id", "")).strip().upper())
        issues: list[str] = []
        if not e or not course:
            rejected.append({**it, "issues": [f"Unknown {'employee' if not e else 'course'}."]})
            continue
        roll = rolls_by_id.get(e.emp_id)
        try:
            start = date.fromisoformat(str(it.get("start_date")))
        except ValueError:
            start = c.as_of
        if roll and start < date.fromisoformat(roll["free_from"]):
            start = date.fromisoformat(roll["free_from"])
            issues.append(f"Start moved to {start.isoformat()}, when {e.name} is free.")
        start = max(start, c.as_of)
        free_left = av.free_pct(c, e.emp_id, start, 2) - matched_pct.get(e.emp_id, 0)
        hpw = max(2, min(int(it.get("hours_per_week") or 8), 40))
        cap = max(0, free_left) / 100 * week_hours(c)
        if cap < 2:
            rejected.append({**it, "name": e.name, "issues": [f"{e.name} has no free time left after the planned matches."]})
            continue
        if hpw > cap:
            issues.append(f"Hours per week cut from {hpw} to {int(cap)} to fit free time.")
            hpw = int(cap)
        weeks = math.ceil(course["hours"] / hpw)
        end = start + timedelta(weeks=weeks)
        if end > horizon_end + timedelta(weeks=4):
            issues.append("Finishes after the planning horizon.")
        kept.append({
            **it, "emp_id": e.emp_id, "name": e.name, "title": e.title, "course_id": course["id"], "course": course["title"],
            "skill": course["skill"], "provider": course["provider"], "course_hours": course["hours"], "cost_inr": course["cost_inr"],
            "hours_per_week": hpw, "start_date": start.isoformat(), "end_date": end.isoformat(), "weeks": weeks,
            "status": "flagged" if issues else "ok", "issues": issues,
        })
    return kept, rejected


# =========================================================================== value of the plan


def plan_value(c: CompanyData, forecast: list[dict], rolls: list[dict], matches: list[dict], upskilling: list[dict]) -> dict:
    """What the plan does to bench cost over the horizon. Deal matches are weighted by the chance the deal is won."""
    bench_cost = sum(w["bench_cost_inr"] for w in forecast)
    bench_hours = sum(w["bench_fte"] for w in forecast) * week_hours(c)
    billable = [m for m in matches if m["target_type"] == "deal"]
    internal = [m for m in matches if m["target_type"] == "internal"]
    billable_h = sum(m["hours_in_horizon"] * m["win_probability"] for m in billable)
    billable_h_all = sum(m["hours_in_horizon"] for m in billable)
    billable_cost = sum(m["cost_covered_inr"] * m["win_probability"] for m in billable)
    internal_h = sum(m["hours_in_horizon"] for m in internal)
    internal_cost = sum(m["cost_covered_inr"] for m in internal)
    training_h = sum(min(u["course_hours"], u["hours_per_week"] * u["weeks"]) for u in upskilling)
    training_cost = sum(min(u["course_hours"], u["hours_per_week"] * u["weeks"]) * role_cost(c, c.employees[u["emp_id"]].role)
                        for u in upskilling)
    fees = sum(u["cost_inr"] for u in upskilling)
    matched_people = {m["emp_id"] for m in matches}
    trained_people = {u["emp_id"] for u in upskilling}
    idle = max(0.0, bench_cost - billable_cost - internal_cost - training_cost)
    return {
        "bench_hours_if_nothing": r1(bench_hours),
        "bench_cost_if_nothing_inr": round(bench_cost),
        "billable_hours_expected": r1(billable_h),
        "billable_hours_if_all_deals_won": r1(billable_h_all),
        "bench_cost_covered_by_billable_inr": round(billable_cost),
        "internal_hours": r1(internal_h),
        "internal_investment_inr": round(internal_cost),
        "training_hours": r1(training_h),
        "training_time_inr": round(training_cost),
        "course_fees_inr": round(fees),
        "idle_cost_remaining_inr": round(idle),
        "people_rolling_off": len(rolls),
        "people_matched": len(matched_people),
        "people_upskilled": len(trained_people),
        "people_without_plan": len({r["emp_id"] for r in rolls} - matched_people - trained_people),
    }


def inr(x: float) -> str:
    """Indian digit grouping: 1234567 -> 12,34,567."""
    s = str(int(round(x)))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


# =========================================================================== calculator fill (safety net)

_PRIORITY = {"high": 0, "medium": 1, "low": 2}


def fill_internal_capacity(c: CompanyData, matches: list[dict], rolls: list[dict], internal: list[dict],
                           horizon_end: date) -> list[dict]:
    """After the Matcher: put people who are still >= 50% free on internal initiatives with spare capacity,
    by initiative priority, only where role and at least one skill fit. Returns the extra (validated) matches."""
    planned: dict[str, int] = {}
    used: dict[str, float] = {}
    for m in matches:
        planned[m["emp_id"]] = planned.get(m["emp_id"], 0) + m["allocation_pct"]
        if m["target_type"] == "internal":
            used[m["target_id"]] = used.get(m["target_id"], 0.0) + m["allocation_pct"] / 100
    internal_by_id = {w["id"]: w for w in internal}
    rolls_by_id = {r["emp_id"]: r for r in rolls}
    extra: list[dict] = []
    for w in sorted(internal, key=lambda x: (_PRIORITY.get(x["priority"], 3), x["id"])):
        spare = w["capacity_fte"] - used.get(w["id"], 0.0)
        cands = []
        for r in rolls:
            left = r["free_pct"] - planned.get(r["emp_id"], 0)
            e = c.employees.get(r["emp_id"])
            if left < 50 or not e or e.role not in w["roles"]:
                continue
            fit, matched = skill_fit(e, w["skills"])
            if not matched:
                continue
            cands.append((-len(matched), r["free_from"], r["emp_id"], left, matched))
        for _, free_from, emp_id, left, matched in sorted(cands):
            if spare < 0.25:
                break
            alloc = int(min(left, spare * 100) // 25 * 25)
            if alloc < 50:
                continue
            start = max(date.fromisoformat(free_from), c.as_of)
            weeks = max(w["min_weeks"], math.ceil((horizon_end - start).days / 7))
            if w.get("max_weeks"):
                weeks = min(weeks, w["max_weeks"])
            m = {"emp_id": emp_id, "target_type": "internal", "target_id": w["id"], "allocation_pct": alloc,
                 "start_date": start.isoformat(), "weeks": weeks, "confidence": "medium", "source": "calculator",
                 "rationale": f"Calculator fill: free {left}% matched to {w['name']} by role and skills ({', '.join(matched[:3])})."}
            v = validate_match(c, m, {}, internal_by_id, rolls_by_id, horizon_end, planned.get(emp_id, 0))
            if v["status"] == "rejected":
                continue
            extra.append(v)
            planned[emp_id] = planned.get(emp_id, 0) + v["allocation_pct"]
            spare -= v["allocation_pct"] / 100
        used[w["id"]] = w["capacity_fte"] - spare
    return extra
