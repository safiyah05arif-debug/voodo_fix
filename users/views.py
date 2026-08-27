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
import csv
from django.http import HttpResponse
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import redirect
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
    if password == "demo123" and (user.password_hash or "").startswith("pbkdf2_sha256$demo$"):
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
        "average_rating": user.average_rating,
        "rating_count": user.rating_count or 0,
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
            "voice_enabled": user.accessibility.voice_enabled if user.accessibility else False,
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
        try:
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
        except PyMongoError:
            raise

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


class DevLoginView(APIView):
    """
    Development helper: POST /api/users/dev-login/
    Accepts JSON { "identifier": "ravi-kumar" } and when settings.DEBUG is True
    will set a lightweight session for demo testing without requiring MongoDB.
    Returns a minimal `user` object similar to `serialize_user`.
    """
    def post(self, request):
        from django.conf import settings
        if not getattr(settings, 'DEBUG', False):
            return Response({'error': 'Dev login disabled.'}, status=status.HTTP_403_FORBIDDEN)
        identifier = (request.data.get('identifier') or '').strip()
        if not identifier:
            return Response({'error': 'identifier required'}, status=status.HTTP_400_BAD_REQUEST)

        # Known demo accounts (match seed_data usernames)
        demo_map = {
            'ravi-kumar': {'username': 'ravi-kumar', 'full_name': 'Ravi Kumar', 'role': 'citizen', 'phone': '+919876543210', 'civic_points': 120},
            'priya-devi': {'username': 'priya-devi', 'full_name': 'Priya Devi', 'role': 'citizen', 'phone': '+919876543211', 'civic_points': 85},
            'murugan-s': {'username': 'murugan-s', 'full_name': 'Murugan S', 'role': 'field_worker', 'phone': '+919876543212', 'civic_points': 0},
            'lakshmi-narayanan': {'username': 'lakshmi-narayanan', 'full_name': 'Lakshmi Narayanan', 'role': 'field_worker', 'phone': '+919876543213', 'civic_points': 0},
            'civix-admin': {'username': 'civix-admin', 'full_name': 'CIVIX System Administrator', 'role': 'admin', 'phone': '+919876543216', 'civic_points': 0},
        }

        demo = demo_map.get(identifier) or demo_map.get(identifier.lower())
        if not demo:
            return Response({'error': 'Unknown demo identifier'}, status=status.HTTP_404_NOT_FOUND)

        # Set session keys to simulate a logged-in user
        request.session['civix_user_id'] = f"dev-{demo['username']}"
        request.session['civix_role'] = demo['role']
        request.session['civix_department'] = demo.get('department', '')

        user_obj = {
            'id': request.session['civix_user_id'],
            'username': demo['username'],
            'phone': demo['phone'],
            'is_active': True,
            'email': '',
            'full_name': demo['full_name'],
            'role': demo['role'],
            'zone': demo.get('zone', 'Zone 5 - Adyar'),
            'department': demo.get('department', ''),
            'civic_points': demo.get('civic_points', 0),
            'level': 1,
            'reports_submitted': 0,
            'upvotes_given': 0,
            'verifications_done': 0,
            'issues_resolved': 0,
            'badges': [],
            'accessibility': {'language': 'en', 'high_contrast': False, 'font_size': 'normal', 'easy_read': False}
        }

        redirect_map = {'citizen': '/citizen/', 'field_worker': '/worker/', 'officer': '/officer/', 'zone_officer': '/officer/', 'admin': '/system-admin/'}
        return Response({'success': True, 'message': f"Dev login: {demo['full_name']}", 'user': user_obj, 'redirect_url': redirect_map.get(demo['role'], '/citizen/')})


