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
import hashlib
from bson import ObjectId
from pymongo.errors import PyMongoError
from rest_framework import status, serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from mongoengine.errors import NotUniqueError

from issues.models import Issue, AIClassification, ResolutionProof, StatusChange, IssueUpvote, IssueVerification, EscalationLog, EmergencyDispatch, VolunteerDrive
from users.models import Badge, CivixUser, AdminAuditLog, Notification
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
            "source": (issue.ai_classification.raw_response or {}).get("cloud", "Unknown"),
        } if issue.ai_classification else None,
        "resolution_proof": {
            "photo_url": issue.resolution_proof.photo_url,
            "geo_verified": issue.resolution_proof.geo_verified,
            "distance_from_issue": issue.resolution_proof.distance_from_issue,
            "submitted_at": issue.resolution_proof.submitted_at.isoformat() if issue.resolution_proof.submitted_at else None,
            "notes": issue.resolution_proof.notes or "",
        } if issue.resolution_proof else None,
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
            if request.data.get("latitude") in (None, "") or request.data.get("longitude") in (None, ""):
                return Response({"error": "Current latitude and longitude are required."}, status=status.HTTP_400_BAD_REQUEST)
            latitude = float(request.data["latitude"])
            longitude = float(request.data["longitude"])
            
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
            photo_hash = None
            
            if "photo" in request.FILES:
                photo_file = request.FILES["photo"]
                photo_bytes = photo_file.read()
                photo_hash = hashlib.sha256(photo_bytes).hexdigest()

                if not force_submit:
                    matching_issue = Issue.objects(
                        photo_hash=photo_hash,
                        status__in=["submitted", "verified", "assigned", "in_progress", "resolved", "reopened", "escalated"],
                    ).first()
                    if matching_issue:
                        return Response({
                            "duplicate_detected": True,
                            "duplicate_type": "photo",
                            "message": "This photo was already used for an existing issue. Would you like to upvote it instead?",
                            "nearby_issues": [serialize_issue(matching_issue)],
                        }, status=status.HTTP_200_OK)
                
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
                photo_hash=photo_hash,
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
            matching_workers = [
                worker for worker in CivixUser.objects(role="field_worker", is_active=True)
                if (not worker.zone or worker.zone == issue.ward)
                and (not worker.department or _department_category(worker.department) in (None, issue.category))
            ]
            if matching_workers:
                worker = matching_workers[0]
                issue.assigned_to = str(worker.id)
                issue.assigned_at = datetime.datetime.utcnow()
                issue.add_status_change(to_status="assigned", changed_by="automatic-routing", reason="Automatically routed by category and zone")
                issue.save()
                Notification(
                    user_id=str(worker.id), title="New task assigned", title_ta="புதிய பணி ஒதுக்கப்பட்டது",
                    message=f"{issue.title} was automatically routed to you.",
                    message_ta=f"{issue.title} தானாக உங்களுக்கு ஒதுக்கப்பட்டது.",
                    notification_type="assignment", related_issue_id=str(issue.id)
                ).save()

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
        if request.session.get("civix_role") == "zone_officer":
            officer = CivixUser.objects(id=request.session.get("civix_user_id")).first()
            if officer and officer.zone:
                query["ward"] = officer.zone

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
        session_id = session_user_id(request, "")
        worker = CivixUser.objects(id=session_id).first() if len(session_id) == 24 else None
        if not worker or worker.role != "field_worker":
            return Response({"error": "A valid field worker session is required."}, status=status.HTTP_403_FORBIDDEN)
        valid_worker_ids = {session_id, worker.full_name, worker.phone}
        if not issue.assigned_to or issue.assigned_to not in valid_worker_ids:
            return Response({"error": "Only the assigned worker can resolve this issue."}, status=status.HTTP_403_FORBIDDEN)
        worker_id = session_id

        issue_lng, issue_lat = location_coordinates(issue.location)
        dist = haversine_distance(worker_lat, worker_lng, issue_lat, issue_lng)
        geo_verified = dist <= 100.0
        if not geo_verified:
            return Response({"error": "Worker must be within 100 meters of the issue."}, status=status.HTTP_403_FORBIDDEN)

        if "photo" not in request.FILES:
            return Response({"error": "An after photo is required."}, status=status.HTTP_400_BAD_REQUEST)
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
        Notification(
            user_id=issue.reported_by,
            title="Your issue was resolved", title_ta="உங்கள் புகார் தீர்க்கப்பட்டது",
            message=f"Proof of work was submitted for: {issue.title}",
            message_ta=f"இதற்கான பணி சான்று சமர்ப்பிக்கப்பட்டது: {issue.title}",
            notification_type="resolution", related_issue_id=str(issue.id)
        ).save()

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
            Notification(
                user_id=issue.assigned_to,
                title="Citizen verified the repair", title_ta="குடிமகன் பழுதுபார்ப்பை சரிபார்த்தார்",
                message=f"The citizen verified: {issue.title}",
                message_ta=f"குடிமகன் சரிபார்த்த புகார்: {issue.title}",
                notification_type="verification", related_issue_id=str(issue.id)
            ).save()
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
        worker = CivixUser.objects(phone=worker_id).first() or CivixUser.objects(full_name=worker_id).first()
        if not worker or worker.role != "field_worker":
            return Response({"error": "A valid field worker must be selected."}, status=status.HTTP_400_BAD_REQUEST)
        officer = CivixUser.objects(id=officer_id).first() if len(officer_id) == 24 else None
        if officer and officer.role == "zone_officer" and officer.zone and issue.ward != officer.zone:
            return Response({"error": "You can only assign issues in your zone."}, status=status.HTTP_403_FORBIDDEN)
        if officer and officer.role == "zone_officer" and worker.zone != officer.zone:
            return Response({"error": "You can only assign workers in your zone."}, status=status.HTTP_403_FORBIDDEN)
        if worker.department and _department_category(worker.department) not in (None, issue.category):
            return Response({"error": "Worker department does not match this issue."}, status=status.HTTP_403_FORBIDDEN)

        issue.assigned_to = worker_id
        issue.assigned_at = datetime.datetime.utcnow()
        issue.add_status_change(to_status="assigned", changed_by=officer_id, reason=f"Assigned to worker {worker_id}")
        issue.save()
        Notification(
            user_id=str(worker.id), title="New task assigned", title_ta="புதிய பணி ஒதுக்கப்பட்டது",
            message=f"{issue.title} has been assigned to you.",
            message_ta=f"{issue.title} உங்களுக்கு ஒதுக்கப்பட்டுள்ளது.",
            notification_type="assignment", related_issue_id=str(issue.id)
        ).save()

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
        worker = CivixUser.objects(id=session_user_id(request, "")).first()
        if not worker or worker.role != "field_worker" or issue.assigned_to not in {str(worker.id), worker.full_name, worker.phone}:
            return Response({"error": "Only the assigned worker can update this issue."}, status=status.HTTP_403_FORBIDDEN)
        next_status = request.data.get("status", "").strip()
        if next_status not in self.allowed_transitions.get(issue.status, set()):
            return Response({"error": f"Cannot move issue from {issue.status} to {next_status}."}, status=status.HTTP_400_BAD_REQUEST)
        issue.add_status_change(
            to_status=next_status,
            changed_by=str(worker.id),
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
        user_id = request.session.get("civix_user_id")
        if not user_id:
            return Response({"error": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)
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
        user_id = session_user_id(request, request.query_params.get("worker_id", ""))
        worker = CivixUser.objects(id=user_id).first() if len(user_id) == 24 else None
        if not worker or worker.role != "field_worker":
            return Response({"error": "A valid field worker session is required."}, status=status.HTTP_403_FORBIDDEN)
        assigned_values = [user_id]
        assigned_values.extend([worker.full_name, worker.phone])
        query = {"assigned_to__in": assigned_values}
        category = _department_category(worker.department)
        if category:
            query["category"] = category
        if worker.zone:
            query["ward"] = worker.zone
        return Response([serialize_issue(i) for i in Issue.objects(**query).order_by("-priority_score")[:50]])


class IssueDetailsView(APIView):
    def get(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        worker = CivixUser.objects(id=session_user_id(request, "")).first()
        if worker and worker.role == "field_worker" and issue and issue.assigned_to not in {str(worker.id), worker.full_name, worker.phone}:
            return Response({"error": "You can only view your assigned issues."}, status=status.HTTP_403_FORBIDDEN)
        return Response(serialize_issue(issue), status=status.HTTP_200_OK) if issue else Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)


class IssueProofView(IssueResolveView):
    def post(self, request, issue_id):
        return self.patch(request, issue_id)


class DepartmentMasterView(IssueListView):
    def get(self, request):
        category = _department_category(request.query_params.get("department_id") or request.query_params.get("department"))
        query = {"category": category} if category else {}
        officer = CivixUser.objects(id=request.session.get("civix_user_id")).first()
        if officer and officer.role == "zone_officer" and officer.zone:
            query["ward"] = officer.zone
        return Response([serialize_issue(i) for i in Issue.objects(**query).order_by("-priority_score")[:50]])


class SLABreachesView(IssueListView):
    def get(self, request):
        now = datetime.datetime.utcnow()
        issues = Issue.objects(sla_deadline__lte=now, status__nin=["resolved", "citizen_verified", "closed"])
        officer = CivixUser.objects(id=request.session.get("civix_user_id")).first()
        if officer and officer.role == "zone_officer" and officer.zone:
            issues = issues.filter(ward=officer.zone)
        escalated = []
        for issue in issues[:100]:
            was_breached = issue.sla_breached
            issue.check_sla_breach()
            if issue.sla_breached and not was_breached:
                issue.escalation_level = min(3, issue.escalation_level + 1)
                issue.add_status_change(to_status="escalated", changed_by="sla-monitor", reason="Automatic SLA breach escalation")
                issue.save()
                escalated.append(issue)
                for recipient in CivixUser.objects(role__in=["officer", "zone_officer", "admin"], is_active=True):
                    Notification(
                        user_id=str(recipient.id), title="SLA breached", title_ta="SLA மீறப்பட்டது",
                        message=f"Immediate attention required: {issue.title}",
                        message_ta=f"உடனடி கவனம் தேவை: {issue.title}",
                        notification_type="sla", related_issue_id=str(issue.id)
                    ).save()
            elif issue.sla_breached and issue.status != "escalated":
                issue.add_status_change(to_status="escalated", changed_by="sla-monitor", reason="Automatic SLA breach escalation")
                issue.save()
        return Response([serialize_issue(i) for i in issues[:100]])


class OverrideDepartmentView(APIView):
    def post(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        officer = CivixUser.objects(id=request.session.get("civix_user_id")).first()
        if officer and officer.role == "zone_officer" and officer.zone and issue.ward != officer.zone:
            return Response({"error": "You can only modify issues in your zone."}, status=status.HTTP_403_FORBIDDEN)
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
        officer = CivixUser.objects(id=request.session.get("civix_user_id")).first()
        if officer and officer.role == "zone_officer" and officer.zone and issue.ward != officer.zone:
            return Response({"error": "You can only escalate issues in your zone."}, status=status.HTTP_403_FORBIDDEN)
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
        if issue.status != "resolved":
            return Response({"error": "Only resolved issues can be deleted from the officer dashboard."}, status=status.HTTP_403_FORBIDDEN)
        issue.delete()
        AdminAuditLog(actor_id=session_user_id(request, "unknown"), action="delete_resolved_issue", target_id=issue_id, details={"status": "resolved"}).save()
        return Response({"success": True, "deleted": issue_id})


class EmergencyDispatchView(APIView):
    """POST /api/emergency-dispatch/ - bypass normal queue for life threats."""
    def post(self, request):
        user_id = session_user_id(request, "citizen_anonymous")
        try:
            latitude = float(request.data["latitude"])
            longitude = float(request.data["longitude"])
        except (KeyError, TypeError, ValueError):
            return Response({"error": "Valid emergency latitude and longitude are required."}, status=status.HTTP_400_BAD_REQUEST)

        emergency_type = request.data.get("emergency_type", "Life-threatening civic emergency").strip()
        description = request.data.get("description", "").strip()
        issue = Issue(
            title=f"EMERGENCY: {emergency_type}", description=description, reported_by=user_id,
            input_method="text", location=[longitude, latitude], category="public_safety",
            issue_type="emergency", severity="critical", status="escalated",
        )
        issue.save()
        dispatch = EmergencyDispatch(
            issue_id=str(issue.id), reported_by=user_id, emergency_type=emergency_type,
            location=[longitude, latitude], description=description,
        )
        dispatch.save()
        for recipient in CivixUser.objects(role__in=["officer", "zone_officer", "admin"], is_active=True):
            Notification(
                user_id=str(recipient.id), title="Emergency dispatch", message=f"{emergency_type}: {description}",
                notification_type="emergency", related_issue_id=str(issue.id),
            ).save()
        return Response({"success": True, "message": "Emergency dispatch alerted immediately.", "issue_id": str(issue.id), "dispatch_id": str(dispatch.id)}, status=status.HTTP_201_CREATED)


class VolunteerDriveView(APIView):
    """POST/GET /api/volunteer-drives/ for officer or highly active citizen planning."""
    def get(self, request):
        def drive_location(drive):
            coordinates = location_coordinates(drive.location)
            return {"longitude": coordinates[0], "latitude": coordinates[1]}

        return Response([{
            "id": str(drive.id), "title": drive.title, "description": drive.description or "",
            "organizer_id": drive.organizer_id, "zone": drive.zone,
            "location": drive_location(drive),
            "scheduled_at": drive.scheduled_at.isoformat(), "status": drive.status,
        } for drive in VolunteerDrive.objects(status__nin=["cancelled"]).order_by("scheduled_at")[:100]])

    def post(self, request):
        organizer_id = session_user_id(request, "")
        role = request.session.get("civix_role", "")
        if role not in {"officer", "zone_officer", "admin", "citizen"}:
            return Response({"error": "You are not allowed to organize volunteer drives."}, status=status.HTTP_403_FORBIDDEN)
        if role == "citizen":
            organizer = CivixUser.objects(id=organizer_id).first() if len(organizer_id) == 24 else None
            if not organizer or organizer.civic_points < 500:
                return Response({"error": "At least 500 civic points are required to organize a drive."}, status=status.HTTP_403_FORBIDDEN)
        try:
            latitude = float(request.data["latitude"])
            longitude = float(request.data["longitude"])
            scheduled_at = datetime.datetime.fromisoformat(request.data["scheduled_at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            return Response({"error": "Valid location and scheduled_at are required."}, status=status.HTTP_400_BAD_REQUEST)
        drive = VolunteerDrive(
            title=request.data.get("title", "Neighborhood civic drive").strip(),
            description=request.data.get("description", "").strip(), organizer_id=organizer_id,
            organizer_role=role, zone=request.data.get("zone", "").strip(), location=[longitude, latitude],
            scheduled_at=scheduled_at,
        )
        drive.save()
        return Response({"success": True, "drive_id": str(drive.id)}, status=status.HTTP_201_CREATED)
