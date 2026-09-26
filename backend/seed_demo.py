"""
Seeds the database with realistic demo data for presentations and testing.

Run: PYTHONPATH=. python3 backend/seed_demo.py
"""

import sys, os, uuid, json
from datetime import datetime, timedelta
import random

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal, init_db
from backend import models
from backend.auth import hash_password

init_db()
db = SessionLocal()

print("🌱 Seeding IDF AI demo data...")

# ── Users ────────────────────────────────────────────────────────────────────
print("  Creating users...")

users_data = [
    {
        "username": "admin",
        "email": "admin@idfai.local",
        "password": "Admin@IDF2025",
        "full_name": "System Administrator",
        "role": "Admin",
    },
    {
        "username": "det_markov",
        "email": "elena.markov@interpol.int",
        "password": "Markov@2025",
        "full_name": "Det. Elena Markov",
        "role": "Investigator",
    },
    {
        "username": "analyst_chen",
        "email": "robert.chen@forensics.int",
        "password": "Chen@2025",
        "full_name": "Analyst Robert Chen",
        "role": "Analyst",
    },
]

for u in users_data:
    existing = db.query(models.User).filter(
        models.User.username == u["username"]
    ).first()
    if not existing:
        user = models.User(
            id=str(uuid.uuid4()),
            username=u["username"],
            email=u["email"],
            hashed_password=hash_password(u["password"]),
            full_name=u["full_name"],
            role=u["role"],
            is_active=True,
        )
        db.add(user)

db.commit()
print("  ✓ Users created")

# ── Cases ─────────────────────────────────────────────────────────────────────
print("  Creating demo cases...")

cases_data = [
    {
        "case_name": "Operation Phantom Trace",
        "case_number": "IDF-2025-001",
        "status": "Active",
        "priority": "Critical",
        "description": "Investigation into Phantom Collective cybercrime network spanning multiple countries.",
        "created_by": "det_markov",
        "tags": json.dumps(["cybercrime", "international", "financial"]),
    },
    {
        "case_name": "Vertex Pharma Leak",
        "case_number": "IDF-2025-002",
        "status": "Active",
        "priority": "High",
        "description": "Corporate espionage investigation — leaked pharmaceutical research.",
        "created_by": "analyst_chen",
        "tags": json.dumps(["corporate", "espionage", "biotech"]),
    },
    {
        "case_name": "Havenport Missing Person",
        "case_number": "IDF-2025-003",
        "status": "Open",
        "priority": "High",
        "description": "Missing person investigation — Lily Vance, 17, last seen October 31.",
        "created_by": "det_markov",
        "tags": json.dumps(["missing_person", "cyberstalking"]),
    },
]

created_case_ids = []
for c in cases_data:
    existing = db.query(models.Case).filter(
        models.Case.case_number == c["case_number"]
    ).first()
    if not existing:
        case_id = str(uuid.uuid4())
        case = models.Case(
            id=case_id,
            **c,
            created_at=datetime.utcnow() - timedelta(days=random.randint(5, 30)),
        )
        db.add(case)
        created_case_ids.append(case_id)
        os.makedirs(f"data/cases/{case_id}/evidence", exist_ok=True)
        os.makedirs(f"data/cases/{case_id}/reports", exist_ok=True)
    else:
        created_case_ids.append(existing.id)

db.commit()
print("  ✓ Cases created")

# ── Entities ──────────────────────────────────────────────────────────────────
print("  Creating demo entities...")

if created_case_ids:
    case_id = created_case_ids[0]
    entities = [
        ("Elena Markov",       "Person",       8),
        ("Andrei Volkov",      "Person",       5),
        ("Sam Delgado",        "Person",       5),
        ("Irina Petrov",       "Person",       4),
        ("Marcus Thorne",      "Person",       3),
        ("Nyx",                "Person",       5),
        ("Phantom Collective", "Organization", 6),
        ("Interpol",           "Organization", 4),
        ("Europol",            "Organization", 3),
        ("Hague",              "Location",     4),
        ("Zurich",             "Location",     3),
        ("Singapore",          "Location",     2),
        ("Moscow",             "Location",     2),
        ("192.168.45.22",      "IP",           3),
        ("10.0.12.87",         "IP",           4),
        ("192.168.0.45",       "IP",           2),
    ]
    for name, etype, freq in entities:
        existing = db.query(models.Entity).filter(
            models.Entity.case_id == case_id,
            models.Entity.name == name,
        ).first()
        if not existing:
            db.add(models.Entity(
                id=str(uuid.uuid4()),
                case_id=case_id,
                name=name,
                entity_type=etype,
                frequency=freq,
                aliases=json.dumps([]),
                is_flagged=name in ["Andrei Volkov", "Nyx", "Irina Petrov"],
            ))

