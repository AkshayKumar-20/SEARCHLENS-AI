import ipaddress
import socket
from unittest.mock import Mock, patch

import pytest
import requests
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.security import UnsafeURL, validate_redirect, validate_url

client = TestClient(app)
REAL_GETADDRINFO = socket.getaddrinfo
METRIC_IDS = ["title_meta", "broken_internal_links", "page_indexability", "core_web_vitals", "product_structured_data"]


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """Resolve hostnames to a public test IP so the suite runs offline.

    IP literals still go through the real resolver, so the private-address checks
    below exercise the real SSRF guard.
    """
    def getaddrinfo(host, port, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port))]
        return REAL_GETADDRINFO(host, port, *args, **kwargs)
    monkeypatch.setattr("backend.app.security.socket.getaddrinfo", getaddrinfo)


def response(text="", status=200, content_type="text/html"):
    r = Mock()
    r.text, r.status_code, r.headers = text, status, {"content-type": content_type}
    r.content = text.encode("utf-8")
    r.ok = status < 400
    r.raise_for_status.side_effect = requests.HTTPError(f"{status} Error", response=r) if status >= 400 else None
    return r


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


# --- Valid input --------------------------------------------------------------

@patch("backend.app.crawler.requests.Session.get")
def test_audit_returns_five_metrics_score_and_action_plan(mock_get):
    html = '<title>Home</title><meta name="description" content="ok"><a href="/about">About</a>'
    mock_get.side_effect = [response(""), response(html), response('<title>About</title>')]
    result = client.post("/api/audit", json={"url": "https://example.com", "max_pages": 2})
    assert result.status_code == 200
    body = result.json()
    assert body["pages_crawled"] == 2
    assert [metric["id"] for metric in body["metrics"]] == METRIC_IDS
    assert 0 <= body["overall_score"] <= 100
    # Titles "Home"/"About" are too short, so title/meta fails and an action is produced.
    assert body["metrics"][0]["status"] == "bad"
    assert body["action_plan"]["source"] == "fallback"  # conftest disables the LLM
    assert body["action_plan"]["actions"][0]["metric_id"] == "title_meta"
    # The stored audit can be read back by id.
    assert client.get(f"/api/audits/{body['id']}").json()["overall_score"] == body["overall_score"]


@patch("backend.app.crawler.requests.Session.get")
def test_audit_page_limit(mock_get):
    mock_get.side_effect = [response(""), response('<a href="/x">x</a><a href="/y">y</a>'), response(""), response("")]
    result = client.post("/api/audit", json={"url": "https://example.com", "max_pages": 1})
    assert result.status_code == 200
    assert result.json()["pages_crawled"] == 1


@patch("backend.app.crawler.requests.Session.get")
def test_broken_link_reports_source_page(mock_get):
    html = '<title>Home</title><a href="/gone">Gone</a>'
    mock_get.side_effect = [response(""), response(html), response("missing", status=404)]
    result = client.post("/api/audit", json={"url": "https://example.com", "max_pages": 1})
    broken = result.json()["broken_links"]
    assert broken == [{"source": "https://example.com/", "destination": "https://example.com/gone", "status": 404, "anchor_text": "Gone"}]
    assert result.json()["metrics"][1]["status"] == "bad"


@patch("backend.app.crawler.requests.Session.get")
def test_sitemap_index_does_not_starve_crawl(mock_get):
    robots = "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml"
    index = '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://example.com/child.xml</loc></sitemap></sitemapindex>'
    child = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/from-sitemap</loc></url></urlset>'
    home = '<title>Home</title><a href="/about">About</a>'
    mock_get.side_effect = [
        response(robots, content_type="text/plain"),
        response(index, content_type="application/xml"),
        response(child, content_type="application/xml"),
        response(home),
        response("<title>About</title>"),
        response("<title>From sitemap</title>"),
    ]
    result = client.post("/api/audit", json={"url": "https://example.com", "max_pages": 3})
    assert result.status_code == 200
    title_meta_rows = result.json()["metrics"][0]["pages"]
    assert [page["url"] for page in title_meta_rows] == [
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/from-sitemap",
    ]


@patch("backend.app.crawler.requests.Session.get")
def test_x_robots_tag_marks_page_noindex(mock_get):
    page_response = response("<title>Home</title>")
    page_response.headers = {"content-type": "text/html", "x-robots-tag": "noindex"}
    mock_get.side_effect = [response(""), page_response]
    result = client.post("/api/audit", json={"url": "https://example.com"})
    page = result.json()["metrics"][2]["pages"][0]
    assert page["noindex"] is True
    assert page["x_robots_tag"] == "noindex"
    assert result.json()["metrics"][2]["status"] == "bad"


# --- Invalid input ------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {},                                                   # url missing
    {"url": "not a url"},
    {"url": "ftp://example.com"},                         # wrong scheme
    {"url": "https://example.com", "max_pages": 0},       # out of range
    {"url": "https://example.com", "max_page": 5},        # typo: unknown field
])
def test_invalid_request_gets_clear_422(body):
    result = client.post("/api/audit", json=body)
    assert result.status_code == 422
    assert isinstance(result.json()["detail"], str) and result.json()["detail"]


