import os
import hashlib
import datetime
from unittest.mock import patch

from django.test import SimpleTestCase

from civix_backend import ai_vision
from issues.models import Issue, ResolutionProof
from issues.views import IssueStatusView, haversine_distance, location_coordinates, serialize_issue, user_has_upvoted, public_status_lifecycle, overdue_issue_details, stalled_issue_details


class IssueLogicTests(SimpleTestCase):
	def test_location_coordinates_accepts_pointfield_forms(self):
		self.assertEqual(location_coordinates([80.27, 13.08]), [80.27, 13.08])
		self.assertEqual(
			location_coordinates({"type": "Point", "coordinates": [80.27, 13.08]}),
			[80.27, 13.08],
		)

	def test_geojson_serialization_accepts_pointfield_list(self):
		issue = Issue(
			title="Pothole",
			description="Road damage",
			reported_by="citizen",
			location=[80.27, 13.08],
			category="road",
			issue_type="pothole",
			severity="high",
		)

		self.assertEqual(issue.to_geojson_feature()["geometry"]["coordinates"], [80.27, 13.08])

	def test_status_change_records_previous_status(self):
		issue = Issue(
			title="Pothole",
			reported_by="citizen",
			location=[80.27, 13.08],
			category="road",
			severity="low",
			status="submitted",
		)

		issue.add_status_change("verified", changed_by="officer", reason="Confirmed")

		self.assertEqual(issue.status, "verified")
		self.assertEqual(issue.status_history[0].from_status, "submitted")
		self.assertEqual(issue.status_history[0].to_status, "verified")

	def test_direct_camera_is_a_valid_input_method(self):
		issue = Issue(
			title="Camera report",
			reported_by="citizen",
			location=[80.27, 13.08],
			category="road",
			severity="low",
			input_method="direct_camera",
		)

		issue.validate()

	def test_haversine_distance_is_zero_for_same_point(self):
		self.assertEqual(haversine_distance(13.08, 80.27, 13.08, 80.27), 0)

	def test_status_transitions_follow_issue_lifecycle(self):
		self.assertNotIn("submitted", IssueStatusView.allowed_transitions)
		self.assertEqual(IssueStatusView.allowed_transitions["in_progress"], {"awaiting_verification"})
		self.assertEqual(IssueStatusView.allowed_transitions["awaiting_verification"], set())
		self.assertNotIn("citizen_verified", IssueStatusView.allowed_transitions)

	@patch.object(ai_vision, "_call_openai_vision", side_effect=AssertionError("OpenAI should not be called"))
	@patch.object(ai_vision, "_call_gemini_vision", return_value={"category": "water"})
	def test_gemini_provider_is_selected(self, gemini_call, _openai_call):
		with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"}, clear=False):
			self.assertEqual(ai_vision.classify_issue_image(title_hint="pipe leak"), {"category": "water"})
		gemini_call.assert_called_once()

	def test_photo_hash_is_stable(self):
		photo = b"demo-image-bytes"
		self.assertEqual(hashlib.sha256(photo).hexdigest(), hashlib.sha256(photo).hexdigest())
		self.assertNotEqual(hashlib.sha256(photo).hexdigest(), hashlib.sha256(b"other-image").hexdigest())

	def test_user_upvote_state_is_serialized_per_user(self):
		issue = Issue(
			title="Drain blockage",
			reported_by="citizen-1",
			location=[80.27, 13.08],
			category="water",
			severity="medium",
			upvote_count=24,
			upvoted_by=["user-123"],
		)

		self.assertTrue(user_has_upvoted(issue, "user-123"))
		self.assertFalse(user_has_upvoted(issue, "user-456"))
		payload = serialize_issue(issue, user_id="user-123")
		self.assertTrue(payload["already_voted"])
		self.assertEqual(payload["upvote_count"], 24)
		self.assertFalse(serialize_issue(issue, user_id="user-456")["already_voted"])

	def test_public_status_lifecycle_tracks_current_stage(self):
		steps = public_status_lifecycle("in_progress")
		self.assertEqual([step["key"] for step in steps], ["reported", "verified", "assigned", "in_progress", "resolved"])
		self.assertTrue(any(step["key"] == "in_progress" and step["active"] for step in steps))
		self.assertTrue(any(step["key"] == "reported" and step["complete"] for step in steps))
		resolved_steps = public_status_lifecycle("resolved")
		self.assertTrue(any(step["key"] == "resolved" and step["active"] for step in resolved_steps))
		self.assertTrue(all(step["complete"] for step in resolved_steps[:4]))

	def test_resolution_proof_keeps_worker_and_ticket_identity(self):
		proof = ResolutionProof(
			photo_url="https://storage.example/proof.jpg",
			worker_id="worker-123",
			ticket_id="ticket-456",
			worker_location=[80.27, 13.08],
		)
		self.assertEqual(proof.worker_id, "worker-123")
		self.assertEqual(proof.ticket_id, "ticket-456")
		self.assertEqual(proof.verification_status, "pending")

	def test_location_verification_flags_large_completion_offset(self):
		issue = Issue(
			title="Road repair",
			reported_by="citizen-1",
			location=[80.27, 13.08],
			category="road",
			severity="medium",
			resolution_proof=ResolutionProof(
				photo_url="https://storage.example/proof.jpg",
				worker_id="worker-123",
				ticket_id="ticket-456",
				worker_location=[80.2707, 13.08],
				distance_from_issue=78.0,
			),
		)
		payload = serialize_issue(issue)
		self.assertEqual(payload["location_verification"]["original_report"], {"latitude": 13.08, "longitude": 80.27})
		self.assertTrue(payload["location_verification"]["warning"])
		self.assertTrue(payload["location_verification"]["supporting_evidence_only"])

	def test_officer_queue_marks_unhandled_reports_overdue_after_twelve_days(self):
		issue = Issue(
			title="Old report",
			reported_by="citizen-1",
			location=[80.27, 13.08],
			category="road",
			severity="high",
			created_at=datetime.datetime.utcnow() - datetime.timedelta(days=12),
			status="submitted",
		)
		details = overdue_issue_details(issue)
		self.assertTrue(details["is_overdue"])
		self.assertGreaterEqual(details["pending_days"], 12)

	def test_stalled_issue_uses_current_stage_timestamp(self):
		issue = Issue(title="Unassigned", reported_by="citizen-1", location=[80.27, 13.08], category="road", severity="high", created_at=datetime.datetime.utcnow() - datetime.timedelta(days=5), status="submitted")
		details = stalled_issue_details(issue)
		self.assertTrue(details["is_stalled"])
		self.assertEqual(details["reason"], "This ticket has been unassigned")
