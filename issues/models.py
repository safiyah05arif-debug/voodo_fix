"""
CIVIX — Issues App: MongoEngine Document Models
=================================================
All civic issue domain models stored in MongoDB Atlas.

Collections:
    - Issue           → Core issue/ticket document with geospatial index
    - IssueUpvote     → Tracks citizen upvotes (one per user per issue)
    - IssueVerification → Citizen verification of resolved issues
    - EscalationLog   → Audit trail for SLA breaches & auto-escalations

Key Features:
    - 2dsphere GeoJSON index on `location` for spatial dedup queries
    - Embedded documents for AI classification & resolution proof
    - Dynamic priority score calculation method
    - SLA deadline tracking with breach detection
"""

import datetime
from mongoengine import (
    Document,
    EmbeddedDocument,
    # Field types
    StringField,
    IntField,
    FloatField,
    BooleanField,
    DateTimeField,
    ListField,
    DictField,
    URLField,
    ObjectIdField,
    PointField,
    # Embedded document fields
    EmbeddedDocumentField,
    # Referencing
    ReferenceField,
    CASCADE,
)

from django.conf import settings


# =============================================================================
# EMBEDDED DOCUMENTS (nested sub-documents within Issue)
# =============================================================================

class AIClassification(EmbeddedDocument):
    """
    Result from the Vision AI analysis of the uploaded photo.
    Embedded inside each Issue document — not a separate collection.

    Example:
        {
            "category": "road",
            "issue_type": "pothole",
            "severity": "high",
            "confidence": 0.92,
            "raw_response": { ... }
        }
    """
    category = StringField(
        required=True,
        choices=[
            "road", "water", "waste", "electricity",
            "drainage", "public_safety", "environment", "other",
        ],
        help_text="Broad category of the civic issue",
    )
    issue_type = StringField(
        required=True,
        help_text="Specific issue type, e.g., 'pothole', 'burst_pipe', 'garbage_dump'",
    )
    severity = StringField(
        required=True,
        choices=["critical", "high", "medium", "low"],
        help_text="AI-assessed severity level",
    )
    confidence = FloatField(
        required=True,
        min_value=0.0,
        max_value=1.0,
        help_text="AI confidence score (0.0 – 1.0)",
    )
    raw_response = DictField(
        help_text="Full raw JSON response from the AI provider for debugging",
    )

    def __str__(self):
        return f"{self.category}/{self.issue_type} [{self.severity}] ({self.confidence:.0%})"

    meta = {"strict": False}


class ResolutionProof(EmbeddedDocument):
    """
    Evidence submitted by a field worker when closing/resolving an issue.
    Includes an "after" photo and geo-verification.

    Geo-fencing check: The worker's GPS at resolution time must be within
    a configurable radius of the original issue location.
    """
    photo_url = URLField(
        required=True,
        help_text="Supabase Storage URL of the 'after' proof photo",
    )
    worker_location = PointField(
        help_text="Worker's GPS coordinates at the time of resolution [lng, lat]",
    )
    geo_verified = BooleanField(
        default=False,
        help_text="True if worker was within acceptable radius of issue location",
    )
    distance_from_issue = FloatField(
        help_text="Distance in meters between worker and issue at resolution time",
    )
    notes = StringField(
        max_length=1000,
        help_text="Optional field worker notes about the resolution",
    )
    submitted_at = DateTimeField(
        default=datetime.datetime.utcnow,
        help_text="Timestamp when the proof was submitted",
    )

    def __str__(self):
        verified = "✅" if self.geo_verified else "❌"
        return f"Proof {verified} — {self.submitted_at}"

    meta = {"strict": False}


class StatusChange(EmbeddedDocument):
    """
    Audit log entry for every status transition on an issue.
    Stored as a list inside the Issue document for full history.
    """
    from_status = StringField(max_length=30)
    to_status = StringField(required=True, max_length=30)
    changed_by = StringField(
        help_text="User ID or system identifier who made the change",
    )
    changed_at = DateTimeField(default=datetime.datetime.utcnow)
    reason = StringField(
        max_length=500,
        help_text="Optional reason for the status change",
    )

    def __str__(self):
        return f"{self.from_status} → {self.to_status} at {self.changed_at}"

    meta = {"strict": False}


# =============================================================================
# CORE ISSUE DOCUMENT
# =============================================================================

