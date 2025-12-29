import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.api.client import AsiacellClient
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
async def test_request_retry_failure():
    client = AsiacellClient()

    # Mock session that raises exception
    mock_session = MagicMock()

    # Mock context manager to raise on enter
    mock_request_ctx = AsyncMock()
    mock_request_ctx.__aenter__.side_effect = aiohttp.ClientError("Network Error")
    mock_request_ctx.__aexit__.return_value = None

    mock_session.request.return_value = mock_request_ctx
    mock_session.closed = False

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(aiohttp.ClientError, match="Network Error"):
             await client._request("GET", "http://test.com")

        # Should be called 3 times (1 initial + 2 retries)
        assert mock_session.request.call_count == 3
