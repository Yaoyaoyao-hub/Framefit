"""Verified YouCam virtual try-on adapters.

Documentation checked 2026-10-20 against docs.perfectcorp.com.
Paths, fields, and enums below are taken from those pages and are not inferred.
"""

from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.errors import ProviderError
from app.images import prepare_provider_image
from app.ssrf import assert_public_url

BASE_DEFAULT = "https://yce-api-01.makeupar.com"

# Clothes V4: https://docs.perfectcorp.com/reference/ai_clothes/v4.0
CLOTHES_PATH = "/s2s/v2.0/task/cloth-v4"
CLOTHES_CATEGORIES = {
    "upper_body": "upper_body",
    "lower_body": "lower_body",
    "full_body": "full_body",
    "outerwear": "outer",
}

# Hat: https://docs.perfectcorp.com/reference/ai_hat/v2.0/paths/~1s2s~1v2.0~1task~1hat/post
HAT_PATH = "/s2s/v2.0/task/hat"
HAT_STYLES = {
    "random",
    "style_sporty_casual",
    "style_urban_fashion",
    "style_vacation_casual",
    "style_warm_cozy",
    "style_bohemian",
}

# Scarf: https://docs.perfectcorp.com/reference/ai_scarf/v2.0/paths/~1s2s~1v2.0~1task~1scarf/post
SCARF_PATH = "/s2s/v2.0/task/scarf"
SCARF_STYLES = {
    "random",
    "style_french_elegance",
    "style_light_luxury",
    "style_cottagecore",
    "style_modern_chic",
    "style_bohemian",
}

# Shoes V3 OpenAPI documents source and reference only.
# https://docs.perfectcorp.com/reference/ai_shoes/v3.0/paths/~1s2s~1v2.0~1task~1shoes-transfer/post
SHOES_PATH = "/s2s/v2.0/task/shoes-transfer"

# Bag: https://docs.perfectcorp.com/reference/ai_bag
# Create task: https://docs.perfectcorp.com/reference/ai_bag/v2.0/paths/~1s2s~1v2.0~1task~1bag/post
BAG_PATH = "/s2s/v2.0/task/bag"
BAG_STYLES = {
    "random",
    "style_parisian_chic",
    "style_urban_chic",
    "style_mediterranean_chic",
    "style_art_deco_style",
}

GENDERS = {"female", "male"}
FILE_PATH = "/s2s/v2.0/file"

ERROR_TEXT = {
    "error_no_face": "No face was found in the photo. Use a photo that shows the face clearly.",
    "error_download_image": "The try-on service could not read one of the images.",
    "error_inference": "The try-on service could not finish this image.",
    "error_nsfw_content_detected": "The try-on service rejected this image.",
    "exceed_max_filesize": "One of the images is too large for the try-on service.",
    "invalid_parameter": "The try-on service rejected the selected options.",
    "unknown_internal_error": "The try-on service had a problem finishing this request.",
    "invalidaccesstoken": "Try-on is unavailable because the service rejected the API key.",
    "unauthorized": "Try-on is unavailable because the service rejected the API key.",
}


def task_path(category: str) -> str:
    name = adapter_name(category)
    return {"clothes": CLOTHES_PATH, "hat": HAT_PATH, "scarf": SCARF_PATH, "shoes": SHOES_PATH, "bag": BAG_PATH}[name]


def adapter_name(category: str) -> str:
    if category == "hat":
        return "hat"
    if category == "scarf":
        return "scarf"
    if category == "shoes":
        return "shoes"
    if category == "bag":
        return "bag"
    if category in CLOTHES_CATEGORIES:
        return "clothes"
    raise ProviderError("This item type cannot be tried on yet.", retryable=False)


def provider_limits(category: str) -> tuple[int, int]:
    if category in {"hat", "scarf", "shoes", "bag"}:
        return 512, 512
    return 512, 384


