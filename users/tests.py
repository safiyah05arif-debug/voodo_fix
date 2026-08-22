from django.test import SimpleTestCase

from users.middleware import RoleAccessMiddleware
from users.models import CivixUser
from users.views import hash_pw, password_matches


class UserLogicTests(SimpleTestCase):
	def test_password_hash_matches_only_original_password(self):
		user = CivixUser(password_hash=hash_pw("correct-password"))

		self.assertTrue(password_matches(user, "correct-password"))
		self.assertFalse(password_matches(user, "wrong-password"))

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
