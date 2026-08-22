"""
CIVIX — Database Connection Test
==================================
Quick script to verify MongoDB Atlas connectivity and model imports.

Usage:
    python test_connection.py
"""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "civix_backend.settings")

import django
django.setup()


def test_connection():
    """Test MongoDB connectivity and model registration."""
    print("=" * 60)
    print("  CIVIX -- MongoDB Connection Test")
    print("=" * 60)

    # ── Test 1: PyMongo direct connection ─────────────────────────────────────
    print("\n[1] Testing PyMongo connection...")
    try:
        from civix_backend.db import check_connection
        result = check_connection()
        if result["status"] == "connected":
            print(f"   [OK] Connected to MongoDB v{result['version']}")
            print(f"   [DB] Database: {result['database']}")
        else:
            print(f"   [FAIL] Connection failed: {result['error']}")
            return False
    except Exception as e:
        print(f"   [FAIL] PyMongo connection error: {e}")
        return False

    # ── Test 2: MongoEngine model imports ─────────────────────────────────────
    print("\n[2] Testing MongoEngine model imports...")
    try:
        from issues.models import (
            Issue, IssueUpvote, IssueVerification, EscalationLog,
            AIClassification, ResolutionProof, StatusChange,
        )
        from users.models import (
            CivixUser, Badge, Notification,
            EarnedBadge, AccessibilityPreferences,
        )
        print("   [OK] All models imported successfully")
        print(f"   [INFO] Issue model fields: {len(Issue._fields)}")
        print(f"   [INFO] CivixUser model fields: {len(CivixUser._fields)}")
    except Exception as e:
        print(f"   [FAIL] Model import error: {e}")
        return False

    # ── Test 3: Collection listing ────────────────────────────────────────────
    print("\n[3] Listing existing collections...")
    try:
        from civix_backend.db import get_db
        db = get_db()
        collections = db.list_collection_names()
        if collections:
            for col in sorted(collections):
                count = db[col].count_documents({})
                print(f"   [COLLECTION] {col}: {count} documents")
        else:
            print("   [INFO] No collections yet (run seed_data.py to populate)")
    except Exception as e:
        print(f"   [FAIL] Collection listing error: {e}")

    # ── Test 4: Write/Read test ───────────────────────────────────────────────
    print("\n[4] Write/Read smoke test...")
    try:
        from issues.models import Issue
        import datetime

        # Create a test issue
        test_issue = Issue(
            title="[TEST] Connection verification issue",
            description="This is a smoke test -- will be deleted immediately.",
            reported_by="test_script",
            location=[80.2707, 13.0827],  # Chennai Central
            category="other",
            issue_type="test",
            severity="low",
        )
        test_issue.save()
        print(f"   [OK] Write OK -- created issue ID: {test_issue.id}")
        print(f"   [INFO] Priority score: {test_issue.priority_score:.2f}")
        print(f"   [INFO] SLA deadline: {test_issue.sla_deadline}")

        # Read it back
        fetched = Issue.objects(id=test_issue.id).first()
        assert fetched is not None, "Failed to read back the test issue"
        assert fetched.title == test_issue.title
        print(f"   [OK] Read OK -- verified title matches")

        # Delete it
        fetched.delete()
        print(f"   [OK] Delete OK -- cleaned up test document")
    except Exception as e:
        print(f"   [FAIL] Write/Read test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("  [SUCCESS] ALL TESTS PASSED -- MongoDB is ready for CIVIX!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
