"""
CIVIX — Users App API Views (Phone-First Authentication & Worker Provisioning)
=================================================================================
Endpoints:
    - POST /api/users/login/            (Phone number + password login)
    - POST /api/users/register/         (New citizen registration via Phone)
    - POST /api/users/workers/add/      (Officer registers a new field worker)
    - GET  /api/users/profile/          (Profile & badges)
    - GET  /api/users/leaderboard/      (Civic leaderboard)
    - GET  /api/users/workers/          (List active workers)
"""

import hashlib
import time
from rest_framework.views import APIView
from rest_framework.response import Response
from pymongo.errors import PyMongoError
from rest_framework import status
from django.conf import settings
from issues.models import Issue, EscalationLog

from users.models import CivixUser, Badge, AccessibilityPreferences


def hash_pw(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def password_matches(user, password):
    if user.password_hash == hash_pw(password):
        return True
    # Seeded demo records use a placeholder; allow the documented demo password once.
    return user.password_hash.startswith("pbkdf2_sha256$demo$") and password == "demo123"


def serialize_user(user):
    return {
        "id": str(user.id),
        "phone": user.phone,
        "email": user.email or "",
        "full_name": user.full_name,
        "role": user.role,
        "zone": user.zone or "Zone 5 - Adyar",
        "department": user.department or "Municipal Administration",
        "civic_points": user.civic_points,
        "level": user.level,
        "reports_submitted": user.reports_submitted,
        "upvotes_given": user.upvotes_given,
        "verifications_done": user.verifications_done,
        "issues_resolved": user.issues_resolved,
        "badges": [
            {
                "badge_slug": b.badge_slug,
                "badge_name": b.badge_name,
                "badge_icon": b.badge_icon,
                "earned_at": b.earned_at.isoformat() if b.earned_at else None
            } for b in user.badges
        ],
        "accessibility": {
            "language": user.accessibility.language if user.accessibility else "en",
            "high_contrast": user.accessibility.high_contrast if user.accessibility else False,
            "font_size": user.accessibility.font_size if user.accessibility else "normal",
        }
    }


class MongoSafeAPIView(APIView):
    def handle_exception(self, exc):
        if isinstance(exc, PyMongoError):
            return Response(
                {"error": "User data is temporarily unavailable. Check the MongoDB connection."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return super().handle_exception(exc)


class UserLoginView(MongoSafeAPIView):
    """
    POST /api/users/login/
    Login using Phone Number (or Email) + Password.
    """
    def post(self, request):
        phone_or_email = request.data.get("phone", "").strip() or request.data.get("email", "").strip()
        password = request.data.get("password", "")

        if not phone_or_email:
            return Response({"error": "Phone number is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Lookup by phone (clean formatting) or email
        clean_phone = phone_or_email.replace(" ", "").replace("-", "")
        user = None
        for attempt in range(2):
            try:
                user = CivixUser.objects(phone__in=[clean_phone, f"+91{clean_phone}", phone_or_email]).first()
                break
            except PyMongoError:
                if attempt == 1:
                    raise
                time.sleep(0.2)
        
        if not user and "@" in phone_or_email:
            user = CivixUser.objects(email=phone_or_email.lower()).first()

        if not user:
            return Response({"error": f"No account found for phone number: {phone_or_email}"}, status=status.HTTP_401_UNAUTHORIZED)
        if not password_matches(user, password):
            return Response({"error": "Invalid phone number or password."}, status=status.HTTP_401_UNAUTHORIZED)

        request.session["civix_user_id"] = str(user.id)
        request.session["civix_role"] = user.role
        request.session["civix_department"] = user.department or ""

        # Redirect mapping
        portal_redirect = {
            "citizen": "/citizen/",
            "field_worker": "/worker/",
            "officer": "/officer/",
            "zone_officer": "/officer/",
            "admin": "/officer/",
        }.get(user.role, "/citizen/")

        return Response({
            "success": True,
            "message": f"Welcome back, {user.full_name}!",
            "user": serialize_user(user),
            "redirect_url": portal_redirect
        }, status=status.HTTP_200_OK)


class UserRegisterView(MongoSafeAPIView):
    """
    POST /api/users/register/
    Citizen registration by Phone Number.
    """
    def post(self, request):
        phone = request.data.get("phone", "").strip().replace(" ", "").replace("-", "")
        full_name = request.data.get("full_name", "").strip()
        password = request.data.get("password", "password123")
        zone = request.data.get("zone", "Zone 5 - Adyar")
        email = request.data.get("email", "").strip().lower()

        if not phone or not full_name:
            return Response({"error": "Full Name and Phone Number are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Check existing
        existing = CivixUser.objects(phone__in=[phone, f"+91{phone}"]).first()
        if existing:
            return Response({"error": "An account with this phone number already exists."}, status=status.HTTP_400_BAD_REQUEST)

        user = CivixUser(
            phone=phone,
            email=email if email else None,
            full_name=full_name,
            password_hash=hash_pw(password),
            role="citizen",
            zone=zone,
            civic_points=50,
            accessibility=AccessibilityPreferences(language="en")
        )
        user.save()
        request.session["civix_user_id"] = str(user.id)
        request.session["civix_role"] = user.role
        request.session["civix_department"] = user.department or ""

        # Award first report badge
        first_badge = Badge.objects(slug="first_report").first()
        if first_badge:
            user.award_badge(first_badge)
            user.save()

        return Response({
            "success": True,
            "message": "Citizen account created successfully! +50 Welcome Points awarded.",
            "user": serialize_user(user),
            "redirect_url": "/citizen/"
        }, status=status.HTTP_201_CREATED)


class WorkerAddView(APIView):
    """
    POST /api/users/workers/add/
    Allows Municipal Officers to provision and onboard a new Field Worker.
    """
    def post(self, request):
        full_name = request.data.get("full_name", "").strip()
        phone = request.data.get("phone", "").strip().replace(" ", "").replace("-", "")
        department = request.data.get("department", "Roads & Maintenance")
        zone = request.data.get("zone", "Zone 5 - Adyar")
        password = request.data.get("password", "worker123")

        if not full_name or not phone:
            return Response({"error": "Worker Name and Phone Number are required."}, status=status.HTTP_400_BAD_REQUEST)

        existing = CivixUser.objects(phone__in=[phone, f"+91{phone}"]).first()
        if existing:
            return Response({"error": "A user with this phone number already exists."}, status=status.HTTP_400_BAD_REQUEST)

        worker = CivixUser(
            full_name=full_name,
            phone=phone,
            department=department,
            zone=zone,
            role="field_worker",
            password_hash=hash_pw(password),
            civic_points=0,
            accessibility=AccessibilityPreferences(language="en", high_contrast=True)
        )
        worker.save()

        return Response({
            "success": True,
            "message": f"Field Worker '{full_name}' successfully added to {department} ({zone})!",
            "worker": serialize_user(worker)
        }, status=status.HTTP_201_CREATED)


class UserProfileView(MongoSafeAPIView):
    def get(self, request):
        user_id = request.session.get("civix_user_id") or request.query_params.get("user_id")
        phone = request.query_params.get("phone")
        user = None

        if user_id and len(user_id) == 24:
            user = CivixUser.objects(id=user_id).first()
        elif phone:
            user = CivixUser.objects(phone__in=[phone, f"+91{phone}"]).first()
        
        if not user:
            user = CivixUser.objects(role="citizen").first()
        
        if not user:
            return Response({"error": "No user found"}, status=status.HTTP_404_NOT_FOUND)

        all_badges = [
            {
                "name": b.name,
                "slug": b.slug,
                "description": b.description,
                "description_ta": b.description_ta,
                "icon": b.icon,
                "points_reward": b.points_reward
            } for b in Badge.objects
        ]

        return Response({
            "user": serialize_user(user),
            "available_badges": all_badges
        }, status=status.HTTP_200_OK)


class LeaderboardView(MongoSafeAPIView):
    def get(self, request):
        users = CivixUser.objects(role="citizen").order_by("-civic_points")[:10]
        return Response([serialize_user(u) for u in users], status=status.HTTP_200_OK)


class WorkerListView(APIView):
    def get(self, request):
        try:
            workers = CivixUser.objects(role="field_worker")
            return Response([
                {
                    "id": str(w.id),
                    "name": w.full_name,
                    "phone": w.phone,
                    "department": w.department or "Public Works",
                    "zone": w.zone or "Zone 5 - Adyar",
                    "issues_resolved": w.issues_resolved
                } for w in workers
            ], status=status.HTTP_200_OK)
        except PyMongoError:
            return Response(
                {"error": "Worker data is temporarily unavailable. Check the MongoDB connection."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class AdminMetricsView(MongoSafeAPIView):
    def get(self, request):
        issues = list(Issue.objects.only("status", "created_at", "resolved_at"))
        status_counts = {}
        for issue in issues:
            status_counts[issue.status] = status_counts.get(issue.status, 0) + 1
        resolved = [issue for issue in issues if issue.resolved_at and issue.created_at]
        average_hours = sum((issue.resolved_at - issue.created_at).total_seconds() for issue in resolved) / 3600 / len(resolved) if resolved else 0
        workers = CivixUser.objects(role="field_worker").count()
        return Response({
            "total_issues": len(issues),
            "status_counts": status_counts,
            "resolved_count": status_counts.get("resolved", 0) + status_counts.get("citizen_verified", 0),
            "resolution_rate": round((len(resolved) / len(issues)) * 100, 1) if issues else 0,
            "average_turnaround_hours": round(average_hours, 1),
            "active_field_workers": workers,
        })


class AdminConfigView(MongoSafeAPIView):
    def get(self, request):
        return Response({
            "sla_deadlines": getattr(settings, "SLA_DEADLINES", {}),
            "priority_weights": getattr(settings, "PRIORITY_WEIGHTS", {}),
        })

    def patch(self, request):
        if "sla_deadlines" in request.data:
            deadlines = dict(getattr(settings, "SLA_DEADLINES", {}))
            deadlines.update(request.data["sla_deadlines"])
            settings.SLA_DEADLINES = deadlines
        if "priority_weights" in request.data:
            weights = dict(getattr(settings, "PRIORITY_WEIGHTS", {}))
            weights.update(request.data["priority_weights"])
            settings.PRIORITY_WEIGHTS = weights
        return self.get(request)


class AdminAnalyticsView(MongoSafeAPIView):
    def get(self, request):
        metrics = AdminMetricsView().get(request)
        data = metrics.data
        by_department = {}
        for issue in Issue.objects.only("category", "status", "sla_breached"):
            bucket = by_department.setdefault(issue.category, {"total": 0, "resolved": 0, "sla_breaches": 0})
            bucket["total"] += 1
            bucket["resolved"] += issue.status in ("resolved", "citizen_verified", "closed")
            bucket["sla_breaches"] += bool(issue.sla_breached)
        data["departments"] = by_department
        return Response(data)


class AdminUsersView(MongoSafeAPIView):
    def get(self, request):
        return Response([serialize_user(user) for user in CivixUser.objects])


class AdminAuditLogsView(MongoSafeAPIView):
    def get(self, request):
        logs = []
        for issue in Issue.objects.only("status_history"):
            logs.extend({"issue_id": str(issue.id), "type": "status_change", "from_status": change.from_status, "to_status": change.to_status, "changed_by": change.changed_by, "changed_at": change.changed_at.isoformat() if change.changed_at else None, "reason": change.reason or ""} for change in (issue.status_history or []))
        logs.extend({"issue_id": log.issue_id, "type": "escalation", "from_level": log.from_level, "to_level": log.to_level, "reason": log.reason, "created_at": log.created_at.isoformat() if log.created_at else None} for log in EscalationLog.objects)
        return Response(logs)


class AdminCreateUserView(MongoSafeAPIView):
    def post(self, request):
        full_name = request.data.get("full_name", "").strip()
        phone = request.data.get("phone", "").strip().replace(" ", "").replace("-", "")
        role = request.data.get("role", "field_worker")
        if role not in ("citizen", "field_worker", "officer", "zone_officer", "admin"):
            return Response({"error": "Invalid role"}, status=status.HTTP_400_BAD_REQUEST)
        if not full_name or not phone:
            return Response({"error": "Full name and phone are required"}, status=status.HTTP_400_BAD_REQUEST)
        if CivixUser.objects(phone__in=[phone, f"+91{phone}"]).first():
            return Response({"error": "Phone number already exists"}, status=status.HTTP_400_BAD_REQUEST)
        user = CivixUser(full_name=full_name, phone=phone, role=role, department=request.data.get("department", "General"), zone=request.data.get("zone", "Zone 5 - Adyar"), password_hash=hash_pw(request.data.get("password", "change-me")))
        user.save()
        return Response({"success": True, "user": serialize_user(user)}, status=status.HTTP_201_CREATED)
