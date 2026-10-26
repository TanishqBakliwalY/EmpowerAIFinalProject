"""Who is free, when, and with which skills. Pure functions over company data (no LLM).

Used by the Staffing module's board and Q&A agent, and by the Deal Desk's Staffing Planner.
Weeks start on the dataset's as-of date. An assignment that touches a week counts for the whole
week (conservative: we would rather under-promise availability than double-book someone).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from ...core.company import CompanyData, Employee

# Skills where "X" must not match "X something" (React is not React Native).
_NO_PREFIX = {"react", "java"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def skill_matches(query: str, skill: str) -> bool:
    q, s = norm(query), norm(skill)
    if q == s:
        return True
    return s.startswith(q + " ") and q not in _NO_PREFIX  # ".net" ~ ".net core", "aws" ~ "aws lambda"


def matched_skills(emp: Employee, wanted: list[str]) -> list[str]:
    return [w for w in wanted if any(skill_matches(w, s) for s in emp.skills)]


def week_starts(c: CompanyData, start: date | None, weeks: int) -> list[date]:
    s = start or c.as_of
    return [s + timedelta(weeks=i) for i in range(weeks)]


def weekly_allocation(c: CompanyData, emp_id: str, start: date | None = None, weeks: int = 12,
                      include_leave: bool = True) -> list[int]:
    """Allocation % per week (projects, plus leave unless excluded); can exceed 100 if double-booked."""
    out = []
    mine = [a for a in c.assignments if a.emp_id == emp_id and (include_leave or a.kind != "leave")]
    for ws in week_starts(c, start, weeks):
        we = ws + timedelta(days=6)
        out.append(sum(a.allocation_pct for a in mine if a.start <= we and a.end >= ws))
    return out


def leave_weeks(c: CompanyData, emp_id: str, start: date | None, weeks: int) -> int:
    """How many weeks of the window are touched by planned leave."""
    mine = [a for a in c.assignments if a.emp_id == emp_id and a.kind == "leave"]
    return sum(1 for ws in week_starts(c, start, weeks)
               if any(a.start <= ws + timedelta(days=6) and a.end >= ws for a in mine))


def free_pct(c: CompanyData, emp_id: str, start: date | None, weeks: int) -> int:
    """The lowest free capacity (%) left by PROJECT commitments in any week of the window.
    Planned leave is reported separately (leave_weeks) so one week off doesn't hide a free person."""
    alloc = weekly_allocation(c, emp_id, start, weeks, include_leave=False)
    return max(0, 100 - max(alloc)) if alloc else 100


def earliest_start(c: CompanyData, emp_id: str, needed_pct: int, from_date: date | None = None,
                   run_weeks: int = 8, horizon_weeks: int = 26) -> date | None:
    """First week start from which the person has `needed_pct` free for `run_weeks` weeks in a row."""
    alloc = weekly_allocation(c, emp_id, from_date, horizon_weeks + run_weeks, include_leave=False)
    starts = week_starts(c, from_date, horizon_weeks)
    for i, ws in enumerate(starts):
        if all(100 - a >= needed_pct for a in alloc[i:i + run_weeks]):
            return ws
    return None


def current_work(c: CompanyData, emp_id: str, on: date | None = None, horizon_weeks: int = 26) -> list[dict]:
    """Assignments that are active now or start within the horizon."""
    day = on or c.as_of
    until = day + timedelta(weeks=horizon_weeks)
    return [
        {"project": a.project_name, "code": a.project_code, "client": a.client, "allocation_pct": a.allocation_pct,
         "from": a.start.isoformat(), "to": a.end.isoformat(), "kind": a.kind}
        for a in sorted(c.assignments, key=lambda a: a.start)
        if a.emp_id == emp_id and a.end >= day and a.start <= until
    ]


def person_card(c: CompanyData, e: Employee, start: date | None = None, weeks: int = 12) -> dict:
    """What staffing tools return about one person. No cost data: that stays inside pricing."""
    return {
        "emp_id": e.emp_id, "name": e.name, "role": e.role, "title": e.title, "level": e.level,
        "office": e.office, "years_exp": e.years_exp, "skills": list(e.skills),
        "free_pct_in_window": free_pct(c, e.emp_id, start, weeks),
        "leave_weeks_in_window": leave_weeks(c, e.emp_id, start, weeks),
        "weekly_allocation_pct_incl_leave": weekly_allocation(c, e.emp_id, start, weeks),
        "assignments": current_work(c, e.emp_id, start),
    }


