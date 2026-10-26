"""Generate the Bench Optimizer's synthetic data in data/seed/bench/ (deterministic, no randomness).

    python scripts/generate_bench_data.py

- internal_work.json: internal initiatives a person on the bench can do while waiting for billable work.
- courses.json: a course catalogue for upskilling toward the skills Empower's pipeline asks for.

Skill names match the ones in data/seed/employees.csv so matching works without translation. Everything
else the module needs (people, assignments, deals) comes from the shared company data and the Deal Desk.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "seed" / "bench"

INTERNAL_WORK = [
    {
        "id": "IW1", "name": "Empower AI accelerator: reusable RAG starter kit",
        "roles": ["ml", "be", "fe"], "skills": ["LLM / RAG", "OpenAI API", "Python", "FastAPI", "React"],
        "capacity_fte": 2.0, "min_weeks": 4, "priority": "high",
        "value": "Cuts 2-3 weeks from every AI deal; reusable demo for CES follow-ups and EdTech/healthcare pitches.",
    },
    {
        "id": "IW2", "name": "Sales demo builds for open proposals",
        "roles": ["fe", "mobile", "uiux"], "skills": ["React", "React Native", "Flutter", "Figma", "Prototyping"],
        "capacity_fte": 1.5, "min_weeks": 2, "max_weeks": 6, "priority": "high",
        "value": "Clickable demos raise win rates on proposals that are waiting for a client decision.",
    },
    {
        "id": "IW3", "name": "Reusable UI component library (React + Angular kits)",
        "roles": ["fe", "uiux"], "skills": ["React", "Angular", "TypeScript", "Design systems", "Accessibility (WCAG)"],
        "capacity_fte": 1.5, "min_weeks": 4, "priority": "medium",
        "value": "Saves 5-10% of frontend hours on new web portals; WCAG compliance built in.",
    },
    {
        "id": "IW4", "name": "Pre-sales proofs of concept: IoT telemetry and BI dashboards",
        "roles": ["be", "data", "devops"], "skills": ["Node.js", "Python", "Power BI", "Azure", "Docker", "Spark"],
        "capacity_fte": 1.5, "min_weeks": 3, "priority": "medium",
        "value": "Ready-made PoCs for manufacturing and energy prospects in Germany and Belgium.",
    },
    {
        "id": "IW5", "name": "Cloud cost and CI/CD hardening for retainer clients",
        "roles": ["devops", "be"], "skills": ["AWS", "Azure", "Terraform", "CI/CD", "Docker", "Kubernetes", "Monitoring"],
        "capacity_fte": 1.0, "min_weeks": 3, "priority": "medium",
        "value": "Billable-adjacent: findings usually turn into paid optimisation work with existing clients.",
    },
    {
        "id": "IW6", "name": "QA automation regression packs for retainers",
        "roles": ["qa"], "skills": ["Cypress", "Playwright", "Selenium", "Appium", "API testing"],
        "capacity_fte": 1.5, "min_weeks": 3, "priority": "medium",
        "value": "Cuts manual regression time on maintenance retainers; reusable across clients.",
    },
    {
        "id": "IW7", "name": "Cloud certification sprint (AWS / Azure)",
        "roles": ["be", "fe", "devops", "data", "ml", "lead"], "skills": ["AWS", "Azure", "Serverless", "AWS Lambda"],
        "capacity_fte": 3.0, "min_weeks": 2, "max_weeks": 3, "priority": "low",
        "value": "More certified engineers strengthen partner status and RFP scoring.",
    },
    {
        "id": "IW8", "name": "Internal data pipelines for the Deal Desk and Staffing data",
        "roles": ["be", "data", "ba"], "skills": ["Python", "SQL", "FastAPI", "ETL", "Requirements"],
        "capacity_fte": 1.0, "min_weeks": 3, "priority": "low",
        "value": "Replaces spreadsheet exports with live data for estimates, staffing and appraisals.",
    },
]

COURSES = [
    {"id": "C01", "skill": "React Native", "title": "React Native: production apps for iOS and Android", "provider": "Udemy", "hours": 32, "cost_inr": 3500, "format": "self-paced"},
    {"id": "C02", "skill": "Flutter", "title": "Flutter and Dart: the complete guide", "provider": "Udemy", "hours": 40, "cost_inr": 3500, "format": "self-paced"},
    {"id": "C03", "skill": "LLM / RAG", "title": "Building RAG applications with LLMs", "provider": "DeepLearning.AI / Coursera", "hours": 24, "cost_inr": 4100, "format": "self-paced"},
    {"id": "C04", "skill": "OpenAI API", "title": "OpenAI API and function calling for developers", "provider": "Empower Academy", "hours": 12, "cost_inr": 0, "format": "internal workshop"},
    {"id": "C05", "skill": "Vector databases", "title": "Vector search with pgvector and managed vector DBs", "provider": "Empower Academy", "hours": 10, "cost_inr": 0, "format": "internal workshop"},
    {"id": "C06", "skill": "Azure", "title": "AZ-204: Developing solutions for Microsoft Azure", "provider": "Microsoft Learn", "hours": 40, "cost_inr": 12500, "format": "self-paced + exam"},
    {"id": "C07", "skill": "AWS", "title": "AWS Certified Developer - Associate", "provider": "AWS Skill Builder", "hours": 40, "cost_inr": 12500, "format": "self-paced + exam"},
    {"id": "C08", "skill": "Terraform", "title": "HashiCorp Terraform Associate", "provider": "HashiCorp Learn", "hours": 24, "cost_inr": 6000, "format": "self-paced + exam"},
    {"id": "C09", "skill": "Kubernetes", "title": "Kubernetes for developers (CKAD prep)", "provider": "Linux Foundation", "hours": 36, "cost_inr": 21000, "format": "self-paced + exam"},
    {"id": "C10", "skill": "MQTT", "title": "IoT messaging with MQTT and Azure IoT Hub", "provider": "Microsoft Learn", "hours": 16, "cost_inr": 0, "format": "self-paced"},
    {"id": "C11", "skill": "Stripe", "title": "Stripe payments integration and PCI basics", "provider": "Stripe Docs + Empower Academy", "hours": 12, "cost_inr": 0, "format": "self-paced"},
    {"id": "C12", "skill": "Power BI", "title": "PL-300: Microsoft Power BI Data Analyst", "provider": "Microsoft Learn", "hours": 32, "cost_inr": 12500, "format": "self-paced + exam"},
    {"id": "C13", "skill": "Playwright", "title": "End-to-end testing with Playwright", "provider": "LinkedIn Learning", "hours": 10, "cost_inr": 1500, "format": "self-paced"},
    {"id": "C14", "skill": "Appium", "title": "Mobile test automation with Appium", "provider": "Udemy", "hours": 16, "cost_inr": 2500, "format": "self-paced"},
    {"id": "C15", "skill": "HIPAA", "title": "HIPAA for software engineers", "provider": "Empower Academy", "hours": 6, "cost_inr": 0, "format": "internal workshop"},
    {"id": "C16", "skill": "GDPR", "title": "GDPR and EU data residency for developers", "provider": "Empower Academy", "hours": 6, "cost_inr": 0, "format": "internal workshop"},
    {"id": "C17", "skill": "Next.js", "title": "Next.js App Router in production", "provider": "Vercel / Udemy", "hours": 18, "cost_inr": 3000, "format": "self-paced"},
    {"id": "C18", "skill": "SAP", "title": "SAP integration basics for developers (OData, BAPI)", "provider": "openSAP", "hours": 20, "cost_inr": 0, "format": "self-paced"},
]


def main() -> None:
    for w in INTERNAL_WORK:  # max_weeks: how long one person usefully stays on it (None = until needed elsewhere)
        w.setdefault("max_weeks", None)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "internal_work.json").write_text(json.dumps(INTERNAL_WORK, indent=2), encoding="utf-8")
    (OUT / "courses.json").write_text(json.dumps(COURSES, indent=2), encoding="utf-8")
    print(f"{len(INTERNAL_WORK)} internal initiatives, {len(COURSES)} courses -> {OUT}")


if __name__ == "__main__":
    main()
