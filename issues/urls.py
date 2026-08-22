from django.urls import path
from issues.views import (
    IssueClassifyView,
    IssueReportView,
    HeatmapGeoJSONView,
    IssueListView,
    IssueUpvoteView,
    IssueResolveView,
    IssueVerifyView,
    IssueAssignView,
)

urlpatterns = [
    path("", IssueListView.as_view(), name="issue-list"),
    path("classify/", IssueClassifyView.as_view(), name="issue-classify"),
    path("report/", IssueReportView.as_view(), name="issue-report"),
    path("heatmap/", HeatmapGeoJSONView.as_view(), name="issue-heatmap"),
    path("<str:issue_id>/upvote/", IssueUpvoteView.as_view(), name="issue-upvote"),
    path("<str:issue_id>/resolve/", IssueResolveView.as_view(), name="issue-resolve"),
    path("<str:issue_id>/verify/", IssueVerifyView.as_view(), name="issue-verify"),
    path("<str:issue_id>/assign/", IssueAssignView.as_view(), name="issue-assign"),
]
