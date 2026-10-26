"""Generate the synthetic Empower-style demo dataset in data/seed/.

Everything here is made up: people, clients, projects and numbers. It is shaped like
the real thing (the same columns Empower's own records would fill) so the app can be
switched to real data later without code changes -- see README "Using real data".

    python scripts/generate_seed_data.py        # deterministic: same seed, same files
"""

from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "data" / "seed"
AS_OF = date(2026, 10, 26)  # the demo's "today" (a Monday)
rng = random.Random(403)

ROLES = ["pm", "ba", "uiux", "fe", "be", "mobile", "qa", "devops", "data", "ml", "lead"]

# --------------------------------------------------------------------------- module catalog
# Base hours per role for a MEDIUM-complexity version of each module (PM/lead overhead is added
# on top by the estimate calculator, so it is not listed per module).
MODULES: dict[str, dict] = {
    "auth": {"name": "User accounts, login & roles", "tags": ["auth", "login", "sso", "roles", "users", "accounts", "permissions"],
             "hours": {"ba": 8, "uiux": 12, "fe": 40, "be": 56, "qa": 24}},
    "admin_panel": {"name": "Admin panel & back office", "tags": ["admin", "back office", "dashboard", "management", "backoffice"],
                    "hours": {"ba": 16, "uiux": 24, "fe": 80, "be": 72, "qa": 40}},
    "web_portal": {"name": "Customer-facing web portal (UI build)", "tags": ["portal", "website", "web app", "frontend", "responsive", "ui"],
                   "hours": {"ba": 16, "uiux": 60, "fe": 160, "qa": 40}},
    "mobile_app": {"name": "Mobile app (iOS + Android, cross-platform)", "tags": ["mobile", "ios", "android", "app", "react native", "flutter"],
                   "hours": {"uiux": 60, "mobile": 320, "be": 40, "qa": 120}},
    "payments": {"name": "Payments & billing integration", "tags": ["payments", "billing", "stripe", "checkout", "subscription", "wallet", "invoice"],
                 "hours": {"ba": 16, "fe": 32, "be": 96, "qa": 48}},
    "booking": {"name": "Booking & scheduling engine", "tags": ["booking", "scheduling", "appointments", "reservations", "calendar", "availability"],
                "hours": {"ba": 24, "uiux": 24, "fe": 64, "be": 120, "qa": 56}},
    "notifications": {"name": "Notifications (email, SMS, push)", "tags": ["notifications", "email", "sms", "push", "alerts", "reminders"],
                      "hours": {"be": 40, "mobile": 16, "qa": 16}},
    "reporting": {"name": "Reporting & analytics dashboard", "tags": ["reporting", "analytics", "dashboard", "kpi", "charts", "bi", "power bi"],
                  "hours": {"uiux": 16, "fe": 56, "be": 40, "data": 40, "qa": 24}},
    "etl": {"name": "Data pipeline / ETL", "tags": ["etl", "data pipeline", "warehouse", "ingestion", "big data", "spark", "airflow"],
            "hours": {"be": 24, "data": 120, "devops": 16, "qa": 24}},
    "iot": {"name": "IoT device ingestion & telemetry", "tags": ["iot", "sensors", "telemetry", "devices", "mqtt", "machines"],
            "hours": {"be": 96, "data": 40, "devops": 40, "qa": 32}},
    "cms": {"name": "CMS & content management", "tags": ["cms", "content", "blog", "pages", "wordpress", "headless"],
            "hours": {"uiux": 16, "fe": 48, "be": 40, "qa": 20}},
    "search": {"name": "Search, filters & listings", "tags": ["search", "filters", "listings", "catalog", "elasticsearch"],
               "hours": {"fe": 40, "be": 56, "qa": 20}},
    "integration": {"name": "Third-party API integration", "tags": ["integration", "api", "third-party", "erp", "salesforce", "sap", "webhook"],
                    "hours": {"ba": 12, "be": 72, "qa": 24}},
    "llm_assistant": {"name": "LLM assistant / RAG chatbot", "tags": ["llm", "ai", "chatbot", "rag", "gpt", "assistant", "genai"],
                      "hours": {"fe": 32, "be": 48, "ml": 140, "qa": 40}},
    "ml_model": {"name": "Predictive ML model", "tags": ["machine learning", "ml", "prediction", "forecast", "model", "recommendation"],
                 "hours": {"data": 60, "ml": 160, "qa": 24}},
    "compliance": {"name": "Audit logging & compliance controls", "tags": ["compliance", "audit", "hipaa", "gdpr", "security", "logging", "pci"],
                   "hours": {"ba": 16, "be": 64, "devops": 24, "qa": 24}},
    "migration": {"name": "Legacy data migration", "tags": ["migration", "legacy", "data migration", "modernization"],
                  "hours": {"ba": 16, "be": 40, "data": 64, "qa": 32}},
    "cloud_infra": {"name": "Cloud infrastructure, CI/CD & environments", "tags": ["aws", "azure", "cloud", "devops", "ci/cd", "serverless", "kubernetes", "hosting"],
                    "hours": {"be": 16, "devops": 80}},
    "realtime": {"name": "Real-time sync & live updates", "tags": ["real-time", "realtime", "live", "websocket", "polling", "streaming", "sync"],
                 "hours": {"fe": 40, "be": 80, "devops": 16, "qa": 32}},
    "ecommerce": {"name": "Product catalog, cart & checkout", "tags": ["ecommerce", "e-commerce", "shop", "cart", "catalog", "orders", "store"],
                  "hours": {"uiux": 32, "fe": 96, "be": 104, "qa": 56}},
    "crm": {"name": "CRM workflows & customer records", "tags": ["crm", "customers", "leads", "sales", "pipeline", "contacts"],
            "hours": {"ba": 32, "fe": 64, "be": 96, "qa": 40}},
    "bpm": {"name": "Workflow & approval engine (BPM)", "tags": ["workflow", "approval", "bpm", "process", "automation", "forms"],
            "hours": {"ba": 32, "fe": 56, "be": 104, "qa": 40}},
    "patient_records": {"name": "Patient records & care plans", "tags": ["patient", "ehr", "emr", "health records", "care plan", "clinical"],
                        "hours": {"ba": 40, "fe": 80, "be": 120, "qa": 56}},
    "tracking": {"name": "Event tracking & pixel analytics", "tags": ["tracking", "pixel", "events", "web analytics", "clickstream", "monitoring"],
                 "hours": {"be": 80, "data": 80, "devops": 32, "qa": 24}},
    "geo": {"name": "Maps, geolocation & route tracking", "tags": ["maps", "gps", "geolocation", "location", "routes", "tracking", "fleet"],
            "hours": {"fe": 40, "be": 56, "mobile": 40, "qa": 24}},
}
COMPLEXITY = {"low": 0.6, "medium": 1.0, "high": 1.6}

