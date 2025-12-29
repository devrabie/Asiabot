import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.api.client import AsiacellClient
from src.api.models import LoginResponse, TokenResponse
import aiohttp

@pytest.mark.asyncio
async def test_client_initialization():
    client = AsiacellClient(proxy_file="data/proxies.txt")
    assert client.proxies is not None
    assert len(client.proxies) > 0
    # Check that proxies are loaded correctly
    assert "http://user1:pass1@127.0.0.1:8080" in [client._get_random_proxy() for _ in range(100)]

@pytest.mark.asyncio
async def test_generate_device_id():
    uuid_val = AsiacellClient.generate_device_id()
    assert len(uuid_val) == 36
    assert "-" in uuid_val

@pytest.mark.asyncio
async def test_request_retry_logic():
    client = AsiacellClient()

    # Mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {"Content-Type": "application/json"}
    mock_response.json.return_value = {"success": True}
    mock_response.cookies = {}

    # Mock context manager returned by session.request
    mock_request_ctx = AsyncMock()
    mock_request_ctx.__aenter__.return_value = mock_response
    mock_request_ctx.__aexit__.return_value = None

    # Mock session
    mock_session = MagicMock()
    mock_session.request.return_value = mock_request_ctx
    mock_session.closed = False

    with patch("aiohttp.ClientSession", return_value=mock_session):
        response = await client._request("GET", "http://test.com")
        # Now expecting the wrapper dict
        assert response["data"] == {"success": True}
        assert response["status"] == 200
        assert mock_session.request.call_count == 1

@pytest.mark.asyncio
async def test_send_login_code_model():
    client = AsiacellClient()

    mock_response = {"status": 200, "headers": {}, "cookies": {}, "data": {"nextUrl": "http://test.com?PID=123"}}

    with patch.object(client, '_request', new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response
        response = await client.send_login_code("devid", "cookie", "07712345678")
        assert isinstance(response, LoginResponse)
        assert response.nextUrl == "http://test.com?PID=123"

@pytest.mark.asyncio
async def test_validate_sms_code_model():
    client = AsiacellClient()

    mock_response = {"status": 200, "headers": {}, "cookies": {}, "data": {"access_token": "at", "refresh_token": "rt"}}

    with patch.object(client, '_request', new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response
        response = await client.validate_sms_code("cookie", "devid", "pid", "123456")
        assert isinstance(response, TokenResponse)
        assert response.access_token == "at"
