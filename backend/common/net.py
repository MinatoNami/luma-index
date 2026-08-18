"""Client address resolution."""

from __future__ import annotations

from django.conf import settings
from rest_framework.settings import api_settings


def client_ip(request) -> str:
    """The client address, trusting exactly `NUM_PROXIES` forwarding hops.

    Mirrors DRF's throttle logic so a logged address and a throttled address
    can never disagree — which is the whole point of logging it.
    """
    num_proxies = api_settings.NUM_PROXIES
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    remote_addr = request.META.get("REMOTE_ADDR", "")

    if num_proxies is None:
        # Anything in X-Forwarded-For is attacker-controlled at this point.
        return remote_addr
    if num_proxies == 0 or not xff:
        return remote_addr

    addrs = xff.split(",")
    return addrs[-min(num_proxies, len(addrs))].strip()


def client_ip_for_log(request) -> str:
    """Address for logs, or a placeholder when logging it is switched off."""
    if not getattr(settings, "LOG_CLIENT_IP", False):
        return "disabled"
    return client_ip(request)
