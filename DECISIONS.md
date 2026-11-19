# Decisions

## Assumptions I made, and why

| Assumption | Why |
|---|---|
| **"Crawl the site" = a bounded sample:** same hostname, breadth-first, 10 pages by default (50 max), sitemap URLs fill leftover budget. | A full store crawl takes hours and is impolite. A marketer needs an answer in about a minute. |
| **Title/meta judged per page, scored per site.** A page passes only if both tags exist and are in range (characters, trimmed). | The brief gives character ranges. Per-page rows show exactly which page to fix. |
| **Weights:** broken links 25, title/meta 20, indexability 20, Product schema 20, Core Web Vitals 15. | Broken links are an unambiguous defect. CWV covers only one URL. |
| **"Not measured" ≠ "failed".** Unmeasurable metrics get `score: null`, are left out of the score, and lower `coverage`. | Scoring a missing PageSpeed key as 0 would call a site slow when we simply don't know. |
| **The LLM writes words, never facts.** Scores are fixed before the call; actions for non-failing metrics and URLs the crawler never saw are dropped. | The brief forbids LLM metric values. I extend that to LLM-invented problems or pages. |
| **Any OpenAI-compatible LLM** (base URL, key, model in `.env`). | OpenAI, Gemini, Groq and Ollama share this API: one client, no lock-in. |

## Unclear in the brief, and how I resolved it

1. **Is "broken" literally any 4xx/5xx?** My first Allbirds audit reported 8 broken links, **all HTTP 429 "Too Many Requests"**: the site was rate-limiting my crawler. Counting them would send a marketer to fix healthy pages. → One retry after `Retry-After`. Links still at 429, or timing out, are reported as **unverified**, not broken.
2. **Per-page or per-site metrics?** → Site-level status and score, with per-page evidence underneath.
3. **No formula for the overall score.** → Documented weights, plus `coverage` so a partial score can't pass as complete.
4. **"Product website" undefined.** → Product schema is conditional: a site with no product pages gets **N/A**, not a penalty.
5. **Unauditable URLs** (robots.txt blocks all, the start page returns 404, the URL is a PDF). → **422 with the reason**, never a misleading score of 0.
6. **"Act on this week."** → At most 5 concrete actions naming the pages, ordered by impact.

## Other decisions I made

- **Cut scope to the brief.** I removed login, a what-if simulator, a rule-based "analyst", and *three competing scores from two different "top 5" sets*. What's left: one set of metrics, one score, code I can explain line by line.
- **Made big sites finish in about a minute.** A college site (370+ links, many PDFs) took over 10 minutes. Link checks now read only the status line, run on 4 workers, and stop at 200 (skipped ones are counted). PageSpeed runs in parallel. → **1 min 4 s.**
- **Fixed the security check for IPv6-only networks.** My ISP's NAT64 address (`64:ff9b::…`) for a public site was rejected as "reserved". The guard now checks the wrapped IPv4, so `64:ff9b::7f00:1` (localhost) stays blocked.

## Three choices I'd most want to revisit

1. **Breadth-first sampling.** 8 of the 10 Allbirds pages were collections or search; only 1 was a product page. I'd sample by template (home, category, product, content).
2. **Intent-blind indexability.** `/search` is `noindex` on purpose but still fails. I'd allow-list intentional exclusions (search, cart, account).
3. **A synchronous API.** A one-minute request is fragile, and the user only sees a spinner. I'd use background jobs with live progress.
