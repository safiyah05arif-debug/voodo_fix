"""
CIVIX — Mock Data Seed Script
===============================
Generates 25 realistic civic issues across Chennai (or any configurable city)
and populates MongoDB for instant demo/heatmap visualization.

Usage:
    python seed_data.py

This script uses MongoEngine models directly, so it connects via the same
Django settings configuration.

All coordinates are real locations around Chennai, India.
"""

import os
import sys
import datetime
import random

# ── Setup Django environment ──────────────────────────────────────────────────
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "civix_backend.settings")

import django
django.setup()

from issues.models import Issue, AIClassification, StatusChange
from users.models import CivixUser, Badge, EarnedBadge, AccessibilityPreferences


# =============================================================================
# BADGE DEFINITIONS
# =============================================================================
BADGE_DEFINITIONS = [
    {
        "name": "First Report",
        "slug": "first_report",
        "description": "Submit your first civic issue report",
        "description_ta": "உங்கள் முதல் குடிமக்கள் புகாரை சமர்ப்பிக்கவும்",
        "icon": "target",
        "category": "reporting",
        "criteria": {"reports_count": 1},
        "points_reward": 10,
    },
    {
        "name": "Watchdog",
        "slug": "watchdog",
        "description": "Upvote 10 civic issues in your area",
        "description_ta": "உங்கள் பகுதியில் 10 புகார்களை ஆதரிக்கவும்",
        "icon": "eye",
        "category": "engagement",
        "criteria": {"upvotes_given": 10},
        "points_reward": 25,
    },
    {
        "name": "Verified Citizen",
        "slug": "verified_citizen",
        "description": "Verify 5 resolved issues in your neighborhood",
        "description_ta": "உங்கள் அருகிலுள்ள 5 தீர்க்கப்பட்ட புகார்களை சரிபார்க்கவும்",
        "icon": "check",
        "category": "verification",
        "criteria": {"verifications_done": 5},
        "points_reward": 30,
    },
    {
        "name": "Community Hero",
        "slug": "community_hero",
        "description": "Earn 500 civic points for outstanding contribution",
        "description_ta": "சிறந்த பங்களிப்புக்காக 500 குடிமக்கள் புள்ளிகள் பெறுங்கள்",
        "icon": "hero",
        "category": "milestone",
        "criteria": {"civic_points": 500},
        "points_reward": 50,
    },
    {
        "name": "Voice of the City",
        "slug": "voice_of_city",
        "description": "Use voice input for 3 issue reports",
        "description_ta": "3 புகார்களுக்கு குரல் உள்ளீட்டை பயன்படுத்துங்கள்",
        "icon": "mic",
        "category": "special",
        "criteria": {"voice_reports": 3},
        "points_reward": 20,
    },
    {
        "name": "Road Warrior",
        "slug": "road_warrior",
        "description": "Report 5 road-related issues",
        "description_ta": "5 சாலை தொடர்பான புகார்களை பதிவு செய்யுங்கள்",
        "icon": "road",
        "category": "reporting",
        "criteria": {"road_reports": 5},
        "points_reward": 15,
    },
]


