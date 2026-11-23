import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from src.services.ocr_service import (
    _resolve_file_download_url,
    extract_card_from_image_bytes,
)


def _make_dummy_png_bytes() -> bytes:
    img = Image.new("RGB", (400, 120), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_resolve_file_download_url_local_bot_api():
    bot = SimpleNamespace(token="123:ABC", base_url="http://localhost:8081/bot")
    url = _resolve_file_download_url(bot, "/var/lib/telegram-bot-api/123:ABC/photos/file_5.jpg")
    assert url == "http://localhost:8081/file/bot123:ABC/photos/file_5.jpg"


def test_resolve_file_download_url_standard_api():
    bot = SimpleNamespace(token="123:ABC", base_url="https://api.telegram.org/bot")
    url = _resolve_file_download_url(bot, "photos/file_5.jpg")
    assert url == "https://api.telegram.org/file/bot123:ABC/photos/file_5.jpg"


def test_resolve_file_download_url_passthrough():
    bot = SimpleNamespace(token="123:ABC", base_url="https://api.telegram.org/bot")
    url = _resolve_file_download_url(bot, "https://cdn.example.com/card.jpg")
    assert url == "https://cdn.example.com/card.jpg"


@pytest.mark.asyncio
async def test_extract_card_from_image_bytes_stops_on_first_valid_pass():
    png_bytes = _make_dummy_png_bytes()
    with patch("src.services.ocr_service.pytesseract.image_to_string") as mock_ocr:
        mock_ocr.return_value = "Asiacell PIN: 1234 5678 9012 345"
        code, raw = await extract_card_from_image_bytes(png_bytes)
        assert code == "123456789012345"
        assert "1234 5678 9012 345" in raw
        assert mock_ocr.call_count == 1


@pytest.mark.asyncio
async def test_extract_card_from_image_bytes_falls_back_to_second_pass():
    png_bytes = _make_dummy_png_bytes()
    with patch("src.services.ocr_service.pytesseract.image_to_string") as mock_ocr:
        mock_ocr.side_effect = ["noisy text", "98765432109876"]
        code, _ = await extract_card_from_image_bytes(png_bytes)
        assert code == "98765432109876"
        assert mock_ocr.call_count == 2
