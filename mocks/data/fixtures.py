"""Realistic fixture data for local mock integrations."""

from __future__ import annotations

from services.common.schemas import Company, Contact, JobPosting

MOCK_COMPANIES: list[dict] = [
    {
        "name": "LedgerFlow",
        "domain": "ledgerflow.ai",
        "industry": "fintech",
        "linkedin_url": "https://linkedin.com/company/ledgerflow",
        "employee_count": 85,
        "segment_id": "primary",
        "signals": ["recent_raise", "live_job_posting"],
    },
    {
        "name": "NeuralPay",
        "domain": "neuralpay.com",
        "industry": "payments",
        "linkedin_url": "https://linkedin.com/company/neuralpay",
        "employee_count": 120,
        "segment_id": "primary",
        "signals": ["stated_hiring_need"],
    },
    {
        "name": "CartBridge",
        "domain": "cartbridge.io",
        "industry": "ecommerce",
        "linkedin_url": "https://linkedin.com/company/cartbridge",
        "employee_count": 45,
        "segment_id": "secondary",
        "signals": ["live_job_posting"],
    },
    {
        "name": "AgentStack",
        "domain": "agentstack.dev",
        "industry": "ai_ml",
        "linkedin_url": "https://linkedin.com/company/agentstack",
        "employee_count": 32,
        "segment_id": "primary",
        "signals": ["recent_raise", "stated_hiring_need"],
    },
]

MOCK_CONTACTS: dict[str, list[dict]] = {
    "ledgerflow.ai": [
        {
            "full_name": "Maya Chen",
            "title": "CTO",
            "linkedin_url": "https://linkedin.com/in/maya-chen-ledgerflow",
            "persona_tier": 1,
        },
        {
            "full_name": "James Ortiz",
            "title": "VP Engineering",
            "linkedin_url": "https://linkedin.com/in/james-ortiz-ledgerflow",
            "persona_tier": 2,
        },
    ],
    "neuralpay.com": [
        {
            "full_name": "Sarah Kim",
            "title": "Co-Founder & CEO",
            "linkedin_url": "https://linkedin.com/in/sarah-kim-neuralpay",
            "persona_tier": 1,
        },
    ],
    "cartbridge.io": [
        {
            "full_name": "Diego Alvarez",
            "title": "Head of Engineering",
            "linkedin_url": "https://linkedin.com/in/diego-alvarez-cartbridge",
            "persona_tier": 2,
        },
    ],
    "agentstack.dev": [
        {
            "full_name": "Priya Nair",
            "title": "Founder",
            "linkedin_url": "https://linkedin.com/in/priya-nair-agentstack",
            "persona_tier": 1,
        },
        {
            "full_name": "Tom Becker",
            "title": "Engineering Manager",
            "linkedin_url": "https://linkedin.com/in/tom-becker-agentstack",
            "persona_tier": 3,
        },
    ],
}

MOCK_JOB_POSTINGS: dict[str, list[dict]] = {
    "ledgerflow.ai": [
        {
            "title": "Senior Backend Engineer",
            "source": "linkedin",
            "description": (
                "Build payment APIs in Python and FastAPI on AWS. "
                "Requires PostgreSQL, Kubernetes, and fintech experience."
            ),
            "url": "https://linkedin.com/jobs/view/ledgerflow-backend",
            "location": "Remote — US",
        },
    ],
    "neuralpay.com": [
        {
            "title": "Staff Platform Engineer",
            "source": "company_website",
            "description": (
                "Own our payments platform on AWS using Python, Terraform, and Kubernetes. "
                "Strong Java and Spring experience a plus."
            ),
            "url": "https://neuralpay.com/careers/platform-engineer",
        },
    ],
    "agentstack.dev": [
        {
            "title": "ML Engineer",
            "source": "linkedin",
            "description": (
                "Ship LLM features with Python, PyTorch, and MLOps tooling on AWS."
            ),
            "url": "https://linkedin.com/jobs/view/agentstack-ml",
        },
    ],
}

MOCK_EMPLOYEES: list[dict] = [
    {
        "employee_id": "101",
        "display_name": "Ana Rodriguez",
        "job_title": "Senior Backend Engineer",
        "department": "Delivery",
        "skills": ["Python", "AWS", "PostgreSQL", "FastAPI"],
    },
    {
        "employee_id": "102",
        "display_name": "Carlos Mendez",
        "job_title": "Frontend Lead",
        "department": "Delivery",
        "skills": ["React", "TypeScript", "Next.js", "GraphQL"],
    },
    {
        "employee_id": "103",
        "display_name": "Laura Smith",
        "job_title": "ML Engineer",
        "department": "AI Practice",
        "skills": ["Python", "PyTorch", "MLOps", "AWS", "LLM"],
    },
    {
        "employee_id": "104",
        "display_name": "Marco Silva",
        "job_title": "DevOps Engineer",
        "department": "Platform",
        "skills": ["AWS", "Terraform", "Kubernetes", "CI/CD"],
    },
    {
        "employee_id": "105",
        "display_name": "Elena Vargas",
        "job_title": "Fintech Consultant",
        "department": "Delivery",
        "skills": ["Python", "fintech", "payments", "Java", "Spring"],
    },
]


def companies_for_segments(segment_ids: list[str], max_results: int) -> list[Company]:
    selected = [
        Company.model_validate(c)
        for c in MOCK_COMPANIES
        if c.get("segment_id") in segment_ids
    ]
    return selected[:max_results]


def contacts_for_company(company: Company) -> list[Contact]:
    key = (company.domain or company.name).lower()
    if company.domain:
        rows = MOCK_CONTACTS.get(company.domain.lower(), [])
    else:
        rows = MOCK_CONTACTS.get(key, [])
    if not rows:
        for domain, contacts in MOCK_CONTACTS.items():
            if company.name.lower() in domain or domain in (company.domain or "").lower():
                rows = contacts
                break
    return [Contact.model_validate(row) for row in rows]


def job_postings_for_company(company: Company) -> list[JobPosting]:
    domain = (company.domain or "").lower()
    rows = MOCK_JOB_POSTINGS.get(domain, [])
    return [JobPosting.model_validate(row) for row in rows]


def lookup_employees(skills: list[str]) -> list[dict]:
    wanted = {s.strip().lower() for s in skills if s and s.strip()}
    if not wanted:
        return []
    matches: list[dict] = []
    for employee in MOCK_EMPLOYEES:
        emp_skills = employee.get("skills") or []
        overlap = [s for s in emp_skills if s.lower() in wanted]
        if overlap:
            matches.append({**employee, "skills": overlap})
    return matches
