import asyncio
import uuid
import random
import aiohttp
from typing import Optional, Dict, Any, List
from loguru import logger

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

    def _load_proxies(self, filepath: str) -> List[str]:
        try:
            with open(filepath, "r") as f:
                lines = f.read().splitlines()
                return [line.strip() for line in lines if line.strip()]
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
            self.session = aiohttp.ClientSession(headers=self.DEFAULT_HEADERS)
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
                logger.warning(f"Request failed: {e}. Retrying...")
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
        # Assuming the caller needs the raw Set-Cookie header value
        headers = response.get("headers", {})
        # Headers are case-insensitive in aiohttp but dict conversion might not be.
        # But multidict usually handles case insensitive lookups.
        # However we converted to dict.
        # Let's try to find it safely.
        for k, v in headers.items():
            if k.lower() == "set-cookie":
                return v
        return ""

    async def send_login_code(self, device_id: str, cookie: str, phone_number: str) -> Any:
        url = f"{self.BASE_URL}/v1/login?lang=ar"

        headers = {
            "DeviceID": device_id,
            "Cookie": cookie
        }

        body = {
            "username": phone_number,
            "captchaCode": ""
        }

        response = await self._request("POST", url, headers=headers, json=body)
        return response.get("data")

    async def validate_sms_code(self, session_cookie: str, device_id: str, pid: str, otp_code: str) -> Dict[str, str]:
        url = f"{self.BASE_URL}/v1/smsvalidation?lang=ar"

        headers = {
            "DeviceID": device_id,
            "Cookie": session_cookie
        }

        body = {
            "PID": pid,
            "token": self.API_KEY,
            "passcode": otp_code
        }

        response = await self._request("POST", url, headers=headers, json=body)
        data = response.get("data", {})
        if isinstance(data, dict):
             return data
        return {}

    async def get_balance(self, access_token: str, device_id: str, cookie: str) -> Any:
        url = f"{self.BASE_URL}/v2/home?lang=ar"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "DeviceID": device_id,
            "Cookie": cookie
        }

        response = await self._request("GET", url, headers=headers)
        return response.get("data")
