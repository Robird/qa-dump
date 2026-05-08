import json
import logging

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class LLMResponseError(Exception):
    pass


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.timeout = timeout

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = True,
    ) -> dict:
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        raw = self._post(body)
        return self._extract_json(raw)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((
            httpx.HTTPStatusError,
            httpx.TimeoutException,
            LLMResponseError,
        )),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _post(self, body: dict) -> dict:
        with httpx.Client() as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=body,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _extract_json(raw_response: dict) -> dict:
        try:
            content = raw_response["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMResponseError(f"Unexpected response structure: {e}")

        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            snippet = cleaned[:500]
            raise LLMResponseError(f"Invalid JSON from model: {e}\nContent preview: {snippet}")
