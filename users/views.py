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

import datetime
import hashlib
import re
import time
from django.contrib.auth.hashers import check_password, make_password
from rest_framework.views import APIView
from rest_framework.response import Response
from pymongo.errors import PyMongoError
from rest_framework import status
from django.conf import settings
from issues.models import Issue, EscalationLog

from users.models import CivixUser, Badge, AccessibilityPreferences, AdminAuditLog, SystemConfig, Notification

RESOLVED_STATUSES = {"resolved", "citizen_verified", "closed"}


def hash_pw(password):
    return make_password(password)


def password_matches(user, password):
    try:
        if check_password(password, user.password_hash):
            return True
    except ValueError:
        pass
    if user.password_hash == hashlib.sha256(password.encode("utf-8")).hexdigest():
        user.password_hash = make_password(password)
        if user.id:
            user.save()
        return True
    # Seeded demo records use a placeholder; allow the documented demo password once.
    if user.password_hash.startswith("pbkdf2_sha256$demo$") and password == "demo123":
        user.password_hash = make_password(password)
        if user.id:
            user.save()
        return True
    return False


def log_admin_action(request, action, target_id="", details=None):
    actor_id = request.session.get("civix_user_id", "unknown")
    AdminAuditLog(actor_id=actor_id, action=action, target_id=target_id, details=details or {}).save()