def search_people(c: CompanyData, *, skills: list[str] | None = None, role: str | None = None,
                  start: date | None = None, weeks: int = 12, min_free_pct: int = 0,
                  office: str | None = None, limit: int = 8) -> list[dict]:
    skills = [s for s in (skills or []) if s.strip()]
    # If nobody in the role has any of the skills, fall back to everyone in the role (skills shown, no match).
    require_skill = bool(skills) and (not role or any(
        matched_skills(e, skills) for e in c.employees.values() if e.role == role))
    rows = []
    for e in c.employees.values():
        if role and e.role != role:
            continue
        if office and norm(e.office) != norm(office):
            continue
        hits = matched_skills(e, skills)
        if require_skill and not hits:
            continue
        free = free_pct(c, e.emp_id, start, weeks)
        if free < min_free_pct:
            continue
        nxt = earliest_start(c, e.emp_id, max(50, min_free_pct), start, run_weeks=min(weeks, 8))
        rows.append({
            "emp_id": e.emp_id, "name": e.name, "role": e.role, "title": e.title, "level": e.level, "office": e.office,
            "years_exp": e.years_exp, "skills": list(e.skills), "matched_skills": hits,
            "free_pct_in_window": free, "leave_weeks_in_window": leave_weeks(c, e.emp_id, start, weeks),
            "earliest_start_50pct_or_more": nxt.isoformat() if nxt else None,
            "busy_with": [w["project"] for w in current_work(c, e.emp_id, start) if w["kind"] == "project"][:3],
        })
    level_rank = {"Lead": 3, "Senior": 2, "Mid": 1, "Junior": 0}
    rows.sort(key=lambda r: (-len(r["matched_skills"]), -r["free_pct_in_window"], -level_rank.get(r["level"], 0)))
    return rows[:limit]


# Generic words that should not make two skills "match" on their own.
_STOP = {"integration", "integrations", "development", "developer", "api", "apis", "and", "or", "the", "app", "apps",
         "services", "service", "platform", "management", "system", "systems", "design", "engineering", "native", "web",
         "support", "framework", "data", "testing", "for", "with", "sdk", "notifications", "mobile"}
# Concepts clients write -> skills Empower's people list.
_CONCEPTS = {
    "payment": ["Stripe"], "payments": ["Stripe"], "card": ["Stripe"], "checkout": ["Stripe"], "billing": ["Stripe"],
    "sms": ["Twilio"], "telephony": ["Twilio"], "video": ["Twilio"], "ios": ["Swift", "React Native", "Flutter"],
    "android": ["Kotlin", "React Native", "Flutter"], "push": ["Push notifications", "Firebase"],
    "hipaa": ["HIPAA"], "gdpr": ["GDPR"], "maps": ["Google Maps SDK"], "gps": ["Google Maps SDK"],
    "llm": ["LLM / RAG", "OpenAI API", "LangChain"], "rag": ["LLM / RAG", "Vector databases"], "chatbot": ["LLM / RAG", "OpenAI API"],
    "ml": ["scikit-learn", "PyTorch", "MLOps"], "predictive": ["scikit-learn", "PyTorch"], "bi": ["Power BI", "Tableau"],
    "dashboard": ["Power BI", "React"], "etl": ["ETL", "Airflow", "AWS Glue", "Spark"], "pipeline": ["Airflow", "ETL", "Spark"],
    "audit": ["Security", "Security testing"], "security": ["Security", "Security testing"], "ci/cd": ["CI/CD"],
    "devops": ["CI/CD", "Docker", "Terraform"], "realtime": ["WebSockets", "Redis"], "real-time": ["WebSockets", "Redis"],
    "accessibility": ["Accessibility (WCAG)"], "wcag": ["Accessibility (WCAG)"], "crm": ["Salesforce API"],
    "offline": ["Offline sync"], "testing": ["Selenium", "Cypress", "Appium", "Playwright"],
}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#./-]+", norm(s)) if t not in _STOP and len(t) > 1}


def skill_inventory(c: CompanyData) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in c.employees.values():
        for s in e.skills:
            counts[s] = counts.get(s, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def related_skills(c: CompanyData, query: str) -> list[str]:
    """In-house skills that cover a client concept ('card payments' -> Stripe) or share a real keyword."""
    inv = skill_inventory(c)
    q = _tokens(query)
    out: list[str] = []
    for t in q:
        out += [s for s in _CONCEPTS.get(t, []) if s in inv]
    out += [s for s in inv if q & _tokens(s)]
    return list(dict.fromkeys(out))


def capability(c: CompanyData, skills: list[str]) -> list[dict]:
    """How deep Empower's bench is in each skill, and where it was used before."""
    out = []
    for skill in skills:
        direct = [e for e in c.employees.values() if any(skill_matches(skill, s) for s in e.skills)]
        related = [] if direct else related_skills(c, skill)
        people = direct or [e for e in c.employees.values() if any(s in related for s in e.skills)]
        projects = [p["project_id"] for p in c.projects.values()
                    if norm(skill) in norm(p["stack"]) or any(norm(r) in norm(p["stack"]) for r in related)]
        out.append({
            "skill": skill,
            "matched_in_house_skills": [skill] if direct else related,
            "people": len(people),
            "senior_or_lead": sum(1 for e in people if e.level in ("Senior", "Lead")),
            "free_now_50pct_plus": sum(1 for e in people if free_pct(c, e.emp_id, None, 4) >= 50),
            "past_projects": projects[:6],
            "assessment": ("strong" if len(people) >= 3 else "thin" if people
                           else "used on past projects, no current specialist" if projects else "none in-house"),
        })
    return out


def team_capacity(c: CompanyData, role: str, start: date | None, weeks: int) -> dict:
    people = [e for e in c.employees.values() if e.role == role]
    per_week = [0.0] * weeks
    for e in people:
        for i, a in enumerate(weekly_allocation(c, e.emp_id, start, weeks)):
            per_week[i] += max(0, 100 - a) / 100
    return {"role": role, "headcount": len(people), "free_fte_by_week": [round(x, 1) for x in per_week]}