class Issue(Document):
    """
    Central document representing a single civic issue report.

    MongoDB collection: `issue`

    Indexes:
        - 2dsphere on `location` for spatial dedup & proximity queries
        - Compound index on (status, category) for dashboard filtering
        - Index on `priority_score` for sorted ticket views
        - Index on `sla_deadline` for escalation cron queries

    Spatial Deduplication:
        On submission, query { location: { $near: { $geometry: <point>,
        $maxDistance: 50 } }, category: <same> } to find potential duplicates.
    """

    # ── Identity & Source ─────────────────────────────────────────────────────
    title = StringField(
        required=True,
        max_length=200,
        help_text="Short descriptive title of the issue",
    )
    description = StringField(
        max_length=2000,
        help_text="Detailed description (may come from voice-to-text)",
    )
    reported_by = StringField(
        required=True,
        help_text="ObjectId reference to the citizen user who reported this",
    )
    input_method = StringField(
        choices=["text", "direct_camera", "voice_en", "voice_ta", "auto"],
        default="text",
        help_text="How the description was entered",
    )

    # ── Geolocation (GeoJSON Point) ──────────────────────────────────────────
    # MongoEngine PointField stores as GeoJSON: { type: "Point", coordinates: [lng, lat] }
    location = PointField(
        required=True,
        help_text="GeoJSON Point [longitude, latitude] of the issue",
    )
    address = StringField(
        max_length=500,
        help_text="Human-readable address (reverse-geocoded or user-entered)",
    )
    ward = StringField(
        max_length=100,
        help_text="Municipal ward/zone identifier",
    )

    # ── Classification ────────────────────────────────────────────────────────
    category = StringField(
        required=True,
        choices=[
            "road", "water", "waste", "electricity",
            "drainage", "public_safety", "environment", "other",
        ],
        help_text="Issue category (may be set by AI or manually)",
    )
    issue_type = StringField(
        max_length=100,
        help_text="Specific sub-type, e.g., 'pothole', 'overflowing_bin'",
    )
    severity = StringField(
        required=True,
        choices=["critical", "high", "medium", "low"],
        default="medium",
        help_text="Severity level — determines SLA deadline",
    )
    ai_classification = EmbeddedDocumentField(
        AIClassification,
        help_text="AI Vision analysis result (if photo was uploaded)",
    )

    # ── Media ──────────────────────────────────────────────────────────────────
    photo_urls = ListField(
        URLField(),
        max_length=5,
        help_text="List of Supabase Storage URLs for uploaded photos (max 5)",
    )

    # ── Engagement & Deduplication ────────────────────────────────────────────
    upvote_count = IntField(
        default=0,
        min_value=0,
        help_text="Number of citizen upvotes (incremented atomically)",
    )
    upvoted_by = ListField(
        StringField(),
        help_text="List of user IDs who have upvoted (prevents double-voting)",
    )
    duplicate_of = StringField(
        help_text="ObjectId of the original issue if this was merged as a duplicate",
    )
    merged_issue_ids = ListField(
        StringField(),
        help_text="List of ObjectIds of issues merged into this one",
    )

    # ── Status & Workflow ─────────────────────────────────────────────────────
    status = StringField(
        required=True,
        choices=[
            "submitted",       # Just reported by citizen
            "verified",        # Confirmed by system/officer
            "assigned",        # Assigned to a field worker
            "in_progress",     # Field worker is on it
            "resolved",        # Worker submitted proof-of-work
            "citizen_verified", # Citizen confirmed the fix
            "reopened",        # Citizen said the fix is bad
            "escalated",       # SLA breached → auto-escalated
            "closed",          # Permanently closed
        ],
        default="submitted",
        help_text="Current workflow status of the issue",
    )
    assigned_to = StringField(
        help_text="ObjectId of the field worker assigned to this issue",
    )
    assigned_at = DateTimeField(
        help_text="Timestamp when the issue was assigned to a worker",
    )

    # ── Resolution ────────────────────────────────────────────────────────────
    resolution_proof = EmbeddedDocumentField(
        ResolutionProof,
        help_text="Proof submitted by field worker (after photo + geo check)",
    )

    # ── Status History ────────────────────────────────────────────────────────
    status_history = ListField(
        EmbeddedDocumentField(StatusChange),
        help_text="Full audit trail of all status transitions",
    )

    # ── Priority & SLA ────────────────────────────────────────────────────────
    priority_score = FloatField(
        default=0.0,
        help_text="Dynamically calculated priority score for sorting",
    )
    location_risk_factor = FloatField(
        default=1.0,
        min_value=0.0,
        max_value=5.0,
        help_text="Risk multiplier based on location (school zone=5, highway=4, etc.)",
    )
    sla_deadline = DateTimeField(
        help_text="Auto-computed deadline based on severity → SLA_DEADLINES setting",
    )
    sla_breached = BooleanField(
        default=False,
        help_text="True if the SLA deadline has passed without resolution",
    )
    escalation_level = IntField(
        default=0,
        min_value=0,
        max_value=3,
        help_text="0=normal, 1=zone officer, 2=commissioner, 3=public alert",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = DateTimeField(
        default=datetime.datetime.utcnow,
        help_text="When the issue was first reported",
    )
    updated_at = DateTimeField(
        default=datetime.datetime.utcnow,
        help_text="Last modification timestamp",
    )
    resolved_at = DateTimeField(
        help_text="When the issue was marked as resolved",
    )

    # ── MongoDB Collection & Index Configuration ──────────────────────────────
    meta = {
        "collection": "issues",
        "ordering": ["-priority_score", "-created_at"],
        "indexes": [
            # 2dsphere index for spatial deduplication & proximity queries
            {
                "fields": ["location"],
                "cls": False,
                "sparse": False,
            },
            # Compound index for dashboard filtering
            {
                "fields": ["status", "category"],
            },
            # Priority score for sorted admin/worker views
            "-priority_score",
            # SLA deadline for escalation cron job
            "sla_deadline",
            # Reporter lookup
            "reported_by",
            # Assignee lookup
            "assigned_to",
            # Created date for time-series queries
            "-created_at",
        ],
        "strict": False,
    }

    # ── Instance Methods ──────────────────────────────────────────────────────

    def calculate_priority_score(self):
        """
        Dynamic Priority Score Calculator.

        Formula:
            Score = (Severity_Weight × 40) + (Upvotes × 20)
                  + (Hours_Pending × 10) + (Location_Risk × 30)

        Severity weights: critical=4, high=3, medium=2, low=1
        """
        severity_map = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        weights = getattr(settings, "PRIORITY_WEIGHTS", {
            "severity": 40, "upvotes": 20, "hours_pending": 10, "location_risk": 30,
        })

        severity_weight = severity_map.get(self.severity, 1)
        hours_pending = 0
        if self.created_at:
            delta = datetime.datetime.utcnow() - self.created_at
            hours_pending = delta.total_seconds() / 3600

        self.priority_score = (
            (severity_weight * weights["severity"])
            + (self.upvote_count * weights["upvotes"])
            + (hours_pending * weights["hours_pending"])
            + (self.location_risk_factor * weights["location_risk"])
        )
        return self.priority_score

    def set_sla_deadline(self):
        """
        Set the SLA deadline based on the issue severity.
        Uses SLA_DEADLINES from Django settings.
        """
        sla_hours = getattr(settings, "SLA_DEADLINES", {}).get(self.severity, 72)
        if self.created_at:
            self.sla_deadline = self.created_at + datetime.timedelta(hours=sla_hours)
        return self.sla_deadline

    def check_sla_breach(self):
        """Check if the SLA has been breached and update the flag."""
        if (
            self.sla_deadline
            and not self.sla_breached
            and self.status not in ("resolved", "citizen_verified", "closed")
        ):
            if datetime.datetime.utcnow() > self.sla_deadline:
                self.sla_breached = True
        return self.sla_breached

    def add_status_change(self, to_status, changed_by=None, reason=None):
        """Record a status transition in the audit history."""
        change = StatusChange(
            from_status=self.status,
            to_status=to_status,
            changed_by=changed_by,
            reason=reason,
        )
        self.status_history.append(change)
        self.status = to_status
        self.updated_at = datetime.datetime.utcnow()

    def save(self, *args, **kwargs):
        """Override save to auto-update computed fields."""
        self.updated_at = datetime.datetime.utcnow()
        self.calculate_priority_score()
        if not self.sla_deadline:
            self.set_sla_deadline()
        self.check_sla_breach()
        return super().save(*args, **kwargs)

    def to_geojson_feature(self):
        """
        Serialize this issue as a GeoJSON Feature for Leaflet rendering.
        Used by the heatmap API endpoint.
        """
        coordinates = self.location.get("coordinates") if isinstance(self.location, dict) else self.location
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": coordinates,
            },
            "properties": {
                "id": str(self.id),
                "title": self.title,
                "category": self.category,
                "severity": self.severity,
                "status": self.status,
                "upvote_count": self.upvote_count,
                "priority_score": self.priority_score,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "sla_breached": self.sla_breached,
            },
        }

    def __str__(self):
        return f"[{self.status.upper()}] {self.title} ({self.category}/{self.severity})"