# --------------------------------------------------------------------------- people
FIRST = ["Aarav", "Priya", "Rohan", "Sneha", "Vikram", "Ananya", "Arjun", "Kavya", "Rahul", "Neha", "Siddharth", "Pooja",
         "Aditya", "Isha", "Karan", "Meera", "Nikhil", "Riya", "Saurabh", "Tanvi", "Yash", "Shruti", "Abhishek", "Divya",
         "Harsh", "Kriti", "Manish", "Nidhi", "Omkar", "Pallavi", "Rakesh", "Simran", "Tarun", "Vaishali", "Akash", "Bhavna",
         "Chirag", "Deepika", "Gaurav", "Hema", "Jayesh", "Komal", "Lokesh", "Mansi", "Naveen", "Ojas", "Prachi", "Rajat",
         "Sakshi", "Tushar", "Uday", "Varsha", "Vivek", "Zoya", "Ankit", "Swati", "Mohit", "Ritika"]
LAST = ["Sharma", "Jain", "Patil", "Kulkarni", "Chouhan", "Joshi", "Mehta", "Agrawal", "Verma", "Gupta", "Rathore", "Deshmukh",
        "Malviya", "Soni", "Saxena", "Iyer", "Bhatt", "Tiwari", "Dubey", "Patidar", "Khandelwal", "Pandey", "Mishra", "Rao",
        "Vyas", "Shukla", "Yadav", "Choudhary", "Pawar", "Nair", "Solanki", "Kaur", "Goyal", "Bhonsle", "Thakur", "Jadhav",
        "Porwal", "Raghuwanshi", "Mandloi", "Sethi", "Gehlot", "Rajput", "Parmar", "Dixit", "Kumar", "Kale", "Bansal",
        "Kothari", "Mahajan", "Shinde", "Bhargava", "More", "Sinha", "Khan"]

