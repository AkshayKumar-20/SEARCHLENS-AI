from unittest.mock import Mock

from backend.app.audits import build_report
from backend.app.pagespeed import measure_core_web_vitals
from backend.app.structured_data import analyze_product_schemas, parse_json_ld, validate_product


def page(**overrides):
    value = {
        "url": "https://shop.example.com/products/blue-widget",
        "title": "Blue Widget - Durable Outdoor Gear",
        "meta_description": "A useful product description that is long enough to represent a real search snippet for this product page.",
        "text": "Blue Widget add to cart. In stock and ready to ship. Price $19.99.",
        "headings": ["Blue Widget"],
        "images_without_alt": 0,
        "structured_data": [
            '{"@context":"https://schema.org","@type":"Product","name":"Blue Widget","image":"https://shop.example.com/blue.jpg","offers":{"@type":"Offer","price":"19.99","priceCurrency":"USD","availability":"https://schema.org/InStock"}}'
        ],
        "links": [],
        "status_code": 200,
        "noindex": False,
        "meta_robots": "",
        "x_robots_tag": "",
        "indexable": True,
        "indexability_reason": "indexable",
        "response_bytes": 12000,
        "resource_count": 8,
    }
    return {**value, **overrides}


def good_crawl(**overrides):
    return {
        "broken_links": [],
        "crawl_errors": [],
        "blocked_by_robots": [],
        "robots_available": True,
        "sitemap_urls": ["https://shop.example.com/sitemap.xml"],
        "core_web_vitals": {
            "status": "measured",
            "overall_status": "good",
            "metrics": {
                "lcp": {"value": 2100, "unit": "ms", "status": "good", "target": "<= 2.5 s"},
                "inp": {"value": 150, "unit": "ms", "status": "good", "target": "<= 200 ms"},
                "cls": {"value": 0.05, "unit": "score", "status": "good", "target": "<= 0.1"},
            },
        },
        **overrides,
    }


def test_title_and_meta_ranges_are_enforced():
    good = build_report([page()], good_crawl())
    title_item = good["metrics"][0]
    assert title_item["status"] == "good"
    assert title_item["pages"][0]["title_length"] == len(page()["title"])
    bad = build_report([page(title="Too short", meta_description="")], good_crawl())
    assert bad["metrics"][0]["status"] == "bad"
    assert len(bad["metrics"][0]["evidence"]) == 1


def test_broken_links_are_reported_with_source():
    crawl = good_crawl(broken_links=[{"source": "https://shop.example.com/", "destination": "https://shop.example.com/products/gone", "status": 404, "anchor_text": "Gone"}])
    report = build_report([page()], crawl)
    item = report["metrics"][1]
    assert item["status"] == "bad"
    assert item["score"] == 0
    assert "https://shop.example.com/ -> https://shop.example.com/products/gone (HTTP 404)" in item["evidence"]


def test_indexability_uses_noindex_x_robots_and_robots_blocks():
    crawl = good_crawl(blocked_by_robots=["https://shop.example.com/private"])
    report = build_report([page(noindex=True, x_robots_tag="noindex", indexable=False, indexability_reason="noindex")], crawl)
    item = report["metrics"][2]
    assert item["status"] == "bad"
    assert any("X-Robots-Tag noindex" in evidence for evidence in item["evidence"])
    assert any("Blocked by robots.txt" in evidence for evidence in item["evidence"])


def test_core_web_vitals_report_uses_measurements_and_unavailable_state():
    report = build_report([page()], good_crawl())
    cwv = report["metrics"][3]
    assert cwv["status"] == "good"
    assert cwv["score"] == 100
    unavailable = build_report([page()], good_crawl(core_web_vitals={}))
    item = unavailable["metrics"][3]
    assert item["status"] == "unavailable"
    assert "not measured" in item["summary"].lower() or "could not" in item["summary"].lower()


def test_product_schema_validation_and_visible_content_match():
    report = build_report([page()], good_crawl())
    product = report["metrics"][4]
    assert product["status"] == "good"
    invalid = build_report([page(structured_data=['{"@type":"Product","name":"Blue Widget"}'])], good_crawl())
    assert invalid["metrics"][4]["status"] == "bad"
    assert "missing product image" in " ".join(invalid["metrics"][4]["evidence"])


def test_structured_data_parser_handles_graph_and_malformed_json():
    nodes, errors = parse_json_ld([
        '{"@context":"https://schema.org","@graph":[{"@type":"Product","name":"A"}]}',
        "{not json",
    ])
    assert len(nodes) == 1
    assert len(errors) == 1
    assert validate_product(nodes[0]) == ["missing product image", "missing offers"]


def test_product_analysis_not_applicable_for_non_product_pages():
    analysis = analyze_product_schemas([page(url="https://example.com/about", text="About our company", structured_data=[])])
    assert analysis["applicable"] is False


def test_pagespeed_parses_crux_field_data():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "loadingExperience": {
            "metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 1800},
                "INTERACTION_TO_NEXT_PAINT": {"percentile": 150},
                "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5},
            }
        }
    }
    session = Mock()
    session.get.return_value = response
    result = measure_core_web_vitals("https://example.com", "key", session=session)
    assert result["status"] == "measured"
    assert result["source"] == "Chrome UX Report field data"
    assert result["overall_status"] == "good"
    assert result["metrics"]["lcp"]["value"] == 1800
    assert result["metrics"]["inp"]["value"] == 150
    assert result["metrics"]["cls"]["value"] == 0.05


def test_pagespeed_uses_lab_data_and_marks_inp_unavailable():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "lighthouseResult": {
            "audits": {
                "largest-contentful-paint": {"numericValue": 4200},
                "cumulative-layout-shift": {"numericValue": 0.3},
            }
        }
    }
    session = Mock()
    session.get.return_value = response
    result = measure_core_web_vitals("https://example.com", "key", session=session)
    assert result["source"] == "Lighthouse lab data"
    assert result["overall_status"] == "bad"
    assert result["metrics"]["lcp"]["status"] == "poor"
    assert result["metrics"]["inp"]["status"] == "unavailable"
    assert result["metrics"]["cls"]["status"] == "poor"


def test_pagespeed_without_key_never_calls_network():
    session = Mock()
    result = measure_core_web_vitals("https://example.com", "", session=session)
    assert result["status"] == "unavailable"
    session.get.assert_not_called()


def test_unmeasured_metrics_are_excluded_from_the_overall_score():
    # Edge case: no PageSpeed data and no product pages. Those two metrics must not
    # count as 0 (which would read as "failed"); they are left out and coverage drops.
    about = page(url="https://example.com/about", text="About our company", structured_data=[])
    report = build_report([about], good_crawl(core_web_vitals={}))
    by_id = {metric["id"]: metric for metric in report["metrics"]}
    assert by_id["core_web_vitals"]["score"] is None
    assert by_id["product_structured_data"]["status"] == "not_applicable"
    assert by_id["product_structured_data"]["score"] is None
    # Remaining weights: title/meta 20 + broken links 25 + indexability 20 = 65 of 100.
    assert report["coverage"] == 0.65
    assert report["overall_score"] == 100
