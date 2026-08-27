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
from bson.errors import InvalidId
from pymongo.errors import PyMongoError
from rest_framework import status, serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from mongoengine.errors import NotUniqueError, ValidationError
from mongoengine.queryset.visitor import Q
from django.conf import settings
from django.utils import timezone

# (No dev-mode demo fallbacks — rely on real MongoDB for data integrity.)

from issues.models import Issue, AIClassification, ResolutionProof, StatusChange, IssueUpvote, IssueVerification, EscalationLog, EmergencyDispatch, VolunteerDrive, WorkerRating, category_priority_value
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


def user_has_upvoted(issue, user_id):
    """Return True when a citizen has already upvoted this issue."""
    if not user_id:
        return False
    upvoted_by = list(issue.upvoted_by or [])
    return user_id in upvoted_by


def session_user_id(request, fallback="anonymous"):
    return request.session.get("civix_user_id", fallback)


def include_priority_for(request):
    return request.session.get("civix_role") in {"officer", "zone_officer", "admin", "field_worker"}


def session_user(request):
    user_id = request.session.get("civix_user_id")
    if user_id and len(str(user_id)) == 24:
        user = CivixUser.objects(id=user_id).first()
        if user:
            return user
    return None


def worker_quality_payload(worker):
    if not worker:
        return {"average": 0, "count": 0}
    return {
        "average": worker.average_rating,
        "count": worker.rating_count or 0,
        "name": worker.full_name,
    }


