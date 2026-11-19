# SearchLens AI

**An SEO audit assistant for marketing teams.** Paste a product website URL. SearchLens crawls the site, measures its **top 5 SEO metrics**, gives an **overall SEO score**, and uses an LLM to turn the findings into a **short, prioritised action list for this week**.

> **The one rule the design is built around:** every number comes from the crawler. Metric values and the score are calculated in Python *before* the LLM is called. The LLM only words and orders the actions, and its reply is checked against the findings before it is shown.

| Document | What it answers |
|---|---|
| [RESULTS.md](RESULTS.md) | The website I audited, why I chose it, and the app's report for it |
| [DECISIONS.md](DECISIONS.md) | My assumptions, what was unclear in the brief and how I resolved it, what I'd revisit |
| [AI_USAGE.md](AI_USAGE.md) | How I used AI tools, where they were wrong, and how I caught it |

---

## 1. The five metrics

| # | Metric | Weight | Pass rule | Type |
|---|---|---:|---|---|
| 1 | **Title & meta description** | 20 | Title 30–60 characters **and** meta description 70–160 characters, on every crawled page | Mandatory |
| 2 | **Broken internal links** | 25 | Zero internal links returning HTTP 4xx/5xx (each reported with the page it was found on) | Mandatory |
| 3 | **Page indexability** | 20 | Every crawled page returns 2xx and is not blocked by robots.txt, meta robots `noindex` or `X-Robots-Tag` | My choice |
| 4 | **Core Web Vitals** | 15 | LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 (Google's "good" thresholds) | My choice |
| 5 | **Product structured data** | 20 | Every product page has valid Product JSON-LD that matches the visible page | My choice, AI-search signal |

### Why I chose metrics 3–5

**3. Page indexability**
- **Why it matters to the business:** a page that search engines are told not to index can't rank and can't be cited by AI answer engines, however good it is. One stray `noindex` on a template silently removes every product or category page that uses it from search. It is the most expensive SEO mistake, and the cheapest to fix.
- **How it's measured:** for every crawled page, the final HTTP status, `<meta name="robots|googlebot|bingbot">` and the `X-Robots-Tag` response header are checked for `noindex`. URLs skipped because robots.txt disallows them are counted too. **Score** = % of these URLs that are indexable.
- **Good / bad:** good = every URL is 2xx with no `noindex` and no robots.txt block. Bad = any exception, reported with the page and the exact directive. Some exclusions (internal search, cart) are intentional, so the evidence is shown for a human to judge.

**4. Core Web Vitals**
- **Why it matters to the business:** Google uses them as a ranking signal, and they measure what visitors feel. A slow main image (LCP), a laggy tap (INP) or a jumping layout (CLS) loses sales directly.
- **How it's measured:** the Google PageSpeed Insights API (mobile) for the start URL. Real-user Chrome UX Report data is used when Google has it, otherwise a Lighthouse lab run. INP only exists in real-user data.
- **Good / bad:** Google's thresholds. Good: LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 (100 points each). Needs improvement: up to 4 s / 500 ms / 0.25 (50 points). Poor: above that (0 points). With no API key the metric shows **"Not measured"** and is left out of the score. It is never estimated.

**5. Product structured data (JSON-LD)**
- **Why it matters to the business:** this is a product's machine-readable name, price and availability. Google uses it for rich results (price and stock right in the search snippet). AI search engines such as ChatGPT, Perplexity and Google AI Overviews rely on it to describe products accurately. If it's missing or wrong, they describe a competitor's product instead.
- **How it's measured:** a page counts as a product page if it has Product JSON-LD, a product-style URL (`/products/`, `/p/`, `/dp/`…), or product wording ("add to cart" plus "in stock"). Each JSON-LD block is parsed, including `@graph`, and must contain `name`, `image`, and `offers` with `price`, `priceCurrency` and `availability`. The product name must also appear on the visible page. **Score** = % of product pages that pass.
- **Good / bad:** good = every product page passes every check. Bad = missing schema, invalid JSON, a missing field, or a name that doesn't match the page. A site with no product pages gets **N/A** and is not penalised.

### The overall SEO score

```
overall = Σ (metric score × weight) / Σ weight      ← only over metrics that were actually measured
```

A metric that is **unavailable** (e.g. no PageSpeed key) or **not applicable** (no product pages) gets `score: null` and is left out of the score. `coverage` says how much of the total weight was measured. "We couldn't measure it" must never look like "it failed".

---

## 2. Quick start

**Requirements:** Python 3.10+ and Node.js 18+.

```bash
# 1. Backend
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                 # macOS/Linux: cp .env.example .env
#    then fill in the keys in .env (see the table below)
python -m uvicorn backend.app.main:app --port 8000

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev                            # open http://localhost:5173
```

### Configuration (`.env`)

| Variable | Needed? | Purpose |
|---|---|---|
| `SEARCHLENS_LLM_BASE_URL` | for the LLM | Any OpenAI-compatible API, e.g. `https://api.openai.com/v1` or `https://generativelanguage.googleapis.com/v1beta/openai` (Gemini) |
| `SEARCHLENS_LLM_API_KEY` | for the LLM | The provider's key. Leave empty for a local server such as Ollama |
| `SEARCHLENS_LLM_MODEL` | for the LLM | e.g. `gpt-4o-mini`, `gemini-3.8-flash`, `llama-3.3-70b-versatile` |
| `SEARCHLENS_PAGESPEED_API_KEY` | recommended | Free key that enables Core Web Vitals ([get one](https://developers.google.com/speed/docs/insights/v5/get-started)). Keyless calls are rate-limited |
| `SEARCHLENS_PAGESPEED_TIMEOUT` | optional | Default `60` seconds. Google often needs 30–40 s per URL |
| `SEARCHLENS_MAX_PAGES` / `_MAX_DEPTH` | optional | Server caps on crawl size (default 10 pages, depth 3) |
| `SEARCHLENS_MAX_LINK_CHECKS` / `_LINK_CHECK_WORKERS` | optional | Unique internal URLs checked per audit (200) and parallel workers (4) |

Without the LLM settings the app still works. The action list comes from a fixed rule (largest score loss first), and the response and UI label it **"Rule-based fallback"**, with the reason.

`.env` is git-ignored, so keys are never committed. Restart the backend after editing it.

---

## 3. Using the API

```bash
curl -X POST http://localhost:8000/api/audit \
     -H "Content-Type: application/json" \
     -d '{"url": "https://www.allbirds.com/", "max_pages": 10}'
```

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/audit` | Crawl and audit a site. Body: `url` (required), `max_pages` 1–50 (default 10), `max_depth` 0–10, `request_delay` seconds, `subdomains` bool |
| `GET` | `/api/audits/{id}` | Fetch a previous audit (in memory, or SQLite if `SEARCHLENS_AUDIT_DB_PATH` is set) |
| `GET` | `/api/health` | Liveness check |
| | `/docs` | Interactive Swagger UI |

**Response (shortened):**

```json
{
  "id": "6f1c…",
  "url": "https://www.allbirds.com/",
  "pages_crawled": 10,
  "overall_score": 78.8,
  "coverage": 0.85,
  "summary": "2 of 4 measured metrics need attention.",
  "metrics": [
    {
      "id": "title_meta", "title": "Title & Meta Description", "mandatory": true, "weight": 20,
      "status": "bad", "score": 20.0,
      "summary": "8 of 10 crawled page(s) have a missing or out-of-range title or meta description.",
      "evidence": ["https://www.allbirds.com/collections/bfcm-mens: title length 11 is outside 30-60, missing meta description"],
      "pages": [{"url": "…", "title_length": 11, "meta_description_present": false, "status": "bad", "issues": ["…"]}]
    },
    { "id": "core_web_vitals", "status": "unavailable", "score": null, "summary": "Set SEARCHLENS_PAGESPEED_API_KEY to measure Core Web Vitals." }
  ],
  "action_plan": {
    "source": "llm", "provider": "generativelanguage.googleapis.com", "model": "gemini-3.8-flash", "reason": "",
    "actions": [{"priority": 1, "metric_id": "title_meta", "action": "…", "why": "…", "pages": ["…"]}]
  },
  "broken_links": [{"source": "page it was found on", "destination": "broken URL", "status": 404, "anchor_text": "…"}],
  "crawl_errors": [],
  "discovery_gaps": ["Page limit reached"]
}
```

### Error responses

Every error returns a readable `detail` string:

| Situation | Status | Example `detail` |
|---|---:|---|
| Missing/malformed URL, non-http(s) scheme, out-of-range or unknown field | 422 | `url: Input should be a valid URL…` |
| Localhost, private or reserved network address (SSRF protection) | 400 | `Private or reserved network targets are not allowed` |
| Nothing crawlable: robots.txt blocks all, start page 4xx/5xx, not HTML | 422 | `No HTML page could be crawled from …: Blocked by robots.txt: …` |
| Unknown audit id | 404 | `Audit not found` |

---

## 4. Tests

```bash
python -m pytest tests -q        # 48 tests, fully offline: HTTP, DNS and the LLM are mocked
cd frontend && npm run build     # TypeScript type-check + production build
```

| File | Tests | Covers |
|---|---:|---|
| `tests/test_api.py` | 28 | **Valid** audits end to end. **Invalid** input (422/400, SSRF incl. IPv6, NAT64, IPv4-mapped). **Edge cases**: start page 404, robots.txt blocks everything, non-HTML start URL, rate-limited (429) links, link-check cap, sitemap index, `X-Robots-Tag` |
| `tests/test_metrics.py` | 11 | Each metric's pass rule, PageSpeed parsing, Product-schema validation, unmeasured metrics left out of the score |
| `tests/test_llm.py` | 9 | The LLM **cannot change the score**, invent URLs or address non-failing metrics; bad replies and HTTP errors fall back; the API key never appears in the output |

Many tests are regression tests for bugs found on live websites; the test name and a comment say which.

---

## 5. Architecture

```
 React page ── POST /api/audit ──▶ FastAPI  (main.py)
                                     │
                                     ├─ security.py    refuse private/local targets (final URL re-checked after redirects)
                                     │
                                     ├─ pagespeed.py   ┐ run in parallel: PageSpeed takes ~30-40 s
                                     ├─ crawler.py     ┘ robots.txt + sitemap → same-domain BFS (≤ max_pages)
                                     │                   → extract title, meta, robots, JSON-LD per page
                                     │                   → check every unique internal link (4 workers, status only)
                                     │
                                     ├─ audits.py      five metrics + weighted overall score     ◀── every number comes from here
                                     ├─ llm.py         findings → LLM → validated action list    ◀── words and order only
                                     └─ storage.py     save and return JSON
```

| Module | Lines | Responsibility |
|---|---:|---|
| `backend/app/main.py` | 112 | API routes, orchestration, error responses |
| `backend/app/security.py` | 58 | SSRF guard: scheme, DNS, private/reserved IPs (unwraps NAT64 / IPv4-mapped) |
| `backend/app/crawler.py` | 278 | Polite bounded crawl, page evidence, link checking |
| `backend/app/audits.py` | 320 | The five metrics and the overall score (pure functions, no I/O) |
| `backend/app/structured_data.py` | 187 | JSON-LD parsing and Product validation |
| `backend/app/pagespeed.py` | 169 | Core Web Vitals from PageSpeed Insights |
| `backend/app/llm.py` | 185 | Prompt, OpenAI-compatible call, reply validation, fallback |
| `frontend/src/App.tsx` | 192 | The single-page UI (displays values; computes nothing) |
| `scripts/render_report.py` | 70 | Turns a saved audit JSON into the Markdown in RESULTS.md |

### Key design choices

- **LLM boundary.** The model receives only the computed findings (no page body text), is told that text copied from the site is data, not instructions, and must reply in JSON. Actions for metrics that aren't failing, and URLs the crawler never saw, are dropped. Nothing is read back into the metrics or score.
- **Honest unknowns.** Unmeasured metrics are `null`, not 0. Links that time out or are rate-limited are reported as *unverified*, not broken. Links beyond the check limit are counted as *not checked*.
- **Polite crawling.** Respects robots.txt, sends its own User-Agent, has an optional delay between requests, retries once after `Retry-After` on HTTP 429, never downloads PDFs or images just to get a status code, and caps response size.
- **One provider-agnostic LLM client.** OpenAI, Gemini, Groq, OpenRouter and Ollama all offer the OpenAI chat API, so switching is a `.env` change, with no SDK per vendor.

```
backend/app/   API, crawler, metrics, LLM          frontend/src/   single-page React UI
tests/         48 offline tests                    scripts/        report renderer
```

---

## 6. Limitations

- **A sample, not a site-wide verdict.** 10 pages by default, chosen breadth-first, so a large store may be over-represented by category pages.
- **Static HTML.** JavaScript-rendered content is not executed (unless Playwright is installed and `"render_mode": "playwright"` is sent).
- **Core Web Vitals cover the start URL only**, and depend on Google having data for it.
- **Synchronous API.** A 10-page audit takes about 30–70 s depending on the site. There is no progress bar yet.
- Crawl only sites you are allowed to audit.
