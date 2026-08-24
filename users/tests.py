from django.test import SimpleTestCase

from users.middleware import RoleAccessMiddleware
from users.models import CivixUser
from users.views import hash_pw, password_matches


class UserLogicTests(SimpleTestCase):
	def test_password_hash_matches_only_original_password(self):
		user = CivixUser(password_hash=hash_pw("correct-password"))

		self.assertTrue(password_matches(user, "correct-password"))
		self.assertFalse(password_matches(user, "wrong-password"))
		self.assertTrue(user.password_hash.startswith("pbkdf2_sha256$") or user.password_hash.startswith("argon2$") or user.password_hash.startswith("bcrypt$"))

	def test_demo_password_is_limited_to_demo_hash(self):
		user = CivixUser(password_hash="pbkdf2_sha256$demo$seed")

		self.assertTrue(password_matches(user, "demo123"))
		self.assertFalse(password_matches(user, "wrong-password"))

	def test_worker_routes_require_worker_role(self):
		self.assertEqual(
			RoleAccessMiddleware.required_role("/api/issues/abc/resolve/", "PATCH"),
			{"field_worker"},
		)
		self.assertEqual(
			RoleAccessMiddleware.required_role("/api/issues/abc/status/", "PATCH"),
			{"field_worker"},
		)

	def test_role_boundaries_cover_new_workflows(self):
		self.assertEqual(RoleAccessMiddleware.required_role("/api/issues/emergency-dispatch/", "POST"), {"citizen"})
		self.assertEqual(RoleAccessMiddleware.required_role("/api/issues/volunteer-drives/", "POST"), {"citizen", "officer", "zone_officer", "admin"})
		self.assertEqual(RoleAccessMiddleware.required_role("/api/issues/abc/delete/", "DELETE"), {"officer", "zone_officer", "admin"})