def serialize_issue(issue, user_id=None, include_priority=False):
    """Convert MongoEngine Issue document to JSON-friendly dict."""
    coordinates = location_coordinates(issue.location)
    overdue = overdue_issue_details(issue)
    stalled = stalled_issue_details(issue)
    proof = issue.resolution_proof
    resolved_worker = None
    if proof and proof.worker_id:
        try:
            resolved_worker = CivixUser.objects(id=proof.worker_id).first()
        except (TypeError, ValueError, ValidationError, InvalidId):
            resolved_worker = None
        if not resolved_worker:
            resolved_worker = CivixUser.objects(full_name=proof.worker_id).first()
    started_at = issue.started_at
    if not started_at:
        started_change = next((change for change in (issue.status_history or []) if change.to_status == "in_progress"), None)
        started_at = started_change.changed_at if started_change else None
    worker_coords = None
    if proof and proof.worker_location:
        worker_coords = location_coordinates(proof.worker_location)
    completion_distance = proof.distance_from_issue if proof else None
    location_warning = completion_distance is not None and completion_distance > 50
    already_voted = user_has_upvoted(issue, user_id)
    payload = {
        "id": str(issue.id),
        "title": issue.title,
        "description": issue.description or "",
        "category": issue.category,
        "issue_type": issue.issue_type or "",
        "severity": issue.severity,
        "officer_priority": issue.officer_priority,
        "officer_decision": issue.officer_decision or "",
        "assigned_officer": issue.assigned_officer or "",
        "status": issue.status,
        "status_label": issue_status_label(issue.status),
        "public_status": public_status_lifecycle(issue.status),
        "location": {
            "longitude": coordinates[0],
            "latitude": coordinates[1],
            "coordinates": coordinates,
        },
        "location_verification": {
            "original_report": {"latitude": coordinates[1], "longitude": coordinates[0]},
            "completion": {"latitude": worker_coords[1], "longitude": worker_coords[0]} if worker_coords else None,
            "distance_meters": completion_distance,
            "warning": location_warning,
            "supporting_evidence_only": True,
        },
        "address": issue.address or "",
        "ward": issue.ward or "",
        "upvote_count": issue.upvote_count,
        "already_voted": already_voted,
        "photo_urls": issue.photo_urls or [],
        "ai_classification": {
            "category": issue.ai_classification.category,
            "issue_type": issue.ai_classification.issue_type,
            "severity": issue.ai_classification.severity,
            "confidence": issue.ai_classification.confidence,
            "source": (issue.ai_classification.raw_response or {}).get("cloud", "Unknown"),
        } if issue.ai_classification else None,
        "resolution_proof": {
            "photo_url": proof.photo_url,
            "worker_id": proof.worker_id,
            "ticket_id": proof.ticket_id,
            "verification_status": proof.verification_status or ("accepted" if issue.status in {"resolved", "citizen_verified", "closed"} else "pending"),
            "worker_location": {
                "longitude": worker_coords[0],
                "latitude": worker_coords[1],
                "coordinates": worker_coords,
            } if worker_coords else None,
            "geo_verified": proof.geo_verified,
            "distance_from_issue": proof.distance_from_issue,
            "submitted_at": proof.submitted_at.isoformat() if proof and proof.submitted_at else None,
            "notes": proof.notes or "",
        } if proof else None,
        "assigned_to": issue.assigned_to or "",
        "resolved_by_name": resolved_worker.full_name if resolved_worker else (proof.worker_id if proof and proof.worker_id else issue.assigned_to or ""),
        "assigned_at": issue.assigned_at.isoformat() if issue.assigned_at else None,
        "started_at": started_at.isoformat() if started_at else None,
        "sla_deadline": issue.sla_deadline.isoformat() if issue.sla_deadline else None,
        "sla_breached": issue.sla_breached,
        "is_overdue": overdue["is_overdue"],
        "pending_days": overdue["pending_days"],
        "is_stalled": stalled["is_stalled"],
        "stalled_days": stalled["pending_days"],
        "stalled_reason": stalled["reason"],
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
    rated = None
    if user_id:
        rating = WorkerRating.objects(issue_id=str(issue.id), user_id=user_id).first()
        if rating:
            rated = rating.stars
    worker_for_quality = resolved_worker
    if not worker_for_quality and issue.assigned_to:
        try:
            worker_for_quality = CivixUser.objects(id=issue.assigned_to).first()
        except Exception:
            worker_for_quality = CivixUser.objects(full_name=issue.assigned_to).first()
    payload["worker_quality"] = worker_quality_payload(worker_for_quality)
    payload["citizen_worker_rating"] = rated
    if include_priority:
        payload["priority_score"] = round(issue.priority_score or 0, 1)
        payload["category_priority_points"] = category_priority_value(issue.category)
    else:
        payload.pop("priority_score", None)
        payload.pop("officer_priority", None)
    return payload


def issue_status_label(status):
    return {
        "submitted": "Reported",
        "verified": "Verified",
        "dismissed": "Dismissed",
        "assigned": "Assigned",
        "in_progress": "Work in Progress",
        "awaiting_verification": "Awaiting Verification",
        "resolved": "Resolved",
        "citizen_verified": "Resolved",
        "reopened": "Reopened",
        "escalated": "Escalated",
        "closed": "Closed",
    }.get(status, "Updated")


def public_status_lifecycle(current_status):
    """Return the civic-facing lifecycle across backend status values."""
    ordered = [
        {"key": "reported", "label": "Reported"},
        {"key": "verified", "label": "Verified"},
        {"key": "assigned", "label": "Assigned"},
        {"key": "in_progress", "label": "Work in Progress"},
        {"key": "resolved", "label": "Resolved"},
    ]
    alias_map = {
        "submitted": "reported",
        "verified": "verified",
        "assigned": "assigned",
        "in_progress": "in_progress",
        "awaiting_verification": "in_progress",
        "resolved": "resolved",
        "citizen_verified": "resolved",
        "closed": "resolved",
    }
    normalized = alias_map.get(current_status, "reported")
    steps = []
    for stage in ordered:
        stage_key = stage["key"]
        complete = ordered.index(stage) < ordered.index(next((step for step in ordered if step["key"] == normalized), ordered[0]))
        active = stage_key == normalized
        steps.append({
            "key": stage_key,
            "label": stage["label"],
            "active": active,
            "complete": complete,
        })
    return steps


def overdue_issue_details(issue):
    if not issue or not issue.created_at or issue.status in {"resolved", "citizen_verified", "closed", "dismissed"}:
        return {"is_overdue": False, "pending_days": 0.0}
    delta = datetime.datetime.utcnow() - issue.created_at
    pending_days = delta.total_seconds() / 86400
    overdue = (
        pending_days >= 12
        and (issue.status in {"submitted", "verified"} or not issue.assigned_to or issue.officer_decision is None)
    )
    return {"is_overdue": overdue, "pending_days": round(pending_days, 1)}


def stalled_issue_details(issue):
    """Return stage-aware five-day inactivity details for officer follow-up."""
    if not issue or issue.status in {"dismissed", "resolved", "citizen_verified", "closed"}:
        return {"is_stalled": False, "pending_days": 0.0, "reason": ""}
    if issue.status in {"submitted", "verified"} and not issue.assigned_to:
        reference_time, reason = issue.created_at, "This ticket has been unassigned"
    elif issue.status == "assigned" and not issue.started_at:
        reference_time, reason = issue.assigned_at or issue.created_at, "This ticket has had no work progress"
    elif issue.status == "in_progress":
        reference_time, reason = issue.started_at or issue.created_at, "This ticket has been in progress"
    else:
        return {"is_stalled": False, "pending_days": 0.0, "reason": ""}
    pending_days = max(0.0, (datetime.datetime.utcnow() - reference_time).total_seconds() / 86400) if reference_time else 0.0
    return {"is_stalled": pending_days >= 5, "pending_days": round(pending_days, 1), "reason": reason}


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
            requested_category = request.data.get("category", "").strip().lower()

            if "photo" in request.FILES:
                photo_file = request.FILES["photo"]
                image_bytes = photo_file.read()

            result = classify_issue_image(
                image_bytes=image_bytes,
                image_url=image_url,
                title_hint=title_hint,
                requested_category=requested_category,
            )
            return Response(result, status=status.HTTP_200_OK if result.get("accepted", True) else status.HTTP_422_UNPROCESSABLE_ENTITY)
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
            force_submit = str(request.data.get("force_submit", "false")).lower() in ("true", "1")
            user = session_user(request)
            user_id = str(user.id) if user else session_user_id(request, "citizen_anonymous")
            input_method = request.data.get("input_method", "text")

            # 2. Check 50m Spatial Deduplication FIRST
            if not force_submit:
                nearby_query = {
                    "location__near": [longitude, latitude],
                    "location__max_distance": 50,
                    "status__in": ["submitted", "verified", "assigned", "in_progress", "reopened", "escalated"],
                }
                if category_override:
                    nearby_query["category"] = category_override
                nearby = Issue.objects(**nearby_query)[:3]
                
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
                if not photo_bytes or not (photo_file.content_type or "").startswith("image/"):
                    return Response({"error": "Please capture or upload a valid image."}, status=status.HTTP_400_BAD_REQUEST)
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
                
                upload_res = upload_image_bytes(
                    file_bytes=photo_bytes,
                    filename=photo_file.name or "camera_snapshot.jpg",
                    folder="issues",
                    content_type=photo_file.content_type
                )
                photo_urls.append(upload_res["public_url"])
            # Determine category and severity
            final_category = category_override or "other"
            final_severity = severity_override or "medium"
            final_type = "general_complaint"
            final_title = title or "Civic Complaint"

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

            issue.save()

            # Award Civic Points for reporting
            if user:
                user.add_points(getattr(settings, "REPORT_CIVIC_POINTS", 20))
                user.reports_submitted = (user.reports_submitted or 0) + 1
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
        user_id = session_user_id(request, "")
        category = request.query_params.get("category")
        severity = request.query_params.get("severity")
        status_filter = request.query_params.get("status")
        assigned_to = request.query_params.get("assigned_to")
        selected_date = request.query_params.get("date", "").strip()
        workflow = request.query_params.get("workflow", "").strip()
        date_filter = None

        query = {}
        if category:
            query["category"] = category
        if severity:
            query["severity"] = severity
        if status_filter:
            query["status"] = status_filter
        if assigned_to:
            query["assigned_to"] = assigned_to
        if selected_date:
            try:
                ticket_date = datetime.date.fromisoformat(selected_date)
            except ValueError:
                return Response({"error": "Date must use YYYY-MM-DD format."}, status=status.HTTP_400_BAD_REQUEST)
            local_zone = timezone.get_current_timezone()
            local_start = timezone.make_aware(datetime.datetime.combine(ticket_date, datetime.time.min), local_zone)
            local_end = local_start + datetime.timedelta(days=1)
            start = local_start.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            end = local_end.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            if workflow == "assigned":
                query["assigned_at__gte"] = start
                query["assigned_at__lt"] = end
            elif workflow == "completed":
                date_filter = Q(resolution_proof__submitted_at__gte=start, resolution_proof__submitted_at__lt=end) | Q(resolved_at__gte=start, resolved_at__lt=end)
            else:
                query["created_at__gte"] = start
                query["created_at__lt"] = end
        if workflow == "not_assigned":
            query["status__in"] = ["submitted", "verified"]
            query["assigned_to__in"] = [None, ""]
        elif workflow == "assigned":
            query["assigned_to__exists"] = True
            query["status__in"] = ["assigned", "in_progress", "awaiting_verification", "reopened", "escalated"]
        elif workflow == "completed":
            query["status__in"] = ["awaiting_verification", "resolved", "citizen_verified", "closed"]
        if request.session.get("civix_role") == "citizen":
            query["status__nin"] = ["dismissed"]
        if request.session.get("civix_role") == "zone_officer":
            officer = CivixUser.objects(id=request.session.get("civix_user_id")).first()
            if officer and officer.zone:
                query["ward"] = officer.zone

        try:
            issue_query = Issue.objects(**query)
            if date_filter is not None:
                issue_query = issue_query.filter(date_filter)
            if workflow in {"not_assigned", "assigned", "completed"}:
                severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
                issues = list(issue_query)
                issues.sort(key=lambda issue: (-severity_rank.get(issue.severity, 0), -(issue.priority_score or 0), -(issue.created_at.timestamp() if issue.created_at else 0)))
                issues = issues[:50]
            else:
                issues = issue_query.order_by("-priority_score")[:50]
            officer_ids = [str(user.id) for user in CivixUser.objects(role__in=["officer", "zone_officer", "admin"], is_active=True)]
            for issue in issues:
                details = overdue_issue_details(issue)
                if details["is_overdue"]:
                    for officer_id in officer_ids:
                        if not Notification.objects(user_id=officer_id, related_issue_id=str(issue.id), notification_type="overdue").first():
                            Notification(
                                user_id=officer_id,
                                title="Ticket overdue — action required",
                                title_ta="புகார் காலாவதியானது — நடவடிக்கை தேவை",
                                message=f"{issue.title}: Pending for {details['pending_days']} days - Action Required.",
                                message_ta=f"{issue.title}: {details['pending_days']} நாட்கள் நிலுவை - நடவடிக்கை தேவை.",
                                notification_type="overdue",
                                related_issue_id=str(issue.id),
                            ).save()
                stalled = stalled_issue_details(issue)
                if stalled["is_stalled"]:
                    assigned_officer = CivixUser.objects(id=issue.assigned_officer).first() if issue.assigned_officer else None
                    recipients = [assigned_officer] if assigned_officer and assigned_officer.is_active else list(CivixUser.objects(role__in=["officer", "zone_officer", "admin"], is_active=True))
                    stage_key = "unassigned" if issue.status in {"submitted", "verified"} else issue.status
                    notification_type = f"stalled_{stage_key}"
                    for officer in recipients:
                        if not Notification.objects(user_id=str(officer.id), related_issue_id=str(issue.id), notification_type=notification_type).first():
                            Notification(
                                user_id=str(officer.id),
                                title="Ticket needs attention",
                                title_ta="புகாருக்கு கவனம் தேவை",
                                message=f"{stalled['reason']} for {stalled['pending_days']} days. Please review: {issue.title}.",
                                message_ta=f"{stalled['pending_days']} நாட்களாக {issue.title} புகாரில் முன்னேற்றம் இல்லை. தயவுசெய்து பரிசீலிக்கவும்.",
                                notification_type=notification_type,
                                related_issue_id=str(issue.id),
                            ).save()
            return Response([serialize_issue(i, user_id=user_id, include_priority=include_priority_for(request)) for i in issues], status=status.HTTP_200_OK)
        except PyMongoError:
            return Response(
                {"error": "Issue data is temporarily unavailable. Check the MongoDB connection."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class IssueUpvoteView(APIView):
    """POST /api/issues/<id>/upvote/"""
    def post(self, request, issue_id):
        user_id = session_user_id(request, "citizen_anon")
        try:
            issue = Issue.objects(id=issue_id).first()
        except Exception:
            return Response({"error": "Issue data is temporarily unavailable. Check the MongoDB connection or issue id."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)

        if user_has_upvoted(issue, user_id):
            return Response({"success": False, "already_voted": True, "message": "You have already voted for this issue.", "upvote_count": issue.upvote_count}, status=status.HTTP_200_OK)

        if not issue.reported_by and not issue.location and not issue.category:
            from civix_backend.db import get_collection

            update_result = get_collection("issues").update_one(
                {"_id": issue.id, "upvoted_by": {"$ne": user_id}},
                {"$addToSet": {"upvoted_by": user_id}, "$inc": {"upvote_count": 1}},
            )
            if not update_result.modified_count:
                return Response({"success": False, "already_voted": True, "message": "You have already voted for this issue."}, status=status.HTTP_200_OK)

            upvote_count = (issue.upvote_count or 0) + 1
            return Response({
                "success": True,
                "already_voted": False,
                "upvote_count": upvote_count,
                "new_priority_score": round(upvote_count * 20, 1),
            }, status=status.HTTP_200_OK)

        if user_id and user_id not in (issue.upvoted_by or []):
            issue.upvoted_by.append(user_id)
        issue.upvote_count = max(0, (issue.upvote_count or 0) + 1)
        issue.save()

        try:
            IssueUpvote(issue_id=str(issue.id), user_id=user_id).save()
        except NotUniqueError:
            issue.reload()
            return Response({"success": False, "already_voted": True, "message": "You have already voted for this issue.", "upvote_count": issue.upvote_count}, status=status.HTTP_200_OK)

        user = session_user(request)
        if user:
            user.upvotes_given = (user.upvotes_given or 0) + 1
            user.add_points(getattr(settings, "UPVOTE_CIVIC_POINTS", 5))
            user.save()

        return Response({
            "success": True,
            "already_voted": False,
            "upvote_count": issue.upvote_count,
            "new_priority_score": round(issue.priority_score, 1)
        }, status=status.HTTP_200_OK)


class IssuePriorityView(APIView):
    """PATCH /api/issues/<id>/priority/ for officer-controlled work priority."""
    def patch(self, request, issue_id):
        if request.session.get("civix_role") not in {"officer", "zone_officer", "admin"}:
            return Response({"error": "Only an officer can set ticket priority."}, status=status.HTTP_403_FORBIDDEN)
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            priority = int(request.data.get("priority"))
        except (TypeError, ValueError):
            return Response({"error": "Priority must be low, medium, or high."}, status=status.HTTP_400_BAD_REQUEST)
        if priority not in {1, 2, 3}:
            return Response({"error": "Priority must be between 1 and 3."}, status=status.HTTP_400_BAD_REQUEST)
        issue.officer_priority = priority
        issue.priority_locked = True
        issue.priority_score = {1: 100.0, 2: 200.0, 3: 300.0}[priority]
        issue.save()
        return Response({"success": True, "priority": priority, "priority_score": issue.priority_score}, status=status.HTTP_200_OK)


class IssueResolveView(APIView):
    """PATCH /api/issues/<id>/resolve/"""
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def patch(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)

        if issue.status != "in_progress":
            return Response({"error": f"Completion evidence requires an in-progress issue, not {issue.status}."}, status=status.HTTP_409_CONFLICT)

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
            worker_id=worker_id,
            ticket_id=str(issue.id),
            verification_status="pending",
            worker_location=[worker_lng, worker_lat] if worker_lng and worker_lat else None,
            geo_verified=geo_verified,
            distance_from_issue=round(dist, 1),
            notes=notes,
            submitted_at=datetime.datetime.utcnow()
        )
        issue.status = "awaiting_verification"
        issue.add_status_change(to_status="awaiting_verification", changed_by=worker_id, reason=notes)
        issue.resolved_at = None
        issue.save()
        assigned_officer = CivixUser.objects(id=issue.assigned_officer).first() if issue.assigned_officer else None
        officers = [assigned_officer] if assigned_officer else list(CivixUser.objects(role__in=["officer", "zone_officer", "admin"], is_active=True))
        for officer in officers:
            if not officer or not officer.is_active:
                continue
            Notification(
                user_id=str(officer.id),
                title="Completion upload awaiting verification",
                title_ta="முடிவை சரிபார்க்க காத்திருக்கிறது",
                message=f"Worker proof submitted for: {issue.title}.",
                message_ta=f"பணியாளர் சான்று சமர்ப்பிக்கப்பட்டது: {issue.title}.",
                notification_type="verification_required",
                related_issue_id=str(issue.id),
            ).save()

        return Response({
            "success": True,
            "message": "Proof submitted to the officer for verification.",
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

        user = session_user(request)
        user_id = str(user.id) if user else session_user_id(request, "citizen_verifier")
        comment = request.data.get("comment", "")
        stars = request.data.get("stars")

        try:
            IssueVerification(
                issue_id=str(issue.id),
                user_id=user_id,
                is_fixed=is_fixed,
                comment=comment
            ).save()
        except NotUniqueError:
            return Response({"error": "You have already verified this issue."}, status=status.HTTP_409_CONFLICT)

        if user:
            user.verifications_done = (user.verifications_done or 0) + 1
            user.add_points(getattr(settings, "VERIFY_CIVIC_POINTS", 10))
            user.save()

        if stars:
            _apply_worker_rating(issue, user_id, stars, comment)

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


def _resolve_issue_worker(issue):
    worker = None
    worker_id = (issue.resolution_proof.worker_id if issue.resolution_proof else None) or issue.assigned_to
    if not worker_id:
        return None
    try:
        worker = CivixUser.objects(id=worker_id).first()
    except Exception:
        worker = None
    if not worker:
        worker = CivixUser.objects(full_name=worker_id).first() or CivixUser.objects(phone=worker_id).first()
    return worker


def _apply_worker_rating(issue, user_id, stars, comment=""):
    try:
        stars = int(stars)
    except (TypeError, ValueError):
        return None
    if stars < 1 or stars > 5:
        return None
    worker = _resolve_issue_worker(issue)
    if not worker:
        return None
    existing = WorkerRating.objects(issue_id=str(issue.id), user_id=user_id).first()
    if existing:
        worker.rating_total = max(0, (worker.rating_total or 0) - existing.stars + stars)
        existing.stars = stars
        existing.comment = comment or existing.comment
        existing.save()
        worker.save()
        return existing
    rating = WorkerRating(
        issue_id=str(issue.id),
        user_id=user_id,
        worker_id=str(worker.id),
        stars=stars,
        comment=comment or "",
    )
    rating.save()
    worker.rating_total = (worker.rating_total or 0) + stars
    worker.rating_count = (worker.rating_count or 0) + 1
    worker.save()
    return rating


class WorkerRateView(APIView):
    """POST /api/issues/<id>/rate-worker/ — citizen 1–5 star rating of the resolving worker."""

    def post(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)
        if issue.status not in {"resolved", "citizen_verified", "closed", "awaiting_verification"}:
            return Response({"error": "You can rate the worker after the issue is completed."}, status=status.HTTP_409_CONFLICT)
        user = session_user(request)
        if not user:
            return Response({"error": "Sign in to rate this worker."}, status=status.HTTP_401_UNAUTHORIZED)
        rating = _apply_worker_rating(issue, str(user.id), request.data.get("stars"), request.data.get("comment", ""))
        if not rating:
            return Response({"error": "Choose a rating from 1 to 5 stars."}, status=status.HTTP_400_BAD_REQUEST)
        worker = CivixUser.objects(id=rating.worker_id).first()
        return Response({
            "success": True,
            "stars": rating.stars,
            "worker_quality": worker_quality_payload(worker),
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
        issue.assigned_to = worker_id
        issue.assigned_officer = officer_id
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


class IssueReviewView(APIView):
    """PATCH /api/issues/<id>/review/ for officer swipe decisions."""
    def patch(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        if not issue:
            return Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)

        decision = request.data.get("decision", "").strip().lower()
        officer_id = session_user_id(request, "officer_admin")
        worker = None
        worker_id = request.data.get("worker_id", "").strip()
        feedback = request.data.get("feedback", "").strip()
        priority_value = request.data.get("priority")

        if decision == "resolved":
            if issue.status != "awaiting_verification":
                return Response({"error": "Only awaiting-verification tickets can be resolved by the officer."}, status=status.HTTP_409_CONFLICT)
            issue.officer_decision = "verified"
            if issue.resolution_proof:
                issue.resolution_proof.verification_status = "accepted"
            issue.status = "resolved"
            issue.resolved_at = datetime.datetime.utcnow()
            issue.add_status_change(to_status="resolved", changed_by=officer_id, reason="Officer verified completion")
            issue.save()
            Notification(
                user_id=issue.reported_by,
                title="Your issue was resolved", title_ta="உங்கள் புகார் தீர்க்கப்பட்டது",
                message=f"The officer verified completion for: {issue.title}",
                message_ta=f"அதிகாரி இந்த பணியை சரிபார்த்தார்: {issue.title}",
                notification_type="resolution", related_issue_id=str(issue.id)
            ).save()
            return Response({"success": True, "issue": serialize_issue(issue)}, status=status.HTTP_200_OK)

        if decision in {"rejected", "reopened"}:
            if issue.status != "awaiting_verification":
                return Response({"error": "Only awaiting-verification tickets can be rejected."}, status=status.HTTP_409_CONFLICT)
            if not feedback:
                return Response({"error": "Feedback is required when rejecting completion evidence."}, status=status.HTTP_400_BAD_REQUEST)
            issue.add_status_change(to_status="in_progress", changed_by=officer_id, reason="Officer rejected completion evidence")
            if issue.resolution_proof:
                issue.resolution_proof.verification_status = "rejected"
            issue.officer_decision = None
            issue.save()
            if issue.assigned_to:
                Notification(
                    user_id=issue.assigned_to,
                    title="Completion evidence rejected", title_ta="முடிப்பு சான்று நிராகரிக்கப்பட்டது",
                    message=f"{issue.title}: {feedback}",
                    message_ta=f"{issue.title}: {feedback}",
                    notification_type="verification_rejected", related_issue_id=str(issue.id)
                ).save()
            return Response({"success": True, "issue": serialize_issue(issue)}, status=status.HTTP_200_OK)

        if decision not in {"verified", "dismissed"}:
            return Response({"error": "Decision must be verified, dismissed or resolved."}, status=status.HTTP_400_BAD_REQUEST)

        if decision == "dismissed":
            issue.officer_priority = None
            issue.officer_decision = "dismissed"
            issue.assigned_to = None
            issue.add_status_change(to_status="dismissed", changed_by=officer_id, reason="Officer dismissed invalid report")
            issue.save()
            return Response({"success": True, "issue": serialize_issue(issue)}, status=status.HTTP_200_OK)

        if decision == "verified":
            if not worker_id:
                return Response({"error": "Select a field worker before verifying this issue."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                priority = int(priority_value)
            except (TypeError, ValueError):
                return Response({"error": "Select a work priority before assigning this issue."}, status=status.HTTP_400_BAD_REQUEST)
            if priority not in {1, 2, 3}:
                return Response({"error": "Priority must be between 1 and 3."}, status=status.HTTP_400_BAD_REQUEST)
            worker = CivixUser.objects(phone=worker_id).first() or CivixUser.objects(full_name=worker_id).first()
            if not worker or worker.role != "field_worker":
                return Response({"error": "Select a valid field worker."}, status=status.HTTP_400_BAD_REQUEST)

        issue.officer_priority = None
        issue.officer_decision = decision
        issue.add_status_change(
            to_status="verified",
            changed_by=officer_id,
            reason=f"Officer decision: {decision}",
        )
        if worker:
            issue.assigned_officer = officer_id
            issue.assigned_to = worker_id
            issue.assigned_at = datetime.datetime.utcnow()
            issue.officer_priority = priority
            issue.priority_locked = True
            issue.priority_score = {1: 100.0, 2: 200.0, 3: 300.0}[priority]
            issue.add_status_change(to_status="assigned", changed_by=officer_id, reason=f"Assigned to worker {worker_id}")
        issue.save()
        if worker:
            Notification(
                user_id=str(worker.id), title="New task assigned", title_ta="புதிய பணி ஒதுக்கப்பட்டது",
                message=f"{issue.title} has been assigned to you.",
                message_ta=f"{issue.title} உங்களுக்கு ஒதுக்கப்பட்டுள்ளது.",
                notification_type="assignment", related_issue_id=str(issue.id)
            ).save()
        return Response({"success": True, "issue": serialize_issue(issue)}, status=status.HTTP_200_OK)


class IssueStatusView(APIView):
    """PATCH /api/issues/<issue_id>/status/ for worker workflow transitions."""
    allowed_transitions = {
        "assigned": {"in_progress"},
        "in_progress": {"awaiting_verification"},
        "awaiting_verification": set(),
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
        if next_status == "in_progress" and not issue.started_at:
            issue.started_at = datetime.datetime.utcnow()
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
        reporter_ids = {user_id}
        user = CivixUser.objects(id=user_id).first() if len(user_id) == 24 else None
        if user:
            reporter_ids.update(filter(None, [str(user.id), user.username, user.phone]))
        reports = Issue.objects(reported_by__in=list(reporter_ids)).order_by("-created_at")[:50]
        return Response([serialize_issue(i, user_id=user_id) for i in reports])


class NearbyIssuesView(IssueListView):
    def get(self, request):
        try:
            user_id = session_user_id(request, "")
            latitude = float(request.query_params.get("latitude", 13.0067))
            longitude = float(request.query_params.get("longitude", 80.2574))
            category = (request.query_params.get("category") or "").strip()
            query = {
                "location__near": [longitude, latitude],
                "location__max_distance": int(request.query_params.get("radius", 50)),
                "status__nin": ["closed", "dismissed"],
            }
            if category:
                query["category"] = category
            issues = Issue.objects(**query)
            return Response([serialize_issue(i, user_id=user_id) for i in issues[:50]])
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
        selected_date = request.query_params.get("date", "").strip()
        if selected_date:
            try:
                task_date = datetime.date.fromisoformat(selected_date)
            except ValueError:
                return Response({"error": "Date must use YYYY-MM-DD format."}, status=status.HTTP_400_BAD_REQUEST)
            start = datetime.datetime.combine(task_date, datetime.time.min)
            end = start + datetime.timedelta(days=1)
            query["assigned_at__gte"] = start
            query["assigned_at__lt"] = end
        severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        tasks = list(Issue.objects(**query))
        tasks.sort(
            key=lambda issue: (
                -severity_rank.get(issue.severity, 0),
                -(issue.priority_score or 0),
                -(issue.assigned_at.timestamp() if issue.assigned_at else 0),
            )
        )
        tasks = tasks[:50]
        return Response([serialize_issue(i, user_id=user_id, include_priority=True) for i in tasks])


class IssueDetailsView(APIView):
    def get(self, request, issue_id):
        issue = Issue.objects(id=issue_id).first()
        user_id = session_user_id(request, "")
        worker = CivixUser.objects(id=user_id).first() if user_id else None
        if worker and worker.role == "field_worker" and issue and issue.assigned_to not in {str(worker.id), worker.full_name, worker.phone}:
            return Response({"error": "You can only view your assigned issues."}, status=status.HTTP_403_FORBIDDEN)
        return Response(serialize_issue(issue, user_id=user_id, include_priority=include_priority_for(request)), status=status.HTTP_200_OK) if issue else Response({"error": "Issue not found"}, status=status.HTTP_404_NOT_FOUND)


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
        return Response([serialize_issue(i, include_priority=True) for i in Issue.objects(**query).order_by("-priority_score")[:50]])


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
        return Response([serialize_issue(i, include_priority=True) for i in issues[:100]])


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
