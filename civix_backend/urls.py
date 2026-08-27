"""
CIVIX — Master URL Configuration
==================================
Routes API endpoints and serves frontend portal templates.
"""

from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render
from issues.views import (
    NearbyIssuesView, MyReportsView, TaskAssignedView, IssueDetailsView,
    IssueStatusView, IssueProofView, HeatmapGeoJSONView, DepartmentMasterView,
    SLABreachesView, IssueAssignView, OverrideDepartmentView, EscalateIssueView,
    DeleteIssueView,
)
from users.views import (
    UserProfileView, AdminAnalyticsView, AdminUsersView, AdminAuditLogsView,
    AdminCreateUserView, AdminConfigView, AdminDeactivateUserView, AdminIssueExportView,
)

def login_view(request):
    return render(request, "login.html")

def citizen_portal_view(request):
    return render(request, "citizen.html")

def worker_portal_view(request):
    return render(request, "worker.html")

def officer_portal_view(request):
    return render(request, "officer.html")

def system_admin_view(request):
    return render(request, "admin_dashboard.html")

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # Frontend Portals
    path("", login_view, name="login-page"),
    path("login/", login_view, name="login"),
    path("citizen/", citizen_portal_view, name="citizen-portal"),
    path("worker/", worker_portal_view, name="worker-portal"),
    path("officer/", officer_portal_view, name="officer-portal"),
    path("system-admin/", system_admin_view, name="system-admin-portal"),

    # REST APIs
    path("api/issues/", include("issues.urls")),
    path("api/users/", include("users.urls")),

    # Role-oriented API aliases
    path("api/issues/my-reports/", MyReportsView.as_view()),
    path("api/issues/nearby/", NearbyIssuesView.as_view()),
    path("api/tasks/assigned/", TaskAssignedView.as_view()),
    path("api/tasks/<str:issue_id>/details/", IssueDetailsView.as_view()),
    path("api/tasks/<str:issue_id>/status/", IssueStatusView.as_view()),
    path("api/tasks/<str:issue_id>/proof/", IssueProofView.as_view()),
    path("api/dashboard/heatmap/", HeatmapGeoJSONView.as_view()),
    path("api/issues/department-master/", DepartmentMasterView.as_view()),
    path("api/sla/breaches/", SLABreachesView.as_view()),
    path("api/issues/<str:issue_id>/assign/", IssueAssignView.as_view()),
    path("api/issues/<str:issue_id>/override-department/", OverrideDepartmentView.as_view()),
    path("api/sla/<str:issue_id>/escalate/", EscalateIssueView.as_view()),
    path("api/admin/analytics/", AdminAnalyticsView.as_view()),
    path("api/admin/issues/export/", AdminIssueExportView.as_view()),
    path("api/admin/users/", AdminUsersView.as_view()),
    path("api/admin/audit-logs/", AdminAuditLogsView.as_view()),
    path("api/admin/users/create/", AdminCreateUserView.as_view()),
    path("api/admin/users/<str:user_id>/deactivate/", AdminDeactivateUserView.as_view()),
    path("api/admin/config/sla/", AdminConfigView.as_view()),
    path("api/admin/issues/<str:issue_id>/", DeleteIssueView.as_view()),
]
