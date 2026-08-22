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
from rest_framework import status, serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from issues.models import Issue, AIClassification, ResolutionProof, StatusChange, IssueUpvote, IssueVerification
from users.models import CivixUser
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


def serialize_issue(issue):
    """Convert MongoEngine Issue document to JSON-friendly dict."""
    return {
        "id": str(issue.id),
        "title": issue.title,
        "description": issue.description or "",
        "category": issue.category,
        "issue_type": issue.issue_type or "",
        "severity": issue.severity,
        "status": issue.status,
        "location": {
            "longitude": issue.location["coordinates"][0],
            "latitude": issue.location["coordinates"][1],
            "coordinates": issue.location["coordinates"],
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
    }


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
            user_id = request.data.get("user_id", "citizen_anonymous")
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
                user.save()

            return Response({
                "success": True,
                "message": "Civic issue successfully registered!",
                "issue": serialize_issue(issue)
            }, status=status.HTTP_201_CREATED)

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

        issues = Issue.objects(**query).order_by("-priority_score")[:50]
        return Response([serialize_issue(i) for i in issues], status=status.HTTP_200_OK)


class IssueUpvoteView(APIView):
    """POST /api/issues/<id>/upvote/"""
    def post(self, request, issue_id):
        user_id = request.data.get("user_id", "citizen_anon")
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)

        if user_id in issue.upvoted_by:
            return Response({"message": "You have already upvoted this issue!", "upvote_count": issue.upvote_count}, status=status.HTTP_200_OK)

        issue.upvoted_by.append(user_id)
        issue.upvote_count += 1
        issue.save()

        try:
            IssueUpvote(issue_id=str(issue.id), user_id=user_id).save()
        except Exception:
            pass

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

        worker_lat = float(request.data.get("latitude", 0.0))
        worker_lng = float(request.data.get("longitude", 0.0))
        notes = request.data.get("notes", "Work completed")
        worker_id = request.data.get("worker_id", "field_worker_1")

        issue_lng, issue_lat = issue.location["coordinates"]
        dist = haversine_distance(worker_lat, worker_lng, issue_lat, issue_lng) if worker_lat and worker_lng else 0.0
        geo_verified = dist <= 100.0 or (worker_lat == 0.0)

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

        is_fixed = request.data.get("is_fixed", True)
        if isinstance(is_fixed, str):
            is_fixed = is_fixed.lower() in ("true", "1", "yes")

        user_id = request.data.get("user_id", "citizen_verifier")
        comment = request.data.get("comment", "")

        try:
            IssueVerification(
                issue_id=str(issue.id),
                user_id=user_id,
                is_fixed=is_fixed,
                comment=comment
            ).save()
        except Exception:
            pass

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
        officer_id = request.data.get("officer_id", "officer_admin")

        issue.assigned_to = worker_id
        issue.assigned_at = datetime.datetime.utcnow()
        issue.add_status_change(to_status="assigned", changed_by=officer_id, reason=f"Assigned to worker {worker_id}")
        issue.save()

        return Response({
            "success": True,
            "assigned_to": issue.assigned_to,
            "status": issue.status
        }, status=status.HTTP_200_OK)
