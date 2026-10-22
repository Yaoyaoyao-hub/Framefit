"""Image validation, orientation, crops, and demo composites."""

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.config import get_settings
from app.errors import APIError

Image.MAX_IMAGE_PIXELS = 40_000_000


@dataclass
class PreparedImage:
    data: bytes
    mime: str
    width: int
    height: int
    sha256: str


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_upload(data: bytes) -> PreparedImage:
    settings = get_settings()
    if not data:
        raise APIError(400, "invalid_image", "Choose a JPEG, PNG, or WebP image.")
    if len(data) > settings.max_upload_bytes:
        raise APIError(400, "invalid_image", "That image is too large. Use one under 12 MB.")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise APIError(400, "invalid_image", "That file is not a readable JPEG, PNG, or WebP image.") from exc
    fmt = (image.format or "").upper()
    if fmt not in {"JPEG", "PNG", "WEBP"}:
        raise APIError(400, "invalid_image", "Use a JPEG, PNG, or WebP image.")
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    if width < 32 or height < 32:
        raise APIError(400, "invalid_image", "That image is too small.")
    if width > settings.max_image_edge or height > settings.max_image_edge:
        raise APIError(400, "invalid_image", "That image is larger than the supported size.")
    buffer = io.BytesIO()
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        image = image.convert("RGBA")
        image.save(buffer, format="PNG")
        mime = "image/png"
    else:
        image = image.convert("RGB")
        image.save(buffer, format="JPEG", quality=95)
        mime = "image/jpeg"
    stored = buffer.getvalue()
    return PreparedImage(stored, mime, image.size[0], image.size[1], _sha(stored))


def open_image(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return ImageOps.exif_transpose(image)


def crop_normalized(data: bytes, x: float, y: float, width: float, height: float, pad: float = 0.08) -> PreparedImage:
    if width <= 0 or height <= 0:
        raise APIError(400, "invalid_box", "Draw a box around the item.")
    image = open_image(data).convert("RGB")
    img_w, img_h = image.size
    x0 = max(0.0, x - width * pad)
    y0 = max(0.0, y - height * pad)
    x1 = min(1.0, x + width + width * pad)
    y1 = min(1.0, y + height + height * pad)
    left = int(x0 * img_w)
    top = int(y0 * img_h)
    right = max(left + 1, int(x1 * img_w))
    bottom = max(top + 1, int(y1 * img_h))
    cropped = image.crop((left, top, right, bottom))
    buffer = io.BytesIO()
    cropped.save(buffer, format="JPEG", quality=92)
    stored = buffer.getvalue()
    return PreparedImage(stored, "image/jpeg", cropped.size[0], cropped.size[1], _sha(stored))


def to_jpeg_under(data: bytes, max_bytes: int, max_edge: int = 1600) -> bytes:
    image = open_image(data).convert("RGB")
    edge = max(image.size)
    if edge > max_edge:
        scale = max_edge / edge
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)
    quality = 85
    stored = b""
    while quality >= 40:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        stored = buffer.getvalue()
        if len(stored) <= max_bytes:
            return stored
        quality -= 10
        image = image.resize((max(1, int(image.width * 0.85)), max(1, int(image.height * 0.85))), Image.Resampling.LANCZOS)
    return stored


def prepare_provider_image(data: bytes, *, min_width: int, min_height: int) -> tuple[bytes, dict]:
    """Convert to JPEG within documented YouCam size limits and pad tiny crops."""
    image = open_image(data).convert("RGB")
    note = {"padded": False, "resized": False, "format": "image/jpeg"}
    edge = max(image.size)
    if edge > 4096:
        scale = 4096 / edge
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)
        note["resized"] = True
    if image.width < min_width or image.height < min_height:
        canvas = Image.new("RGB", (max(image.width, min_width), max(image.height, min_height)), (245, 241, 234))
        canvas.paste(image, ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2))
        image = canvas
        note["padded"] = True
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    stored = buffer.getvalue()
    if len(stored) >= 10_000_000:
        stored = to_jpeg_under(stored, 9_500_000, 4096)
        note["resized"] = True
    note["bytes"] = len(stored)
    note["width"] = image.size[0]
    note["height"] = image.size[1]
    return stored, note


def place_hat_on_original(original: Image.Image, generated: Image.Image, src_face: tuple[int, int, int, int], gen_face: tuple[int, int, int, int]) -> Image.Image:
    """Copy only the headwear from a hat-task result onto the original photo."""
    sx, sy, sw, _sh = src_face
    gx, gy, gw, gh = gen_face
    if sw < 8 or gw < 8 or gh < 8:
        return original
    gx0 = int(gx - 0.55 * gw)
    gy0 = int(gy - 1.35 * gh)
    gx1 = int(gx + gw + 0.55 * gw)
    gy1 = int(gy + 0.18 * gh)
    gx0c, gy0c = max(0, gx0), max(0, gy0)
    gx1c, gy1c = min(generated.width, gx1), min(generated.height, gy1)
    if gx1c - gx0c < 8 or gy1c - gy0c < 8:
        return original
    scale = sw / gw
    dx0 = int(sx + (gx0c - gx) * scale)
    dy0 = int(sy + (gy0c - gy) * scale)
    dw = max(1, int((gx1c - gx0c) * scale))
    dh = max(1, int((gy1c - gy0c) * scale))
    crop = generated.crop((gx0c, gy0c, gx1c, gy1c)).resize((dw, dh), Image.Resampling.LANCZOS)
    crop.putalpha(_hat_mask(dw, dh))
    canvas = original.convert("RGBA")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(crop, (dx0, dy0), crop)
    return Image.alpha_composite(canvas, layer).convert("RGB")