# =============================================================================
# DEMO USERS
# =============================================================================
DEMO_USERS = [
    {
        "email": "ravi.kumar@example.com",
        "phone": "+919876543210",
        "full_name": "Ravi Kumar",
        "password_hash": "pbkdf2_sha256$demo$hashed_password_placeholder",
        "role": "citizen",
        "zone": "Zone 5 - Adyar",
        "civic_points": 120,
    },
    {
        "email": "priya.devi@example.com",
        "phone": "+919876543211",
        "full_name": "Priya Devi",
        "password_hash": "pbkdf2_sha256$demo$hashed_password_placeholder",
        "role": "citizen",
        "zone": "Zone 8 - Anna Nagar",
        "civic_points": 85,
    },
    {
        "email": "murugan.s@example.com",
        "phone": "+919876543212",
        "full_name": "Murugan S",
        "password_hash": "pbkdf2_sha256$demo$hashed_password_placeholder",
        "role": "field_worker",
        "zone": "Zone 5 - Adyar",
        "department": "Roads",
        "civic_points": 0,
    },
    {
        "email": "lakshmi.n@example.com",
        "phone": "+919876543213",
        "full_name": "Lakshmi Narayanan",
        "password_hash": "pbkdf2_sha256$demo$hashed_password_placeholder",
        "role": "field_worker",
        "zone": "Zone 10 - Kodambakkam",
        "department": "Water & Drainage",
        "civic_points": 0,
    },
    {
        "email": "officer.chennai@example.com",
        "phone": "+919876543214",
        "full_name": "Anand Krishnan (Officer)",
        "password_hash": "pbkdf2_sha256$demo$hashed_password_placeholder",
        "role": "officer",
        "zone": "Zone 5 - Adyar",
        "department": "Public Works",
        "civic_points": 0,
    },
    {
        "email": "zone.officer@example.com",
        "phone": "+919876543215",
        "full_name": "Deepa Sundaram (Zone Officer)",
        "password_hash": "pbkdf2_sha256$demo$hashed_password_placeholder",
        "role": "zone_officer",
        "zone": "Zone 5 - Adyar",
        "department": "Municipal Administration",
        "civic_points": 0,
    },
]


