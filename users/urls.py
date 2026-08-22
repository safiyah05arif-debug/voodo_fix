from django.urls import path
from users.views import UserProfileView, LeaderboardView, WorkerListView

urlpatterns = [
    path("profile/", UserProfileView.as_view(), name="user-profile"),
    path("leaderboard/", LeaderboardView.as_view(), name="user-leaderboard"),
    path("workers/", WorkerListView.as_view(), name="worker-list"),
]
