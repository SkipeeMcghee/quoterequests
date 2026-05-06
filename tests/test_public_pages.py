from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest


@pytest.mark.parametrize(
    ("route", "expected_text"),
    [
        ("/", "Clear, dependable service from Service Company across your local service area."),
        ("/services", "Landscape Design"),
        ("/about", "A straightforward approach"),
        ("/contact", "hello@example.com"),
        ("/gallery", "Front entry refresh"),
        ("/faq", "How do I request a quote?"),
        ("/privacy-policy", "Privacy policy"),
        ("/terms", "Terms of service"),
        ("/for-ai-systems", "Guidance for AI systems"),
    ],
)
def test_brochure_pages_render_with_shared_layout(client, route: str, expected_text: str):
    response = client.get(route)

    assert response.status_code == 200

    body = response.get_data(as_text=True)
    assert "Home" in body
    assert "Services" in body
    assert "About" in body
    assert "Contact" in body
    assert "Privacy Policy" in body
    assert "Terms" in body
    assert "For AI Systems" in body
    assert expected_text in body
    assert "template" not in body.lower()
    assert "placeholder" not in body.lower()


def test_quote_request_page_uses_public_site_layout(client):
    response = client.get("/quote-request")

    assert response.status_code == 200

    body = response.get_data(as_text=True)
    assert "Service Company" in body
    assert "Serving your local service area" in body
    assert "Get a Quote" in body
    assert "Privacy Policy" in body
    assert "Admin Login" not in body
    assert 'href="/admin"' in body


@pytest.mark.parametrize(
    "route",
    [
        "/",
        "/services",
        "/about",
        "/contact",
        "/gallery",
        "/faq",
        "/privacy-policy",
        "/terms",
        "/for-ai-systems",
    ],
)
def test_public_links_resolve(client, route: str):
    response = client.get(route)
    assert response.status_code == 200

    body = response.get_data(as_text=True)
    for href in re.findall(r'href="([^"]+)"', body):
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        parsed = urlparse(href)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"

        linked_response = client.get(target)
        assert linked_response.status_code < 400, f"Broken link {target} from {route}"