# =============================================================================
# 25 REALISTIC CIVIC ISSUES AROUND CHENNAI
# =============================================================================
# Coordinates: [longitude, latitude] — real locations in Chennai, Tamil Nadu
MOCK_ISSUES = [
    {
        "title": "Large pothole on Adyar Bridge Road",
        "description": "Deep pothole near Adyar signal causing vehicle damage. Multiple two-wheelers have fallen here in the past week.",
        "location": [80.2574, 13.0067],
        "address": "Adyar Bridge Road, near Adyar Signal, Chennai 600020",
        "ward": "Zone 5 - Adyar",
        "category": "road",
        "issue_type": "pothole",
        "severity": "critical",
        "upvote_count": 34,
        "location_risk_factor": 4.0,
        "status": "submitted",
    },
    {
        "title": "Overflowing garbage bin at Besant Nagar Beach entrance",
        "description": "The community bin at the Besant Nagar beach parking area has not been collected for 4 days. Stray dogs are scattering waste.",
        "location": [80.2668, 12.9988],
        "address": "Besant Nagar Beach Parking, Elliot's Beach Rd, Chennai 600090",
        "ward": "Zone 5 - Adyar",
        "category": "waste",
        "issue_type": "overflowing_bin",
        "severity": "high",
        "upvote_count": 18,
        "location_risk_factor": 3.0,
        "status": "assigned",
    },
    {
        "title": "Streetlight not working on TTK Road",
        "description": "Three consecutive streetlights are off near the Music Academy. Very dark and unsafe for pedestrians at night.",
        "location": [80.2593, 13.0374],
        "address": "TTK Road, near Music Academy, Mylapore, Chennai 600004",
        "ward": "Zone 9 - Teynampet",
        "category": "electricity",
        "issue_type": "streetlight_outage",
        "severity": "high",
        "upvote_count": 22,
        "location_risk_factor": 3.5,
        "status": "submitted",
    },
    {
        "title": "Water pipeline leak on Anna Salai",
        "description": "Major water pipeline leaking near Gemini Flyover. Water has been running for 2 days, causing traffic issues and water wastage.",
        "location": [80.2480, 13.0557],
        "address": "Anna Salai, near Gemini Flyover, Chennai 600002",
        "ward": "Zone 9 - Teynampet",
        "category": "water",
        "issue_type": "pipeline_leak",
        "severity": "critical",
        "upvote_count": 45,
        "location_risk_factor": 4.5,
        "status": "in_progress",
    },
    {
        "title": "Blocked storm drain on Nungambakkam High Road",
        "description": "Storm water drain completely blocked with plastic waste. Area floods even with light rain.",
        "location": [80.2404, 13.0601],
        "address": "Nungambakkam High Road, Chennai 600034",
        "ward": "Zone 8 - Anna Nagar",
        "category": "drainage",
        "issue_type": "blocked_drain",
        "severity": "high",
        "upvote_count": 28,
        "location_risk_factor": 3.5,
        "status": "submitted",
    },
    {
        "title": "Dangerous open manhole near school",
        "description": "Manhole cover missing on the road right outside DAV School, Gopalapuram. Children are at severe risk during school hours.",
        "location": [80.2536, 13.0499],
        "address": "Near DAV School, Gopalapuram, Chennai 600086",
        "ward": "Zone 9 - Teynampet",
        "category": "public_safety",
        "issue_type": "open_manhole",
        "severity": "critical",
        "upvote_count": 67,
        "location_risk_factor": 5.0,
        "status": "escalated",
    },
    {
        "title": "Illegal garbage dumping at Cooum riverbank",
        "description": "Construction debris and household waste being dumped along the Cooum river near Chetpet. Environmental hazard and breeding ground for mosquitoes.",
        "location": [80.2412, 13.0702],
        "address": "Cooum River Bank, near Chetpet Bridge, Chennai 600031",
        "ward": "Zone 7 - Ambattur",
        "category": "environment",
        "issue_type": "illegal_dumping",
        "severity": "high",
        "upvote_count": 31,
        "location_risk_factor": 4.0,
        "status": "submitted",
    },
    {
        "title": "Cracked footpath on Mount Road",
        "description": "Pedestrian footpath badly cracked and uneven near Express Avenue Mall. Wheelchair users cannot pass safely.",
        "location": [80.2603, 13.0542],
        "address": "Mount Road, near Express Avenue, Royapettah, Chennai 600014",
        "ward": "Zone 9 - Teynampet",
        "category": "road",
        "issue_type": "damaged_footpath",
        "severity": "medium",
        "upvote_count": 14,
        "location_risk_factor": 3.0,
        "status": "submitted",
    },
    {
        "title": "No water supply for 3 days in T. Nagar",
        "description": "Entire Pondy Bazaar area has had no Metro Water supply for 3 consecutive days. Residents relying on private tankers.",
        "location": [80.2339, 13.0418],
        "address": "Pondy Bazaar, T. Nagar, Chennai 600017",
        "ward": "Zone 10 - Kodambakkam",
        "category": "water",
        "issue_type": "no_supply",
        "severity": "critical",
        "upvote_count": 89,
        "location_risk_factor": 3.0,
        "status": "submitted",
    },
    {
        "title": "Fallen tree blocking road in Anna Nagar",
        "description": "Large banyan tree fell during last night's wind. Completely blocking 2nd Avenue. Traffic diverted through narrow lanes.",
        "location": [80.2090, 13.0850],
        "address": "2nd Avenue, Anna Nagar, Chennai 600040",
        "ward": "Zone 8 - Anna Nagar",
        "category": "public_safety",
        "issue_type": "fallen_tree",
        "severity": "critical",
        "upvote_count": 42,
        "location_risk_factor": 4.0,
        "status": "assigned",
    },
    {
        "title": "Stagnant water breeding mosquitoes in Velachery",
        "description": "Large pool of stagnant water in the vacant lot near Velachery Main Road. Dengue cases reported in the area.",
        "location": [80.2206, 12.9815],
        "address": "Velachery Main Road, near MMDA Colony, Chennai 600042",
        "ward": "Zone 14 - Perungudi",
        "category": "environment",
        "issue_type": "stagnant_water",
        "severity": "high",
        "upvote_count": 36,
        "location_risk_factor": 4.5,
        "status": "submitted",
    },
    {
        "title": "Broken traffic signal at Kathipara Junction",
        "description": "Traffic light at Kathipara flyover base has been malfunctioning for a week. Showing green on all sides simultaneously.",
        "location": [80.1984, 13.0088],
        "address": "Kathipara Junction, Alandur, Chennai 600016",
        "ward": "Zone 13 - Alandur",
        "category": "public_safety",
        "issue_type": "broken_traffic_signal",
        "severity": "critical",
        "upvote_count": 55,
        "location_risk_factor": 5.0,
        "status": "in_progress",
    },
    {
        "title": "Sewage overflow on ECR near Thiruvanmiyur",
        "description": "Sewage overflowing onto East Coast Road causing terrible stench. Road surface becoming slippery and dangerous.",
        "location": [80.2598, 12.9834],
        "address": "ECR, near Thiruvanmiyur Bus Stop, Chennai 600041",
        "ward": "Zone 14 - Perungudi",
        "category": "drainage",
        "issue_type": "sewage_overflow",
        "severity": "high",
        "upvote_count": 27,
        "location_risk_factor": 3.5,
        "status": "submitted",
    },
    {
        "title": "Damaged speed breaker causing accidents",
        "description": "Speed breaker on Arcot Road near Vadapalani has broken apart. Exposed rebar is puncturing tires.",
        "location": [80.2122, 13.0502],
        "address": "Arcot Road, Vadapalani, Chennai 600026",
        "ward": "Zone 10 - Kodambakkam",
        "category": "road",
        "issue_type": "damaged_speed_breaker",
        "severity": "high",
        "upvote_count": 19,
        "location_risk_factor": 4.0,
        "status": "submitted",
    },
    {
        "title": "Electricity transformer sparking in Mylapore",
        "description": "Transformer on Kutchery Road sparking intermittently, especially during rain. Residents afraid of electrocution.",
        "location": [80.2680, 13.0330],
        "address": "Kutchery Road, Mylapore, Chennai 600004",
        "ward": "Zone 9 - Teynampet",
        "category": "electricity",
        "issue_type": "sparking_transformer",
        "severity": "critical",
        "upvote_count": 38,
        "location_risk_factor": 5.0,
        "status": "escalated",
    },
    {
        "title": "Unauthorized construction blocking drainage",
        "description": "New building construction on Poonamallee High Road has blocked the main drainage channel. Flooding risk during monsoon.",
        "location": [80.2088, 13.0793],
        "address": "Poonamallee High Road, Kilpauk, Chennai 600010",
        "ward": "Zone 6 - Kilpauk",
        "category": "drainage",
        "issue_type": "construction_blocking_drain",
        "severity": "medium",
        "upvote_count": 15,
        "location_risk_factor": 3.0,
        "status": "submitted",
    },
    {
        "title": "Abandoned vehicle on Harrington Road",
        "description": "Rusted car abandoned for over 2 months on Harrington Road, Chetpet. Taking up parking space and attracting rodents.",
        "location": [80.2425, 13.0670],
        "address": "Harrington Road, Chetpet, Chennai 600031",
        "ward": "Zone 7 - Ambattur",
        "category": "other",
        "issue_type": "abandoned_vehicle",
        "severity": "low",
        "upvote_count": 7,
        "location_risk_factor": 1.5,
        "status": "submitted",
    },
    {
        "title": "Public toilet not maintained at Central Station",
        "description": "Sulabh Shauchalaya near Chennai Central entrance is in deplorable condition. No running water, broken locks, extremely unhygienic.",
        "location": [80.2757, 13.0827],
        "address": "Chennai Central Railway Station, Park Town, Chennai 600003",
        "ward": "Zone 4 - Tondiarpet",
        "category": "public_safety",
        "issue_type": "unmaintained_toilet",
        "severity": "medium",
        "upvote_count": 24,
        "location_risk_factor": 3.0,
        "status": "submitted",
    },
    {
        "title": "Road cave-in near Tambaram station",
        "description": "Part of the road has caved in near Tambaram railway station. Gap is approximately 4 feet wide. Very dangerous at night.",
        "location": [80.1268, 12.9249],
        "address": "Near Tambaram Railway Station, Chennai 600045",
        "ward": "Zone 15 - Sholinganallur",
        "category": "road",
        "issue_type": "road_cave_in",
        "severity": "critical",
        "upvote_count": 52,
        "location_risk_factor": 5.0,
        "status": "submitted",
    },
    {
        "title": "Contaminated water from public tap in Royapuram",
        "description": "Water from the public tap in Royapuram fish market area has yellow color and foul smell. Local residents getting skin rashes.",
        "location": [80.2942, 13.1060],
        "address": "Royapuram Fish Market Road, Chennai 600013",
        "ward": "Zone 3 - Madhavaram",
        "category": "water",
        "issue_type": "contaminated_water",
        "severity": "critical",
        "upvote_count": 41,
        "location_risk_factor": 4.5,
        "status": "submitted",
    },
    {
        "title": "Encroached park in Chromepet",
        "description": "Corporation park in Chromepet has been encroached by illegal vendors. Children have no safe place to play.",
        "location": [80.1419, 12.9516],
        "address": "Corporation Park, Chromepet, Chennai 600044",
        "ward": "Zone 15 - Sholinganallur",
        "category": "environment",
        "issue_type": "park_encroachment",
        "severity": "medium",
        "upvote_count": 16,
        "location_risk_factor": 2.5,
        "status": "submitted",
    },
    {
        "title": "Damaged bus shelter at Guindy",
        "description": "MTC bus shelter roof collapsed partially after recent rains. Sharp metal edges exposed. Commuters at risk.",
        "location": [80.2121, 13.0105],
        "address": "Guindy Industrial Estate Bus Stop, Chennai 600032",
        "ward": "Zone 13 - Alandur",
        "category": "public_safety",
        "issue_type": "damaged_bus_shelter",
        "severity": "high",
        "upvote_count": 20,
        "location_risk_factor": 3.5,
        "status": "assigned",
    },
    {
        "title": "Loose hanging electrical wire at Perambur",
        "description": "Live electrical wire hanging low on Perambur High Road. Dangerously close to head height. Immediate danger during rain.",
        "location": [80.2400, 13.1087],
        "address": "Perambur High Road, Chennai 600012",
        "ward": "Zone 4 - Tondiarpet",
        "category": "electricity",
        "issue_type": "hanging_wire",
        "severity": "critical",
        "upvote_count": 48,
        "location_risk_factor": 5.0,
        "status": "submitted",
    },
    {
        "title": "Waterlogged underpass at Mambalam",
        "description": "Mambalam railway underpass is perpetually waterlogged. Two-wheelers get stuck. Water level reaches 2 feet during light rain.",
        "location": [80.2283, 13.0336],
        "address": "Mambalam Railway Underpass, West Mambalam, Chennai 600033",
        "ward": "Zone 10 - Kodambakkam",
        "category": "drainage",
        "issue_type": "waterlogged_underpass",
        "severity": "high",
        "upvote_count": 33,
        "location_risk_factor": 4.0,
        "status": "submitted",
    },
    {
        "title": "Garbage not collected in Porur for a week",
        "description": "Door-to-door garbage collection stopped in Porur Lake area since last Monday. Waste piling up outside homes, attracting rats.",
        "location": [80.1576, 13.0365],
        "address": "Porur Lake Area, Porur, Chennai 600116",
        "ward": "Zone 11 - Valasaravakkam",
        "category": "waste",
        "issue_type": "garbage_not_collected",
        "severity": "high",
        "upvote_count": 25,
        "location_risk_factor": 3.0,
        "status": "submitted",
    },
]


