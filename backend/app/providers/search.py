"""SerpApi Google Lens visual matches.

Docs checked 2026-10-20:
https://serpapi.com/google-lens-api
https://serpapi.com/google-lens-visual-matches-api
https://serpapi.com/image-api
https://serpapi.com/google-lens-upload-an-image
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from app.config import get_settings
from app.errors import ProviderError
from app.images import to_jpeg_under
from app.ssrf import assert_public_url, is_safe_link

PRODUCT_HINTS = ("/product", "/products/", "/dp/", "/gp/", "/item", "/shop/", "/p/", "/itm/")
NON_PRODUCT_HOSTS = {
    "reddit.com",
    "www.reddit.com",
    "pinterest.com",
    "www.pinterest.com",
    "instagram.com",
    "www.instagram.com",
    "facebook.com",
    "www.facebook.com",
    "tiktok.com",
    "www.tiktok.com",
    "youtube.com",
    "www.youtube.com",
    "wikipedia.org",
    "en.wikipedia.org",
}


def search_visual_matches(image: bytes, query: str, *, client: httpx.Client | None = None) -> list[dict]:
    settings = get_settings()
    if not settings.serpapi_configured:
        raise ProviderError("Product search is not available until it is configured.", retryable=False)
    prepared = to_jpeg_under(image, 490_000, 1400)
    owns = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(45.0, connect=15.0), follow_redirects=False)
    try:
        upload = http.post(
            f"{settings.serpapi_base_url.rstrip('/')}/image",
            data={"api_key": settings.serpapi_api_key},
            files={"image": ("item.jpg", prepared, "image/jpeg")},
        )
        upload_body = _body(upload)
        if upload.status_code >= 400 or upload_body.get("error") or not upload_body.get("image_id"):
            raise ProviderError("Product search could not read this item. You can still try it on.")
        params = {
            "engine": "google_lens",
            "type": "visual_matches",
            "image_id": upload_body["image_id"],
            "hl": "en",
            "api_key": settings.serpapi_api_key,
        }
        if query:
            params["q"] = query
        search = http.get(f"{settings.serpapi_base_url.rstrip('/')}/search.json", params=params)
        search_body = _body(search)
        if search.status_code >= 400 or search_body.get("error"):
            raise ProviderError("Product search is unavailable right now. You can still try this item on.")
        return normalize_visual_matches(search_body.get("visual_matches") or [])
    finally:
        if owns:
            http.close()


def normalize_visual_matches(matches: list) -> list[dict]:
    results = []
    seen: set[str] = set()
    for match in matches:
        if not isinstance(match, dict):
            continue
        link = match.get("link")
        if not is_safe_link(link):
            continue
        key = _dedupe_key(str(link))
        if key in seen:
            continue
        seen.add(key)
        price_info = match.get("price") if isinstance(match.get("price"), dict) else {}
        price = price_info.get("extracted_value")
        currency = price_info.get("currency")
        if price is not None:
            try:
                price = float(price)
            except (TypeError, ValueError):
                price = None
                currency = None
        image = match.get("image") if is_safe_link(match.get("image")) else None
        thumbnail = match.get("thumbnail") if is_safe_link(match.get("thumbnail")) else None
        title = match.get("title") or "Untitled result"
        source = match.get("source") or _host(str(link))
        result_type = "product" if _looks_like_product(str(link), price) else "similar_style"
        results.append(
            {
                "title": str(title),
                "source": str(source) if source else None,
                "image": image,
                "thumbnail": thumbnail,
                "url": str(link),
                "price": price,
                "currency": str(currency) if currency and price is not None else None,
                "result_type": result_type,
                "in_stock": match.get("in_stock") if isinstance(match.get("in_stock"), bool) else None,
                "exact_image_match": bool(match.get("exact_matches")) if "exact_matches" in match else None,
            }
        )
    results.sort(key=lambda item: 0 if item["result_type"] == "product" else 1)
    return results[:24]


def _looks_like_product(url: str, price: float | None) -> bool:
    host = _host(url)
    if host in NON_PRODUCT_HOSTS or host.endswith(".wikipedia.org"):
        return False
    path = urlparse(url).path.lower()
    if any(hint in path for hint in PRODUCT_HINTS):
        return True
    return price is not None


def _dedupe_key(url: str) -> str:
    parsed = urlparse(url)
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_")))
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", query, ""))


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _body(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except Exception as exc:
        raise ProviderError("Product search returned an unexpected response.") from exc
    if not isinstance(body, dict):
        raise ProviderError("Product search returned an unexpected response.")
    return body


def fetch_remote_image(url: str, *, client: httpx.Client | None = None, limit: int = 8_000_000) -> bytes:
    owns = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False)
    current = url
    try:
        for _ in range(3):
            assert_public_url(current)
            response = http.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ProviderError("The product image could not be opened.", retryable=False)
                current = str(httpx.URL(current).join(location))
                continue
            if response.status_code >= 400:
                raise ProviderError("The product image could not be opened.", retryable=True)
            data = response.content
            if len(data) > limit:
                raise ProviderError("The product image is too large.", retryable=False)
            content_type = response.headers.get("content-type", "")
            if content_type and "image" not in content_type.lower() and not content_type.lower().startswith("application/octet-stream"):
                raise ProviderError("The product link did not return an image.", retryable=False)
            return data
        raise ProviderError("The product image could not be opened.", retryable=False)
    finally:
        if owns:
            http.close()