def serialize_user(user):
    return {
        "id": str(user.id),
        "username": user.username or "",
        "phone": user.phone,
        "is_active": getattr(user, "is_active", True),
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
            "easy_read": user.accessibility.easy_read if user.accessibility else False,
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
    Login using Username, Phone Number, or Email + Password.
    """
    def post(self, request):
        identifier = (
            request.data.get("identifier", "").strip()
            or request.data.get("username", "").strip()
            or request.data.get("phone", "").strip()
            or request.data.get("email", "").strip()
        )
        password = request.data.get("password", "")

        if not identifier:
            return Response({"error": "Username or phone number is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Lookup the friendly username first, then preserve phone/email login.
        clean_phone = identifier.replace(" ", "").replace("-", "")
        user = None
        for attempt in range(2):
            try:
                user = CivixUser.objects(username=identifier.lower()).first()
                if not user:
                    user = CivixUser.objects(phone__in=[clean_phone, f"+91{clean_phone}", identifier]).first()
                break
            except PyMongoError:
                if attempt == 1:
                    raise
                time.sleep(0.2)
        
        if not user and "@" in identifier:
            user = CivixUser.objects(email=identifier.lower()).first()

        if not user:
            return Response({"error": f"No account found for username or phone number: {identifier}"}, status=status.HTTP_401_UNAUTHORIZED)
        if not getattr(user, "is_active", True):
            return Response({"error": "This account is deactivated. Contact a system administrator."}, status=status.HTTP_403_FORBIDDEN)
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
            "admin": "/system-admin/",
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

        username_base = re.sub(r"[^a-z0-9]+", "-", full_name.lower()).strip("-") or "citizen"
        username = f"{username_base}-{phone[-4:]}"
        username_index = 2
        while CivixUser.objects(username=username).first():
            username = f"{username_base}-{phone[-4:]}-{username_index}"
            username_index += 1

        user = CivixUser(
            phone=phone,
            username=username,
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
        password = request.data.get("password", "").strip()

        if not full_name or not phone:
            return Response({"error": "Worker Name and Phone Number are required."}, status=status.HTTP_400_BAD_REQUEST)
        if len(password) < 6:
            return Response({"error": "Worker password must be at least 6 characters."}, status=status.HTTP_400_BAD_REQUEST)

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
        user_id = request.session.get("civix_user_id")
        user = None

        if user_id and len(user_id) == 24:
            user = CivixUser.objects(id=user_id).first()
        
        if not user:
            return Response({"error": "No user found or unauthorized"}, status=status.HTTP_404_NOT_FOUND)

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


class NotificationListView(MongoSafeAPIView):
    def get(self, request):
        user_id = request.session.get("civix_user_id")
        if not user_id:
            return Response({"error": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)
        notifications = Notification.objects(user_id=user_id).order_by("-created_at")[:50]
        return Response([{
            "id": str(notification.id),
            "title": notification.title,
            "title_ta": notification.title_ta or "",
            "message": notification.message,
            "message_ta": notification.message_ta or "",
            "notification_type": notification.notification_type,
            "related_issue_id": notification.related_issue_id or "",
            "is_read": notification.is_read,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        } for notification in notifications])

    def patch(self, request):
        notification = Notification.objects(
            id=request.data.get("notification_id"),
            user_id=request.session.get("civix_user_id"),
        ).first()
        if not notification:
            return Response({"error": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)
        notification.is_read = True
        notification.save()
        return Response({"success": True})


class AdminMetricsView(MongoSafeAPIView):
    def get(self, request):
        issues = list(Issue.objects.only("status", "created_at", "resolved_at"))
        status_counts = {}
        for issue in issues:
            status_counts[issue.status] = status_counts.get(issue.status, 0) + 1
        resolved_issues = [issue for issue in issues if issue.status in RESOLVED_STATUSES]
        resolved_with_dates = [issue for issue in resolved_issues if issue.resolved_at and issue.created_at]
        average_hours = sum((issue.resolved_at - issue.created_at).total_seconds() for issue in resolved_with_dates) / 3600 / len(resolved_with_dates) if resolved_with_dates else 0
        workers = CivixUser.objects(role="field_worker").count()
        return Response({
            "total_issues": len(issues),
            "status_counts": status_counts,
            "resolved_count": len(resolved_issues),
            "resolution_rate": round((len(resolved_issues) / len(issues)) * 100, 1) if issues else 0,
            "average_turnaround_hours": round(average_hours, 1),
            "active_field_workers": workers,
        })


class AdminConfigView(MongoSafeAPIView):
    def get(self, request):
        config = SystemConfig.objects(key="default").first()
        if not config:
            config = SystemConfig(
                key="default",
                sla_deadlines=dict(getattr(settings, "SLA_DEADLINES", {})),
                priority_weights=dict(getattr(settings, "PRIORITY_WEIGHTS", {})),
            ).save()
        return Response({
            "sla_deadlines": config.sla_deadlines,
            "priority_weights": config.priority_weights,
        })

    def patch(self, request):
        config = SystemConfig.objects(key="default").first() or SystemConfig(key="default")
        if "sla_deadlines" in request.data:
            deadlines = dict(getattr(settings, "SLA_DEADLINES", {}))
            deadlines.update(request.data["sla_deadlines"])
            settings.SLA_DEADLINES = deadlines
            config.sla_deadlines = deadlines
        if "priority_weights" in request.data:
            weights = dict(getattr(settings, "PRIORITY_WEIGHTS", {}))
            weights.update(request.data["priority_weights"])
            settings.PRIORITY_WEIGHTS = weights
            config.priority_weights = weights
        config.updated_at = datetime.datetime.utcnow()
        config.save()
        log_admin_action(request, "update_system_config", details={"keys": list(request.data.keys())})
        return self.get(request)


class AdminAnalyticsView(MongoSafeAPIView):
    def get(self, request):
        metrics = AdminMetricsView().get(request)
        data = metrics.data
        by_department = {}
        for issue in Issue.objects.only("category", "status", "sla_breached"):
            bucket = by_department.setdefault(issue.category, {"total": 0, "resolved": 0, "sla_breaches": 0})
            bucket["total"] += 1
            bucket["resolved"] += issue.status in RESOLVED_STATUSES
            bucket["sla_breaches"] += bool(issue.sla_breached)
        data["departments"] = by_department
        return Response(data)


class AdminUsersView(MongoSafeAPIView):
    def get(self, request):
        return Response([serialize_user(user) for user in CivixUser.objects])


class AdminAuditLogsView(MongoSafeAPIView):
    def get(self, request):
        logs = []
        logs.extend({"issue_id": log.target_id, "type": "admin_action", "action": log.action, "changed_by": log.actor_id, "created_at": log.created_at.isoformat() if log.created_at else None} for log in AdminAuditLog.objects)
        for issue in Issue.objects.only("status_history"):
            logs.extend({"issue_id": str(issue.id), "type": "status_change", "from_status": change.from_status, "to_status": change.to_status, "changed_by": change.changed_by, "changed_at": change.changed_at.isoformat() if change.changed_at else None, "reason": change.reason or ""} for change in (issue.status_history or []))
        logs.extend({"issue_id": log.issue_id, "type": "escalation", "from_level": log.from_level, "to_level": log.to_level, "reason": log.reason, "created_at": log.created_at.isoformat() if log.created_at else None} for log in EscalationLog.objects)
        return Response(logs)


class AdminCreateUserView(MongoSafeAPIView):
    def post(self, request):
        full_name = request.data.get("full_name", "").strip()
        phone = request.data.get("phone", "").strip().replace(" ", "").replace("-", "")
        username = request.data.get("username", "").strip().lower()
        password = request.data.get("password", "").strip()
        role = request.data.get("role", "field_worker")
        if role not in ("citizen", "field_worker", "officer", "zone_officer", "admin"):
            return Response({"error": "Invalid role"}, status=status.HTTP_400_BAD_REQUEST)
        if not full_name or not phone:
            return Response({"error": "Full name and phone are required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(password) < 6:
            return Response({"error": "Password must be at least 6 characters"}, status=status.HTTP_400_BAD_REQUEST)
        if CivixUser.objects(phone__in=[phone, f"+91{phone}"]).first():
            return Response({"error": "Phone number already exists"}, status=status.HTTP_400_BAD_REQUEST)
        if username and CivixUser.objects(username=username).first():
            return Response({"error": "Username already exists"}, status=status.HTTP_400_BAD_REQUEST)
        user = CivixUser(username=username or None, full_name=full_name, phone=phone, role=role, department=request.data.get("department", "General"), zone=request.data.get("zone", "Zone 5 - Adyar"), password_hash=hash_pw(password))
        user.save()
        log_admin_action(request, "create_user", target_id=str(user.id), details={"role": role})
        return Response({"success": True, "user": serialize_user(user)}, status=status.HTTP_201_CREATED)


class AdminUpdateUserView(MongoSafeAPIView):
    def patch(self, request, user_id):
        user = CivixUser.objects(id=user_id).first()
        if not user:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        role = request.data.get("role", user.role)
        if role not in ("citizen", "field_worker", "officer", "zone_officer", "admin"):
            return Response({"error": "Invalid role"}, status=status.HTTP_400_BAD_REQUEST)
        if str(user.id) == request.session.get("civix_user_id") and role != "admin":
            return Response({"error": "You cannot remove your own admin role."}, status=status.HTTP_400_BAD_REQUEST)
        if str(user.id) == request.session.get("civix_user_id") and request.data.get("is_active") is False:
            return Response({"error": "You cannot deactivate your own admin account."}, status=status.HTTP_400_BAD_REQUEST)

        username = request.data.get("username", user.username or "").strip().lower()
        phone = request.data.get("phone", user.phone or "").strip().replace(" ", "").replace("-", "")
        duplicate_phone = CivixUser.objects(phone__in=[phone, f"+91{phone}"]).first()
        if duplicate_phone and duplicate_phone.id != user.id:
            return Response({"error": "Phone number already exists"}, status=status.HTTP_400_BAD_REQUEST)
        duplicate_username = CivixUser.objects(username=username).first() if username else None
        if duplicate_username and duplicate_username.id != user.id:
            return Response({"error": "Username already exists"}, status=status.HTTP_400_BAD_REQUEST)

        password = request.data.get("password", "").strip()
        if password and len(password) < 6:
            return Response({"error": "Password must be at least 6 characters"}, status=status.HTTP_400_BAD_REQUEST)

        user.username = username or None
        user.full_name = request.data.get("full_name", user.full_name).strip()
        user.phone = phone
        user.role = role
        user.department = request.data.get("department", user.department or "General").strip()
        user.zone = request.data.get("zone", user.zone or "Zone 5 - Adyar").strip()
        if "is_active" in request.data:
            user.is_active = bool(request.data["is_active"])
        if password:
            user.password_hash = hash_pw(password)
        user.save()
        log_admin_action(request, "update_user", target_id=str(user.id), details={"role": role, "password_changed": bool(password)})
        return Response({"success": True, "user": serialize_user(user)})


class AdminDeactivateUserView(MongoSafeAPIView):
    def patch(self, request, user_id):
        user = CivixUser.objects(id=user_id).first()
        if not user:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        if str(user.id) == request.session.get("civix_user_id"):
            return Response({"error": "You cannot deactivate your own admin account."}, status=status.HTTP_400_BAD_REQUEST)
        user.is_active = False
        user.save()
        log_admin_action(request, "deactivate_user", target_id=str(user.id))
        return Response({"success": True, "user_id": str(user.id), "is_active": False})
