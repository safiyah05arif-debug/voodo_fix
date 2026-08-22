"""
CIVIX — Users App: MongoEngine Document Models
================================================
User profiles, gamification, and role management stored in MongoDB Atlas.

Collections:
    - CivixUser    → User profile with role, civic points, and badges
    - Badge        → Badge definitions for the gamification system
    - Notification → Push/in-app notifications for users

Roles:
    - citizen       → Reports issues, upvotes, verifies fixes
    - field_worker  → Assigned tasks, submits proof-of-work
    - officer       → Municipal officer, manages tickets from command center
    - zone_officer  → Escalation target for SLA breaches in a zone
    - admin         → Platform administrator
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


# =============================================================================
# BADGE DEFINITIONS
# =============================================================================

class Badge(Document):
    """
    Gamification badge definition.
    Badges are earned by citizens for civic engagement milestones.

    MongoDB collection: `badges`

    Examples:
        - "First Report"      → Submit your first issue
        - "Watchdog"          → Upvote 10 issues
        - "Verified Citizen"  → Verify 5 resolved issues
        - "Community Hero"    → Earn 500 civic points
        - "Voice of the City" → Use voice input for 3 reports
    """
    name = StringField(
        required=True,
        unique=True,
        max_length=100,
        help_text="Display name of the badge",
    )
    slug = StringField(
        required=True,
        unique=True,
        max_length=100,
        help_text="URL-safe identifier, e.g., 'first_report'",
    )
    description = StringField(
        max_length=500,
        help_text="What the user did to earn this badge",
    )
    description_ta = StringField(
        max_length=500,
        help_text="Tamil translation of the badge description",
    )
    icon = StringField(
        max_length=10,
        default="🏅",
        help_text="Emoji or icon identifier for the badge",
    )
    category = StringField(
        choices=["reporting", "engagement", "verification", "milestone", "special"],
        default="milestone",
        help_text="Badge category for grouping in the dashboard",
    )
    criteria = DictField(
        help_text="JSON criteria for auto-awarding, e.g., {'reports_count': 1}",
    )
    points_reward = IntField(
        default=10,
        min_value=0,
        help_text="Civic points awarded when this badge is earned",
    )
    created_at = DateTimeField(default=datetime.datetime.utcnow)

    meta = {
        "collection": "badges",
        "indexes": [
            "slug",
            "category",
        ],
        "strict": False,
    }

    def __str__(self):
        return f"{self.icon} {self.name}"


# =============================================================================
# EARNED BADGE (embedded in user profile)
# =============================================================================

class EarnedBadge(EmbeddedDocument):
    """
    Record of a badge earned by a user.
    Embedded inside the CivixUser document.
    """
    badge_slug = StringField(
        required=True,
        help_text="Reference to Badge.slug",
    )
    badge_name = StringField(
        help_text="Denormalized badge name for quick display",
    )
    badge_icon = StringField(
        default="🏅",
        help_text="Denormalized badge icon",
    )
    earned_at = DateTimeField(
        default=datetime.datetime.utcnow,
        help_text="When the badge was earned",
    )

    def __str__(self):
        return f"{self.badge_icon} {self.badge_name} (earned {self.earned_at})"

    meta = {"strict": False}


# =============================================================================
# ACCESSIBILITY PREFERENCES (embedded in user profile)
# =============================================================================

class AccessibilityPreferences(EmbeddedDocument):
    """
    Per-user accessibility settings.
    Synced to the frontend on login to restore user preferences.
    """
    language = StringField(
        choices=["en", "ta"],
        default="en",
        help_text="Preferred UI language: English or Tamil",
    )
    high_contrast = BooleanField(
        default=False,
        help_text="High-contrast mode enabled",
    )
    font_size = StringField(
        choices=["normal", "large", "extra_large"],
        default="normal",
        help_text="Font size preference: A, A+, A++",
    )
    easy_read = BooleanField(
        default=False,
        help_text="Simplified text mode for easier comprehension",
    )
    voice_enabled = BooleanField(
        default=False,
        help_text="Voice assistant (TTS/STT) enabled by default",
    )

    meta = {"strict": False}


# =============================================================================
# CIVIX USER PROFILE
# =============================================================================

class CivixUser(Document):
    """
    Platform user profile. Supports multiple roles with gamification.

    MongoDB collection: `civix_users`

    This is NOT Django's built-in User model. It lives entirely in MongoDB.
    Authentication can be handled via JWT tokens or session mapping.

    Indexes:
        - Unique on `email`
        - Unique on `phone`
        - 2dsphere on `last_known_location` for proximity-based features
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    email = EmailField(
        required=True,
        unique=True,
        help_text="Primary email address (used for login)",
    )
    phone = StringField(
        max_length=15,
        unique=True,
        sparse=True,
        help_text="Phone number with country code, e.g., '+91XXXXXXXXXX'",
    )
    full_name = StringField(
        required=True,
        max_length=200,
        help_text="Display name",
    )
    avatar_url = URLField(
        help_text="Profile picture URL (Supabase Storage)",
    )

    # ── Authentication ────────────────────────────────────────────────────────
    password_hash = StringField(
        required=True,
        help_text="Bcrypt/Argon2 hashed password",
    )
    is_active = BooleanField(
        default=True,
        help_text="Account active flag",
    )

    # ── Role & Permissions ────────────────────────────────────────────────────
    role = StringField(
        required=True,
        choices=["citizen", "field_worker", "officer", "zone_officer", "admin"],
        default="citizen",
        help_text="Primary user role determining portal access",
    )
    zone = StringField(
        max_length=100,
        help_text="Municipal zone/ward assignment (for workers & officers)",
    )
    department = StringField(
        max_length=100,
        help_text="Municipal department (for officers), e.g., 'Roads', 'Water'",
    )

    # ── Geolocation ───────────────────────────────────────────────────────────
    last_known_location = PointField(
        help_text="Last known GPS position [lng, lat] — updated by mobile app",
    )
    location_updated_at = DateTimeField(
        help_text="When the location was last updated",
    )

    # ── Gamification ──────────────────────────────────────────────────────────
    civic_points = IntField(
        default=0,
        min_value=0,
        help_text="Total accumulated civic points",
    )
    level = IntField(
        default=1,
        min_value=1,
        help_text="Gamification level (derived from civic points)",
    )
    badges = ListField(
        EmbeddedDocumentField(EarnedBadge),
        help_text="List of badges earned by this user",
    )

    # ── Activity Stats ────────────────────────────────────────────────────────
    reports_submitted = IntField(
        default=0,
        min_value=0,
        help_text="Total number of issues reported",
    )
    upvotes_given = IntField(
        default=0,
        min_value=0,
        help_text="Total upvotes given to other issues",
    )
    verifications_done = IntField(
        default=0,
        min_value=0,
        help_text="Total issue verifications completed",
    )
    issues_resolved = IntField(
        default=0,
        min_value=0,
        help_text="Total issues resolved (for field workers)",
    )

    # ── Accessibility ─────────────────────────────────────────────────────────
    accessibility = EmbeddedDocumentField(
        AccessibilityPreferences,
        default=AccessibilityPreferences,
        help_text="User's accessibility preferences",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = DateTimeField(
        default=datetime.datetime.utcnow,
        help_text="Account creation timestamp",
    )
    updated_at = DateTimeField(
        default=datetime.datetime.utcnow,
        help_text="Last profile update",
    )
    last_login = DateTimeField(
        help_text="Last login timestamp",
    )

    meta = {
        "collection": "civix_users",
        "ordering": ["-civic_points"],
        "indexes": [
            # Unique email lookup
            {
                "fields": ["email"],
                "unique": True,
            },
            # Unique phone lookup (sparse for users without phone)
            {
                "fields": ["phone"],
                "unique": True,
                "sparse": True,
            },
            # 2dsphere for worker proximity sorting
            {
                "fields": ["last_known_location"],
                "cls": False,
                "sparse": True,
            },
            # Role-based queries
            "role",
            # Zone assignment for officer/worker lookups
            "zone",
            # Leaderboard queries
            "-civic_points",
        ],
        "strict": False,
    }

    # ── Instance Methods ──────────────────────────────────────────────────────

    def calculate_level(self):
        """
        Derive gamification level from civic points.
        Level thresholds: 1=0, 2=50, 3=150, 4=300, 5=500, 6=800, 7=1200, 8=2000
        """
        thresholds = [0, 50, 150, 300, 500, 800, 1200, 2000]
        self.level = 1
        for i, threshold in enumerate(thresholds):
            if self.civic_points >= threshold:
                self.level = i + 1
            else:
                break
        return self.level

    def add_points(self, points, reason=None):
        """Add civic points and recalculate level."""
        self.civic_points += points
        self.calculate_level()
        self.updated_at = datetime.datetime.utcnow()

    def award_badge(self, badge_doc):
        """
        Award a badge to the user (if not already earned).
        Also adds the badge's point reward.

        Args:
            badge_doc: A Badge document instance
        """
        # Check if already earned
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
        """Override save to auto-update computed fields."""
        self.updated_at = datetime.datetime.utcnow()
        self.calculate_level()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.role}) — {self.civic_points} pts"


