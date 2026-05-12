"""LLM-backed realization of structured policy records into text."""

from __future__ import annotations

import hashlib
import json
import re

from api import LLMClient, LLMResponseError
from policy_models import PolicyRecord
from policy_text_models import (
    DEFER_CUES_ZH,
    DEFER_CUES_EN,
    IMMEDIATE_HELP_CUES_ZH,
    IMMEDIATE_HELP_CUES_EN,
    IntentSpec,
    PolicyTextRealization,
    PolicyTextRealizationInput,
    PolicyTextDecisionInput,
    PolicyTextRelationInput,
    PolicyTextRequestContextInput,
    PolicyTextStateInput,
)


STYLE_PROFILES: dict[str, str] = {
    "warm_brief_v1": "Warm, concise, human, slightly relational.",
    "neutral_direct_v1": "Neutral, direct, practical, low-drama.",
    "guarded_soft_v1": "Soft but guarded, slightly defensive, still natural.",
    "busy_practical_v1": "Busy, time-aware, practical, task-focused.",
    "candid_close_v1": "Candid and familiar, appropriate for closer relationships.",
}

HIGH_SIGNAL_REASON_TAGS: tuple[str, ...] = (
    "time_pressure_high",
    "energy_low",
    "energy_high",
    "can_do_later",
    "can_do_now",
    "trust_constrains_engagement",
    "trust_enables_engagement",
    "closeness_enables_engagement",
    "tension_inhibits_engagement",
    "regret_high",
    "socially_guarded",
    "socially_ready",
    "clarity_constrains",
    "clarity_enables",
)


def select_text_profile(source_policy_record_id: str, seed: int) -> str:
    names = sorted(STYLE_PROFILES)
    digest = hashlib.sha256(f"{seed}:{source_policy_record_id}".encode("utf-8")).digest()
    return names[int.from_bytes(digest[:4], "big") % len(names)]


