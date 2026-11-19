"""The five SEO metrics and the overall score, computed only from crawl evidence.

Each metric returns a status (good / warning / bad / unavailable / not_applicable),
a 0-100 score (None when it could not be measured or does not apply), a one-line
summary, and the evidence behind it. Nothing in this module calls an LLM.
"""

from .structured_data import analyze_product_schemas

TITLE_RANGE = (30, 60)
DESCRIPTION_RANGE = (70, 160)

# Weights for the overall score. Broken links weigh most because a broken link
# is an unambiguous defect that costs both users and crawlers.
WEIGHTS = {
    "title_meta": 20,
    "broken_internal_links": 25,
    "page_indexability": 20,
    "core_web_vitals": 15,
    "product_structured_data": 20,
}

# Statuses that mean "we have no measurement", so the metric is left out of the score.
UNSCORED = {"unavailable", "not_applicable"}


def _score(value: float) -> float:
    return round(max(0, min(100, value)), 1)


def _metadata_rows(pages: list[dict]) -> list[dict]:
    rows = []
    for page in pages:
        title = page.get("title", "") or ""
        description = page.get("meta_description", "") or ""
        title_length = page.get("title_length", len(title))
        description_length = page.get("meta_description_length", len(description))
        issues = []
        if not title.strip():
            issues.append("missing title")
        elif not TITLE_RANGE[0] <= title_length <= TITLE_RANGE[1]:
            issues.append(f"title length {title_length} is outside 30-60")
        if not description.strip():
            issues.append("missing meta description")
        elif not DESCRIPTION_RANGE[0] <= description_length <= DESCRIPTION_RANGE[1]:
            issues.append(f"description length {description_length} is outside 70-160")
        rows.append({
            "url": page.get("url", ""),
            "title": title,
            "title_present": bool(title.strip()),
            "title_length": title_length,
            "meta_description": description,
            "meta_description_present": bool(description.strip()),
            "meta_description_length": description_length,
            "status": "good" if not issues else "bad",
            "issues": issues,
        })
    return rows


def _indexability_rows(pages: list[dict], crawl: dict) -> tuple[list[dict], list[dict], list[dict]]:
    rows = []
    for page in pages:
        status_code = page.get("status_code", 200)
        noindex = bool(page.get("noindex"))
        http_ok = isinstance(status_code, int) and 200 <= status_code <= 299
        indexable = page.get("indexable")
        if indexable is None:
            indexable = http_ok and not noindex
        issues = []
        if not http_ok:
            issues.append(f"HTTP {status_code}")
        if noindex:
            if page.get("x_robots_tag"):
                issues.append("X-Robots-Tag noindex")
            if page.get("meta_robots"):
                issues.append("meta robots noindex")
            if not page.get("x_robots_tag") and not page.get("meta_robots"):
                issues.append("noindex directive")
        rows.append({
            "url": page.get("url", ""),
            "status_code": status_code,
            "noindex": noindex,
            "nofollow": bool(page.get("nofollow")),
            "meta_robots": page.get("meta_robots", ""),
            "x_robots_tag": page.get("x_robots_tag", ""),
            "indexable": bool(indexable),
            "reason": page.get("indexability_reason", "indexable" if indexable else "not indexable"),
            "issues": issues,
        })
    blocked = [
        {"url": url, "status": None, "reason": "Blocked by robots.txt", "issues": ["robots.txt disallow"]}
        for url in crawl.get("blocked_by_robots", [])
    ]
    http_errors = []
    seen_errors = set()
    for error in crawl.get("crawl_errors", []):
        status_code = error.get("status")
        # 429 is the site rate-limiting the crawler, not a property of the page.
        if isinstance(status_code, int) and 400 <= status_code <= 599 and status_code != 429 and error.get("url") not in seen_errors:
            seen_errors.add(error.get("url"))
            http_errors.append({
                "url": error.get("url", ""),
                "status_code": status_code,
                "reason": f"HTTP {status_code}",
                "issues": [f"HTTP {status_code}"],
            })
    return rows, blocked, http_errors


def _cwv_rows(crawl: dict) -> list[dict]:
    metrics = (crawl.get("core_web_vitals") or {}).get("metrics") or {}
    rows = []
    for key, label in (("lcp", "LCP"), ("inp", "INP"), ("cls", "CLS")):
        metric = metrics.get(key) or {}
        value = metric.get("value")
        unit = metric.get("unit", "")
        if isinstance(value, (int, float)) and key in {"lcp", "inp"}:
            display = f"{value / 1000:.1f} s" if value >= 1000 else f"{round(value)} ms"
        elif isinstance(value, (int, float)):
            display = f"{value:.3f}"
        else:
            display = "not measured"
        rows.append({
            "name": key,
            "label": label,
            "value": value,
            "unit": unit,
            "display": display,
            "status": metric.get("status", "unavailable"),
            "target": metric.get("target", ""),
            "note": metric.get("note", ""),
        })
    return rows


