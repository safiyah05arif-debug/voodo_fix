import os
from unittest.mock import patch

from django.test import SimpleTestCase

from civix_backend import ai_vision
from issues.models import Issue
from issues.views import IssueStatusView, haversine_distance, location_coordinates


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
		self.assertEqual(IssueStatusView.allowed_transitions["submitted"], {"verified", "assigned"})
		self.assertEqual(IssueStatusView.allowed_transitions["in_progress"], {"resolved"})
		self.assertEqual(IssueStatusView.allowed_transitions["citizen_verified"], {"closed"})

	@patch.object(ai_vision, "_call_openai_vision", side_effect=AssertionError("OpenAI should not be called"))
	@patch.object(ai_vision, "_call_gemini_vision", return_value={"category": "water"})
	def test_gemini_provider_is_selected(self, gemini_call, _openai_call):
		with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"}, clear=False):
			self.assertEqual(ai_vision.classify_issue_image(title_hint="pipe leak"), {"category": "water"})
		gemini_call.assert_called_once()
