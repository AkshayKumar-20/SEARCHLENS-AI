from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class AuditRequest(BaseModel):
    # Unknown fields are rejected so a typo like "max_page" gets a clear 422
    # instead of being silently ignored.
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    max_pages: int = Field(default=10, ge=1, le=50)
    max_depth: int = Field(default=3, ge=0, le=10)
    request_delay: float = Field(default=0, ge=0, le=10)
    subdomains: bool = False
    render_mode: str = Field(default="static", pattern="^(static|playwright)$")


class MetricResult(BaseModel):
    # Each metric also carries its own detail rows (pages, broken_links, ...),
    # which differ per metric, so extra keys are allowed through.
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    mandatory: bool
    weight: int
    status: str
    score: float | None = Field(default=None, ge=0, le=100)
    summary: str
    target: str
    bad: str
    action: str
    evidence: list[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    priority: int
    metric_id: str
    action: str
    why: str = ""
    pages: list[str] = Field(default_factory=list)


class ActionPlan(BaseModel):
    source: Literal["llm", "fallback", "none"]
    provider: str
    model: str | None = None
    reason: str = ""
    actions: list[ActionItem] = Field(default_factory=list)


class AuditResult(BaseModel):
    id: str
    url: str
    created_at: str
    pages_crawled: int
    overall_score: float = Field(ge=0, le=100)
    coverage: float = Field(ge=0, le=1)
    summary: str
    metrics: list[MetricResult]
    action_plan: ActionPlan
    broken_links: list[dict[str, Any]] = Field(default_factory=list)
    crawl_errors: list[dict[str, Any]] = Field(default_factory=list)
    discovery_gaps: list[str] = Field(default_factory=list)
    core_web_vitals: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    service: str