class UserLogoutView(APIView):
    """Clear the server session and local client identity."""
    def get(self, request):
        request.session.flush()
        return redirect("/login/")


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

        reporter_ids = list(filter(None, [str(user.id), user.username, user.phone]))
        actual_reports = Issue.objects(reported_by__in=reporter_ids).count()
        if actual_reports > (user.reports_submitted or 0):
            missing = actual_reports - (user.reports_submitted or 0)
            user.reports_submitted = actual_reports
            user.add_points(missing * getattr(settings, "REPORT_CIVIC_POINTS", 20))
            user.save()

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

    def patch(self, request):
        user_id = request.session.get("civix_user_id")
        user = CivixUser.objects(id=user_id).first() if user_id and len(user_id) == 24 else None
        if not user:
            return Response({"error": "No user found or unauthorized"}, status=status.HTTP_404_NOT_FOUND)

        allowed = {
            "language": {"en", "ta"},
            "font_size": {"normal", "large", "extra_large"},
        }
        preferences = user.accessibility or AccessibilityPreferences()
        for field, values in allowed.items():
            if field in request.data:
                value = request.data[field]
                if value not in values:
                    return Response({"error": f"Invalid accessibility value for {field}."}, status=status.HTTP_400_BAD_REQUEST)
                setattr(preferences, field, value)
        for field in ("high_contrast", "easy_read", "voice_enabled"):
            if field in request.data:
                value = request.data[field]
                if not isinstance(value, bool):
                    return Response({"error": f"{field} must be true or false."}, status=status.HTTP_400_BAD_REQUEST)
                setattr(preferences, field, value)
        user.accessibility = preferences
        user.save()
        return Response({"success": True, "accessibility": serialize_user(user)["accessibility"]}, status=status.HTTP_200_OK)


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
                    "issues_resolved": w.issues_resolved,
                    "average_rating": w.average_rating,
                    "rating_count": w.rating_count or 0,
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
                category_priority_points=dict(getattr(settings, "CATEGORY_PRIORITY_POINTS", {})),
            ).save()
        return Response({
            "sla_deadlines": config.sla_deadlines,
            "priority_weights": config.priority_weights,
            "category_priority_points": config.category_priority_points or dict(getattr(settings, "CATEGORY_PRIORITY_POINTS", {})),
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
        if "category_priority_points" in request.data:
            points = dict(getattr(settings, "CATEGORY_PRIORITY_POINTS", {}))
            incoming = request.data["category_priority_points"] or {}
            for key, value in incoming.items():
                try:
                    points[key] = max(0, int(value))
                except (TypeError, ValueError):
                    continue
            settings.CATEGORY_PRIORITY_POINTS = points
            config.category_priority_points = points
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


class AdminIssueExportView(MongoSafeAPIView):
    """Download a month of issue, resolution, and completion details for Excel."""
    def get(self, request):
        def coordinates_for(value):
            if isinstance(value, dict):
                value = value.get("coordinates", [])
            elif hasattr(value, "coordinates"):
                value = value.coordinates
            return list(value or [])

        def coordinate_at(value, index):
            try:
                coordinates = coordinates_for(value)
                return coordinates[index] if len(coordinates) > index else ""
            except (KeyError, IndexError, TypeError):
                return ""

        month = request.query_params.get("month", "").strip()
        scope = request.query_params.get("scope", "all").strip()
        if scope not in {"all", "reports", "resolved", "completion"}:
            return Response({"error": "Invalid export scope."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            selected_month = datetime.date.fromisoformat(f"{month}-01") if month else datetime.date.today().replace(day=1)
        except ValueError:
            return Response({"error": "Month must use YYYY-MM format."}, status=status.HTTP_400_BAD_REQUEST)

        next_month = (selected_month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        issue_query = Issue.objects(
            created_at__gte=datetime.datetime.combine(selected_month, datetime.time.min),
            created_at__lt=datetime.datetime.combine(next_month, datetime.time.min),
        )
        if scope == "resolved":
            issue_query = issue_query.filter(status__in=list(RESOLVED_STATUSES))
        elif scope == "completion":
            issue_query = issue_query.filter(resolution_proof__exists=True)
        issues = issue_query.order_by("created_at")

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="civix-issues-{selected_month:%Y-%m}.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow([
            "Issue ID", "Reported At", "Title", "Description", "Category", "Issue Type", "Severity",
            "Status", "Officer Decision", "Assigned Worker", "Ward", "Address", "Latitude", "Longitude",
            "Upvotes", "SLA Deadline", "SLA Breached", "Photo URL", "Resolved At", "Resolved By",
            "Completion Proof Photo", "Completion Submitted At", "Completion Latitude", "Completion Longitude",
            "Completion Distance (m)", "Verification Status", "Completion Notes",
        ])
        for issue in issues:
            coordinates = coordinates_for(issue.location)
            proof = issue.resolution_proof
            writer.writerow([
                str(issue.id), issue.created_at.isoformat() if issue.created_at else "", issue.title, issue.description or "",
                issue.category, issue.issue_type or "", issue.severity, issue.status, issue.officer_decision or "",
                issue.assigned_to or "", issue.ward or "", issue.address or "", coordinate_at(coordinates, 1),
                coordinate_at(coordinates, 0), issue.upvote_count or 0, issue.sla_deadline.isoformat() if issue.sla_deadline else "",
                "Yes" if issue.sla_breached else "No", (issue.photo_urls or [""])[0], issue.resolved_at.isoformat() if issue.resolved_at else "",
                proof.worker_id if proof else "", proof.photo_url if proof else "", proof.submitted_at.isoformat() if proof and proof.submitted_at else "",
                coordinate_at(proof.worker_location, 1) if proof else "",
                coordinate_at(proof.worker_location, 0) if proof else "", proof.distance_from_issue if proof else "",
                proof.verification_status if proof else "", proof.notes if proof else "",
            ])
        return response


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


class AdminResetPasswordView(MongoSafeAPIView):
    """PATCH /api/users/admin/users/<id>/reset-password/ for admin access recovery."""
    def patch(self, request, user_id):
        user = CivixUser.objects(id=user_id).first()
        if not user:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        password = request.data.get("password", "").strip()
        if len(password) < 8:
            return Response({"error": "Reset password must be at least 8 characters."}, status=status.HTTP_400_BAD_REQUEST)
        user.password_hash = hash_pw(password)
        user.save()
        log_admin_action(request, "reset_user_password", target_id=str(user.id), details={"role": user.role})
        return Response({"success": True, "user_id": str(user.id), "message": "Access password reset securely."})


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
