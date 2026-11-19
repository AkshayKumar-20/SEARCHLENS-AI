# Results

## The website and why I chose it

**Allbirds** (`https://www.allbirds.com/`), a direct-to-consumer shoe brand.

1. **It is a real product website**, which is what the brief describes. It has a homepage, category (collection) pages, product pages and internal search, so all five metrics have something to measure. A SaaS landing page would have made Product schema "N/A".
2. **It is a site a marketing team would actually run:** seasonal campaign collections (the Black Friday `bfcm-*` pages) are created quickly by marketers, and that is exactly where metadata tends to be skipped.
3. **It is well-built, so the audit has to be precise.** A broken site would make any tool look good. On a mostly healthy site, false positives show up, and the first run exposed one (rate-limited links counted as broken, see DECISIONS.md #2).
4. **It is public and robots.txt allows the pages crawled.** I crawled 10 public pages with a 0.3 s delay and did not touch cart, checkout or account pages.

## How this report was produced

```bash
curl -s -X POST localhost:8000/api/audit -H "Content-Type: application/json"      -d '{"url": "https://www.allbirds.com/", "max_pages": 10, "request_delay": 0.3}' > audit.json
python scripts/render_report.py audit.json
```

Everything between the two lines below is the script's output, unedited. The numbers are a point-in-time sample and will change as the site changes.

> **Status of this run:** no PageSpeed key and no LLM were configured, so Core Web Vitals is "Not measured" (left out of the score) and the action list is the labelled rule-based fallback. **Re-run with `SEARCHLENS_LLM_BASE_URL`, `SEARCHLENS_LLM_API_KEY` and `SEARCHLENS_LLM_MODEL` (and ideally `SEARCHLENS_PAGESPEED_API_KEY`) set and replace this section** before submitting.

---

**Audited:** https://www.allbirds.com/ on 2026-11-19 · **pages crawled:** 10

## Overall SEO score: 78.8 / 100

2 of 4 measured metrics need attention. The score covers 85% of the metric weight; metrics that were not measured or do not apply are left out rather than scored 0.

## The five metrics

| Metric | Weight | Status | Score | Finding |
|---|---:|---|---:|---|
| Title & Meta Description | 20 | Fail | 20.0 | 8 of 10 crawled page(s) have a missing or out-of-range title or meta description. |
| Broken Internal Links | 25 | Pass | 100.0 | No broken internal links found across 70 checked internal URL(s). |
| Page Indexability | 20 | Fail | 90.0 | 1 of 10 URL(s) are blocked by robots.txt, marked noindex, or returned an HTTP error. |
| Core Web Vitals | 15 | Not measured | — | Set SEARCHLENS_PAGESPEED_API_KEY to measure Core Web Vitals. |
| Product Structured Data | 20 | Pass | 100.0 | Valid Product schema was found on all 1 product page(s). |

## Action list for this week

_Source: rule-based fallback: No LLM configured. Set SEARCHLENS_LLM_BASE_URL and SEARCHLENS_LLM_MODEL (and SEARCHLENS_LLM_API_KEY if the API needs one)._

1. **Rewrite titles to 30-60 characters and meta descriptions to 70-160 characters, and add any that are missing.** 8 of 10 crawled page(s) have a missing or out-of-range title or meta description.
   Pages: https://www.allbirds.com/collections/bfcm-mens, https://www.allbirds.com/collections/bfcm-womens, https://www.allbirds.com/search, https://www.allbirds.com/collections/bfcm-all, https://www.allbirds.com/collections/shop-all-26
2. **Check each non-indexable page: remove noindex or robots.txt blocks from pages that should rank, and leave intentional ones alone.** 1 of 10 URL(s) are blocked by robots.txt, marked noindex, or returned an HTTP error.
   Pages: https://www.allbirds.com/search

## Title and meta description by page

| Page | Title length (30-60) | Description length (70-160) | Result |
|---|---:|---:|---|
| https://www.allbirds.com/ | 50 | 151 | Pass |
| https://www.allbirds.com/collections/bfcm-mens | 11 | missing | Fail: title length 11 is outside 30-60; missing meta description |
| https://www.allbirds.com/collections/bfcm-womens | 13 | missing | Fail: title length 13 is outside 30-60; missing meta description |
| https://www.allbirds.com/search | 17 | missing | Fail: title length 17 is outside 30-60; missing meta description |
| https://www.allbirds.com/collections/bfcm-all | 10 | missing | Fail: title length 10 is outside 30-60; missing meta description |
| https://www.allbirds.com/collections/shop-all-26 | 12 | 212 | Fail: title length 12 is outside 30-60; description length 212 is outside 70-160 |
| https://www.allbirds.com/collections/mens-new-arrivals | 69 | 133 | Fail: title length 69 is outside 30-60 |
| https://www.allbirds.com/collections/mens-bestsellers | 55 | 144 | Pass |
| https://www.allbirds.com/collections/mens-terralux-cl | 74 | 251 | Fail: title length 74 is outside 30-60; description length 251 is outside 70-160 |
| https://www.allbirds.com/products/mens-wool-runners | 83 | 298 | Fail: title length 83 is outside 30-60; description length 298 is outside 70-160 |

## Broken internal links

None found.

**Page Indexability evidence:**

- https://www.allbirds.com/search: meta robots noindex

**Core Web Vitals evidence:**

- LCP not measured (unavailable; target <= 2.5 s)
- INP not measured (unavailable; target <= 200 ms)
- CLS not measured (unavailable; target <= 0.1)

---

## What a marketer should take from it

- **Metadata is the main problem, and it sits on the newest pages.** The homepage and the bestsellers collection pass. The Black Friday collections (`bfcm-mens`, `bfcm-womens`, `bfcm-all`) have 10–13-character titles and no meta description at all. Those are the pages the team is about to drive campaign traffic to.
- **The product page over-shoots.** The Wool Runners title is 83 characters and its description 298, so Google will truncate both mid-sentence in results.
- **No broken internal links** across 70 checked internal URLs. (An earlier run reported 8, all HTTP 429 rate-limiting from the site, which the tool now reports as unverified instead; see DECISIONS.md #2.)
- **The one indexability failure is intentional.** `/search` is `noindex`, which is standard practice. The tool reports the directive, but it should not be "fixed" (see DECISIONS.md, revisit #2).
- **Product schema is valid on the one product page sampled.** That is one page, not proof for the whole catalogue (DECISIONS.md, revisit #1).