def seed_badges():
    """Create badge definitions if they don't exist."""
    print("\n[INFO] Seeding badges...")
    for badge_data in BADGE_DEFINITIONS:
        existing = Badge.objects(slug=badge_data["slug"]).first()
        if existing:
            print(f"   [SKIP] Badge '{badge_data['name']}' already exists")
            continue

        badge = Badge(**badge_data)
        badge.save()
        print(f"   [OK] Created badge: {badge}")

    print(f"   [TOTAL] Badges in DB: {Badge.objects.count()}")


def seed_users():
    """Create demo users if they don't exist."""
    print("\n[INFO] Seeding demo users...")
    user_ids = []

    for user_data in DEMO_USERS:
        existing = CivixUser.objects(email=user_data["email"]).first()
        if existing:
            print(f"   [SKIP] User '{user_data['full_name']}' already exists")
            user_ids.append(str(existing.id))
            continue

        user = CivixUser(
            email=user_data["email"],
            phone=user_data.get("phone"),
            full_name=user_data["full_name"],
            password_hash=user_data["password_hash"],
            role=user_data["role"],
            zone=user_data.get("zone", ""),
            department=user_data.get("department", ""),
            civic_points=user_data.get("civic_points", 0),
            accessibility=AccessibilityPreferences(language="en"),
        )
        user.save()
        user_ids.append(str(user.id))
        print(f"   [OK] Created user: {user}")

    print(f"   [TOTAL] Users in DB: {CivixUser.objects.count()}")
    return user_ids


