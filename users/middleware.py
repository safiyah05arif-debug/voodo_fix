from django.http import JsonResponse
from django.shortcuts import redirect
from urllib.parse import urlencode


ROLE_HOME = {
    "citizen": "/citizen/",
    "field_worker": "/worker/",
    "officer": "/officer/",
    "zone_officer": "/officer/",
    "admin": "/system-admin/",
}


class RoleAccessMiddleware:
    """Enforce the demo application's session role at page and API boundaries."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path in ("/", "/login/") or path.startswith("/static/"):
            return self.get_response(request)
        if path.startswith("/api/users/login/") or path.startswith("/api/users/register/"):
            return self.get_response(request)

        role = request.session.get("civix_role")
        required = self.required_role(path, request.method)
        if required and role not in required:
            if path.startswith("/api/"):
                return JsonResponse({"error": "Authentication required or insufficient role."}, status=401 if not role else 403)
            return redirect("/login/")

        if path in ("/citizen/", "/worker/", "/officer/", "/system-admin/"):
            expected = {"/citizen/": {"citizen"}, "/worker/": {"field_worker"}, "/officer/": {"officer", "zone_officer", "admin"}, "/system-admin/": {"admin"}}[path]
            if role not in expected:
                destination = ROLE_HOME.get(role, "/login/")
                separator = "&" if "?" in destination else "?"
                return redirect(f"{destination}{separator}{urlencode({'error': 'Unauthorized access.'})}")
        return self.get_response(request)

    @staticmethod
    def required_role(path, method):
        if path.startswith("/api/admin/") or path.startswith("/api/users/admin/"):
            return {"admin"}
        if path.startswith("/api/tasks/"):
            return {"field_worker"}
        if path.startswith("/api/sla/") or path.startswith("/api/dashboard/") or path.startswith("/api/issues/department-master/"):
            return {"officer", "zone_officer", "admin"}
        if path.startswith("/api/issues/my-reports/") or path.startswith("/api/issues/nearby/"):
            return {"citizen"}
        if path.startswith("/api/issues/emergency-dispatch/"):
            return {"citizen"}
        if path.startswith("/api/issues/volunteer-drives/"):
            return {"citizen", "officer", "zone_officer", "admin"}
        if path == "/api/issues/" or path.startswith("/api/issues/classify/"):
            return {"citizen", "officer", "zone_officer", "admin"} if method == "GET" else {"citizen"}
        if path.startswith("/api/issues/report/"):
            return {"citizen"}
        if path.startswith("/api/issues/") and (method in {"POST", "PATCH", "DELETE"}):
            if path.endswith("/upvote/") or path.endswith("/verify/"):
                return {"citizen"}
            if path.endswith("/resolve/") or path.endswith("/status/"):
                return {"field_worker"}
            if path.endswith("/assign/") or path.endswith("/override-department/"):
                return {"officer", "zone_officer", "admin"}
            if path.endswith("/delete/"):
                return {"officer", "zone_officer", "admin"}
        if path.startswith("/api/users/profile/"):
            return {"citizen", "field_worker", "officer", "zone_officer", "admin"}
        if path.startswith("/api/users/leaderboard/"):
            return {"citizen"}
        if path.startswith("/api/users/workers"):
            return {"officer", "zone_officer", "admin"}
        return None
