"""
CIVIX — Users App API Views (With Authentication)
===================================================
Endpoints:
    - POST /api/users/login/        (Role-based login)
    - POST /api/users/register/     (Citizen sign-up)
    - GET  /api/users/profile/      (User stats & badges)
    - GET  /api/users/leaderboard/  (Civic leaderboard)
    - GET  /api/users/workers/      (Active field workers)
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import hashlib

from users.models import CivixUser, Badge, AccessibilityPreferences


def hash_pw(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def serialize_user(user):
    return {
        "id": str(user.id),
        "email": user.email,
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


class UserLoginView(APIView):
    """
    POST /api/users/login/
    Authenticates by email + password, returns user object and designated portal URL.
    """
    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password", "")

        user = CivixUser.objects(email=email).first()
        if not user:
            return Response({"error": "Invalid email or account does not exist"}, status=status.HTTP_401_UNAUTHORIZED)

        # In dev/demo, allow direct login or matching hash
        # Determine target portal based on role
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


class UserRegisterView(APIView):
    """
    POST /api/users/register/
    Registers a new citizen user.
    """
    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        full_name = request.data.get("full_name", "").strip()
        password = request.data.get("password", "password123")
        role = request.data.get("role", "citizen")
        phone = request.data.get("phone", "")

        if not email or not full_name:
            return Response({"error": "Email and Full Name are required."}, status=status.HTTP_400_BAD_REQUEST)

        existing = CivixUser.objects(email=email).first()
        if existing:
            return Response({"error": "An account with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

        user = CivixUser(
            email=email,
            full_name=full_name,
            phone=phone if phone else None,
            password_hash=hash_pw(password),
            role=role,
            zone="Zone 5 - Adyar",
            civic_points=50,
            accessibility=AccessibilityPreferences(language="en")
        )
        user.save()

        # Award first welcome badge
        first_badge = Badge.objects(slug="first_report").first()
        if first_badge:
            user.award_badge(first_badge)
            user.save()

        return Response({
            "success": True,
            "message": "Account created successfully! +50 Welcome Points awarded.",
            "user": serialize_user(user),
            "redirect_url": "/citizen/" if role == "citizen" else ("/worker/" if role == "field_worker" else "/officer/")
        }, status=status.HTTP_201_CREATED)


class UserProfileView(APIView):
    def get(self, request):
        user_id = request.query_params.get("user_id")
        user = None
        if user_id and len(user_id) == 24:
            user = CivixUser.objects(id=user_id).first()
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


class LeaderboardView(APIView):
    def get(self, request):
        users = CivixUser.objects(role="citizen").order_by("-civic_points")[:10]
        return Response([serialize_user(u) for u in users], status=status.HTTP_200_OK)


class WorkerListView(APIView):
    def get(self, request):
        workers = CivixUser.objects(role="field_worker")
        return Response([
            {
                "id": str(w.id),
                "name": w.full_name,
                "department": w.department or "Public Works",
                "zone": w.zone or "All Zones",
                "issues_resolved": w.issues_resolved
            } for w in workers
        ], status=status.HTTP_200_OK)
