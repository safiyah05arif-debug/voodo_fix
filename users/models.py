"""
CIVIX — Users App: MongoEngine Document Models
================================================
User profiles, gamification, and role management stored in MongoDB Atlas.

Updated:
    - Primary identifier is now `phone` (required & unique)
    - `email` is optional
    - Full role support (citizen, field_worker, officer, zone_officer, admin)
"""

import datetime
from mongoengine import (
    Document,
    EmbeddedDocument,
    StringField,
    IntField,
    FloatField,
    BooleanField,
    DateTimeField,
    ListField,
    DictField,
    URLField,
    PointField,
    EmbeddedDocumentField,
    EmailField,
)


class Badge(Document):
    """Gamification badge definition."""
    name = StringField(required=True, unique=True, max_length=100)
    slug = StringField(required=True, unique=True, max_length=100)
    description = StringField(max_length=500)
    description_ta = StringField(max_length=500)
    icon = StringField(max_length=10, default="target")
    category = StringField(choices=["reporting", "engagement", "verification", "milestone", "special"], default="milestone")
    criteria = DictField()
    points_reward = IntField(default=10, min_value=0)
    created_at = DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "badges", "indexes": ["slug", "category"], "strict": False}

    def __str__(self):
        return f"{self.icon} {self.name}"


class EarnedBadge(EmbeddedDocument):
    badge_slug = StringField(required=True)
    badge_name = StringField()
    badge_icon = StringField(default="target")
    earned_at = DateTimeField(default=datetime.datetime.utcnow)

    def __str__(self):
        return f"{self.badge_icon} {self.badge_name}"

    meta = {"strict": False}


class AccessibilityPreferences(EmbeddedDocument):
    language = StringField(choices=["en", "ta"], default="en")
    high_contrast = BooleanField(default=False)
    font_size = StringField(choices=["normal", "large", "extra_large"], default="normal")
    easy_read = BooleanField(default=False)
    voice_enabled = BooleanField(default=False)

    meta = {"strict": False}


class CivixUser(Document):
    """
    Platform user profile. Supports Phone-first authentication.
    MongoDB collection: `civix_users`
    """
    # Primary Identifier
    phone = StringField(
        required=True,
        unique=True,
        sparse=True,
        max_length=20,
        help_text="Primary phone number used for login, e.g. '9876543210'",
    )
    email = EmailField(
        required=False,
        unique=True,
        sparse=True,
        help_text="Optional email address",
    )
    full_name = StringField(
        required=True,
        max_length=200,
        help_text="Display name",
    )
    avatar_url = URLField()

    password_hash = StringField(
        required=True,
        help_text="Hashed password",
    )
    is_active = BooleanField(default=True)

    role = StringField(
        required=True,
        choices=["citizen", "field_worker", "officer", "zone_officer", "admin"],
        default="citizen",
    )
    zone = StringField(max_length=100, default="Zone 5 - Adyar")
    department = StringField(max_length=100, default="General")

    last_known_location = PointField()
    location_updated_at = DateTimeField()

    # Gamification
    civic_points = IntField(default=0, min_value=0)
    level = IntField(default=1, min_value=1)
    badges = ListField(EmbeddedDocumentField(EarnedBadge))

    # Activity Stats
    reports_submitted = IntField(default=0, min_value=0)
    upvotes_given = IntField(default=0, min_value=0)
    verifications_done = IntField(default=0, min_value=0)
    issues_resolved = IntField(default=0, min_value=0)

    accessibility = EmbeddedDocumentField(
        AccessibilityPreferences,
        default=AccessibilityPreferences
    )

    created_at = DateTimeField(default=datetime.datetime.utcnow)
    updated_at = DateTimeField(default=datetime.datetime.utcnow)
    last_login = DateTimeField()

    meta = {
        "collection": "civix_users",
        "ordering": ["-civic_points"],
        "indexes": [
            {"fields": ["phone"], "unique": True, "sparse": True},
            {"fields": ["email"], "unique": True, "sparse": True},
            {"fields": ["last_known_location"], "cls": False, "sparse": True},
            "role",
            "zone",
            "-civic_points",
        ],
        "strict": False,
    }

    def calculate_level(self):
        thresholds = [0, 50, 150, 300, 500, 800, 1200, 2000]
        self.level = 1
        for i, threshold in enumerate(thresholds):
            if self.civic_points >= threshold:
                self.level = i + 1
            else:
                break
        return self.level

    def add_points(self, points, reason=None):
        self.civic_points += points
        self.calculate_level()
        self.updated_at = datetime.datetime.utcnow()

    def award_badge(self, badge_doc):
        existing_slugs = [b.badge_slug for b in self.badges]
        if badge_doc.slug in existing_slugs:
            return False

        earned = EarnedBadge(
            badge_slug=badge_doc.slug,
            badge_name=badge_doc.name,
            badge_icon=badge_doc.icon,
        )
        self.badges.append(earned)
        self.add_points(badge_doc.points_reward)
        return True

    def save(self, *args, **kwargs):
        self.updated_at = datetime.datetime.utcnow()
        self.calculate_level()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.phone} - {self.role}) — {self.civic_points} pts"


class Notification(Document):
    user_id = StringField(required=True)
    title = StringField(required=True, max_length=200)
    title_ta = StringField(max_length=200)
    message = StringField(required=True, max_length=1000)
    message_ta = StringField(max_length=1000)
    notification_type = StringField(default="system")
    related_issue_id = StringField()
    is_read = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.datetime.utcnow)

    meta = {
        "collection": "notifications",
        "ordering": ["-created_at"],
        "indexes": [
            {"fields": ["user_id", "-created_at"]},
            {"fields": ["user_id", "is_read"]},
        ],
        "strict": False,
    }