# role -> (headcount, title, skill pool, monthly loaded cost range in INR by level)
ROLE_SETUP = {
    "pm": (4, "Project Manager", ["Scrum", "Jira", "Client communication", "Risk management", "Agile", "HIPAA", "GDPR"]),
    "ba": (3, "Business Analyst", ["Requirements", "User stories", "Process mapping", "Figma", "SQL", "Power BI", "Healthcare domain", "Fintech domain"]),
    "uiux": (3, "UI/UX Designer", ["Figma", "Design systems", "Prototyping", "Accessibility (WCAG)", "Mobile UI", "User research"]),
    "fe": (8, "Frontend Developer", ["React", "Angular", "Vue", "TypeScript", "Next.js", "Tailwind", "Redux", "Accessibility (WCAG)", "WordPress"]),
    "be": (10, "Backend Developer", [".NET Core", "C#", "ASP.NET MVC", "Node.js", "Python", "Django", "FastAPI", "SQL Server", "PostgreSQL",
                                     "MongoDB", "REST APIs", "GraphQL", "Stripe", "Twilio", "Salesforce API", "Redis", "WebSockets", "Elasticsearch"]),
    "mobile": (6, "Mobile Developer", ["React Native", "Flutter", "Swift", "Kotlin", "Firebase", "Push notifications", "Google Maps SDK", "Offline sync"]),
    "qa": (7, "QA Engineer", ["Manual testing", "Selenium", "Cypress", "Appium", "JMeter", "API testing", "Playwright", "Security testing"]),
    "devops": (3, "DevOps / Cloud Engineer", ["AWS", "AWS Lambda", "Serverless", "Azure", "Docker", "Kubernetes", "Terraform", "CI/CD", "Monitoring"]),
    "data": (3, "Data / BI Engineer", ["Power BI", "Tableau", "SQL", "Spark", "Airflow", "AWS Glue", "Python", "Snowflake", "ETL"]),
    "ml": (3, "AI / ML Engineer", ["Python", "LLM / RAG", "OpenAI API", "LangChain", "PyTorch", "scikit-learn", "Vector databases", "MLOps"]),
    "lead": (4, "Tech Lead / Architect", [".NET Core", "Azure", "AWS", "Node.js", "React", "Microservices", "System design", "Security", "Python"]),
}
LEVEL_COST = {  # monthly loaded cost to company in INR (salary + benefits), before office/bench overhead
    "Junior": (45_000, 70_000), "Mid": (80_000, 120_000), "Senior": (130_000, 190_000), "Lead": (200_000, 290_000),
}
OFFICES = ["Indore"] * 6 + ["Pune"] * 3 + ["Bhopal"] * 2


def level_for(role: str) -> str:
    if role == "lead":
        return "Lead"
    if role == "pm":
        return rng.choice(["Senior", "Senior", "Lead"])
    return rng.choices(["Junior", "Mid", "Senior"], weights=[3, 5, 3])[0]


def make_employees() -> list[dict]:
    names = rng.sample([f"{f} {l}" for f in FIRST for l in LAST], 60)
    people, n = [], 1
    for role, (count, title, pool) in ROLE_SETUP.items():
        for _ in range(count):
            level = level_for(role)
            years = {"Junior": rng.randint(1, 3), "Mid": rng.randint(3, 6), "Senior": rng.randint(6, 11), "Lead": rng.randint(10, 18)}[level]
            k = {"Junior": 3, "Mid": 4, "Senior": 5, "Lead": 6}[level]
            skills = rng.sample(pool, min(k, len(pool)))
            lo, hi = LEVEL_COST[level]
            people.append({
                "emp_id": f"E{n:03d}",
                "name": names[n - 1],
                "role": role,
                "title": f"{level} {title}" if level not in ("Lead",) or role != "lead" else title,
                "level": level,
                "office": rng.choice(OFFICES),
                "years_exp": years,
                "skills": ";".join(skills),
                "monthly_cost_inr": int(rng.randint(lo, hi) / 1000) * 1000,
                "joined": (AS_OF - timedelta(days=rng.randint(200, 365 * min(years, 12)))).isoformat(),
            })
            n += 1
    return people


# --------------------------------------------------------------------------- clients + historical projects
CLIENTS = [
    # name, country, industry, since, notes
    ("CareBridge Health", "US", "Healthcare", 2018, "Long-term client; HIPAA-heavy work; slow UAT sign-offs"),
    ("MediLink Partners", "US", "Healthcare", 2021, "Pays on time; prefers fixed price"),
    ("PayNest", "UK", "Fintech", 2020, "Wallet and payments platform; strict PCI expectations"),
    ("Kraftwerk Maschinenbau GmbH", "DE", "Manufacturing", 2019, "German manufacturer; GDPR + data residency in EU required"),
    ("Coachline Travel", "UK", "Travel", 2017, "Coach and tour booking; peak-season deadlines"),
    ("BrightPath Learning", "US", "EdTech", 2022, "K-12 learning platform; interested in AI tutoring"),
    ("StoryLive Media", "US", "Media", 2016, "Live TV companion apps; hard real-time deadlines"),
    ("SafeWatch Registry", "US", "Public safety", 2015, "Government-adjacent; 50-state data; security reviews"),
    ("Vandenberg Retail NV", "BE", "Retail", 2021, "Belgian retailer; BI and e-commerce"),
    ("Gulf Freight Lines", "AE", "Logistics", 2023, "Fleet tracking; Arabic UI was a scope surprise"),
    ("Outback Realty Group", "AU", "Real estate", 2022, "Listing portal; time-zone gap needs async process"),
    ("Kiwi Insure", "NZ", "Insurance", 2024, "Claims portal; legacy data migration was messy"),
    ("CapeTech Ventures", "ZA", "Startup / VC", 2023, "Funds MVPs; budget-sensitive, fast timelines"),
    ("Pixelwise Analytics", "US", "Marketing tech", 2016, "Pixel tracking at ~1B hits/month"),
    ("Nordlicht Energie AG", "DE", "Energy", 2024, "Smart-meter dashboards; EU hosting only"),
    ("Sakura Learning KK", "JP", "EdTech", 2025, "Language-learning app; Japanese localisation"),
]