def title_meta_metric(pages: list[dict]) -> dict:
    if not pages:
        return {"score": None, "status": "unavailable", "summary": "No HTML pages were crawled.", "evidence": [], "pages": []}
    rows = _metadata_rows(pages)
    failed = [row for row in rows if row["status"] != "good"]
    evidence = [f"{row['url']}: {', '.join(row['issues'])}" for row in failed[:10]]
    summary = (
        f"All {len(rows)} crawled page(s) have a title and meta description in range."
        if not failed
        else f"{len(failed)} of {len(rows)} crawled page(s) have a missing or out-of-range title or meta description."
    )
    return {
        "score": _score((len(rows) - len(failed)) / len(rows) * 100),
        "status": "good" if not failed else "bad",
        "summary": summary,
        "evidence": evidence,
        "pages": rows,
    }


def broken_links_metric(pages: list[dict], crawl: dict) -> dict:
    broken = crawl.get("broken_links", [])
    if not pages and not broken:
        return {"score": None, "status": "unavailable", "summary": "No internal links could be checked.", "evidence": [], "broken_links": []}
    evidence = [
        f"{item.get('source', '')} -> {item.get('destination', '')} (HTTP {item.get('status', 'unknown')})"
        for item in broken[:10]
    ]
    checked = crawl.get("link_targets_checked")
    unverified = crawl.get("link_targets_unverified") or 0
    checked_note = f" across {checked} checked internal URL(s)" if isinstance(checked, int) else ""
    # Links we could not check (timeouts, rate limiting) are not counted as broken,
    # but the summary says how many there were so "0 broken" is not overstated.
    unverified_note = f" {unverified} URL(s) could not be verified (timeout or rate limiting)." if unverified else ""
    skipped = crawl.get("link_targets_skipped") or 0
    if skipped:
        unverified_note += f" {skipped} more URL(s) were not checked (link-check limit reached)."
    return {
        "score": 100 if not broken else 0,
        "status": "good" if not broken else "bad",
        "summary": (f"No broken internal links found{checked_note}." if not broken else f"{len(broken)} broken internal link(s) found{checked_note}.") + unverified_note,
        "evidence": evidence,
        "broken_links": broken,
    }


def indexability_metric(pages: list[dict], crawl: dict) -> dict:
    rows, blocked, http_errors = _indexability_rows(pages, crawl)
    failures = [row for row in rows if not row["indexable"]]
    total = len(rows) + len(blocked) + len(http_errors)
    if total == 0:
        return {"score": None, "status": "unavailable", "summary": "No pages or blocked URLs were available for indexability checks.", "evidence": [], "pages": [], "blocked_urls": [], "http_errors": []}
    failed_count = len(failures) + len(blocked) + len(http_errors)
    evidence = [f"{row['url']}: {', '.join(row['issues']) or row['reason']}" for row in failures[:6]]
    evidence += [f"{row['url']}: {row['reason']}" for row in blocked[:6]]
    evidence += [f"{row['url']}: {row['reason']}" for row in http_errors[:6]]
    summary = (
        "All crawled pages are indexable."
        if failed_count == 0
        else f"{failed_count} of {total} URL(s) are blocked by robots.txt, marked noindex, or returned an HTTP error."
    )
    return {
        "score": _score((total - failed_count) / total * 100),
        "status": "good" if failed_count == 0 else "bad",
        "summary": summary,
        "evidence": evidence,
        "pages": rows,
        "blocked_urls": blocked,
        "http_errors": http_errors,
    }


def core_web_vitals_metric(crawl: dict) -> dict:
    rows = _cwv_rows(crawl)
    measured = [row for row in rows if row["status"] != "unavailable"]
    evidence = [
        f"{row['label']} {row['display']} ({row['status'].replace('_', ' ')}; target {row['target']})"
        for row in rows
    ]
    if not measured:
        reason = (crawl.get("core_web_vitals") or {}).get("reason") or "Core Web Vitals were not measured."
        return {"score": None, "status": "unavailable", "summary": reason, "evidence": evidence, "metrics": rows}
    weights = {"good": 100, "needs_improvement": 50, "poor": 0}
    score = sum(weights.get(row["status"], 0) for row in measured) / len(measured)
    status = "good"
    if any(row["status"] == "poor" for row in measured):
        status = "bad"
    elif any(row["status"] != "good" for row in measured) or len(measured) < len(rows):
        status = "warning"
    outside = ", ".join(row["label"] for row in measured if row["status"] != "good") or "none"
    return {
        "score": _score(score),
        "status": status,
        "summary": (
            "All measured Core Web Vitals are in the good range."
            if status == "good"
            else f"Core Web Vitals outside the good range: {outside}."
        ),
        "evidence": evidence,
        "metrics": rows,
    }


