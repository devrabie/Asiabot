import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.utils.card_parser import extract_card_number, normalize_text
from src.api.client import AsiacellClient

def test_normalize_text():
    assert normalize_text("١٢٣٤٥٦٧٨٩٠") == "1234567890"
    assert normalize_text("۰۱۲۳۴۵۶۷۸۹") == "0123456789"
    assert normalize_text("ABC 123") == "ABC 123"

def test_extract_card_number_direct():
    assert extract_card_number("123456789012345") == "123456789012345"
    assert extract_card_number("Card code: 12345678901234") == "12345678901234"

def test_extract_card_number_formatted():
    assert extract_card_number("1234 5678 9012 345") == "123456789012345"
    assert extract_card_number("1234-5678-9012-34") == "12345678901234"
    assert extract_card_number("1234.5678.9012.345") == "123456789012345"
    assert extract_card_number("123 456 789 012 345") == "123456789012345"

def test_extract_card_number_arabic_digits():
    assert extract_card_number("١٢٣٤٥٦٧٨٩٠١٢٣٤٥") == "123456789012345"
    assert extract_card_number("الرقم السري: ١٢٣٤ ٥٦٧٨ ٩٠١٢ ٣٤٥") == "123456789012345"

def test_extract_card_number_keywords():
    text = "Asiacell Card\nSerial: 9988776655\nالرقم السري\n\n123456789012345\nThank you"
    assert extract_card_number(text) == "123456789012345"

    text2 = "Asiacell Card\nSerial: 12345678901234\nالرقم السري: 987654321098765"
    assert extract_card_number(text2) == "987654321098765"

@pytest.mark.asyncio
async def test_extract_text_from_image_url_success():
    client = AsiacellClient()
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json.return_value = {"text": "123456789012345", "status": "success"}

    mock_post = AsyncMock()
    mock_post.__aenter__.return_value = mock_response

    with patch("aiohttp.ClientSession.post", return_value=mock_post):
        res = await client.extract_text_from_image_url("http://example.com/image.jpg")
        assert res == "123456789012345"

@pytest.mark.asyncio
async def test_extract_text_from_image_url_422_error():
    client = AsiacellClient()
    mock_response = AsyncMock()
    mock_response.status = 422
    mock_response.json.return_value = {"detail": "Failed to extract text from image using all available methods."}

    mock_post = AsyncMock()
    mock_post.__aenter__.return_value = mock_response

    with patch("aiohttp.ClientSession.post", return_value=mock_post):
        res = await client.extract_text_from_image_url("http://example.com/image.jpg")
        assert res == ""