# (project name, client index, type, stack, [(module, complexity)], contract, start, duration_weeks)
HISTORY = [
    ("Patient portal v2", 0, "web", ".NET Core, React, SQL Server, Azure", [("auth", "high"), ("patient_records", "high"), ("booking", "medium"), ("notifications", "medium"), ("compliance", "high"), ("web_portal", "medium"), ("cloud_infra", "medium")], "fixed", "2023-02-06", 30),
    ("Telehealth mobile app", 0, "mobile", "React Native, Node.js, Twilio, AWS", [("mobile_app", "high"), ("auth", "medium"), ("booking", "medium"), ("notifications", "medium"), ("integration", "medium"), ("compliance", "medium")], "tm", "2024-04-01", 28),
    ("Care-plan analytics dashboard", 1, "bi", "Power BI, Azure SQL, Python", [("etl", "medium"), ("reporting", "high"), ("auth", "low"), ("compliance", "medium")], "fixed", "2022-09-05", 16),
    ("Provider scheduling system", 1, "web", ".NET Core, Angular, SQL Server", [("booking", "high"), ("auth", "medium"), ("admin_panel", "medium"), ("notifications", "low"), ("integration", "medium")], "fixed", "2024-08-12", 22),
    ("Wallets on the Fly", 2, "mobile", "Flutter, Node.js, PostgreSQL, AWS", [("mobile_app", "high"), ("payments", "high"), ("auth", "high"), ("notifications", "medium"), ("compliance", "high"), ("admin_panel", "medium")], "tm", "2021-03-01", 40),
    ("Merchant onboarding portal", 2, "web", "React, .NET Core, Azure", [("web_portal", "medium"), ("bpm", "medium"), ("integration", "high"), ("auth", "medium")], "fixed", "2023-10-02", 18),
    ("Machine monitoring dashboard", 3, "iot", "Node.js, MQTT, InfluxDB, React, Azure", [("iot", "high"), ("reporting", "medium"), ("realtime", "medium"), ("auth", "low"), ("cloud_infra", "medium")], "fixed", "2022-01-10", 24),
    ("Spare-parts B2B ordering portal", 3, "ecommerce", ".NET Core, Angular, SQL Server", [("ecommerce", "medium"), ("search", "medium"), ("integration", "high"), ("auth", "medium"), ("admin_panel", "low")], "fixed", "2024-11-04", 20),
    ("Coach booking platform", 4, "web", "PHP Laravel, Vue, MySQL, AWS", [("booking", "high"), ("payments", "medium"), ("search", "medium"), ("web_portal", "medium"), ("admin_panel", "medium"), ("notifications", "low")], "fixed", "2019-06-03", 26),
    ("Sightseeing tours mobile app", 4, "mobile", "React Native, Node.js, Stripe", [("mobile_app", "medium"), ("booking", "medium"), ("payments", "medium"), ("geo", "medium")], "fixed", "2023-05-08", 20),
    ("Adaptive learning platform (LMS)", 5, "web", "React, Python FastAPI, PostgreSQL, AWS", [("web_portal", "high"), ("auth", "medium"), ("cms", "medium"), ("reporting", "medium"), ("admin_panel", "medium")], "tm", "2022-07-11", 30),
    ("AI homework tutor (LLM)", 5, "ai", "Python, OpenAI API, RAG, React", [("llm_assistant", "high"), ("web_portal", "low"), ("auth", "low"), ("compliance", "medium")], "tm", "2025-01-13", 18),
    ("Live show story-sync app", 6, "mobile", "React Native, Node.js, WebSockets, AWS", [("mobile_app", "medium"), ("realtime", "high"), ("cms", "medium"), ("cloud_infra", "medium")], "fixed", "2020-08-03", 16),
    ("Multi-time-zone live polling", 6, "web", "React, Node.js, Redis, AWS Lambda", [("realtime", "high"), ("web_portal", "low"), ("reporting", "low"), ("cloud_infra", "high")], "fixed", "2023-01-09", 12),
    ("50-state offender search", 7, "web", ".NET Core, SQL Server, Elasticsearch, Azure", [("search", "high"), ("etl", "high"), ("web_portal", "medium"), ("compliance", "high"), ("geo", "medium")], "tm", "2019-02-04", 36),
    ("Registry data-sync modernization", 7, "migration", ".NET Core, Azure Functions, SQL Server", [("migration", "high"), ("etl", "medium"), ("integration", "medium"), ("cloud_infra", "medium")], "fixed", "2024-02-05", 20),
    ("Store performance BI", 8, "bi", "Power BI, Snowflake, Airflow", [("etl", "high"), ("reporting", "high"), ("integration", "low")], "fixed", "2022-03-07", 14),
    ("Headless e-commerce storefront", 8, "ecommerce", "Next.js, Node.js, Stripe, AWS", [("ecommerce", "high"), ("cms", "medium"), ("payments", "medium"), ("search", "medium"), ("integration", "medium")], "fixed", "2024-06-03", 24),
    ("Fleet tracking app", 9, "mobile", "Flutter, Node.js, Google Maps, AWS IoT", [("mobile_app", "medium"), ("geo", "high"), ("iot", "medium"), ("admin_panel", "medium"), ("reporting", "low")], "fixed", "2023-09-04", 26),
    ("Property listing portal", 10, "web", "React, Node.js, PostgreSQL, AWS", [("search", "high"), ("web_portal", "medium"), ("cms", "medium"), ("auth", "medium"), ("integration", "low")], "fixed", "2022-10-03", 18),
    ("Claims processing portal", 11, "web", ".NET Core, Angular, SQL Server, Azure", [("bpm", "high"), ("web_portal", "medium"), ("migration", "high"), ("auth", "medium"), ("compliance", "medium")], "fixed", "2024-09-02", 28),
    ("Marketplace MVP", 12, "web", "React, Node.js, PostgreSQL, Stripe", [("web_portal", "low"), ("auth", "low"), ("payments", "medium"), ("search", "low"), ("admin_panel", "low")], "fixed", "2025-02-03", 10),
    ("Fintech savings MVP", 12, "mobile", "Flutter, Firebase, Stripe", [("mobile_app", "low"), ("auth", "low"), ("payments", "medium"), ("notifications", "low")], "fixed", "2025-06-02", 12),
    ("Pixel tracking at scale", 13, "bigdata", "Node.js, Kafka, Spark, AWS", [("tracking", "high"), ("etl", "high"), ("reporting", "medium"), ("cloud_infra", "high")], "tm", "2017-04-03", 34),
    ("360 web monitoring dashboard", 13, "bi", "React, Python, ClickHouse, AWS", [("reporting", "high"), ("tracking", "medium"), ("realtime", "medium"), ("auth", "low")], "fixed", "2021-11-01", 18),
    ("Smart-meter analytics", 14, "iot", "Python, Azure IoT Hub, Power BI", [("iot", "high"), ("etl", "medium"), ("reporting", "medium"), ("compliance", "medium"), ("cloud_infra", "medium")], "fixed", "2024-10-07", 22),
    ("Language-learning app", 15, "mobile", "React Native, Node.js, OpenAI API", [("mobile_app", "high"), ("llm_assistant", "medium"), ("auth", "low"), ("cms", "medium"), ("payments", "low")], "tm", "2025-05-05", 26),
    ("Sales CRM customization", 1, "crm", ".NET Core, React, Salesforce API", [("crm", "high"), ("integration", "high"), ("reporting", "low"), ("auth", "low")], "fixed", "2025-03-03", 16),
    ("Demand forecasting model", 8, "ai", "Python, scikit-learn, Snowflake, AWS SageMaker", [("ml_model", "high"), ("etl", "medium"), ("reporting", "low")], "tm", "2025-07-07", 14),
    ("Customer support RAG assistant", 2, "ai", "Python, OpenAI API, PostgreSQL pgvector, React", [("llm_assistant", "high"), ("integration", "medium"), ("compliance", "medium"), ("admin_panel", "low")], "fixed", "2025-08-04", 14),
]

