import asyncio
import io
import os
from typing import Optional, Tuple

import aiohttp
import pytesseract
from loguru import logger
from PIL import Image, ImageOps

from src.utils.card_parser import extract_card_number


def _resolve_file_download_url(bot, file_path: str) -> str:
    """Resolve a Telegram Bot API file_path into an HTTP download URL."""
    if file_path.startswith(("http://", "https://")):
        return file_path

    base_url = "https://api.telegram.org"
    raw_base = getattr(bot, "base_url", None)
    if raw_base:
        # PTB's bot.base_url typically ends with '/bot' (e.g. 'http://localhost:8081/bot')
        base_str = str(raw_base).rstrip("/")
        if base_str.endswith("/bot"):
            base_url = base_str[:-4]
        else:
            base_url = base_str

    rel_path = file_path.lstrip("/")
    # Local telegram-bot-api container returns paths like '/var/lib/telegram-bot-api/<token>/photos/file_0.jpg'
    marker = f"{bot.token}/"
    if marker in rel_path:
        rel_path = rel_path.split(marker, 1)[1]

    return f"{base_url}/file/bot{bot.token}/{rel_path}"


async def download_telegram_photo_bytes(bot, file_id: str, timeout_seconds: int = 10) -> bytes:
    """Download a Telegram photo into memory, supporting both local Bot API and standard API."""
    tg_file = await bot.get_file(file_id)
    file_path = tg_file.file_path or ""

    if file_path and os.path.isfile(file_path):
        def _read_local() -> bytes:
            with open(file_path, "rb") as f:
                return f.read()

        return await asyncio.to_thread(_read_local)

    download_url = _resolve_file_download_url(bot, file_path)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(download_url) as resp:
            resp.raise_for_status()
            return await resp.read()


def _prepare_image(image_bytes: bytes) -> Image.Image:
    """Convert raw image bytes to an upscaled, high-contrast grayscale image for OCR."""
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img).convert("L")
    img = ImageOps.autocontrast(img)

    # Upscale smaller images so Tesseract reads 14-15 digit scratch card numbers cleanly
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
    """Extract a 14 or 15 digit recharge code from image bytes without blocking the event loop."""
    return await asyncio.to_thread(_ocr_sync, image_bytes)