class YouCamClient:
    def __init__(self, api_key: str, base_url: str | None = None, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.base_url = (base_url or BASE_DEFAULT).rstrip("/")
        self._client = httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0), transport=transport, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def upload_file(self, data: bytes, filename: str) -> str:
        payload = {
            "files": [
                {
                    "content_type": "image/jpg",
                    "file_name": filename,
                    "file_size": len(data),
                }
            ]
        }
        response = self._request("POST", FILE_PATH, json=payload)
        body = _json(response)
        files = ((body.get("data") or {}).get("files") or [])
        if not files:
            raise ProviderError("The try-on service did not accept the image.")
        file_info = files[0]
        file_id = file_info.get("file_id")
        requests = file_info.get("requests") or []
        if not file_id or not requests:
            raise ProviderError("The try-on service did not accept the image.")
        upload = requests[0]
        url = upload.get("url")
        method = (upload.get("method") or "PUT").upper()
        headers = dict(upload.get("headers") or {})
        if not url:
            raise ProviderError("The try-on service did not accept the image.")
        assert_public_url(url)
        upload_response = self._client.request(method, url, content=data, headers=headers)
        if upload_response.status_code >= 300:
            raise ProviderError("The images could not be sent to the try-on service.")
        return file_id

    def create_task(self, path: str, payload: dict[str, Any]) -> str:
        response = self._request("POST", path, json=payload)
        body = _json(response)
        task_id = ((body.get("data") or {}).get("task_id"))
        if not task_id:
            raise ProviderError(_message_from_body(body) or "The try-on service did not start.")
        return str(task_id)

    def poll_task(self, path: str, task_id: str) -> str:
        settings = get_settings()
        deadline = time.monotonic() + settings.youcam_timeout_seconds
        interval = settings.youcam_poll_interval_seconds
        while True:
            state, url = self.check_task(path, task_id)
            if state == "success":
                return url
            if time.monotonic() >= deadline:
                raise ProviderError("This try-on took too long. You can try again.")
            time.sleep(interval)
            interval = min(interval * 1.5, 10)

    def check_task(self, path: str, task_id: str) -> tuple[str, str]:
        response = self._request("GET", f"{path}/{quote(task_id, safe='')}")
        return _parse_poll(_json(response))

    def download_result(self, url: str) -> bytes:
        data = _download_public_image(self._client, url, limit=12_000_000)
        if not data:
            raise ProviderError("The try-on service finished without an image.")
        return data

    def _request(self, method: str, path: str, json: dict | None = None) -> httpx.Response:
        url = f"{self.base_url}{path}"
        last_error: ProviderError | None = None
        for attempt in range(3):
            headers = self._headers()
            kwargs: dict[str, Any] = {}
            if json is not None:
                headers["Content-Type"] = "application/json"
                kwargs["json"] = json
            response = self._client.request(method, url, headers=headers, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                last_error = ProviderError("The try-on service is busy. You can try again.")
                time.sleep(min(2 ** attempt, 8))
                continue
            if response.status_code == 401:
                raise ProviderError(ERROR_TEXT["unauthorized"], retryable=False)
            if response.status_code >= 400:
                body = _safe_json(response)
                raise ProviderError(_message_from_body(body) or "The try-on service rejected this request.", retryable=False)
            return response
        raise last_error or ProviderError("The try-on service is busy. You can try again.")


def build_task_payload(category: str, settings: dict, *, src_file_id: str | None = None, ref_file_id: str | None = None, src_file_url: str | None = None, ref_file_url: str | None = None) -> tuple[str, dict[str, Any]]:
    name = adapter_name(category)
    if bool(src_file_id) == bool(src_file_url) or bool(ref_file_id) == bool(ref_file_url):
        raise ProviderError("The images for this try-on were not prepared.", retryable=False)
    payload: dict[str, Any] = {}
    if src_file_id:
        payload["src_file_id"] = src_file_id
    else:
        payload["src_file_url"] = src_file_url
    if ref_file_id:
        payload["ref_file_id"] = ref_file_id
    else:
        payload["ref_file_url"] = ref_file_url

    if name == "clothes":
        payload["garment_category"] = CLOTHES_CATEGORIES[category]
        payload["change_shoes"] = bool(settings.get("change_shoes", False))
        filter_value = settings.get("filter_multi_person", "off")
        if filter_value not in {"off", "normal", "strict"}:
            raise ProviderError("That person filter is not supported.", retryable=False)
        payload["filter_multi_person"] = filter_value
        return CLOTHES_PATH, payload
    if name == "hat":
        payload["gender"] = _gender(settings)
        # Named styles restyle the outfit and background. Omit style to keep the documented default,
        # then the caller pastes only the hat back onto the original photo.
        if not settings.get("keep_outfit"):
            payload["style"] = _style(settings, HAT_STYLES)
        return HAT_PATH, payload
    if name == "scarf":
        payload["gender"] = _gender(settings)
        payload["style"] = _style(settings, SCARF_STYLES)
        return SCARF_PATH, payload
    if name == "bag":
        payload["gender"] = _gender(settings)
        payload["style"] = _style(settings, BAG_STYLES)
        return BAG_PATH, payload
    return SHOES_PATH, payload


def run_youcam(category: str, source: bytes, reference: bytes, settings: dict, *, client: YouCamClient | None = None, signed_url_factory: Callable[[bytes, str], str] | None = None) -> tuple[bytes, dict]:
    app_settings = get_settings()
    owns_client = client is None
    if client is None:
        if not app_settings.youcam_configured:
            raise ProviderError("Try-on is not available until it is configured.", retryable=False)
        client = YouCamClient(app_settings.youcam_api_key, app_settings.youcam_base_url)
    min_w, min_h = provider_limits(category)
    source_jpeg, source_note = prepare_provider_image(source, min_width=min_w, min_height=min_h)
    ref_jpeg, ref_note = prepare_provider_image(reference, min_width=min_w, min_height=min_h)
    mode = settings.get("input_mode") or app_settings.youcam_input_mode
    try:
        if mode == "public_url":
            if signed_url_factory is None:
                raise ProviderError("Public image links are not configured for try-on.", retryable=False)
            src_url = signed_url_factory(source_jpeg, "source.jpg")
            ref_url = signed_url_factory(reference_jpeg, "reference.jpg")
            path, payload = build_task_payload(category, settings, src_file_url=src_url, ref_file_url=ref_url)
        else:
            src_id = client.upload_file(source_jpeg, "source.jpg")
            ref_id = client.upload_file(ref_jpeg, "reference.jpg")
            path, payload = build_task_payload(category, settings, src_file_id=src_id, ref_file_id=ref_id)
        task_id = client.create_task(path, payload)
        result_url = client.poll_task(path, task_id)
        image = client.download_result(result_url)
        meta = {
            "provider": "youcam",
            "endpoint": path,
            "provider_task_id": task_id,
            "input_mode": mode,
            "source_prep": source_note,
            "reference_prep": ref_note,
        }
        return image, meta
    finally:
        if owns_client:
            client.close()


def _gender(settings: dict) -> str:
    gender = str(settings.get("gender") or "").lower()
    if gender not in GENDERS:
        raise ProviderError("Choose female or male for this try-on.", retryable=False)
    return gender


def _style(settings: dict, allowed: set[str]) -> str:
    style = str(settings.get("style") or "random")
    if style not in allowed:
        raise ProviderError("That style option is not supported for this item.", retryable=False)
    return style


def _json(response: httpx.Response) -> dict:
    body = _safe_json(response)
    if not isinstance(body, dict):
        raise ProviderError("The try-on service returned an unexpected response.")
    return body


def _safe_json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _message_from_body(body: dict) -> str | None:
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    raw = body.get("error_code") or body.get("error") or data.get("error") or data.get("error_code")
    if not raw:
        return None
    if isinstance(raw, dict):
        raw = raw.get("code") or raw.get("message") or ""
    key = str(raw).strip()
    return ERROR_TEXT.get(key.lower(), ERROR_TEXT.get(key, None) or "The try-on service could not finish this request.")


def _parse_poll(body: dict) -> tuple[str, str]:
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    status = str(data.get("task_status") or body.get("task_status") or "").lower()
    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    url = results.get("url") or data.get("url") or ""
    if status in {"error", "failed"}:
        raise ProviderError(_message_from_body(body) or "The try-on service could not finish this request.")
    if status == "success":
        if not url:
            raise ProviderError("The try-on service finished without an image.")
        return "success", str(url)
    if url and not status:
        return "success", str(url)
    return "pending", ""


def _download_public_image(client: httpx.Client, url: str, limit: int) -> bytes:
    current = url
    for _ in range(3):
        assert_public_url(current)
        response = client.get(current, follow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise ProviderError("The result image could not be saved.")
            current = str(httpx.URL(current).join(location))
            continue
        if response.status_code >= 400:
            raise ProviderError("The result image could not be saved.")
        data = response.content
        if len(data) > limit:
            raise ProviderError("The result image was too large to save.")
        return data
    raise ProviderError("The result image could not be saved.")