# How badly each kind of project historically overran its estimate (mean actual/estimate) -- the
# pattern the Estimator is supposed to discover from the data and correct for.
OVERRUN_BY_TYPE = {"web": 1.14, "mobile": 1.22, "bi": 1.06, "iot": 1.18, "ecommerce": 1.15, "ai": 1.30,
                   "migration": 1.26, "bigdata": 1.17, "crm": 1.12}
OUTCOME_NOTES = {
    "mobile": ["App-store review added 2 weeks", "Device fragmentation drove extra QA", "Offline sync was underestimated"],
    "ai": ["Prompt/eval iterations took longer than planned", "Client changed the knowledge base mid-project", "Hallucination guardrails added late"],
    "migration": ["Legacy data quality far worse than sampled", "Two extra reconciliation cycles", "Cut-over weekend slipped once"],
    "iot": ["Device firmware changes from client side", "Field testing delayed by hardware shipping"],
    "web": ["Scope creep in admin features", "UAT sign-off slow on client side", "Delivered on time"],
    "bi": ["Source data definitions unclear at start", "Delivered on time"],
    "ecommerce": ["Payment gateway certification delayed go-live", "Catalog import edge cases"],
    "bigdata": ["Traffic spikes forced re-architecture of ingestion"],
    "crm": ["Salesforce API limits needed batching redesign"],
}
RATE_USD = {"pm": 38, "ba": 32, "uiux": 30, "fe": 28, "be": 30, "mobile": 32, "qa": 22, "devops": 36, "data": 36, "ml": 45, "lead": 45}
FX_TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "AUD": 0.66, "NZD": 0.60, "ZAR": 0.055, "AED": 0.27, "JPY": 0.0067}
CURRENCY_BY_COUNTRY = {"US": "USD", "UK": "GBP", "DE": "EUR", "BE": "EUR", "AE": "USD", "AU": "AUD", "NZ": "NZD", "ZA": "USD", "JP": "USD"}

BRIEF_OPENERS = [
    "Hi Empower team, we are {client}, a {industry} company based in {country}. We'd like a quote to build {what}.",
    "Hello, {client} ({country}) is looking for an offshore partner to deliver {what}.",
    "Dear Empower, following our call, here is a short description of {what} for {client}.",
]


def module_hours(module: str, complexity: str, noise: float) -> dict[str, float]:
    base = MODULES[module]["hours"]
    return {r: round(h * COMPLEXITY[complexity] * noise, 1) for r, h in base.items()}


