"""API root.

Namespaces follow PRD §30. Only `auth` and `health` exist today; the remaining
includes get uncommented as their phases land.
"""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from . import health

urlpatterns = [
    path("health/", health.LivenessView.as_view(), name="health-live"),
    path("health/ready/", health.ReadinessView.as_view(), name="health-ready"),

    path("auth/", include("accounts.urls")),

    path("library/", include("library.urls")),

    # Later: /api/reader/, /api/shared/, /api/users/

    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
