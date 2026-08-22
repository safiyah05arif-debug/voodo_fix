from django.urls import path
from users.views import (
    UserLoginView,
    UserRegisterView,
    UserProfileView,
    LeaderboardView,
    WorkerListView,
)

urlpatterns = [
    path("login/", UserLoginView.as_view(), name="user-login"),
    path("register/", UserRegisterView.as_view(), name="user-register"),
    path("profile/", UserProfileView.as_view(), name="user-profile"),
    path("leaderboard/", LeaderboardView.as_view(), name="user-leaderboard"),
    path("workers/", WorkerListView.as_view(), name="worker-list"),
]