def make_history() -> tuple[list[dict], list[dict]]:
    projects, rows = [], []
    for i, (name, ci, ptype, stack, mods, contract, start, weeks) in enumerate(HISTORY, start=101):
        client, country, industry, _, _ = CLIENTS[ci]
        pid = f"P{i}"
        est_total = act_total = 0.0
        overrun_mean = OVERRUN_BY_TYPE[ptype]
        for module, cx in mods:
            est = module_hours(module, cx, rng.uniform(0.85, 1.15))
            for role, h in est.items():
                ratio = max(0.85, rng.gauss(overrun_mean, 0.08))
                if module in ("integration", "migration", "llm_assistant") and rng.random() < 0.5:
                    ratio += 0.1  # the classic surprises
                act = round(h * ratio, 1)
                rows.append({"project_id": pid, "module": module, "complexity": cx, "role": role,
                             "est_hours": h, "actual_hours": act})
                est_total += h
                act_total += act
        # PM + tech-lead overhead is tracked as its own "management" line
        dev = est_total
        for role, pct in (("pm", 0.10), ("lead", 0.06)):
            h = round(dev * pct, 1)
            a = round(h * rng.uniform(1.0, 1.2), 1)
            rows.append({"project_id": pid, "module": "management", "complexity": "medium", "role": role,
                         "est_hours": h, "actual_hours": a})
            est_total += h
            act_total += a
        currency = CURRENCY_BY_COUNTRY[country]
        blended_usd = sum(RATE_USD[r["role"]] * r["est_hours"] for r in rows if r["project_id"] == pid) / est_total
        price_usd = est_total * blended_usd * (1.12 if contract == "fixed" else 1.0) * rng.uniform(0.95, 1.08)
        price = round(price_usd / FX_TO_USD[currency], -2)
        start_d = date.fromisoformat(start)
        planned_end = start_d + timedelta(weeks=weeks)
        slip_weeks = max(0, round((act_total / est_total - 1) * weeks * rng.uniform(0.4, 0.9)))
        actual_end = planned_end + timedelta(weeks=slip_weeks)
        notes = rng.choice(OUTCOME_NOTES[ptype])
        what = name.lower()
        features = ", ".join(MODULES[m]["name"].lower() for m, _ in mods)
        brief = (rng.choice(BRIEF_OPENERS).format(client=client, industry=industry.lower(), country=country, what=f"a {what}")
                 + f" It needs: {features}. Preferred stack if you have no strong opinion: {stack}."
                 + f" We would like to launch in about {weeks // 4 + 1} months.")
        projects.append({
            "project_id": pid, "name": name, "client": client, "country": country, "industry": industry,
            "project_type": ptype, "stack": stack, "contract_type": contract, "currency": currency,
            "price": int(price), "est_hours": round(est_total), "actual_hours": round(act_total),
            "start_date": start, "planned_end": planned_end.isoformat(), "actual_end": actual_end.isoformat(),
            "team_size": max(3, round(est_total / (weeks * 40 * 0.8))),
            "modules": ";".join(m for m, _ in mods), "outcome_notes": notes, "brief": brief,
        })
    return projects, rows


LOST_DEALS = [
    # client, country, project_type, quoted_usd_per_hour, reason
    ("HelixPay", "US", "mobile", 34, "Lost to a Vietnam vendor quoting $24/h; client prioritised price over PCI experience"),
    ("Brennan Dental Group", "US", "web", 31, "Client chose a local US agency for in-person workshops"),
    ("Rhein Logistik", "DE", "iot", 37, "We could not commit a German-speaking PM; requirement was buried in the RFP"),
    ("EduSpark", "UK", "ai", 48, "Quoted 9 months; competitor promised 5. Our estimate turned out realistic"),
    ("TableTurn", "US", "web", 26, "Won on price but walked away: client wanted unlimited change requests on fixed price"),
    ("Mercato Uno", "BE", "ecommerce", 33, "Client paused the project (budget freeze)"),
]


# --------------------------------------------------------------------------- current work + availability
ACTIVE = [
    # code, name, client index, end offset weeks from AS_OF, roles needed [(role, alloc)]
    ("A201", "Wallets on the Fly - v3 features", 2, 14, [("pm", 50), ("lead", 50), ("mobile", 100), ("mobile", 100), ("be", 100), ("be", 50), ("qa", 100)]),
    ("A202", "Patient portal - maintenance retainer", 0, 30, [("be", 50), ("fe", 50), ("qa", 50), ("devops", 25)]),
    ("A203", "Smart-meter analytics - phase 2", 14, 6, [("pm", 50), ("data", 100), ("data", 50), ("be", 100), ("devops", 50), ("qa", 50)]),
    ("A204", "Language-learning app - growth features", 15, 10, [("pm", 50), ("mobile", 100), ("mobile", 100), ("ml", 100), ("be", 100), ("qa", 50), ("uiux", 50)]),
    ("A205", "Headless storefront - retainer", 8, 22, [("fe", 50), ("qa", 25)]),
    ("A206", "Claims portal - stabilisation", 11, 3, [("lead", 50), ("be", 100), ("be", 100), ("fe", 100), ("qa", 100), ("ba", 50)]),
    ("A207", "Support RAG assistant - v2", 2, 8, [("ml", 100), ("be", 50), ("fe", 50), ("qa", 50)]),
    ("A208", "Internal: Empower AI accelerator", None, 52, [("ml", 50), ("lead", 25)]),
    ("A209", "Fleet tracking - Arabic + iPad", 9, 12, [("pm", 50), ("mobile", 100), ("fe", 100), ("be", 50), ("qa", 50), ("uiux", 50), ("ba", 50)]),
    ("A210", "Sales CRM - phase 2", 1, 18, [("lead", 50), ("be", 100), ("fe", 100), ("qa", 50), ("ba", 50), ("devops", 25)]),
]


