import asyncio
import json
import os
from typing import Any

import httpx
from cachetools import TTLCache
from dotenv import load_dotenv

load_dotenv()

_instance: "CongressClient | None" = None


def get_client() -> "CongressClient":
    global _instance
    if _instance is None:
        api_key = os.environ.get("CONGRESS_API_KEY")
        if not api_key:
            raise RuntimeError("CONGRESS_API_KEY environment variable is not set")
        _instance = CongressClient(api_key=api_key)
    return _instance


class CongressClient:
    BASE_URL = "https://api.congress.gov/v3"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._http = httpx.AsyncClient(timeout=30.0)
        self._cache: TTLCache = TTLCache(maxsize=512, ttl=300)
        self._lock = asyncio.Lock()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = {**(params or {}), "api_key": self._api_key, "format": "json"}
        cache_key = f"{path}:{json.dumps(merged, sort_keys=True)}"

        async with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        for attempt in range(2):
            try:
                response = await self._http.get(
                    f"{self.BASE_URL}/{path}", params=merged
                )
            except httpx.NetworkError:
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return {
                    "error": "network_error",
                    "message": "Unable to reach Congress.gov API. Please try again.",
                }

            if response.status_code == 429:
                return {
                    "error": "rate_limited",
                    "message": "Congress.gov API rate limit reached. Please wait a moment and try again.",
                }
            if response.status_code == 404:
                return {"error": "not_found", "message": f"Not found: {path}"}

            response.raise_for_status()
            data: dict[str, Any] = response.json()

            async with self._lock:
                self._cache[cache_key] = data

            return data

        return {
            "error": "network_error",
            "message": "Unable to reach Congress.gov API after retry.",
        }
