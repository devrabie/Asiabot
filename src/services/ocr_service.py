import asyncio
import io
import os
from typing import Optional, Tuple

import aiohttp
import pytesseract
from loguru import logger
from PIL import Image, ImageOps

from src.config import settings
from src.utils.card_parser import extract_card_number

OCR_SPACE_URL = "https://api.ocr.space/parse/image"
LOCAL_BOT_API_CONTAINER_PREFIX = "/var/lib/telegram-bot-api/"
LOCAL_BOT_API_HOST_PREFIX = "/var/lib/docker/volumes/telegram-bot-server_telegram-bot-api-data/_data/"


def _resolve_local_file_path(file_path: str) -> Optional[str]:
    """Resolve a local Bot API file path to an existing file on the host filesystem."""
    if not file_path:
        return None
    if os.path.isfile(file_path):
        return file_path
    if file_path.startswith(LOCAL_BOT_API_CONTAINER_PREFIX):
        mapped = LOCAL_BOT_API_HOST_PREFIX + file_path[len(LOCAL_BOT_API_CONTAINER_PREFIX):]
        if os.path.isfile(mapped):
            return mapped
    return None


def _resolve_file_download_url(bot, file_path: str) -> str:
    """Resolve a Telegram Bot API file_path into an HTTP download URL."""
    if file_path.startswith(("http://", "https://")):
        return file_path

    base_url = "https://api.telegram.org"
    raw_base = getattr(bot, "base_url", None)
    if raw_base:
        base_str = str(raw_base).rstrip("/")
        token_suffix = f"/bot{bot.token}"
        if base_str.endswith(token_suffix):
            base_url = base_str[: -len(token_suffix)]
        elif base_str.endswith("/bot"):
            base_url = base_str[:-4]
        else:
            base_url = base_str

    rel_path = file_path.lstrip("/")
    marker = f"{bot.token}/"
    if marker in rel_path:
        rel_path = rel_path.split(marker, 1)[1]

    return f"{base_url}/file/bot{bot.token}/{rel_path}"


async def download_telegram_photo_bytes(bot, file_id: str, timeout_seconds: int = 10) -> bytes:
    """Download a Telegram photo into memory, supporting local Bot API volumes and standard HTTP."""
    tg_file = await bot.get_file(file_id)
    file_path = tg_file.file_path or ""

    local_path = _resolve_local_file_path(file_path)
    if local_path:
        def _read_local() -> bytes:
            with open(local_path, "rb") as f:
                return f.read()

        return await asyncio.to_thread(_read_local)

    download_url = _resolve_file_download_url(bot, file_path)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(download_url) as resp:
            resp.raise_for_status()
            return await resp.read()


def _parse_ocr_space_response(data: dict) -> str:
    """Extract parsed text from an OCR.space JSON response."""
    if not isinstance(data, dict):
        return ""
    if data.get("IsErroredOnProcessing"):
        err = data.get("ErrorMessage") or data.get("ErrorDetails")
        logger.warning(f"OCR.space processing error: {err}")
        return ""
    results = data.get("ParsedResults") or []
    return "\n".join(
        str(item.get("ParsedText") or "").strip()
        for item in results
        if isinstance(item, dict) and item.get("ParsedText")
    ).strip()


async def _extract_via_ocr_space(image_bytes: bytes) -> str:
    """Send image bytes directly to OCR.space (OCREngine=2) like Store_bot."""
    api_key = (settings.OCR_SPACE_API_KEY or "").strip()
    if not api_key:
        return ""

    form = aiohttp.FormData()
    form.add_field("language", "auto")
    form.add_field("isOverlayRequired", "false")
    form.add_field("scale", "true")
    form.add_field("OCREngine", "2")
    form.add_field("detectOrientation", "true")
    form.add_field("isTable", "true")
    form.add_field("file", image_bytes, filename="card.jpg", content_type="image/jpeg")

    timeout = aiohttp.ClientTimeout(total=settings.OCR_SPACE_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OCR_SPACE_URL,
                data=form,
                headers={"apikey": api_key, "Accept": "application/json"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return _parse_ocr_space_response(data)
                logger.warning(f"OCR.space returned HTTP {resp.status}")
    except Exception as exc:
        logger.warning(f"OCR.space request failed: {exc}")
    return ""


def _prepare_image(image_bytes: bytes) -> Image.Image:
    """Convert raw image bytes to an upscaled, high-contrast grayscale image for Tesseract fallback."""
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img).convert("L")
    img = ImageOps.autocontrast(img)

    if img.width < 1000:
        scale = max(2, 1200 // max(img.width, 1))
        img = img.resize((img.width * scale, img.height * scale), Image.Resampling.LANCZOS)

    return img


def _ocr_sync(image_bytes: bytes) -> Tuple[Optional[str], str]:
    """Run fast multi-pass Tesseract OCR synchronously inside a worker thread."""
    img = _prepare_image(image_bytes)

    passes = [
        ("eng", "--psm 6", img),
        ("eng", "--psm 11 -c tessedit_char_whitelist=0123456789", img),
        ("eng", "--psm 6 -c tessedit_char_whitelist=0123456789", img.point(lambda p: 255 if p > 140 else 0)),
    ]

    best_text = ""
    for lang, config, target_img in passes:
        try:
            text = pytesseract.image_to_string(target_img, lang=lang, config=config) or ""
        except Exception as exc:
            logger.warning(f"Tesseract pass ({config}) failed: {exc}")
            continue

        if text and not best_text:
            best_text = text

        code = extract_card_number(text)
        if code:
            return code, text

    return None, best_text


async def extract_card_from_image_bytes(image_bytes: bytes) -> Tuple[Optional[str], str]:
    """Extract a 14 or 15 digit recharge code via OCR.space first, with Tesseract fallback."""
    ocr_space_text = await _extract_via_ocr_space(image_bytes)
    if ocr_space_text:
        code = extract_card_number(ocr_space_text)
        if code:
            return code, ocr_space_text

    code, tesseract_text = await asyncio.to_thread(_ocr_sync, image_bytes)
    return code, tesseract_text or ocr_space_text
