from collections import deque
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urldefrag, urlparse
import re
import time
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser
from .security import validate_url, UnsafeURL


ROBOTS_META_NAMES = {"robots", "googlebot", "bingbot"}
RATE_LIMIT_DEFAULT_WAIT = 2.0  # seconds to wait after a 429 without Retry-After
RATE_LIMIT_MAX_WAIT = 10.0  # never honour a Retry-After longer than this


def _robots_evidence(soup, headers) -> tuple[str, str, bool, bool]:
    meta_values = []
    for tag in soup.select("meta[name]"):
        if (tag.get("name") or "").lower() in ROBOTS_META_NAMES:
            meta_values.append(tag.get("content") or "")
    meta_robots = ", ".join(value for value in meta_values if value).strip()
    x_robots_tag = (headers.get("x-robots-tag") or headers.get("X-Robots-Tag") or "").strip()
    directives = f"{meta_robots},{x_robots_tag}".lower()
    return meta_robots, x_robots_tag, "noindex" in directives, "nofollow" in directives


class Crawler:
    def __init__(self, timeout: float = 8.0, session=None, max_response_bytes: int = 2_000_000, request_delay: float = 0.0,
                 max_link_checks: int = 200, link_check_workers: int = 4):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.max_response_bytes = max_response_bytes
        self.request_delay = request_delay
        self.max_link_checks = max_link_checks
        self.link_check_workers = max(1, link_check_workers)

    def _get(self, url: str, stream: bool = False):
        """GET with the crawler's headers; on HTTP 429 wait once and retry.

        429 means the site is rate-limiting us, not that the page is broken, so it
        gets one polite retry before the caller decides what to do with it.
        """
        if self.request_delay:
            time.sleep(self.request_delay)
        options = {"timeout": self.timeout, "headers": {"User-Agent": "SearchLensAI/1.0"}, "allow_redirects": True, "stream": stream}
        response = self.session.get(url, **options)
        if response.status_code == 429:
            retry_after = str(response.headers.get("retry-after", "")).strip()
            time.sleep(min(float(retry_after), RATE_LIMIT_MAX_WAIT) if retry_after.isdigit() else RATE_LIMIT_DEFAULT_WAIT)
            response = self.session.get(url, **options)
        return response

    def _check_link(self, target: str, host_allowed) -> dict:
        """Return {"status": code} or {"error": type, "message": text} for one internal URL."""
        try:
            validate_url(target)
            # stream=True reads the status line and headers only; closing straight away
            # means a linked PDF or image is never downloaded just to get its status.
            response = self._get(target, stream=True)
            response.close()
            final_url = getattr(response, "url", None)
            if isinstance(final_url, str):
                validate_url(final_url)
                if not host_allowed(final_url):
                    raise UnsafeURL("Link redirect leaves the audited domain")
            if response.status_code == 429:
                # Still rate-limited after a retry: we could not check this link,
                # which is different from the link being broken.
                return {"error": "rate_limited", "message": "HTTP 429 after one retry; link not verified"}
            return {"status": response.status_code}
        except requests.RequestException as exc:
            return {"error": type(exc).__name__, "message": "Link could not be verified"}
        except UnsafeURL as exc:
            return {"error": type(exc).__name__, "message": str(exc)}

    def crawl(self, start_url: str, max_pages: int = 10, max_depth: int = 3, allow_subdomains: bool = False, render_mode: str = "static", render_timeout: float = 10.0) -> dict:
        start_url = validate_url(start_url)
        root = urlparse(start_url)
        allowed_host = root.netloc.lower()
        base_hostname = (root.hostname or "").lower()
        def host_allowed(target: str) -> bool:
            target_host = (urlparse(target).hostname or "").lower()
            return target_host == base_hostname or (allow_subdomains and target_host.endswith("." + base_hostname))
        robots_url = f"{root.scheme}://{root.netloc}/robots.txt"
        robots = RobotFileParser()
        robots.set_url(robots_url)
        sitemap_urls = []
        robots_available = False
        crawl_errors = []
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
            robots_available = response.ok
            robots.parse(response.text.splitlines() if response.ok else [])
            sitemap_urls = robots.site_maps() or re.findall(r"(?im)^sitemap:\s*(\S+)", response.text if response.ok else "")
        except requests.RequestException as exc:
            robots.parse([])
            crawl_errors.append({"url": robots_url, "type": type(exc).__name__, "message": "robots.txt could not be fetched"})
        pages, queue, seen, gaps, internal_targets = [], deque([(start_url, 0)]), set(), [], []
        blocked_by_robots = []
        sitemap_targets = []
        sitemap_queue = deque(sitemap_urls)
        sitemap_seen = set()
        sitemap_fetch_count = 0
        while sitemap_queue and sitemap_fetch_count < 10 and len(sitemap_targets) < max_pages * 5:
            sitemap_url = sitemap_queue.popleft()
            if sitemap_url in sitemap_seen:
                continue
            sitemap_seen.add(sitemap_url)
            sitemap_fetch_count += 1
            try:
                sitemap = self.session.get(sitemap_url, timeout=self.timeout)
                if not sitemap.ok:
                    continue
                content = getattr(sitemap, "content", None)
                if isinstance(content, bytes):
                    if len(content) > self.max_response_bytes:
                        crawl_errors.append({"url": sitemap_url, "type": "response_too_large", "message": "Sitemap exceeded the response limit"})
                        continue
                    sitemap_text = content.decode("utf-8", errors="replace")
                else:
                    sitemap_text = sitemap.text
                root_element = ET.fromstring(sitemap_text)
                is_index = root_element.tag.lower().endswith("sitemapindex")
                for loc in root_element.findall(".//{*}loc"):
                    target = urldefrag(loc.text or "")[0]
                    if not target or not host_allowed(target):
                        continue
                    if is_index:
                        sitemap_queue.append(target)
                    elif not urlparse(target).path.lower().endswith((".xml", ".xml.gz")):
                        sitemap_targets.append(target)
            except (requests.RequestException, ET.ParseError, TypeError, ValueError) as exc:
                crawl_errors.append({"url": sitemap_url, "type": type(exc).__name__, "message": "Sitemap could not be read"})
        while queue or sitemap_targets:
            if len(pages) >= max_pages:
                break
            if not queue:
                budget = max_pages - len(pages)
                queue.extend((target, 0) for target in sitemap_targets[:budget])
                sitemap_targets = sitemap_targets[budget:]
                if not queue:
                    break
            url, depth = queue.popleft()
            normalized = urldefrag(url)[0]
            if normalized in seen:
                continue
            seen.add(normalized)
            if not robots.can_fetch("SearchLensAI", normalized):
                gaps.append(f"Blocked by robots.txt: {normalized}")
                blocked_by_robots.append(normalized)
                continue
            try:
                # Stream so the body is only downloaded once we know it is HTML.
                response = self._get(normalized, stream=True)
                response_url = getattr(response, "url", normalized)
                if not isinstance(response_url, str):
                    response_url = normalized
                normalized = validate_url(response_url)
                if not host_allowed(normalized):
                    raise UnsafeURL("Redirect leaves the audited domain")
                if int(response.headers.get("content-length", 0) or 0) > self.max_response_bytes:
                    response.close()
                    crawl_errors.append({"url": normalized, "type": "response_too_large", "message": "Response exceeded the size limit"})
                    continue
                response.raise_for_status()
            except (requests.RequestException, UnsafeURL) as exc:
                error = {"url": normalized, "type": type(exc).__name__, "message": str(exc)}
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if isinstance(status, int):
                    error["status"] = status
                crawl_errors.append(error)
                continue
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type and content_type:
                response.close()  # e.g. a linked PDF: never download it
                gaps.append(f"Non-HTML page skipped: {normalized}")
                continue
            raw_content = getattr(response, "content", None)
            body = raw_content if isinstance(raw_content, bytes) else response.text.encode("utf-8", errors="replace")
            body = body[: self.max_response_bytes]
            page_render_mode = "static"
            if render_mode == "playwright":
                try:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        rendered = browser.new_page()
                        rendered.goto(normalized, wait_until="domcontentloaded", timeout=int(render_timeout * 1000))
                        body = rendered.content().encode("utf-8")
                        browser.close()
                        page_render_mode = "playwright"
                except (ImportError, OSError, RuntimeError, TimeoutError) as exc:
                    crawl_errors.append({"url": normalized, "type": "rendering_unavailable", "message": f"Static HTML used: {type(exc).__name__}"})
            soup = BeautifulSoup(body, "html.parser")
            links = []
            resources = [tag.get("src") or tag.get("href") for tag in soup.select("[src],link[href]") if tag.get("src") or tag.get("href")]
            for anchor in soup.select("a[href]"):
                target = urldefrag(urljoin(normalized, anchor["href"]))[0]
                parsed = urlparse(target)
                if parsed.scheme in {"http", "https"} and host_allowed(target):
                    links.append(target)
                    internal_targets.append({"source": normalized, "destination": target, "anchor_text": anchor.get_text(" ", strip=True)[:200]})
                    if target not in seen and depth < max_depth and len(pages) + len(queue) < max_pages:
                        queue.append((target, depth + 1))
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            meta_description_tag = soup.select_one('meta[name="description"]')
            meta_description = (meta_description_tag.get("content") or "").strip() if meta_description_tag else ""
            meta_robots, x_robots_tag, noindex, nofollow = _robots_evidence(soup, response.headers)
            indexable = 200 <= response.status_code <= 299 and not noindex
            pages.append({
                "url": normalized,
                "title": title,
                "title_length": len(title),
                "text": soup.get_text(" ", strip=True),
                "headings": [h.get_text(" ", strip=True) for h in soup.select("h1,h2,h3")],
                "images_without_alt": sum(1 for image in soup.select("img") if not image.get("alt", "").strip()),
                "links": links,
                "canonical": (soup.select_one('link[rel="canonical"]') or {}).get("href", "") if soup.select_one('link[rel="canonical"]') else "",
                "structured_data": [x.get_text(strip=True) for x in soup.select('script[type="application/ld+json"]')],
                "meta_description": meta_description,
                "meta_description_length": len(meta_description),
                "meta_robots": meta_robots,
                "x_robots_tag": x_robots_tag,
                "noindex": noindex,
                "nofollow": nofollow,
                "indexable": indexable,
                "indexability_reason": "indexable" if indexable else ("noindex" if noindex else f"http_{response.status_code}"),
                "status_code": response.status_code,
                "response_bytes": len(body),
                "resource_count": len(resources),
                "depth": depth,
                "render_mode": page_render_mode,
            })
        if len(pages) >= max_pages and queue:
            gaps.append("Page limit reached")
        # Check every unique internal destination once (pages already fetched are known).
        checked = {page["url"]: {"status": page.get("status_code", 200)} for page in pages}
        to_check = [target for target in dict.fromkeys(edge["destination"] for edge in internal_targets) if target not in checked]
        skipped = to_check[self.max_link_checks:]
        to_check = to_check[:self.max_link_checks]
        # A few parallel workers: a college site with 300+ unique links took over 10
        # minutes one at a time. Each worker still waits request_delay between requests.
        with ThreadPoolExecutor(max_workers=self.link_check_workers) as pool:
            results = pool.map(lambda target: self._check_link(target, host_allowed), to_check)
            for target, result in zip(to_check, results):
                checked[target] = result
                if "error" in result:
                    crawl_errors.append({"url": target, "type": result["error"], "message": result["message"], "context": "link_check"})

        broken_links = []
        seen_broken = set()
        for edge in internal_targets:
            source, target = edge["source"], edge["destination"]
            status = checked.get(target, {}).get("status")
            key = (source, target, status)
            if isinstance(status, int) and 400 <= status <= 599 and key not in seen_broken:
                seen_broken.add(key)
                broken_links.append({
                    "source": source,
                    "destination": target,
                    "status": status,
                    "anchor_text": edge.get("anchor_text", ""),
                })
        return {
            "pages": pages,
            "gaps": gaps,
            "broken_links": broken_links,
            "crawl_errors": crawl_errors,
            "blocked_by_robots": blocked_by_robots,
            "internal_link_count": len(internal_targets),
            "link_targets_checked": len(checked),
            "link_targets_unverified": sum(1 for result in checked.values() if "error" in result),
            "link_targets_skipped": len(skipped),
            "robots_available": robots_available,
            "sitemap_urls": sitemap_urls,
        }