# =============================================================================
# NOTIFICATIONS
# =============================================================================

class Notification(Document):
    """
    In-app notification for users.
    Created by system events (SLA alerts, badge awards, status changes).

    MongoDB collection: `notifications`
    """
    user_id = StringField(
        required=True,
        help_text="ObjectId of the target user",
    )
    title = StringField(
        required=True,
        max_length=200,
        help_text="Notification title",
    )
    title_ta = StringField(
        max_length=200,
        help_text="Tamil translation of the title",
    )
    message = StringField(
        required=True,
        max_length=1000,
        help_text="Notification body text",
    )
    message_ta = StringField(
        max_length=1000,
        help_text="Tamil translation of the message",
    )
    notification_type = StringField(
        choices=[
            "issue_update",      # Status change on a reported/upvoted issue
            "badge_earned",      # New badge awarded
            "task_assigned",     # New task for field workers
            "sla_warning",       # SLA approaching deadline
            "sla_breach",        # SLA breached
            "escalation",       # Issue escalated
            "verification_needed", # Resolved issue needs citizen verification
            "system",           # System announcements
        ],
        default="system",
        help_text="Type of notification for filtering/routing",
    )
    related_issue_id = StringField(
        help_text="ObjectId of the related issue (if applicable)",
    )
    is_read = BooleanField(
        default=False,
        help_text="Whether the user has read this notification",
    )
    created_at = DateTimeField(
        default=datetime.datetime.utcnow,
    )

    meta = {
        "collection": "notifications",
        "ordering": ["-created_at"],
        "indexes": [
            # User's notification feed
            {
                "fields": ["user_id", "-created_at"],
            },
            # Unread notifications query
            {
                "fields": ["user_id", "is_read"],
            },
        ],
        "strict": False,
    }

    def __str__(self):
        read = "📖" if self.is_read else "🔔"
        return f"{read} [{self.notification_type}] {self.title}"
