"""
CIVIX — Issues App REST API Views & Serializers
=================================================
Implements DRF endpoints:
    - POST /api/issues/classify/         (Instant Vision AI preview on photo capture)
    - POST /api/issues/report/           (Direct photo + GPS + AI + Dedup)
    - GET  /api/issues/heatmap/          (GeoJSON for Leaflet)
    - GET  /api/issues/                  (Master ticket queue)
    - POST /api/issues/<id>/upvote/      (One-vote-per-user)
    - PATCH /api/issues/<id>/resolve/    (Worker proof + Geo-fencing)
    - POST /api/issues/<id>/verify/      (Citizen confirmation)
    - PATCH /api/issues/<id>/assign/     (Officer task assignment)
"""

import math
import datetime
from bson import ObjectId
from pymongo.errors import PyMongoError
from rest_framework import status, serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from mongoengine.errors import NotUniqueError

from issues.models import Issue, AIClassification, ResolutionProof, StatusChange, IssueUpvote, IssueVerification, EscalationLog
from users.models import Badge, CivixUser
from civix_backend.storage import upload_image_bytes
from civix_backend.ai_vision import classify_issue_image


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance in meters between two lat/lng coordinates."""
    R = 6371000  # Radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def location_coordinates(location):
    """Return a PointField value as [longitude, latitude]."""
    return location.get("coordinates") if isinstance(location, dict) else location


def serialize_issue(issue):
    """Convert MongoEngine Issue document to JSON-friendly dict."""
    coordinates = location_coordinates(issue.location)
    return {
        "id": str(issue.id),
        "title": issue.title,
        "description": issue.description or "",
        "category": issue.category,
        "issue_type": issue.issue_type or "",
        "severity": issue.severity,
        "status": issue.status,
        "location": {
            "longitude": coordinates[0],
            "latitude": coordinates[1],
            "coordinates": coordinates,
        },
        "address": issue.address or "",
        "ward": issue.ward or "",
        "upvote_count": issue.upvote_count,
        "priority_score": round(issue.priority_score, 1),
        "photo_urls": issue.photo_urls or [],
        "ai_classification": {
            "category": issue.ai_classification.category,
            "issue_type": issue.ai_classification.issue_type,
            "severity": issue.ai_classification.severity,
            "confidence": issue.ai_classification.confidence,
        } if issue.ai_classification else None,
        "assigned_to": issue.assigned_to or "",
        "sla_deadline": issue.sla_deadline.isoformat() if issue.sla_deadline else None,
        "sla_breached": issue.sla_breached,
        "escalation_level": issue.escalation_level,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None,
        "status_history": [
            {
                "from_status": change.from_status,
                "to_status": change.to_status,
                "changed_by": change.changed_by,
                "changed_at": change.changed_at.isoformat() if change.changed_at else None,
                "reason": change.reason or "",
            } for change in (issue.status_history or [])
        ],
    }


def session_user_id(request, fallback="anonymous"):
    return request.session.get("civix_user_id", fallback)


class IssueClassifyView(APIView):
    """
    POST /api/issues/classify/
    Real-time Vision AI classifier endpoint called immediately when user snaps a photo.
    Returns detected category, issue type, severity, confidence, and suggested title.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        try:
            image_bytes = None
            image_url = request.data.get("image_url")
            title_hint = request.data.get("description", "")

            if "photo" in request.FILES:
                photo_file = request.FILES["photo"]
                image_bytes = photo_file.read()

            result = classify_issue_image(
                image_bytes=image_bytes,
                image_url=image_url,
                title_hint=title_hint
            )
            return Response(result, status=status.HTTP_200_OK)
        except PyMongoError:
            return Response(
                {"error": "Report storage is temporarily unavailable. Check the MongoDB connection."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class IssueReportView(APIView):
    """
    POST /api/issues/report/
    Handles citizen report with direct camera upload + live GPS + AI vision + 50m dedup check.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        try:
            # 1. Extract GPS coordinates
            latitude = float(request.data.get("latitude", 13.0827))
            longitude = float(request.data.get("longitude", 80.2707))
            
            title = request.data.get("title", "").strip()
            description = request.data.get("description", "").strip()
            category_override = request.data.get("category", "").strip()
            severity_override = request.data.get("severity", "").strip()
            force_submit = request.data.get("force_submit", "false").lower() in ("true", "1")
            user_id = session_user_id(request, "citizen_anonymous")
            input_method = request.data.get("input_method", "text")

            # 2. Check 50m Spatial Deduplication FIRST
            if not force_submit:
                nearby = Issue.objects(
                    location__near=[longitude, latitude],
                    location__max_distance=50, # 50 meters
                    status__in=["submitted", "verified", "assigned", "in_progress"]
                )[:3]
                
                if nearby:
                    duplicate_candidates = [serialize_issue(iss) for iss in nearby]
                    return Response({
                        "duplicate_detected": True,
                        "message": f"Found {len(duplicate_candidates)} existing issue(s) within 50 meters! Would you like to upvote instead?",
                        "nearby_issues": duplicate_candidates
                    }, status=status.HTTP_200_OK)

            # 3. Handle Direct Camera Image
            photo_urls = []
            ai_data = None
            
            if "photo" in request.FILES:
                photo_file = request.FILES["photo"]
                photo_bytes = photo_file.read()
                
                # Upload directly to Supabase Storage CDN
                upload_res = upload_image_bytes(
                    file_bytes=photo_bytes,
                    filename=photo_file.name or "camera_snapshot.jpg",
                    folder="issues",
                    content_type=photo_file.content_type
                )
                photo_urls.append(upload_res["public_url"])

                # Run Vision AI Classification
                ai_data = classify_issue_image(
                    image_bytes=photo_bytes,
                    image_url=upload_res["public_url"],
                    title_hint=title or description
                )
            elif title or description:
                # Classify voice-only and text-only reports using the description.
                ai_data = classify_issue_image(title_hint=title or description)

            # Determine category and severity
            final_category = category_override or (ai_data.get("category") if ai_data else "road")
            final_severity = severity_override or (ai_data.get("severity") if ai_data else "medium")
            final_type = ai_data.get("issue_type") if ai_data else "general_complaint"
            final_title = title or (ai_data.get("suggested_title") if ai_data else "Civic Complaint")

            # Build Issue Document
            issue = Issue(
                title=final_title,
                description=description,
                reported_by=user_id,
                input_method=input_method,
                location=[longitude, latitude],
                address=request.data.get("address", "Chennai, Tamil Nadu"),
                ward=request.data.get("ward", "Zone 5 - Adyar"),
                category=final_category,
                issue_type=final_type,
                severity=final_severity,
                photo_urls=photo_urls,
                status="submitted",
            )

            if ai_data:
                issue.ai_classification = AIClassification(
                    category=ai_data.get("category", final_category),
                    issue_type=ai_data.get("issue_type", final_type),
                    severity=ai_data.get("severity", final_severity),
                    confidence=float(ai_data.get("confidence", 0.90)),
                    raw_response=ai_data.get("raw_response", {})
                )

            issue.save()

            # Award Civic Points (+20 for verified reporting)
            user = CivixUser.objects(id=user_id).first() if len(user_id) == 24 else None
            if user:
                user.add_points(20)
                user.reports_submitted += 1
                first_badge = Badge.objects(slug="first_report").first()
                if first_badge:
                    user.award_badge(first_badge)
                user.save()

            return Response({
                "success": True,
                "message": "Civic issue successfully registered!",
                "issue": serialize_issue(issue)
            }, status=status.HTTP_201_CREATED)

        except PyMongoError:
            return Response(
                {"error": "Report storage is temporarily unavailable. Check the MongoDB connection."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class HeatmapGeoJSONView(APIView):
    """GET /api/issues/heatmap/"""
    def get(self, request):
        status_filter = request.query_params.get("status")
        category_filter = request.query_params.get("category")

        query = {}
        if status_filter:
            query["status"] = status_filter
        if category_filter:
            query["category"] = category_filter

        issues = Issue.objects(**query)
        features = [issue.to_geojson_feature() for issue in issues]

        return Response({
            "type": "FeatureCollection",
            "features": features
        }, status=status.HTTP_200_OK)


class IssueListView(APIView):
    """GET /api/issues/"""
    def get(self, request):
        category = request.query_params.get("category")
        severity = request.query_params.get("severity")
        status_filter = request.query_params.get("status")
        assigned_to = request.query_params.get("assigned_to")

        query = {}
        if category:
            query["category"] = category
        if severity:
            query["severity"] = severity
        if status_filter:
            query["status"] = status_filter
        if assigned_to:
            query["assigned_to"] = assigned_to

        try:
            issues = Issue.objects(**query).order_by("-priority_score")[:50]
            return Response([serialize_issue(i) for i in issues], status=status.HTTP_200_OK)
        except PyMongoError:
            return Response(
                {"error": "Issue data is temporarily unavailable. Check the MongoDB connection."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class IssueUpvoteView(APIView):
    """POST /api/issues/<id>/upvote/"""
    def post(self, request, issue_id):
        user_id = session_user_id(request, "citizen_anon")
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)

        if user_id in (issue.upvoted_by or []):
            return Response({"message": "You have already upvoted this issue!", "upvote_count": issue.upvote_count}, status=status.HTTP_200_OK)

        issue.upvoted_by.append(user_id)
        issue.upvote_count += 1
        issue.save()

        try:
            IssueUpvote(issue_id=str(issue.id), user_id=user_id).save()
        except NotUniqueError:
            return Response({"message": "You have already upvoted this issue!", "upvote_count": issue.upvote_count}, status=status.HTTP_200_OK)

        user = CivixUser.objects(id=user_id).first() if len(user_id) == 24 else None
        if user:
            user.upvotes_given += 1
            user.save()

        return Response({
            "success": True,
            "upvote_count": issue.upvote_count,
            "new_priority_score": round(issue.priority_score, 1)
        }, status=status.HTTP_200_OK)


class IssueResolveView(APIView):
    """PATCH /api/issues/<id>/resolve/"""
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def patch(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)

        if issue.status not in ("assigned", "in_progress"):
            return Response({"error": f"Cannot resolve an issue in {issue.status} status."}, status=status.HTTP_409_CONFLICT)

        try:
            worker_lat = float(request.data["latitude"])
            worker_lng = float(request.data["longitude"])
        except (KeyError, TypeError, ValueError):
            return Response({"error": "Valid worker latitude and longitude are required."}, status=status.HTTP_400_BAD_REQUEST)
        notes = request.data.get("notes", "Work completed")
        worker_id = request.data.get("worker_id", "field_worker_1")
        if issue.assigned_to and issue.assigned_to != worker_id:
            return Response({"error": "Only the assigned worker can resolve this issue."}, status=status.HTTP_403_FORBIDDEN)

        issue_lng, issue_lat = location_coordinates(issue.location)
        dist = haversine_distance(worker_lat, worker_lng, issue_lat, issue_lng)
        geo_verified = dist <= 100.0

        photo_url = "https://xvnrvhoelkqkeltwepew.supabase.co/storage/v1/object/public/civix-uploads/issues/sample_after.png"
        if "photo" in request.FILES:
            proof_file = request.FILES["photo"]
            upload_res = upload_image_bytes(
                file_bytes=proof_file.read(),
                filename=proof_file.name or "proof_after.jpg",
                folder="resolutions",
                content_type=proof_file.content_type
            )
            photo_url = upload_res["public_url"]

        issue.resolution_proof = ResolutionProof(
            photo_url=photo_url,
            worker_location=[worker_lng, worker_lat] if worker_lng and worker_lat else None,
            geo_verified=geo_verified,
            distance_from_issue=round(dist, 1),
            notes=notes,
            submitted_at=datetime.datetime.utcnow()
        )
        issue.add_status_change(to_status="resolved", changed_by=worker_id, reason=notes)
        issue.resolved_at = datetime.datetime.utcnow()
        issue.save()

        return Response({
            "success": True,
            "message": "Proof-of-work submitted! Ticket marked as Resolved.",
            "geo_verified": geo_verified,
            "distance_meters": round(dist, 1),
            "issue": serialize_issue(issue)
        }, status=status.HTTP_200_OK)


class IssueVerifyView(APIView):
    """POST /api/issues/<id>/verify/"""
    def post(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        if issue.status != "resolved":
            return Response({"error": "Only resolved issues can be verified."}, status=status.HTTP_409_CONFLICT)

        is_fixed = request.data.get("is_fixed", True)
        if isinstance(is_fixed, str):
            is_fixed = is_fixed.lower() in ("true", "1", "yes")

        user_id = session_user_id(request, "citizen_verifier")
        comment = request.data.get("comment", "")

        try:
            IssueVerification(
                issue_id=str(issue.id),
                user_id=user_id,
                is_fixed=is_fixed,
                comment=comment
            ).save()
        except NotUniqueError:
            return Response({"error": "You have already verified this issue."}, status=status.HTTP_409_CONFLICT)

        user = CivixUser.objects(id=user_id).first() if len(user_id) == 24 else None
        if user:
            user.verifications_done += 1
            user.save()

        if is_fixed:
            issue.add_status_change(to_status="citizen_verified", changed_by=user_id, reason="Citizen verified fix")
        else:
            issue.add_status_change(to_status="reopened", changed_by=user_id, reason=f"Citizen rejected fix: {comment}")
            issue.priority_score += 150

        issue.save()

        return Response({
            "success": True,
            "status": issue.status,
            "message": "Thank you for verifying your neighborhood repair!"
        }, status=status.HTTP_200_OK)


class IssueAssignView(APIView):
    """PATCH /api/issues/<id>/assign/"""
    def patch(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)

        worker_id = request.data.get("worker_id", "")
        officer_id = session_user_id(request, "officer_admin")

        issue.assigned_to = worker_id
        issue.assigned_at = datetime.datetime.utcnow()
        issue.add_status_change(to_status="assigned", changed_by=officer_id, reason=f"Assigned to worker {worker_id}")
        issue.save()

        return Response({
            "success": True,
            "assigned_to": issue.assigned_to,
            "status": issue.status
        }, status=status.HTTP_200_OK)


class IssueStatusView(APIView):
    """PATCH /api/issues/<issue_id>/status/ for worker workflow transitions."""
    allowed_transitions = {
        "assigned": {"in_progress"},
        "in_progress": {"resolved"},
        "submitted": {"verified", "assigned"},
        "verified": {"assigned"},
        "reopened": {"assigned"},
        "escalated": {"assigned"},
        "citizen_verified": {"closed"},
    }

    def patch(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        next_status = request.data.get("status", "").strip()
        if next_status not in self.allowed_transitions.get(issue.status, set()):
            return Response({"error": f"Cannot move issue from {issue.status} to {next_status}."}, status=status.HTTP_400_BAD_REQUEST)
        issue.add_status_change(
            to_status=next_status,
            changed_by=request.data.get("changed_by", "field_worker"),
            reason=request.data.get("reason", "Workflow status updated"),
        )
        issue.save()
        return Response({"success": True, "status": issue.status, "issue": serialize_issue(issue)}, status=status.HTTP_200_OK)


def _department_category(department):
    return {
        "roads": "road", "road": "road", "sanitation": "waste", "waste": "waste",
        "electrical": "electricity", "electricity": "electricity", "water": "water",
        "drainage": "drainage", "public_safety": "public_safety",
    }.get((department or "").lower())


class MyReportsView(IssueListView):
    def get(self, request):
        user_id = request.query_params.get("user_id", "citizen_anonymous")
        return Response([serialize_issue(i) for i in Issue.objects(reported_by=user_id).order_by("-created_at")[:50]])


class NearbyIssuesView(IssueListView):
    def get(self, request):
        try:
            latitude = float(request.query_params.get("latitude", 13.0067))
            longitude = float(request.query_params.get("longitude", 80.2574))
            issues = Issue.objects(location__near=[longitude, latitude], location__max_distance=50, status__nin=["closed"])
            return Response([serialize_issue(i) for i in issues[:50]])
        except PyMongoError:
            return Response({"error": "Issue data is temporarily unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class TaskAssignedView(IssueListView):
    def get(self, request):
        query = {"assigned_to": session_user_id(request, request.query_params.get("worker_id", ""))}
        category = _department_category(request.query_params.get("department_id") or request.query_params.get("department"))
        if category:
            query["category"] = category
        return Response([serialize_issue(i) for i in Issue.objects(**query).order_by("-priority_score")[:50]])


class IssueDetailsView(APIView):
    def get(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        return Response(serialize_issue(issue), status=status.HTTP_200_OK) if issue else Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)


class IssueProofView(IssueResolveView):
    def post(self, request, issue_id):
        return self.patch(request, issue_id)


class DepartmentMasterView(IssueListView):
    def get(self, request):
        category = _department_category(request.query_params.get("department_id") or request.query_params.get("department"))
        query = {"category": category} if category else {}
        return Response([serialize_issue(i) for i in Issue.objects(**query).order_by("-priority_score")[:50]])


class SLABreachesView(IssueListView):
    def get(self, request):
        now = datetime.datetime.utcnow()
        issues = Issue.objects(sla_deadline__lte=now, status__nin=["resolved", "citizen_verified", "closed"])
        return Response([serialize_issue(i) for i in issues[:100]])


class OverrideDepartmentView(APIView):
    def post(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        category = request.data.get("category", "").strip()
        if category not in ["road", "water", "waste", "electricity", "drainage", "public_safety", "environment", "other"]:
            return Response({"error": "Invalid department category"}, status=status.HTTP_400_BAD_REQUEST)
        issue.category = category
        issue.save()
        return Response({"success": True, "category": issue.category})


class EscalateIssueView(APIView):
    def patch(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        old_level = issue.escalation_level
        issue.escalation_level = min(3, old_level + 1)
        issue.add_status_change(to_status="escalated", changed_by=request.data.get("changed_by", "officer"), reason="Manual SLA escalation")
        issue.save()
        EscalationLog(issue_id=str(issue.id), from_level=old_level, to_level=issue.escalation_level, reason="manual_escalation").save()
        return Response({"success": True, "escalation_level": issue.escalation_level, "status": issue.status})


class DeleteIssueView(APIView):
    def delete(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        issue.delete()
        return Response({"success": True, "deleted": issue_id})
