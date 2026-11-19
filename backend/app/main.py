from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .audits import build_report
from .config import settings
from .crawler import Crawler
from .llm import generate_action_plan
from .pagespeed import measure_core_web_vitals
from .schemas import AuditRequest, AuditResult, HealthResponse
from .security import UnsafeURL, validate_url
from .storage import AuditStore, now_iso

app = FastAPI(title="SearchLens AI API", version="2.0.0")
store = AuditStore(settings.audit_db_path)


@app.exception_handler(RequestValidationError)
def validation_error(request: Request, exc: RequestValidationError):
    """Return one readable sentence (plus the raw errors) instead of only Pydantic's list."""
    messages = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"] if part != "body") or "body"
        messages.append(f"{field}: {error['msg']}")
    return JSONResponse(status_code=422, content={"detail": "; ".join(messages), "errors": jsonable_encoder(exc.errors())})


@app.get("/api/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "service": "searchlens-backend"}


@app.post("/api/audit", response_model=AuditResult)
def audit(request: AuditRequest):
    url = str(request.url)
    try:
        validate_url(url)  # refuse unsafe targets before sending the URL anywhere, PageSpeed included
    except UnsafeURL as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # PageSpeed Insights takes 30-40 s per URL and needs nothing from the crawl,
    # so it runs in a background thread while we crawl instead of after it.
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        cwv_future = pool.submit(
            measure_core_web_vitals,
            url,
            settings.pagespeed_api_key,
            strategy=settings.pagespeed_strategy,
            timeout=settings.pagespeed_timeout,
        )
        try:
            crawl = Crawler(
                settings.request_timeout,
                max_response_bytes=settings.max_response_bytes,
                request_delay=request.request_delay,
                max_link_checks=settings.max_link_checks,
                link_check_workers=settings.link_check_workers,
            ).crawl(
                url,
                min(request.max_pages, settings.max_pages),
                max_depth=min(request.max_depth, settings.max_depth),
                allow_subdomains=request.subdomains,
                render_mode=request.render_mode,
            )
        except UnsafeURL as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not crawl["pages"]:
            # Scoring zero pages would produce a meaningless score, so say why instead.
            reasons = crawl.get("gaps", []) + [
                f"{error.get('url')}: {error.get('message') or error.get('type')}" for error in crawl.get("crawl_errors", [])
            ]
            raise HTTPException(
                status_code=422,
                detail=f"No HTML page could be crawled from {url}. " + ("; ".join(reasons[:3]) or "The site returned no HTML."),
            )
        crawl["core_web_vitals"] = cwv_future.result()
    finally:
        # On an error response, do not make the user wait for PageSpeed to finish.
        pool.shutdown(wait=False)

    # Scores are fixed here, before the LLM runs. The LLM only adds action_plan.
    report = build_report(crawl["pages"], crawl)
    action_plan = generate_action_plan(url, report, settings)
    payload = {
        "id": str(uuid4()),
        "url": url,
        "created_at": now_iso(),
        "pages_crawled": len(crawl["pages"]),
        "overall_score": report["overall_score"],
        "coverage": report["coverage"],
        "summary": report["summary"],
        "metrics": report["metrics"],
        "action_plan": action_plan,
        "broken_links": crawl.get("broken_links", []),
        "crawl_errors": crawl.get("crawl_errors", []),
        "discovery_gaps": crawl.get("gaps", []),
        "core_web_vitals": crawl["core_web_vitals"],
    }
    return store.save(payload)


@app.get("/api/audits/{audit_id}", response_model=AuditResult)
def get_audit(audit_id: str):
    result = store.get(audit_id)
    if not result:
        raise HTTPException(status_code=404, detail="Audit not found")
    return result