def seed_issues(user_ids):
    """Create 25 realistic civic issues around Chennai."""
    print("\n[INFO] Seeding civic issues...")

    citizen_ids = user_ids[:2] if len(user_ids) >= 2 else ["demo_citizen_1"]
    worker_ids = user_ids[2:4] if len(user_ids) >= 4 else []

    for i, issue_data in enumerate(MOCK_ISSUES):
        existing = Issue.objects(title=issue_data["title"]).first()
        if existing:
            print(f"   [SKIP] Issue '{issue_data['title'][:50]}...' already exists")
            continue

        hours_ago = random.randint(1, 168)
        created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=hours_ago)

        ai_class = AIClassification(
            category=issue_data["category"],
            issue_type=issue_data["issue_type"],
            severity=issue_data["severity"],
            confidence=round(random.uniform(0.78, 0.98), 2),
            raw_response={"model": "gpt-4o", "simulated": True},
        )

        issue = Issue(
            title=issue_data["title"],
            description=issue_data["description"],
            reported_by=random.choice(citizen_ids),
            input_method=random.choice(["text", "voice_en", "voice_ta"]),
            location=issue_data["location"],
            address=issue_data["address"],
            ward=issue_data["ward"],
            category=issue_data["category"],
            issue_type=issue_data["issue_type"],
            severity=issue_data["severity"],
            ai_classification=ai_class,
            upvote_count=issue_data["upvote_count"],
            status=issue_data["status"],
            location_risk_factor=issue_data["location_risk_factor"],
            created_at=created_at,
        )

        if issue_data["status"] in ("assigned", "in_progress") and worker_ids:
            issue.assigned_to = random.choice(worker_ids)
            issue.assigned_at = created_at + datetime.timedelta(hours=random.randint(1, 6))
            issue.add_status_change(
                to_status=issue_data["status"],
                changed_by=issue.assigned_to,
                reason="Auto-assigned by priority queue",
            )

        issue.save()
        print(f"   [OK] [{issue.severity.upper():8}] {issue.title[:55]}... (score: {issue.priority_score:.0f})")

    print(f"\n   [TOTAL] Issues in DB: {Issue.objects.count()}")


