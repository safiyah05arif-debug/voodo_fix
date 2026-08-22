"""
CIVIX — Users App API Views
=============================
Endpoints:
    - GET /api/users/profile/       (Current user points, level, earned badges)
    - GET /api/users/leaderboard/   (Top civic contributors by ward/points)
    - GET /api/users/workers/       (Active field workers list for dropdowns)
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from users.models import CivixUser, Badge


def serialize_user(user):
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "zone": user.zone or "",
        "department": user.department or "",
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


class UserProfileView(APIView):
    def get(self, request):
        user_id = request.query_params.get("user_id")
        user = None
        if user_id:
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
