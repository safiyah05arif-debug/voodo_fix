from django.test import SimpleTestCase

from issues.models import Issue
from issues.views import haversine_distance, location_coordinates


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

	def test_haversine_distance_is_zero_for_same_point(self):
		self.assertEqual(haversine_distance(13.08, 80.27, 13.08, 80.27), 0)
