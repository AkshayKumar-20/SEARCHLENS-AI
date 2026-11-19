"""Product structured-data detection and validation over crawled JSON-LD."""

import json
import re
from urllib.parse import urlparse

PRODUCT_TYPES = {"Product", "IndividualProduct", "ProductModel", "ProductGroup"}
PRODUCT_PATH_RE = re.compile(r"/(?:products?|items?|shop|dp|p|buy)(?:/|$)", re.IGNORECASE)
PRODUCT_TEXT_SIGNALS = ("add to cart", "add to bag", "out of stock", "in stock", "sku")
PRODUCT_TEXT_FALLBACK = ("add to cart", "add to bag", "buy now", "checkout")


def _nodes(value):
    if isinstance(value, dict):
        graph = value.get("@graph")
        if isinstance(graph, (dict, list)):
            if value.get("@type"):
                yield value
            yield from _nodes(graph)
        else:
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from _nodes(item)


def parse_json_ld(raw_values: list) -> tuple[list[dict], list[str]]:
    nodes, errors = [], []
    for index, raw in enumerate(raw_values or []):
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(f"JSON-LD block {index + 1} is invalid ({type(exc).__name__})")
            continue
        nodes.extend(_nodes(data))
    return nodes, errors


def _types(node: dict) -> set[str]:
    value = node.get("@type", [])
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def is_product_node(node: dict) -> bool:
    return bool(_types(node) & PRODUCT_TYPES)


def _offer_nodes(node: dict) -> list[dict]:
    offers = node.get("offers")
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [offer for offer in offers if isinstance(offer, dict)]
    return []


def _image_present(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_image_present(item) for item in value)
    if isinstance(value, dict):
        return bool(str(value.get("url") or value.get("contentUrl") or "").strip())
    return False


def _first_price(offer: dict):
    for key in ("price", "lowPrice", "highPrice"):
        value = offer.get(key)
        if value is not None and str(value).strip() != "":
            return value
    specification = offer.get("priceSpecification")
    if isinstance(specification, dict):
        value = specification.get("price")
        if value is not None and str(value).strip() != "":
            return value
    return None


def validate_product(node: dict) -> list[str]:
    issues = []
    name = node.get("name")
    if not isinstance(name, str) or not name.strip():
        issues.append("missing product name")
    if not _image_present(node.get("image")):
        issues.append("missing product image")
    offers = _offer_nodes(node)
    if not offers:
        issues.append("missing offers")
    for offer in offers:
        if _first_price(offer) is None:
            issues.append("missing offer price")
        availability = offer.get("availability")
        if not isinstance(availability, str) or not availability.strip():
            issues.append("missing availability")
        currency = offer.get("priceCurrency")
        specification = offer.get("priceSpecification")
        if not isinstance(currency, str) or not currency.strip():
            if isinstance(specification, dict):
                currency = specification.get("priceCurrency")
        if not isinstance(currency, str) or not currency.strip():
            issues.append("missing priceCurrency")
    return list(dict.fromkeys(issues))


def _normalize(value: str) -> str:
    return " ".join(str(value).split()).casefold()


def product_matches_visible_content(name: str, page: dict) -> bool:
    normalized = _normalize(name)
    if not normalized:
        return False
    haystack = _normalize(f"{page.get('title', '')} {page.get('text', '')}")
    if normalized in haystack:
        return True
    tokens = [token for token in re.findall(r"[a-z0-9]{4,}", normalized)][:5]
    return bool(tokens) and all(token in haystack for token in tokens)


def _looks_like_product_page(page: dict, products: list[dict]) -> bool:
    if products:
        return True
    path = urlparse(page.get("url", "")).path
    if PRODUCT_PATH_RE.search(path):
        return True
    text = page.get("text", "").lower()
    return any(signal in text for signal in PRODUCT_TEXT_SIGNALS) and any(
        signal in text for signal in PRODUCT_TEXT_FALLBACK
    )


def analyze_product_schemas(pages: list[dict]) -> dict:
    page_reports, product_page_count, valid_page_count = [], 0, 0
    for page in pages:
        nodes, parse_errors = parse_json_ld(page.get("structured_data", []))
        products = [node for node in nodes if is_product_node(node)]
        if not _looks_like_product_page(page, products):
            continue

        product_page_count += 1
        issues = list(parse_errors)
        product_rows = []
        if not products:
            issues.append("missing Product JSON-LD")

        for product in products:
            field_issues = validate_product(product)
            name = product.get("name", "")
            matches = product_matches_visible_content(name, page) if isinstance(name, str) else False
            if not matches:
                issues.append("Product name does not match visible page content")
            issues.extend(field_issues)
            product_rows.append(
                {
                    "name": name if isinstance(name, str) else "",
                    "issues": list(dict.fromkeys(field_issues + ([] if matches else ["visible content mismatch"]))),
                }
            )

        unique_issues = list(dict.fromkeys(issues))
        valid = bool(products) and not unique_issues
        if valid:
            valid_page_count += 1
        page_reports.append(
            {
                "url": page.get("url", ""),
                "status": "good" if valid else "bad",
                "product_count": len(products),
                "products": product_rows,
                "issues": unique_issues,
            }
        )

    return {
        "applicable": product_page_count > 0,
        "page_count": product_page_count,
        "valid_page_count": valid_page_count,
        "invalid_page_count": product_page_count - valid_page_count,
        "pages": page_reports,
    }
