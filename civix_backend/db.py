"""
CIVIX — MongoDB Connection Utility
====================================
Centralized MongoDB connection helper that can be used outside Django
context (e.g., standalone scripts, management commands).

Usage:
    from civix_backend.db import get_db, get_collection

    db = get_db()
    issues = get_collection("issues")
    issues.find({"status": "submitted"})
"""

import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# Module-level singleton
_client = None
_db = None


def get_client():
    """
    Get or create a PyMongo MongoClient singleton.
    Uses the MONGODB_URI from environment variables.
    """
    global _client
    if _client is None:
        uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    return _client


def get_db(db_name=None):
    """
    Get a reference to the MongoDB database.

    Args:
        db_name: Override database name. Defaults to MONGODB_NAME env var.

    Returns:
        pymongo.database.Database
    """
    global _db
    if _db is None or db_name:
        name = db_name or os.getenv("MONGODB_NAME", "civix_db")
        _db = get_client()[name]
    return _db


def get_collection(collection_name):
    """
    Shortcut to get a collection from the default database.

    Args:
        collection_name: Name of the MongoDB collection.

    Returns:
        pymongo.collection.Collection
    """
    return get_db()[collection_name]


def ensure_indexes():
    """
    Create required indexes directly via PyMongo.
    This is a fallback/supplement to MongoEngine's auto-indexing.
    Useful for ensuring the 2dsphere index exists before first spatial query.
    """
    from pymongo import GEOSPHERE, ASCENDING, DESCENDING

    db = get_db()

    try:
        issues = db["issues"]
        issues.create_index([("location", GEOSPHERE)])
        issues.create_index([("status", ASCENDING), ("category", ASCENDING)])
        issues.create_index([("priority_score", DESCENDING)])
        issues.create_index([("sla_deadline", ASCENDING)])
        issues.create_index([("reported_by", ASCENDING)])
        issues.create_index([("assigned_to", ASCENDING)])

        users = db["civix_users"]
        users.create_index([("email", ASCENDING)], unique=True)
        users.create_index([("phone", ASCENDING)], unique=True, sparse=True)
        users.create_index([("last_known_location", GEOSPHERE)], sparse=True)

        upvotes = db["issue_upvotes"]
        upvotes.create_index([("issue_id", ASCENDING), ("user_id", ASCENDING)], unique=True)

        verifications = db["issue_verifications"]
        verifications.create_index([("issue_id", ASCENDING), ("user_id", ASCENDING)], unique=True)

        notifications = db["notifications"]
        notifications.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    except Exception as e:
        # If MongoEngine already built standard default index names, skip error
        pass

    print("[CIVIX] [OK] All MongoDB indexes ensured successfully.")


def check_connection():
    """
    Test the MongoDB connection and return server info.
    Useful for health checks and startup verification.
    """
    try:
        client = get_client()
        info = client.server_info()
        return {
            "status": "connected",
            "version": info.get("version", "unknown"),
            "database": os.getenv("MONGODB_NAME", "civix_db"),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }
