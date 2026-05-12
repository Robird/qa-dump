"""Runtime construction helpers for policy_text generation."""

from __future__ import annotations

from contextlib import ExitStack, closing
from dataclasses import dataclass

from api import LLMClient
from policy_text_generator import PolicyTextGenerator
from policy_text_judge import PolicyTextSemanticJudge


@dataclass(frozen=True)
class PolicyTextRuntimeConfig:
    model: str
    temperature: float
    judge_model: str | None = None

    @property
    def resolved_judge_model(self) -> str:
        return self.judge_model or self.model


@dataclass(frozen=True)
class PolicyTextRuntime:
    generator: PolicyTextGenerator
    semantic_judge: PolicyTextSemanticJudge


def build_policy_text_runtime(
    stack: ExitStack,
    *,
    base_url: str,
    api_key: str,
    language: str,
    config: PolicyTextRuntimeConfig,
) -> PolicyTextRuntime:
    llm = stack.enter_context(closing(LLMClient(base_url=base_url, api_key=api_key, model=config.model)))
    judge_llm = llm
    if config.resolved_judge_model != config.model:
        judge_llm = stack.enter_context(
            closing(LLMClient(base_url=base_url, api_key=api_key, model=config.resolved_judge_model))
        )
    return PolicyTextRuntime(
        generator=PolicyTextGenerator(
            llm,
            language=language,
            temperature=config.temperature,
        ),
        semantic_judge=PolicyTextSemanticJudge(judge_llm, language=language),
    )