class PolicyTextGenerator:
    def __init__(
        self,
        llm: LLMClient,
        *,
        language: str,
        temperature: float = 0.8,
        max_tokens: int = 300,
    ):
        self.llm = llm
        self.language = language
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(
        self,
        policy_record: PolicyRecord,
        *,
        intent_spec: IntentSpec,
        text_profile: str,
    ) -> PolicyTextRealization:
        profile_instruction = STYLE_PROFILES[text_profile]
        realization_input = self._project_policy_record(policy_record, intent_spec=intent_spec)
        messages = [
            {
                "role": "system",
                "content": self._system_prompt(),
            },
            {
                "role": "user",
                "content": self._user_prompt(
                    realization_input,
                    intent_spec=intent_spec,
                    text_profile=text_profile,
                    profile_instruction=profile_instruction,
                ),
            },
        ]
        raw = self.llm.chat_json_result(
            messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        realization = PolicyTextRealization(**raw.data)
        issues = self.validate(
            realization,
            intent_spec=intent_spec,
        )
        if issues:
            raise LLMResponseError(
                "Policy text realization failed validation: " + "; ".join(issues)
            )
        return realization

    def validate(
        self,
        realization: PolicyTextRealization,
        *,
        intent_spec: IntentSpec,
    ) -> list[str]:
        issues: list[str] = []
        belief = realization.belief.strip()
        thinking = realization.thinking.strip()
        if not belief:
            issues.append("belief is empty")
        if not thinking:
            issues.append("thinking is empty")
        if len(belief) > 220:
            issues.append("belief too long")
        if len(thinking) > 120:
            issues.append("thinking too long")
        lowered = f"{belief}\n{thinking}".lower()
        for forbidden in (
            "relation_closeness",
            "trust_in_target",
            "role_obligation",
            "power_asymmetry",
            "unfinished_tension",
            "reciprocity_history",
            "time_pressure",
            "cognitive_clarity",
            "reason_tags",
        ):
            if forbidden in lowered:
                issues.append(f"contains schema jargon: {forbidden}")
        if self.language == "zh" and belief and "我" not in belief:
            issues.append("belief should be first-person in zh")
        if self.language == "en" and belief and not re.search(r"\b(i|i'm|i’ve|i'd|i'll|me|my)\b", belief.lower()):
            issues.append("belief should be first-person in en")
        immediate_help_cues = self._immediate_help_cues()
        must_have_cues, must_not_have_cues = self._intent_cues(intent_spec)
        if not intent_spec.will_help_now and self._contains_any(thinking, immediate_help_cues):
            issues.append("thinking implies immediate help while will_help_now=false")
        if intent_spec.will_help_now and not self._contains_any(thinking, immediate_help_cues):
            issues.append("help_now intent missing immediate-help cue")
        if must_have_cues and not self._contains_any(thinking, must_have_cues):
            issues.append(f"{intent_spec.response_intent} intent missing cue")
        if must_not_have_cues and self._contains_any(thinking, must_not_have_cues):
            issues.append(f"{intent_spec.response_intent} intent contains conflicting cue")
        return issues

    @staticmethod
    def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
        lowered = text.lower()
        return any(cue.lower() in lowered for cue in cues)

    def _immediate_help_cues(self) -> tuple[str, ...]:
        if self.language == "zh":
            return IMMEDIATE_HELP_CUES_ZH
        return IMMEDIATE_HELP_CUES_EN

    def _intent_cues(self, intent_spec: IntentSpec) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if self.language == "zh":
            return intent_spec.must_have_any_zh, intent_spec.must_not_have_any_zh
        return intent_spec.must_have_any_en, intent_spec.must_not_have_any_en

    def _intent_cue_prompt_lines(self, intent_spec: IntentSpec) -> tuple[str, ...]:
        must_have_cues, must_not_have_cues = self._intent_cues(intent_spec)
        lines: list[str] = []
        if self.language == "zh":
            if must_have_cues:
                lines.append(
                    "- thinking 应至少自然体现下面任一表达倾向（不必逐字照抄，但语义要明显）："
                    + ", ".join(must_have_cues)
                    + "。\n"
                )
            if must_not_have_cues:
                lines.append(
                    "- 避免出现会把 thinking 误导成别的分支的表达，例如："
                    + ", ".join(must_not_have_cues)
                    + "。\n"
                )
            return tuple(lines)

        if must_have_cues:
            lines.append(
                "- thinking should naturally convey at least one of these phrasing cues "
                "(not verbatim, but clearly similar in meaning): "
                + ", ".join(must_have_cues)
                + ".\n"
            )
        if must_not_have_cues:
            lines.append(
                "- Avoid wording that would make the branch read like a different intent, for example: "
                + ", ".join(must_not_have_cues)
                + ".\n"
            )
        return tuple(lines)

    @staticmethod
    def _select_reason_tags(policy_record: PolicyRecord) -> list[str]:
        selected = [tag for tag in policy_record.policy.reason_tags if tag in HIGH_SIGNAL_REASON_TAGS]
        if not selected:
            selected = [
                tag for tag in policy_record.policy.reason_tags if tag not in {"cost_acceptable", "risk_acceptable"}
            ]
        return selected[:4]

    def _project_policy_record(
        self,
        policy_record: PolicyRecord,
        *,
        intent_spec: IntentSpec,
    ) -> PolicyTextRealizationInput:
        return PolicyTextRealizationInput(
            relation=PolicyTextRelationInput(
                label=policy_record.relation.relation_label,
                closeness=policy_record.relation.relation_closeness,
                trust=policy_record.relation.trust_in_target,
                obligation=policy_record.relation.role_obligation,
                tension=policy_record.relation.unfinished_tension,
                reciprocity=policy_record.relation.reciprocity_history,
                power=policy_record.relation.power_asymmetry,
            ),
            state=PolicyTextStateInput(
                energy=policy_record.state.energy,
                time_pressure=policy_record.state.time_pressure,
                clarity=policy_record.state.cognitive_clarity,
                emotional_activation=policy_record.state.emotional_activation,
                social_readiness=policy_record.state.social_readiness,
                confidence=policy_record.state.confidence_in_doing_the_action,
            ),
            request_context=PolicyTextRequestContextInput(
                is_doable_now=policy_record.request_contract.is_doable_now,
            ),
            decision=PolicyTextDecisionInput(
                will_help_now=intent_spec.will_help_now,
                response_intent=intent_spec.response_intent,
                policy_decision=policy_record.policy.decision,
                policy_strategy=policy_record.policy.strategy,
            ),
            reason_tags=self._select_reason_tags(policy_record),
        )

    def _system_prompt(self) -> str:
        if self.language == "zh":
            return (
                "你要把结构化的社交决策记录，改写成自然、简短、可读的中文文本。"
                "输出必须是 JSON 对象，且只包含 belief 和 thinking 两个字符串字段。"
                "belief 是第一人称已知背景；thinking 是可见的简短理由和结论。"
                "不要输出长链路推理，不要泄露字段名，不要写模板化标签。"
            )
        return (
            "Rewrite a structured social decision record into short natural text."
            " Return a JSON object with only belief and thinking."
            " belief is first-person known context; thinking is a short visible reason plus conclusion."
            " Do not expose schema labels or long chain-of-thought."
        )

    def _user_prompt(
        self,
        realization_input: PolicyTextRealizationInput,
        *,
        intent_spec: IntentSpec,
        text_profile: str,
        profile_instruction: str,
    ) -> str:
        if self.language == "zh":
            branch_rule = (
                "结论必须明确表示：现在不帮忙。"
                if not intent_spec.will_help_now
                else "结论必须明确表示：现在就帮忙。"
            )
            intent_cue_lines = "".join(self._intent_cue_prompt_lines(intent_spec))
            return (
                f"Language: {self.language}\n"
                f"text_profile: {text_profile}\n"
                f"profile_instruction: {profile_instruction}\n"
                f"decision: {intent_spec.decision}\n"
                f"response_intent: {intent_spec.response_intent}\n"
                f"will_help_now: {json.dumps(intent_spec.will_help_now)}\n"
                f"intent_description: {intent_spec.prompt_description_zh}\n"
                f"branch_rule: {branch_rule}\n\n"
                "Realization input:\n"
                f"{json.dumps(realization_input.model_dump(), ensure_ascii=False, indent=2)}\n\n"
                "Requirements:\n"
                "- belief 必须是第一人称，基于 realization input 自然表达，不要像字段翻译。\n"
                "- belief 应自然提到关系背景和我当前状态，不必覆盖每个字段。\n"
                "- thinking 必须是 1-3 句短句，给出可见理由和行动结论。\n"
                "- thinking 必须符合 response_intent，不要只满足二分类分支。\n"
                "- reason_tags 只是可参考线索，不是逐条复述清单。\n"
                "- 不要编造名字、性别、具体任务细节或场景细节。\n"
                "- 如果身份细节未给出，优先用对方、这个人、这位同事等中性称呼。\n"
                f"{intent_cue_lines}"
                f"- defer 类表达应包含这类推迟感：{', '.join(DEFER_CUES_ZH)}。\n"
                f"- help_now 类表达应包含明确立即帮忙感：{', '.join(IMMEDIATE_HELP_CUES_ZH)}。\n"
                "- 不要输出原始字段名，不要写成长链路推理。\n"
                "- Return JSON only.\n"
            )

        response_rule = (
            "The agent should clearly indicate helping right now."
            if intent_spec.will_help_now
            else "The agent should clearly indicate not helping right now."
        )
        intent_cue_lines = "".join(self._intent_cue_prompt_lines(intent_spec))
        return (
            f"Language: {self.language}\n"
            f"text_profile: {text_profile}\n"
            f"profile_instruction: {profile_instruction}\n"
            f"decision: {intent_spec.decision}\n"
            f"response_intent: {intent_spec.response_intent}\n"
            f"will_help_now: {json.dumps(intent_spec.will_help_now)}\n"
            f"intent_description: {intent_spec.prompt_description_en}\n"
            f"rule: {response_rule}\n\n"
            "Realization input:\n"
            f"{json.dumps(realization_input.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            "Requirements:\n"
            "- belief must be first-person and grounded in the realization input.\n"
            "- belief should mention relationship context and current state naturally.\n"
            "- thinking must be 1-3 short sentences.\n"
            "- thinking should give a visible reason and action conclusion.\n"
            "- thinking should reflect the given response_intent, not just the binary branch bit.\n"
            "- reason_tags are hints, not a checklist.\n"
            "- Do not invent names, genders, exact tasks, or scene details.\n"
            f"{intent_cue_lines}"
            f"- defer-like phrasing should sound delayed, for example: {', '.join(DEFER_CUES_EN)}.\n"
            f"- help-now phrasing should sound immediate, for example: {', '.join(IMMEDIATE_HELP_CUES_EN)}.\n"
            "- Do not output raw field names or long hidden reasoning.\n"
            "- Return JSON only.\n"
        )