def keep_original_outfit(original: bytes, generated: bytes) -> tuple[bytes, str]:
    source = open_image(original).convert("RGB")
    result = open_image(generated).convert("RGB")
    src_face = _largest_face(source)
    gen_face = _largest_face(result)
    if src_face is None or gen_face is None:
        return generated, "full_result"
    placed = place_hat_on_original(source, result, src_face, gen_face)
    buffer = io.BytesIO()
    placed.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue(), "hat_only"


def _hat_mask(width: int, height: int) -> Image.Image:
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    fade_start = int(height * 0.62)
    draw.rectangle((0, 0, width, fade_start), fill=255)
    span = max(1, height - fade_start)
    for y in range(fade_start, height):
        alpha = int(255 * (1 - (y - fade_start) / span) ** 1.4)
        draw.line((0, y, width, y), fill=alpha)
    return mask.filter(ImageFilter.GaussianBlur(radius=max(1, width // 48)))


def _largest_face(image: Image.Image) -> tuple[int, int, int, int] | None:
    try:
        import cv2
    except ImportError:
        return None
    gray = cv2.cvtColor(_np_rgb(image), cv2.COLOR_RGB2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    if cascade.empty():
        return None
    found = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(32, 32))
    if len(found) == 0:
        return None
    x, y, w, h = max(found, key=lambda box: int(box[2]) * int(box[3]))
    return int(x), int(y), int(w), int(h)


def _np_rgb(image: Image.Image):
    import numpy as np

    return np.array(image.convert("RGB"))


def demo_composite(source: bytes, reference: bytes, category: str, origin: str) -> bytes:
    base = open_image(source).convert("RGB")
    ref = open_image(reference).convert("RGB")
    draw = ImageDraw.Draw(base)
    regions = {
        "hat": (0.3, 0.02, 0.4, 0.18),
        "scarf": (0.28, 0.18, 0.44, 0.14),
        "outerwear": (0.22, 0.2, 0.56, 0.38),
        "upper_body": (0.26, 0.22, 0.48, 0.3),
        "lower_body": (0.28, 0.52, 0.44, 0.3),
        "full_body": (0.22, 0.16, 0.56, 0.7),
        "shoes": (0.3, 0.8, 0.4, 0.16),
        "bag": (0.62, 0.34, 0.24, 0.28),
    }
    rx, ry, rw, rh = regions.get(category, (0.25, 0.25, 0.5, 0.3))
    box = (
        int(base.width * rx),
        int(base.height * ry),
        int(base.width * (rx + rw)),
        int(base.height * (ry + rh)),
    )
    thumb = ref.resize((max(1, box[2] - box[0]), max(1, box[3] - box[1])), Image.Resampling.LANCZOS)
    tinted = Image.blend(base.crop(box), thumb, 0.72)
    base.paste(tinted, box)
    accent = (154, 52, 18) if origin == "inspiration" else (30, 64, 84)
    draw.rectangle(box, outline=accent, width=max(2, base.width // 180))
    buffer = io.BytesIO()
    base.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def sample_person() -> bytes:
    image = Image.new("RGB", (768, 1024), (244, 236, 226))
    draw = ImageDraw.Draw(image)
    draw.ellipse((314, 70, 454, 230), fill=(214, 176, 154))
    draw.rounded_rectangle((250, 240, 518, 620), radius=40, fill=(88, 96, 108))
    draw.polygon([(250, 620), (518, 620), (560, 900), (208, 900)], fill=(55, 62, 78))
    draw.rounded_rectangle((230, 900, 340, 980), radius=12, fill=(72, 64, 58))
    draw.rounded_rectangle((428, 900, 538, 980), radius=12, fill=(72, 64, 58))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def sample_inspiration() -> bytes:
    image = Image.new("RGB", (768, 1024), (232, 224, 214))
    draw = ImageDraw.Draw(image)
    draw.ellipse((330, 48, 438, 170), fill=(196, 164, 146))
    draw.polygon([(300, 40), (468, 40), (430, 110), (338, 110)], fill=(122, 86, 64))
    draw.rounded_rectangle((250, 180, 520, 430), radius=24, fill=(142, 58, 34))
    draw.rectangle((270, 430, 500, 760), fill=(46, 58, 72))
    draw.ellipse((250, 760, 360, 860), fill=(28, 28, 28))
    draw.ellipse((410, 760, 520, 860), fill=(28, 28, 28))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def sample_product(category: str) -> bytes:
    colors = {
        "hat": (122, 86, 64),
        "scarf": (176, 92, 70),
        "shoes": (32, 32, 32),
        "outerwear": (46, 58, 72),
        "upper_body": (142, 58, 34),
        "lower_body": (70, 78, 96),
        "full_body": (90, 70, 84),
        "bag": (92, 74, 48),
    }
    image = Image.new("RGB", (640, 800), (250, 247, 242))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((170, 120, 470, 640), radius=28, fill=colors.get(category, (90, 70, 84)))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()