def product_schema_metric(pages: list[dict]) -> dict:
    analysis = analyze_product_schemas(pages)
    if not analysis["applicable"]:
        return {
            "score": None,
            "status": "not_applicable",
            "summary": "No product pages were found in the crawl, so Product schema was not scored.",
            "evidence": [],
            "pages": [],
        }
    evidence = [
        f"{page['url']}: {', '.join(page['issues'])}"
        for page in analysis["pages"]
        if page["status"] != "good"
    ][:10]
    return {
        "score": _score(analysis["valid_page_count"] / analysis["page_count"] * 100),
        "status": "good" if analysis["invalid_page_count"] == 0 else "bad",
        "summary": (
            f"Valid Product schema was found on all {analysis['page_count']} product page(s)."
            if analysis["invalid_page_count"] == 0
            else f"{analysis['invalid_page_count']} of {analysis['page_count']} product page(s) have missing, invalid, or mismatched Product schema."
        ),
        "evidence": evidence,
        "pages": analysis["pages"],
    }


def build_report(pages: list[dict], crawl: dict) -> dict:
    """Return the five metrics and the weighted overall score.

    Metrics that could not be measured (unavailable) or do not apply to this site
    (not_applicable) are left out of the score, and `coverage` says how much of the
    total weight was actually measured.
    """
    metrics = [
        {"id": "title_meta", "title": "Title & Meta Description", "mandatory": True,
         "target": "Title 30-60 characters; meta description 70-160 characters.",
         "bad": "A title or meta description is missing or outside the target range.",
         "action": "Rewrite titles to 30-60 characters and meta descriptions to 70-160 characters, and add any that are missing.",
         **title_meta_metric(pages)},
        {"id": "broken_internal_links", "title": "Broken Internal Links", "mandatory": True,
         "target": "Zero internal links returning HTTP 4xx or 5xx.",
         "bad": "One or more internal links return HTTP 4xx or 5xx.",
         "action": "Fix or remove each broken internal link on the page where it was found.",
         **broken_links_metric(pages, crawl)},
        {"id": "page_indexability", "title": "Page Indexability", "mandatory": False,
         "target": "Every crawled page returns HTTP 2xx and is not blocked by robots.txt or marked noindex.",
         "bad": "A page is blocked by robots.txt, marked noindex (meta tag or X-Robots-Tag), or returns an HTTP error.",
         "action": "Check each non-indexable page: remove noindex or robots.txt blocks from pages that should rank, and leave intentional ones alone.",
         **indexability_metric(pages, crawl)},
        {"id": "core_web_vitals", "title": "Core Web Vitals", "mandatory": False,
         "target": "LCP <= 2.5 s, INP <= 200 ms, CLS <= 0.1 (Google's 'good' thresholds).",
         "bad": "LCP > 2.5 s, INP > 200 ms, or CLS > 0.1.",
         "action": "Use the PageSpeed Insights report to fix the slow or unstable element on the start page template.",
         **core_web_vitals_metric(crawl)},
        {"id": "product_structured_data", "title": "Product Structured Data", "mandatory": False,
         "target": "Product pages carry valid Product JSON-LD (name, image, offers with price, currency, availability) that matches visible content.",
         "bad": "Product schema is missing, invalid, incomplete, or does not match the visible page.",
         "action": "Add or correct Product JSON-LD so name, image, price, currency and availability match what the page shows.",
         **product_schema_metric(pages)},
    ]
    for metric in metrics:
        metric["weight"] = WEIGHTS[metric["id"]]

    scored = [metric for metric in metrics if metric["status"] not in UNSCORED]
    scored_weight = sum(metric["weight"] for metric in scored)
    overall = sum(metric["score"] * metric["weight"] for metric in scored) / scored_weight if scored else 0
    needs_attention = [metric for metric in scored if metric["status"] in {"bad", "warning"}]
    if not scored:
        summary = "None of the five metrics could be measured from this crawl."
    elif not needs_attention:
        summary = f"All {len(scored)} measured metrics passed."
    else:
        summary = f"{len(needs_attention)} of {len(scored)} measured metrics need attention."
    return {
        "overall_score": _score(overall),
        "coverage": round(scored_weight / sum(WEIGHTS.values()), 2),
        "summary": summary,
        "metrics": metrics,
    }