db.commit()
print("  ✓ Entities created")

# ── Audit Logs ────────────────────────────────────────────────────────────────
print("  Creating audit history...")

audit_events = [
    (
        "CASE_CREATED", "det_markov",
        created_case_ids[0] if created_case_ids else None,
        {"case_name": "Operation Phantom Trace"},
    ),
    (
        "FILE_UPLOADED", "det_markov",
        created_case_ids[0] if created_case_ids else None,
        {"filename": "suspect_disk.E01", "size": "8.2GB"},
    ),
    (
        "FILE_INGESTED", "system",
        created_case_ids[0] if created_case_ids else None,
        {"filename": "suspect_disk.E01", "chunks": 1842, "entities": 127},
    ),
    (
        "QUERY_MADE", "det_markov",
        created_case_ids[0] if created_case_ids else None,
        {"question": "Who is Andrei Volkov?"},
    ),
    (
        "PROFILE_GENERATED", "det_markov",
        created_case_ids[0] if created_case_ids else None,
        {"entity": "Andrei Volkov"},
    ),
    (
        "REPORT_GENERATED", "det_markov",
        created_case_ids[0] if created_case_ids else None,
        {"type": "Full Investigation", "pages": 14},
    ),
    (
        "LOGIN_SUCCESS", "admin",
        None,
        {"username": "admin"},
    ),
    (
        "CASE_CREATED", "analyst_chen",
        created_case_ids[1] if len(created_case_ids) > 1 else None,
        {"case_name": "Vertex Pharma Leak"},
    ),
]

for action, user, cid, details in audit_events:
    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        case_id=cid,
        action_type=action,
        performed_by=user,
        performed_at=datetime.utcnow() - timedelta(
            days=random.randint(0, 7),
            hours=random.randint(0, 12),
        ),
        details=json.dumps(details),
    ))

db.commit()
print("  ✓ Audit history created")

# ── Notes ─────────────────────────────────────────────────────────────────────
print("  Creating demo notes...")

if created_case_ids:
    notes = [
        (
            created_case_ids[0],
            "det_markov",
            "Confirmed Andrei Volkov = Kaelen. "
            "Check Luxembourg company registration.",
        ),
        (
            created_case_ids[0],
            "det_markov",
            "IP 10.0.12.87 is a honeypot — "
            "Phantom Collective infiltrated Interpol mail server.",
        ),
        (
            created_case_ids[0],
            "analyst_chen",
            "Cross-reference with Vertex Pharma case — same Kaelen alias used.",
        ),
    ]
    for cid, author, content in notes:
        db.add(models.Note(
            id=str(uuid.uuid4()),
            case_id=cid,
            author=author,
            content=content,
            created_at=datetime.utcnow() - timedelta(days=random.randint(1, 5)),
        ))

db.commit()
print("  ✓ Notes created")

# ── Watchlist ─────────────────────────────────────────────────────────────────
print("  Creating watchlist keywords...")

if created_case_ids:
    keywords = [
        ("Andrei Volkov",      "suspect_name",    created_case_ids[0]),
        ("Phantom Collective", "organization",    created_case_ids[0]),
        ("nyx@proton.pw",      "communication",   created_case_ids[0]),
        ("bitcoin",            "financial_term",  created_case_ids[0]),
    ]
    for kw, cat, cid in keywords:
        existing = db.query(models.WatchlistKeyword).filter(
            models.WatchlistKeyword.case_id == cid,
            models.WatchlistKeyword.keyword == kw,
        ).first()
        if not existing:
            db.add(models.WatchlistKeyword(
                id=str(uuid.uuid4()),
                case_id=cid,
                keyword=kw,
                category=cat,
                added_by="det_markov",
                hit_count=random.randint(0, 8),
            ))

db.commit()
print("  ✓ Watchlist created")

db.close()

print()
print("✅ Demo data seeded successfully!")
print()
print("Demo accounts:")
print("  admin        / Admin@IDF2025  (Admin)")
print("  det_markov   / Markov@2025     (Investigator)")
print("  analyst_chen / Chen@2025       (Analyst)")
print()
