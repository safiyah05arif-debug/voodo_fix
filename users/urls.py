from django.urls import path
from users.views import (
    UserLoginView,
    UserRegisterView,
    WorkerAddView,
    UserProfileView,
    LeaderboardView,
    WorkerListView,
    AdminMetricsView,
    AdminConfigView,
    AdminAnalyticsView, AdminUsersView, AdminAuditLogsView, AdminCreateUserView, AdminUpdateUserView, NotificationListView,
)

urlpatterns = [
    path("login/", UserLoginView.as_view(), name="user-login"),
    path("register/", UserRegisterView.as_view(), name="user-register"),
    path("workers/add/", WorkerAddView.as_view(), name="worker-add"),
    path("workers/", WorkerListView.as_view(), name="worker-list"),
    path("profile/", UserProfileView.as_view(), name="user-profile"),
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path("leaderboard/", LeaderboardView.as_view(), name="user-leaderboard"),
    path("admin/metrics/", AdminMetricsView.as_view(), name="admin-metrics"),
    path("admin/config/", AdminConfigView.as_view(), name="admin-config"),
    path("admin/analytics/", AdminAnalyticsView.as_view(), name="admin-analytics"),
    path("admin/users/", AdminUsersView.as_view(), name="admin-users"),
    path("admin/audit-logs/", AdminAuditLogsView.as_view(), name="admin-audit-logs"),
    path("admin/users/create/", AdminCreateUserView.as_view(), name="admin-create-user"),
    path("admin/users/<str:user_id>/", AdminUpdateUserView.as_view(), name="admin-update-user"),
    path("admin/config/sla/", AdminConfigView.as_view(), name="admin-sla-config"),
]
