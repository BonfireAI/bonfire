"""Knight RED tests — Front Door security hardening.

Two-defect convergence on the host-only Front Door:

1. ``ui.html`` previously imported a stylesheet from ``fonts.googleapis.com``,
   sending the user's browser fingerprint + IP + Referer to Google on every
   ``bonfire scan`` invocation. The Front Door is bound to ``127.0.0.1``
   precisely because the page exposes scraped local state; the third-party
   font fetch contradicted that posture.

2. ``_process_request`` returned only ``Content-Type`` on the HTML response —
   no ``Content-Security-Policy``, no ``X-Frame-Options``, no
   ``Referrer-Policy``, no ``X-Content-Type-Options``. A drive-by visit to
   ``http://127.0.0.1:<port>/`` while an operator had a scan running could
   render the page in an iframe inside an attacker tab, and any third-party
   subresource fetch would leak the referrer.

Both findings ship as one PR — the CSP and the @import removal are the
two halves of "the page makes no third-party network requests." Add the
@import back later and CSP will refuse to load it; remove it without CSP
and the next contributor can re-introduce it silently.

Contract:

- ``ui.html`` contains zero ``https://`` URLs (no third-party subresources).
- The Front Door's HTTP response for ``GET /`` carries:
    * ``Content-Security-Policy`` with ``default-src 'self'`` (forbids any
      third-party subresource).
    * ``X-Frame-Options: DENY`` (forbids iframe embedding).
    * ``Referrer-Policy: no-referrer`` (no Referer leak on outbound links).
    * ``X-Content-Type-Options: nosniff`` (no MIME confusion).

Out of scope (separate ticket, larger Pydantic-validation wire-up):

- WebSocket ``_ws_handler`` Pydantic-validation half of the Front Door
  hardening — that needs ``parse_client_message`` wired into the dispatch
  path + ``flow.py`` adjustments. Filed for a follow-up PR.
"""

from __future__ import annotations

import asyncio
import re
import urllib.request
from importlib import resources

from bonfire.onboard.server import FrontDoorServer


class TestUiHtmlNoThirdPartyResources:
    """ui.html must not request any third-party HTTPS resources."""

    def test_ui_html_has_no_third_party_https_references(self) -> None:
        """No ``https://`` URLs in the served HTML — privacy-egress closure."""
        body = resources.files("bonfire.onboard").joinpath("ui.html").read_bytes()
        text = body.decode("utf-8")
        # Match http(s)://host references that are NOT in HTML comments.
        # Simple approach: strip <!-- ... --> comment blocks then search.
        text_no_comments = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        https_refs = re.findall(r"https://[^\s'\"<>)]+", text_no_comments)
        assert https_refs == [], (
            "ui.html must make ZERO third-party network requests on render — "
            f"found {https_refs!r}. Inline the resource, ship it as a sibling "
            "served from the same origin, or drop it and fall back."
        )


class TestFrontDoorSecurityHeaders:
    """``GET /`` HTTP response carries the four hardening headers."""

    async def test_response_carries_content_security_policy(self) -> None:
        """CSP header forbids third-party subresources (``default-src 'self'``)."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/",
            )
            csp = response.headers.get("Content-Security-Policy", "")
            assert csp, (
                "GET / response missing Content-Security-Policy header — "
                "drive-by iframe + subresource fetch surface unsealed"
            )
            assert "default-src 'self'" in csp, (
                "CSP must include `default-src 'self'` to forbid third-party "
                f"subresources; got: {csp!r}"
            )
        finally:
            await server.stop()

    async def test_response_carries_x_frame_options_deny(self) -> None:
        """X-Frame-Options: DENY forbids iframe embedding."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/",
            )
            xfo = response.headers.get("X-Frame-Options", "")
            assert xfo == "DENY", (
                "GET / response must carry X-Frame-Options: DENY — drive-by "
                f"iframe attack surface unsealed. Got: {xfo!r}"
            )
        finally:
            await server.stop()

    async def test_response_carries_referrer_policy_no_referrer(self) -> None:
        """Referrer-Policy: no-referrer prevents Referer leak on outbound links."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/",
            )
            rp = response.headers.get("Referrer-Policy", "")
            assert rp == "no-referrer", (
                "GET / response must carry Referrer-Policy: no-referrer — "
                f"Referer-leak surface open. Got: {rp!r}"
            )
        finally:
            await server.stop()

    async def test_response_carries_x_content_type_options_nosniff(self) -> None:
        """X-Content-Type-Options: nosniff prevents MIME confusion."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/",
            )
            xcto = response.headers.get("X-Content-Type-Options", "")
            assert xcto == "nosniff", (
                f"GET / response must carry X-Content-Type-Options: nosniff. Got: {xcto!r}"
            )
        finally:
            await server.stop()

    async def test_content_type_header_still_present(self) -> None:
        """Regression guard: the new headers don't remove the existing Content-Type."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/",
            )
            ct = response.headers.get("Content-Type", "")
            assert "text/html" in ct
            assert "charset=utf-8" in ct.lower()
        finally:
            await server.stop()
