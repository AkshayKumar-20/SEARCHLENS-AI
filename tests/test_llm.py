import json
from types import SimpleNamespace
from unittest.mock import Mock

import requests

from backend.app.audits import build_report
from backend.app.llm import build_findings, generate_action_plan, parse_actions

PRODUCT = "https://shop.example.com/products/blue-widget"
HOME = "https://shop.example.com/"


def failing_report():
    pages = [
        {"url": HOME, "title": "Shop", "meta_description": "", "text": "Welcome", "structured_data": []},
        {"url": PRODUCT, "title": "Blue Widget - Durable Outdoor Gear", "text": "Blue Widget",
         "meta_description": "A useful product description that is long enough to represent a real search snippet.",
         "structured_data": []},
    ]
    crawl = {"broken_links": [{"source": HOME, "destination": "https://shop.example.com/gone", "status": 404}]}
    return build_report(pages, crawl)


def config(**overrides):
    values = {"llm_base_url": "https://api.example-llm.com/v1", "llm_api_key": "test-key", "llm_model": "test-model", "llm_timeout": 5}
    return SimpleNamespace(**{**values, **overrides})


def llm_session(content):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    session = Mock()
    session.post.return_value = response
    return session


def test_without_llm_config_uses_fallback_and_never_calls_network():
    session = Mock()
    plan = generate_action_plan(HOME, failing_report(), config(llm_base_url="", llm_model=""), session=session)
    session.post.assert_not_called()
    assert plan["source"] == "fallback"
    assert "SEARCHLENS_LLM_BASE_URL" in plan["reason"]
    # Ordered by points lost (weight x shortfall): broken links 25x100, product schema
    # 20x100 (product page has no JSON-LD), title/meta 20x50 (one of two pages fails).
    assert [action["metric_id"] for action in plan["actions"]] == ["broken_internal_links", "product_structured_data", "title_meta"]


def test_valid_llm_reply_becomes_the_action_list():
    reply = json.dumps({"actions": [
        {"metric_id": "broken_internal_links", "action": "Remove the dead link on the homepage.", "why": "Visitors hit a 404.", "pages": [HOME]},
        {"metric_id": "title_meta", "action": "Add a meta description to the homepage.", "why": "Better snippet.", "pages": [HOME]},
    ]})
    session = llm_session(f"```json\n{reply}\n```")
    plan = generate_action_plan(HOME, failing_report(), config(), session=session)
    assert plan["source"] == "llm"
    assert plan["model"] == "test-model"
    assert plan["provider"] == "api.example-llm.com"
    assert [action["priority"] for action in plan["actions"]] == [1, 2]
    call = session.post.call_args
    assert call.args[0] == "https://api.example-llm.com/v1/chat/completions"
    assert call.kwargs["json"]["model"] == "test-model"
    assert call.kwargs["headers"] == {"Authorization": "Bearer test-key"}


def test_full_chat_completions_url_and_empty_key_are_accepted():
    # Local servers such as Ollama need no key, and some docs give the full endpoint URL.
    reply = json.dumps({"actions": [{"metric_id": "title_meta", "action": "Fix titles.", "pages": []}]})
    session = llm_session(reply)
    plan = generate_action_plan(HOME, failing_report(), config(llm_base_url="http://localhost:11434/v1/chat/completions/", llm_api_key=""), session=session)
    assert plan["source"] == "llm"
    assert session.post.call_args.args[0] == "http://localhost:11434/v1/chat/completions"
    assert session.post.call_args.kwargs["headers"] == {}


def test_llm_cannot_invent_urls_or_metrics():
    reply = json.dumps({"actions": [
        {"metric_id": "backlinks", "action": "Buy backlinks.", "pages": []},
        {"metric_id": "title_meta", "action": "Fix titles.", "pages": [HOME, "https://invented.example.com/page"]},
    ]})
    actions = parse_actions(reply, failing_report())
    assert len(actions) == 1
    assert actions[0]["metric_id"] == "title_meta"
    assert actions[0]["pages"] == [HOME]


def test_llm_cannot_change_the_score():
    report = failing_report()
    score_before = report["overall_score"]
    reply = json.dumps({"overall_score": 100, "actions": [{"metric_id": "title_meta", "action": "Fix titles.", "pages": []}]})
    plan = generate_action_plan(HOME, report, config(), session=llm_session(reply))
    assert plan["source"] == "llm"
    assert report["overall_score"] == score_before
    assert "overall_score" not in plan


def test_unusable_llm_reply_falls_back_with_a_reason():
    plan = generate_action_plan(HOME, failing_report(), config(), session=llm_session("Sure! Here are some tips..."))
    assert plan["source"] == "fallback"
    assert "could not be used" in plan["reason"]
    assert plan["actions"]


def test_llm_http_error_falls_back_without_leaking_the_key():
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError(response=SimpleNamespace(status_code=429))
    session = Mock()
    session.post.return_value = response
    plan = generate_action_plan(HOME, failing_report(), config(llm_api_key="secret-123"), session=session)
    assert plan["source"] == "fallback"
    assert "HTTP 429" in plan["reason"]
    assert "secret-123" not in json.dumps(plan)


def test_findings_sent_to_llm_hold_no_page_body_text():
    findings = build_findings(HOME, failing_report())
    assert {metric["id"] for metric in findings["failing_metrics"]} == {"title_meta", "broken_internal_links", "product_structured_data"}
    assert "Welcome" not in json.dumps(findings)


def test_all_metrics_passing_needs_no_llm_call():
    report = build_report([], {})
    session = Mock()
    plan = generate_action_plan(HOME, report, config(), session=session)
    assert plan["source"] == "none"
    session.post.assert_not_called()