def make_assignments(people: list[dict]) -> list[dict]:
    by_role: dict[str, list[dict]] = {}
    for p in people:
        by_role.setdefault(p["role"], []).append(p)
    load: dict[str, int] = {p["emp_id"]: 0 for p in people}
    out = []
    for code, name, ci, end_w, needs in ACTIVE:
        client = CLIENTS[ci][0] if ci is not None else "Empower (internal)"
        start = AS_OF - timedelta(weeks=rng.randint(6, 40))
        end = AS_OF + timedelta(weeks=end_w)
        used: set[str] = set()
        for role, alloc in needs:
            pool = sorted((p for p in by_role[role] if p["emp_id"] not in used and load[p["emp_id"]] + alloc <= 100),
                          key=lambda p: (load[p["emp_id"]], rng.random()))
            if not pool:
                continue
            person = pool[0]
            used.add(person["emp_id"])
            load[person["emp_id"]] += alloc
            out.append({"emp_id": person["emp_id"], "project_code": code, "project_name": name, "client": client,
                        "allocation_pct": alloc, "start_date": start.isoformat(), "end_date": end.isoformat(), "kind": "project"})
    # a few signed-but-not-started projects that will absorb people soon
    for emp_id, wk, weeks, alloc, label in (("E030", 3, 16, 100, "Kiwi Insure - claims v2 (signed)"),
                                            ("E012", 2, 20, 100, "Kiwi Insure - claims v2 (signed)"),
                                            ("E045", 4, 12, 50, "Coachline - peak-season upgrades (signed)")):
        if any(p["emp_id"] == emp_id for p in people):
            s = AS_OF + timedelta(weeks=wk)
            out.append({"emp_id": emp_id, "project_code": "A211" if "Kiwi" in label else "A212", "project_name": label,
                        "client": "Kiwi Insure" if "Kiwi" in label else "Coachline Travel", "allocation_pct": alloc,
                        "start_date": s.isoformat(), "end_date": (s + timedelta(weeks=weeks)).isoformat(), "kind": "project"})
    # planned leave (Diwali / weddings / exams) -- availability is never just "on a project or not"
    for p in rng.sample(people, 7):
        s = AS_OF + timedelta(days=rng.randint(5, 70))
        out.append({"emp_id": p["emp_id"], "project_code": "LEAVE", "project_name": "Planned leave", "client": "",
                    "allocation_pct": 100, "start_date": s.isoformat(), "end_date": (s + timedelta(days=rng.randint(5, 14))).isoformat(),
                    "kind": "leave"})
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    people = make_employees()
    projects, modules = make_history()
    assignments = make_assignments(people)
    write_csv(SEED_DIR / "employees.csv", people)
    write_csv(SEED_DIR / "projects.csv", projects)
    write_csv(SEED_DIR / "project_modules.csv", modules)
    write_csv(SEED_DIR / "assignments.csv", assignments)
    write_csv(SEED_DIR / "clients.csv", [{"client": c, "country": co, "industry": ind, "client_since": s, "notes": n}
                                         for c, co, ind, s, n in CLIENTS])
    write_csv(SEED_DIR / "lost_deals.csv", [{"client": c, "country": co, "project_type": t, "quoted_usd_per_hour": q, "reason": r}
                                            for c, co, t, q, r in LOST_DEALS])
    catalog = {k: {"name": v["name"], "tags": v["tags"], "base_hours_medium": v["hours"]} for k, v in MODULES.items()}
    (SEED_DIR / "module_catalog.json").write_text(json.dumps({"complexity_multipliers": COMPLEXITY, "modules": catalog}, indent=2), encoding="utf-8")
    (SEED_DIR / "meta.json").write_text(json.dumps({
        "dataset": "synthetic-demo",
        "as_of": AS_OF.isoformat(),
        "description": "Synthetic Empower-style data generated by scripts/generate_seed_data.py. No real people, clients or numbers.",
    }, indent=2), encoding="utf-8")
    print(f"{len(people)} employees, {len(projects)} past projects, {len(modules)} module rows, {len(assignments)} assignments -> {SEED_DIR}")


if __name__ == "__main__":
    main()