def print_summary():
    """Print a summary of all seeded data."""
    print("\n" + "=" * 70)
    print("  CIVIX DATABASE SEED -- SUMMARY")
    print("=" * 70)
    print(f"  Badges:        {Badge.objects.count()}")
    print(f"  Users:         {CivixUser.objects.count()}")
    print(f"  Issues:        {Issue.objects.count()}")
    print(f"  Critical:      {Issue.objects(severity='critical').count()}")
    print(f"  High:          {Issue.objects(severity='high').count()}")
    print(f"  Medium:        {Issue.objects(severity='medium').count()}")
    print(f"  Low:           {Issue.objects(severity='low').count()}")
    print(f"  SLA Breached:  {Issue.objects(sla_breached=True).count()}")
    print(f"  Escalated:     {Issue.objects(status='escalated').count()}")
    print("=" * 70)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    print("[INFO] CIVIX -- Seeding MongoDB with demo data...")
    print(f"   Database: {os.getenv('MONGODB_NAME', 'civix_db')}")

    try:
        seed_badges()
        user_ids = seed_users()
        seed_issues(user_ids)

        # Ensure indexes exist
        from civix_backend.db import ensure_indexes
        ensure_indexes()

        print_summary()
        print("\n[SUCCESS] Seed completed successfully! Your demo data is ready.")

    except Exception as e:
        print(f"\n[ERROR] Seed failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
