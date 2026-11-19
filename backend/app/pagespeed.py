"""Core Web Vitals measurement through the PageSpeed Insights API.

The API is optional. When no key is configured the audit reports an explicit
unavailable state instead of inventing metrics.
"""

from datetime import datetime, timezone

import requests

PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

THRESHOLDS = {
    "lcp": {"unit": "ms", "good": 2500, "needs_improvement": 4000, "target": "<= 2.5 s"},
    "inp": {"unit": "ms", "good": 200, "needs_improvement": 500, "target": "<= 200 ms"},
    "cls": {"unit": "score", "good": 0.1, "needs_improvement": 0.25, "target": "<= 0.1"},
}


def _status(value: float, good: float, needs_improvement: float) -> str:
    if value <= good:
        return "good"
    if value <= needs_improvement:
        return "needs_improvement"
    return "poor"


def _measured(value, name: str, note: str = "") -> dict:
    threshold = THRESHOLDS[name]
    if not isinstance(value, (int, float)):
        return {
            "value": None,
            "unit": threshold["unit"],
            "status": "unavailable",
            "target": threshold["target"],
            "note": note or "Not returned by PageSpeed Insights.",
        }
    rounded = round(float(value), 3) if name == "cls" else round(float(value))
    metric = {
        "value": rounded,
        "unit": threshold["unit"],
        "status": _status(rounded, threshold["good"], threshold["needs_improvement"]),
        "target": threshold["target"],
    }
    if note:
        metric["note"] = note
    return metric


def _field_value(metrics: dict, key: str):
    entry = metrics.get(key)
    if not isinstance(entry, dict):
        return None
    value = entry.get("percentile")
    if isinstance(value, (int, float)):
        return value
    return None


def _lab_value(audits: dict, key: str):
    entry = audits.get(key)
    if not isinstance(entry, dict):
        return None
    value = entry.get("numericValue")
    if isinstance(value, (int, float)):
        return value
    return None


def _overall_status(metrics: dict) -> str:
    measured = [metric for metric in metrics.values() if metric["status"] != "unavailable"]
    if not measured:
        return "unavailable"
    statuses = {metric["status"] for metric in measured}
    if "poor" in statuses:
        return "bad"
    if "needs_improvement" in statuses or len(measured) < len(metrics):
        return "warning"
    return "good"


def measure_core_web_vitals(
    url: str,
    api_key: str = "",
    strategy: str = "mobile",
    timeout: float = 20.0,
    session=None,
) -> dict:
    if not api_key:
        return {
            "status": "unavailable",
            "source": "none",
            "strategy": strategy,
            "url": url,
            "reason": "Set SEARCHLENS_PAGESPEED_API_KEY to measure Core Web Vitals.",
            "measured_at": None,
            "metrics": {
                name: _measured(None, name, "PageSpeed Insights is not configured.")
                for name in THRESHOLDS
            },
        }

    try:
        response = (session or requests.Session()).get(
            PAGESPEED_ENDPOINT,
            params={"url": url, "strategy": strategy, "category": "performance", "key": api_key},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        return {
            "status": "unavailable",
            "source": "pagespeed",
            "strategy": strategy,
            "url": url,
            "reason": f"PageSpeed Insights could not be reached or returned invalid data: {type(exc).__name__}.",
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "metrics": {
                name: _measured(None, name, "Measurement failed.")
                for name in THRESHOLDS
            },
        }

    if not isinstance(payload, dict):
        payload = {}
    field_metrics = ((payload.get("loadingExperience") or {}).get("metrics") or {})
    lab_audits = ((payload.get("lighthouseResult") or {}).get("audits") or {})

    field_lcp = _field_value(field_metrics, "LARGEST_CONTENTFUL_PAINT_MS")
    field_inp = _field_value(field_metrics, "INTERACTION_TO_NEXT_PAINT")
    field_cls = _field_value(field_metrics, "CUMULATIVE_LAYOUT_SHIFT_SCORE")
    if field_cls is not None:
        field_cls = field_cls / 100

    lab_lcp = _lab_value(lab_audits, "largest-contentful-paint")
    lab_cls = _lab_value(lab_audits, "cumulative-layout-shift")

    lcp = field_lcp if field_lcp is not None else lab_lcp
    inp = field_inp
    cls = field_cls if field_cls is not None else lab_cls

    if field_lcp is not None or field_inp is not None or field_cls is not None:
        source = "Chrome UX Report field data"
    elif lab_lcp is not None or lab_cls is not None:
        source = "Lighthouse lab data"
    else:
        source = "pagespeed"

    metrics = {
        "lcp": _measured(lcp, "lcp"),
        "inp": _measured(
            inp,
            "inp",
            "INP requires Chrome UX Report field data and was not returned for this URL.",
        ),
        "cls": _measured(cls, "cls"),
    }
    status = _overall_status(metrics)
    return {
        "status": "unavailable" if status == "unavailable" else "measured",
        "overall_status": status,
        "source": source,
        "strategy": strategy,
        "url": url,
        "reason": "" if status != "unavailable" else "No Core Web Vital was returned.",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
    }