def test_private_network_target_is_refused():
    result = client.post("/api/audit", json={"url": "http://127.0.0.1:8000/"})
    assert result.status_code == 400
    assert "Private or reserved" in result.json()["detail"]


def test_unknown_audit_id_is_404():
    assert client.get("/api/audits/not-found").status_code == 404


def test_validate_scheme():
    with pytest.raises(UnsafeURL):
        validate_url("ftp://example.com")


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://10.0.0.1/", "http://[::1]/"])
def test_validate_rejects_private_addresses(url):
    with pytest.raises(UnsafeURL):
        validate_url(url)


def test_validate_redirect_stays_on_audited_host():
    with pytest.raises(UnsafeURL):
        validate_redirect("https://other.example/path", "example.com")


# --- Edge cases: nothing crawlable gives an explanation, not a score of 0 --------

@patch("backend.app.crawler.requests.Session.get")
def test_start_page_404_is_explained(mock_get):
    mock_get.side_effect = [response(""), response("missing", status=404)]
    result = client.post("/api/audit", json={"url": "https://example.com/old-page"})
    assert result.status_code == 422
    assert "No HTML page could be crawled" in result.json()["detail"]
    assert "404" in result.json()["detail"]


@patch("backend.app.crawler.requests.Session.get")
def test_robots_txt_blocking_everything_is_explained(mock_get):
    mock_get.side_effect = [response("User-agent: *\nDisallow: /")]
    result = client.post("/api/audit", json={"url": "https://example.com"})
    assert result.status_code == 422
    assert "Blocked by robots.txt" in result.json()["detail"]


@patch("backend.app.crawler.requests.Session.get")
def test_non_html_start_url_is_explained(mock_get):
    mock_get.side_effect = [response(""), response("data", content_type="application/pdf")]
    result = client.post("/api/audit", json={"url": "https://example.com/brochure.pdf"})
    assert result.status_code == 422
    assert "Non-HTML" in result.json()["detail"]


@patch("backend.app.crawler.time.sleep")
@patch("backend.app.crawler.requests.Session.get")
def test_rate_limited_link_is_unverified_not_broken(mock_get, mock_sleep):
    # Found in the live Allbirds run: the site answered 429 to our link checks and
    # 8 healthy product pages were reported as broken links.
    html = '<title>Home</title><a href="/products/shoe">Shoe</a>'
    mock_get.side_effect = [response(""), response(html), response("slow down", status=429), response("slow down", status=429)]
    result = client.post("/api/audit", json={"url": "https://example.com", "max_pages": 1})
    body = result.json()
    assert body["broken_links"] == []
    assert body["metrics"][1]["status"] == "good"
    assert "1 URL(s) could not be verified" in body["metrics"][1]["summary"]
    assert any(error["type"] == "rate_limited" for error in body["crawl_errors"])
    mock_sleep.assert_called_once()  # exactly one polite retry


@patch("backend.app.crawler.time.sleep")
@patch("backend.app.crawler.requests.Session.get")
def test_rate_limit_retry_that_succeeds_is_checked_normally(mock_get, mock_sleep):
    html = '<title>Home</title><a href="/gone">Gone</a>'
    mock_get.side_effect = [response(""), response(html), response("slow down", status=429), response("missing", status=404)]
    result = client.post("/api/audit", json={"url": "https://example.com", "max_pages": 1})
    assert [link["status"] for link in result.json()["broken_links"]] == [404]


def test_nat64_address_of_a_public_site_is_allowed():
    # Found auditing https://www.kitsw.ac.in/ on an IPv6-only ISP: DNS64 returned
    # 64:ff9b::7712:3692, which wraps the public IPv4 119.18.54.146. Python flags the
    # whole NAT64 prefix as "reserved", so the site was wrongly refused.
    assert validate_url("http://[64:ff9b::7712:3692]/") == "http://[64:ff9b::7712:3692]/"


@pytest.mark.parametrize("url", [
    "http://[64:ff9b::7f00:1]/",       # NAT64 wrapping 127.0.0.1
    "http://[64:ff9b::a00:1]/",        # NAT64 wrapping 10.0.0.1
    "http://[::ffff:10.0.0.1]/",       # IPv4-mapped private address
])
def test_wrapped_private_ipv4_is_still_refused(url):
    with pytest.raises(UnsafeURL):
        validate_url(url)


@patch("backend.app.crawler.requests.Session.get")
def test_link_checks_are_capped_streamed_and_reported(mock_get, monkeypatch):
    # Edge case from a college site with 300+ links and many PDFs: the audit ran for
    # over 10 minutes. Link checks are now capped, and bodies are never downloaded.
    monkeypatch.setattr("backend.app.main.settings.max_link_checks", 1)
    html = '<title>Home</title><a href="/a.pdf">A</a><a href="/b">B</a>'
    mock_get.side_effect = [response(""), response(html), response("pdf bytes", content_type="application/pdf")]
    body = client.post("/api/audit", json={"url": "https://example.com", "max_pages": 1}).json()
    link_check_call = mock_get.call_args_list[2]
    assert link_check_call.args[0] == "https://example.com/a.pdf"
    assert link_check_call.kwargs["stream"] is True
    assert mock_get.call_count == 3  # /b was not requested
    assert "1 more URL(s) were not checked" in body["metrics"][1]["summary"]
