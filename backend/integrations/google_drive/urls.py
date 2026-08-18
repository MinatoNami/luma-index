from django.urls import path

from . import views

app_name = "drive"

urlpatterns = [
    path("status/", views.DriveStatusView.as_view(), name="status"),
    path("connect/", views.DriveConnectView.as_view(), name="connect"),
    path("oauth/callback", views.DriveCallbackView.as_view(), name="callback"),
    path("disconnect/", views.DriveDisconnectView.as_view(), name="disconnect"),
    path("folders/", views.DriveFolderListView.as_view(), name="folders"),
    path("roots/", views.DriveRootListView.as_view(), name="roots"),
    path("roots/<int:root_id>/", views.DriveRootDetailView.as_view(), name="root-detail"),
    path("sync/", views.DriveSyncView.as_view(), name="sync"),
    path("sync/<int:run_id>/", views.DriveSyncDetailView.as_view(), name="sync-detail"),
]
