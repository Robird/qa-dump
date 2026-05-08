from dataclasses import dataclass
import json
import logging
import re
from typing import Any

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


@dataclass(frozen=True)
class ChatJSONResult:
    data: dict[str, Any]
    reasoning_content: str = ""


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
    ) -> dict:
        return self.chat_json_result(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ).data

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
    def chat_json_result(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> ChatJSONResult:
        raw = self._post(self._build_chat_body(messages, temperature, max_tokens))
        return self._parse_chat_json_result(raw)

    def _build_chat_body(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

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

    @classmethod
    def _parse_chat_json_result(cls, raw_response: dict) -> ChatJSONResult:
        return ChatJSONResult(
            data=cls._extract_json(raw_response),
            reasoning_content=cls._extract_reasoning_content(raw_response),
        )

    @staticmethod
    def _extract_json(raw_response: dict) -> dict:
        try:
            message = raw_response["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise LLMResponseError(f"Unexpected response structure: {e}")

        cleaned = LLMClient._normalize_message_content(message.get("content", ""))
        if not cleaned:
            finish_reason = raw_response.get("choices", [{}])[0].get("finish_reason", "unknown")
            reasoning = LLMClient._extract_reasoning_content(raw_response).strip()
            raise LLMResponseError(
                "Empty content from model when JSON was expected. "
                f"finish_reason={finish_reason!r}, reasoning_preview={reasoning[:200]!r}"
            )

        cleaned = LLMClient._strip_code_fences(cleaned)
        candidate = LLMClient._extract_json_candidate(cleaned)

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as e:
            snippet = cleaned[:500]
            raise LLMResponseError(f"Invalid JSON from model: {e}\nContent preview: {snippet}")
        if not isinstance(parsed, dict):
            raise LLMResponseError(f"Expected JSON object from model, got {type(parsed).__name__}")
        return parsed

    @staticmethod
    def _normalize_message_content(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    text = item.strip()
                    if text:
                        parts.append(text)
                    continue
                if not isinstance(item, dict):
                    continue
                text = item.get("text") or item.get("content", "")
                if text:
                    parts.append(str(text).strip())
            return "\n".join(part for part in parts if part).strip()
        return str(content).strip() if content else ""

    @staticmethod
    def _strip_code_fences(content: str) -> str:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            lines = [line for line in lines if not line.startswith("```")]
            cleaned = "\n".join(lines).strip()
        return cleaned

    @staticmethod
    def _extract_json_candidate(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if match:
            return match.group(0)
        return stripped

    @staticmethod
    def _extract_reasoning_content(raw_response: dict) -> str:
        try:
            message = raw_response["choices"][0]["message"]
        except (KeyError, IndexError):
            return ""

        reasoning = message.get("reasoning_content", "")
        if isinstance(reasoning, list):
            parts: list[str] = []
            for item in reasoning:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    if text:
                        parts.append(str(text))
                elif item:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(reasoning) if reasoning else ""
