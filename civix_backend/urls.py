"""
CIVIX — Master URL Configuration
==================================
Routes API endpoints and serves frontend portal templates.
"""

from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render

def citizen_portal_view(request):
    return render(request, "citizen.html")

def worker_portal_view(request):
    return render(request, "worker.html")

def officer_portal_view(request):
    return render(request, "officer.html")

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # Frontend Portals
    path("", citizen_portal_view, name="home"),
    path("citizen/", citizen_portal_view, name="citizen-portal"),
    path("worker/", worker_portal_view, name="worker-portal"),
    path("officer/", officer_portal_view, name="officer-portal"),

    # REST APIs
    path("api/issues/", include("issues.urls")),
    path("api/users/", include("users.urls")),
]
