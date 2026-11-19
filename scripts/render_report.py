"""Render a saved /api/audit JSON response as the Markdown report used in RESULTS.md.

    curl -s -X POST localhost:8000/api/audit -H "Content-Type: application/json" \
         -d '{"url": "https://www.allbirds.com/", "max_pages": 10, "request_delay": 0.3}' > audit.json
    python scripts/render_report.py audit.json > report.md

It only formats values from the JSON; it does not compute anything.
"""

import json
import sys

STATUS = {"good": "Pass", "warning": "Warning", "bad": "Fail", "unavailable": "Not measured", "not_applicable": "N/A"}


def render(audit: dict) -> str:
    lines = [
        f"**Audited:** {audit['url']} on {audit['created_at'][:10]} · **pages crawled:** {audit['pages_crawled']}",
        "",
        f"## Overall SEO score: {audit['overall_score']} / 100",
        "",
        f"{audit['summary']} The score covers {round(audit['coverage'] * 100)}% of the metric weight; "
        "metrics that were not measured or do not apply are left out rather than scored 0.",
        "",
        "## The five metrics",
        "",
        "| Metric | Weight | Status | Score | Finding |",
        "|---|---:|---|---:|---|",
    ]
    for metric in audit["metrics"]:
        score = "—" if metric["score"] is None else metric["score"]
        lines.append(f"| {metric['title']} | {metric['weight']} | {STATUS[metric['status']]} | {score} | {metric['summary']} |")

    plan = audit["action_plan"]
    source = f"LLM ({plan['model']})" if plan["source"] == "llm" else f"rule-based fallback: {plan['reason']}"
    lines += ["", "## Action list for this week", "", f"_Source: {source}_", ""]
    for action in plan["actions"]:
        lines.append(f"{action['priority']}. **{action['action']}** {action['why']}")
        if action["pages"]:
            lines.append(f"   Pages: {', '.join(action['pages'])}")

    title_meta = next(metric for metric in audit["metrics"] if metric["id"] == "title_meta")
    lines += ["", "## Title and meta description by page", "",
              "| Page | Title length (30-60) | Description length (70-160) | Result |", "|---|---:|---:|---|"]
    for row in title_meta.get("pages", []):
        title = row["title_length"] if row["title_present"] else "missing"
        description = row["meta_description_length"] if row["meta_description_present"] else "missing"
        result = "Pass" if row["status"] == "good" else "Fail: " + "; ".join(row["issues"])
        lines.append(f"| {row['url']} | {title} | {description} | {result} |")

    lines += ["", "## Broken internal links", ""]
    if audit["broken_links"]:
        lines += ["| Found on | Broken link | HTTP |", "|---|---|---:|"]
        lines += [f"| {link['source']} | {link['destination']} | {link['status']} |" for link in audit["broken_links"]]
    else:
        lines.append("None found.")

    for metric in audit["metrics"]:
        if metric["id"] != "title_meta" and metric["evidence"]:
            lines += ["", f"**{metric['title']} evidence:**", ""] + [f"- {item}" for item in metric["evidence"]]
    if audit["crawl_errors"]:
        lines += ["", "**Could not verify:**", ""]
        lines += [f"- {error['url']} ({error['type']})" for error in audit["crawl_errors"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    with open(sys.argv[1], encoding="utf-8") as handle:
        sys.stdout.write(render(json.load(handle)))
