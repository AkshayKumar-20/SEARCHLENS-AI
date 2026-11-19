# AI usage

## Which AI tools I used, and for what

| Tool | Used for | Not used for |
|---|---|---|
| **Claude Code** (Claude Opus 5.5) | Reviewing the code base against the brief, pair-programming the crawler, metrics, LLM and tests, debugging live-site failures, drafting docs | Choosing metrics, weights or pass rules; any number in RESULTS.md |
| **OpenAI-compatible LLM** (Gemini, via `SEARCHLENS_LLM_*`) | *Inside the product:* turning computed findings into a prioritised action list | Metric values or the score (fixed before the call, reply validated) |

**How I worked:** the AI drafted and I verified. Every change ran against the test suite *and* a real website before commit, because most of the bugs below passed every mocked test.

## Where the AI was wrong, and how I noticed

**1. Rate-limiting reported as broken links.** The AI's link checker counted every 4xx as broken. My first Allbirds audit showed **8 broken links**. When I opened the evidence, all were **HTTP 429**, and a slower re-run found no 4xx at all. → One polite retry, an "unverified" state, and a regression test.

**2. The security check blocked a real website.** Auditing `kitsw.ac.in` failed with *"Private or reserved network targets are not allowed."* `nslookup` on my network vs Google DNS showed my IPv6-only ISP returns a NAT64 address (`64:ff9b::7712:3692`) wrapping the public IP `119.18.54.146`, and the AI's guard rejected that whole range. → Check the wrapped IPv4 instead; a test proves localhost is still refused.

**3. An LLM model that no longer exists.** The AI defaulted to `gemini-2.5-flash`. The mocked tests passed, but the first real call returned **404 "no longer available to new users"**; its knowledge was out of date. → Lesson: mocks test my logic, not an API's current contract, so I verify each integration with one real call.

**4. Correct but unusable.** The college-site audit ran for **10+ minutes**. Timing every request showed 370+ link checks done one at a time, with PDFs downloaded in full just to read a status code. → Streamed, parallel, capped checks: **1 min 4 s**.

**Smaller slips I caught by checking:** a test mock raised a plain `Exception` the crawler never catches, so the 404 path was untestable. A doc draft said "9 of 10 pages", where the JSON says 8. One test expected the wrong order; working through `weight × (100 − score)` by hand showed the code was right.

## What I checked without AI, and why

**The scoring and every number in RESULTS.md.** I recalculated the score by hand from the raw JSON: (20×20 + 100×25 + 90×20 + 100×20) / 85 = **78.8**. I checked each RESULTS figure against the API response. The score is the number a marketer will quote, and wrong generated arithmetic looks perfectly plausible. I also reviewed the SSRF checks myself: a mistake there is a security hole, not just a wrong number.

## What I'd improve with one more day

1. **LLM resilience:** retry with backoff on 429/503 (Gemini's free tier returned 503 "overloaded" in testing), then a second model, before the rule-based fallback.
2. **Template-aware sampling**, with Core Web Vitals per template.
3. **Background audits with live progress** for larger crawls.
4. **An evaluation set** of 10 sites to score LLM action lists for faithfulness across models.