# =============================================================================
# UPVOTE TRACKING
# =============================================================================

class IssueUpvote(Document):
    """
    Records individual upvote events for analytics and duplicate prevention.
    One document per (user, issue) pair — enforced by a unique compound index.

    MongoDB collection: `issue_upvotes`
    """
    issue_id = StringField(
        required=True,
        help_text="ObjectId of the issue being upvoted",
    )
    user_id = StringField(
        required=True,
        help_text="ObjectId of the citizen who upvoted",
    )
    created_at = DateTimeField(
        default=datetime.datetime.utcnow,
    )

    meta = {
        "collection": "issue_upvotes",
        "indexes": [
            # Unique compound index: one vote per user per issue
            {
                "fields": ["issue_id", "user_id"],
                "unique": True,
            },
        ],
        "strict": False,
    }

    def __str__(self):
        return f"Upvote: user {self.user_id} → issue {self.issue_id}"


# =============================================================================
# CITIZEN VERIFICATION OF RESOLVED ISSUES
# =============================================================================

class IssueVerification(Document):
    """
    When a field worker marks an issue as 'resolved', nearby citizens can
    verify whether the fix is actually done. If enough citizens reject,
    the issue is reopened automatically.

    MongoDB collection: `issue_verifications`
    """
    issue_id = StringField(
        required=True,
        help_text="ObjectId of the resolved issue being verified",
    )
    user_id = StringField(
        required=True,
        help_text="ObjectId of the verifying citizen",
    )
    is_fixed = BooleanField(
        required=True,
        help_text="True = citizen confirms fix, False = citizen says NOT fixed",
    )
    comment = StringField(
        max_length=500,
        help_text="Optional citizen comment about the verification",
    )
    photo_url = URLField(
        help_text="Optional photo evidence from the citizen",
    )
    location = PointField(
        help_text="Citizen's GPS at verification time (for proximity validation)",
    )
    created_at = DateTimeField(
        default=datetime.datetime.utcnow,
    )

    meta = {
        "collection": "issue_verifications",
        "indexes": [
            {
                "fields": ["issue_id", "user_id"],
                "unique": True,
            },
            "issue_id",
        ],
        "strict": False,
    }

    def __str__(self):
        status = "✅ Fixed" if self.is_fixed else "❌ Not fixed"
        return f"Verification: {status} by {self.user_id} on issue {self.issue_id}"


# =============================================================================
# ESCALATION AUDIT LOG
# =============================================================================

class EscalationLog(Document):
    """
    Audit trail for SLA breaches and automated escalations.
    Created by the background escalation checker task.

    MongoDB collection: `escalation_logs`
    """
    issue_id = StringField(
        required=True,
        help_text="ObjectId of the escalated issue",
    )
    from_level = IntField(
        required=True,
        help_text="Previous escalation level (0–3)",
    )
    to_level = IntField(
        required=True,
        help_text="New escalation level (0–3)",
    )
    reason = StringField(
        required=True,
        choices=["sla_breach", "citizen_reopen", "manual_escalation", "high_upvotes"],
        help_text="What triggered the escalation",
    )
    escalated_to = StringField(
        help_text="User ID of the officer/authority the issue was escalated to",
    )
    hours_overdue = FloatField(
        help_text="How many hours past the SLA deadline",
    )
    created_at = DateTimeField(
        default=datetime.datetime.utcnow,
    )

    meta = {
        "collection": "escalation_logs",
        "indexes": [
            "issue_id",
            "-created_at",
        ],
        "strict": False,
    }

    def __str__(self):
        return f"Escalation: Issue {self.issue_id} L{self.from_level}→L{self.to_level} ({self.reason})"
