import asyncio
import uuid
import random
import aiohttp
from typing import Optional, Dict, Any, List, Union
from loguru import logger
from src.api.models import LoginResponse, TokenResponse

class AsiacellClient:
    BASE_URL = "https://odpapp.asiacell.com/api"
    API_KEY = "1ccbc4c913bc4ce785a0a2de444aa0d6"

    DEFAULT_HEADERS = {
        "User-Agent": "okhttp/5.0.0-alpha.2",
        "Content-Type": "application/json",
        "X-ODP-API-KEY": API_KEY,
        "X-OS-Version": "11",
        "X-Device-Type": "[Android][realme][RMX2189 11] [R]",
        "X-ODP-APP-VERSION": "4.2.4",
        "X-FROM-APP": "odp",
        "X-ODP-CHANNEL": "mobile",
        "X-SCREEN-TYPE": "MOBILE",
        "Cache-Control": "private, max-age=240"
    }

    def __init__(self, proxy_file: str = "data/proxies.txt"):
        self.proxies: List[str] = self._load_proxies(proxy_file)
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _load_proxies(self, filepath: str) -> List[str]:
        try:
            with open(filepath, "r") as f:
                lines = f.read().splitlines()
                # Filter out comments and empty lines
                return [
                    line.strip() for line in lines
                    if line.strip() and not line.strip().startswith("#")
                ]
        except FileNotFoundError:
            logger.warning(f"Proxy file not found at {filepath}. No proxies will be used.")
            return []

    def _get_random_proxy(self) -> Optional[str]:
        if not self.proxies:
            return None

        proxy_str = random.choice(self.proxies)
        try:
            # Format: ip:port:user:pass
            parts = proxy_str.split(":")
            if len(parts) == 4:
                ip, port, user, password = parts
                return f"http://{user}:{password}@{ip}:{port}"
            elif len(parts) == 2:
                ip, port = parts
                return f"http://{ip}:{port}"
            else:
                logger.warning(f"Invalid proxy format: {proxy_str}")
                return None
        except Exception as e:
            logger.error(f"Error parsing proxy {proxy_str}: {e}")
            return None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers=self.DEFAULT_HEADERS,
                cookie_jar=aiohttp.DummyCookieJar()
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        session = await self._get_session()
        retries = 2

        for attempt in range(retries + 1):
            proxy = self._get_random_proxy()

            try:
                logger.debug(f"Requesting {method} {url} (Attempt {attempt+1}/{retries+1}) Proxy: {proxy is not None}")

                async with session.request(method, url, proxy=proxy, **kwargs) as response:
                    response.raise_for_status()

                    data = None
                    try:
                        data = await response.json()
                    except:
                        data = await response.text()

                    return {
                        "status": response.status,
                        "headers": dict(response.headers),
                        "cookies": response.cookies,
                        "data": data
                    }

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                # Log generic error to avoid leaking proxy details if desired,
                # or rely on log levels.
                # To make it "untraceable" in logs as requested, we hide the detailed exception string
                # if it contains the proxy IP.
                err_str = str(e)
                if proxy:
                    # Simple masking if proxy string is present in error
                    # Note: e might be complex, so this is a basic attempt
                    safe_err = "Connection failed"
                else:
                    safe_err = err_str

                logger.warning(f"Request failed: {safe_err}. Retrying...")
                if attempt == retries:
                    logger.error("Max retries reached.")
                    raise e
                await asyncio.sleep(1) # small delay
            except Exception as e:
                logger.exception(f"Unexpected error: {e}")
                raise e

        raise Exception("Unreachable code in _request")

    @staticmethod
    def generate_device_id() -> str:
        return str(uuid.uuid4())

    async def get_login_cookie(self) -> str:
        url = f"{self.BASE_URL}/v1/login-screen?lang=ar"
        response = await self._request("GET", url)
        cookies = response.get("cookies", {})

        # If we have parsed cookies, construct the header value without attributes
        if cookies:
            cookie_parts = []
            for name, morsel in cookies.items():
                cookie_parts.append(f"{name}={morsel.value}")
            return "; ".join(cookie_parts)

        # Fallback to header extraction if no cookies in jar (unlikely with aiohttp)
        headers = response.get("headers", {})
        for k, v in headers.items():
            if k.lower() == "set-cookie":
                # PHP: explode(';', $session_data[0])[0]
                # Return only the name=value part
                return v.split(';')[0]
        return ""

    async def send_login_code(self, device_id: str, cookie: str, phone_number: str) -> LoginResponse:
        url = f"{self.BASE_URL}/v1/login?lang=ar"

        headers = {
            "DeviceID": device_id,
        }

        body = {
            "username": phone_number,
            "captchaCode": ""
        }

        response = await self._request("POST", url, headers=headers, json=body)
        return LoginResponse.model_validate(response.get("data", {}))

    async def validate_sms_code(self, session_cookie: str, device_id: str, pid: str, otp_code: str) -> TokenResponse:
        url = f"{self.BASE_URL}/v1/smsvalidation?lang=ar"

        headers = {
            "DeviceID": device_id,
        }

        body = {
            "PID": pid,
            "token": self.API_KEY,
            "passcode": otp_code
        }

        response = await self._request("POST", url, headers=headers, json=body)
        return TokenResponse.model_validate(response.get("data", {}))

    async def get_balance(self, access_token: str, device_id: str, cookie: str) -> Any:
        url = f"{self.BASE_URL}/v2/home?lang=ar"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "DeviceID": device_id,
        }

        response = await self._request("GET", url, headers=headers)
        return response.get("data")

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        url = f"{self.BASE_URL}/v1/validate"

        # PHP implementation does NOT send Authorization header for this request
        # It sends refreshToken in the body.

        body = {
            "refreshToken": f"Bearer {refresh_token}"
        }

        response = await self._request("POST", url, json=body)
        return TokenResponse.model_validate(response.get("data", {}))

    async def submit_recharge_other(self, voucher_code: str, target_msisdn: str, access_token: str) -> dict:
        url = f"{self.BASE_URL}/v1/top-up?lang=ar"

        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        body = {
            "voucher": voucher_code,
            "msisdn": target_msisdn,
            "rechargeType": 1
        }

        response = await self._request("POST", url, headers=headers, json=body)
        return response.get("data", {})
