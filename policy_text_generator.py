"""LLM-backed realization of structured policy records into text."""

from __future__ import annotations

import json
import logging
import re

from api import LLMClient, LLMResponseError
from entity_catalog import CounterpartyMention
from policy_text_issues import PolicyTextIssue, retry_feedback_needs_name_repetition, summarize_issue_messages
from policy_text_models import (
    DEFER_CUES_EN,
    DEFER_CUES_ZH,
    IMMEDIATE_HELP_CUES_EN,
    IMMEDIATE_HELP_CUES_ZH,
    IntentSpec,
    PolicyTextRealization,
    PolicyTextRealizationInput,
)
from policy_text_preparation import PreparedPolicyTextTask

logger = logging.getLogger(__name__)

GENERIC_COUNTERPARTY_TERMS_ZH: tuple[str, ...] = (
    "对方",
    "这个人",
    "那个人",
)

GENERIC_COUNTERPARTY_TERMS_EN: tuple[str, ...] = (
    "the other person",
    "this person",
    "that person",
)

ZH_COUNTERPARTY_PRONOUN_RE = re.compile(r"(?:他们|她们|(?<![其吉])他|她)")
ZH_COUNTERPARTY_ROMANIZED_PRONOUN_RE = re.compile(r"(?<![A-Za-z])ta(?![A-Za-z])", flags=re.IGNORECASE)
EN_COUNTERPARTY_PRONOUN_RE = re.compile(
    r"\b(?:you|your|he|she|him|his|her|hers|himself|herself|they|them|their|theirs|themself|themselves)\b"
)

ZH_BELIEF_DECISION_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"我(?:现在)?决定"),
    re.compile(r"还是先"),
    re.compile(r"我(?:得|要|需要|必须)先"),
    re.compile(r"我(?:得|要|需要|必须)(?:跟|和).{0,12}(?:说清|讲清|说明|明确)"),
    re.compile(r"先(?:跟|和).{0,12}(?:说清|讲清|说明|明确)"),
    re.compile(r"(?:我来处理|这就处理|现在接下|马上处理|立刻处理)"),
    re.compile(r"(?:不接这个请求|现在不接|先不接)"),
    re.compile(r"(?:晚点|之后|回头|稍后|改天|等我).{0,8}(?:处理|再说|再聊|再帮|再回)"),
    re.compile(r"(?:收到|知道了|先回应|先答一句|先说一声)"),
)

EN_BELIEF_DECISION_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bi (?:decide|decided|am deciding)\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:first )?i(?:'ll| will)\b", flags=re.IGNORECASE),
    re.compile(r"\blet me\b", flags=re.IGNORECASE),
    re.compile(r"\bi (?:need|have) to (?:reply|respond|tell|say no|set|handle|take)\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:got it|noted|message received)\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:later|tomorrow|tonight|after this)\b.{0,16}\b(?:handle|reply|help|deal with|get back to)\b", flags=re.IGNORECASE),
)


class PolicyTextGenerationError(LLMResponseError):
    pass


class PolicyTextRuleValidationError(PolicyTextGenerationError):
    def __init__(self, issues: list[PolicyTextIssue]):
        self.issues = tuple(issues)
        super().__init__("Policy text realization failed rule validation: " + summarize_issue_messages(self.issues))


class PolicyTextGenerator:
    def __init__(
        self,
        llm: LLMClient,
        *,
        language: str,
        temperature: float = 0.8,
        max_tokens: int | None = None,
    ):
        self.llm = llm
        self.language = language
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(
        self,
        task: PreparedPolicyTextTask,
        *,
        retry_feedback: tuple[PolicyTextIssue, ...] = (),
    ) -> PolicyTextRealization:
        messages = [
            {
                "role": "system",
                "content": self._system_prompt(),
            },
            {
                "role": "user",
                "content": self._user_prompt(
                    task.realization_input,
                    intent_spec=task.intent_spec,
                    retry_feedback=retry_feedback,
                ),
            },
        ]
        logger.debug(
            "PolicyTextGenerator request for %s: %s",
            task.source_policy.record_id,
            _preview_text(messages[1]["content"], limit=1000),
        )
        # Keep generator and judge on the same structured-output protocol.
        # We intentionally leave max_tokens unset for this synthetic-data path:
        # on DeepSeek, quality and complete tool submission matter more than
        # token thrift, and hard caps can truncate the tool call entirely.
        raw = self.llm.chat_structured_result(
            messages,
            output_model=PolicyTextRealization,
            tool_name="submit_policy_text_realization",
            tool_description="Submit the realized belief and thinking text for one policy_text record.",
            tool_choice=None,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        realization = raw.payload
        logger.debug(
            "PolicyTextGenerator raw realization for %s: belief=%r thinking=%r",
            task.source_policy.record_id,
            realization.belief,
            realization.thinking,
        )
        issues = self.validate(
            realization,
            intent_spec=task.intent_spec,
            counterparty_mention=task.counterparty_mention,
        )
        if issues:
            logger.debug(
                "PolicyTextGenerator rule validation issues for %s: %s",
                task.source_policy.record_id,
                issues,
            )
            raise PolicyTextRuleValidationError(issues)
        return realization

    def validate(
        self,
        realization: PolicyTextRealization,
        *,
        intent_spec: IntentSpec,
        counterparty_mention: CounterpartyMention,
    ) -> list[PolicyTextIssue]:
        issues: list[PolicyTextIssue] = []
        belief = realization.belief.strip()
        thinking = realization.thinking.strip()
        if not belief:
            issues.append(
                self._issue(
                    "belief_empty",
                    "belief is empty",
                    "Rewrite belief as a non-empty first-person context sentence.",
                    field="belief",
                )
            )
        if not thinking:
            issues.append(
                self._issue(
                    "thinking_empty",
                    "thinking is empty",
                    "Rewrite thinking as a non-empty internal monologue with a visible conclusion.",
                    field="thinking",
                )
            )
        for field_name, text in (("belief", belief), ("thinking", thinking)):
            if text and not self._contains_counterparty_name(text, counterparty_mention):
                issues.append(
                    self._issue(
                        "missing_counterparty_name",
                        f"{field_name} missing counterparty mention/name",
                        "Use the provided counterparty name or mention explicitly, and repeat it instead of using a pronoun.",
                        field=field_name,
                    )
                )
        if len(belief) > 220:
            issues.append(
                self._issue(
                    "belief_too_long",
                    "belief too long",
                    "Shorten belief while keeping only the most relevant first-person context.",
                    field="belief",
                )
            )
        if len(thinking) > 120:
            issues.append(
                self._issue(
                    "thinking_too_long",
                    "thinking too long",
                    "Shorten thinking to 1-3 short sentences with a visible reason and conclusion.",
                    field="thinking",
                )
            )
        combined = f"{belief}\n{thinking}"
        lowered = combined.lower()
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
            "counterparty_mention",
            "counterparty_entity_id",
            "counterparty_canonical_name",
            "counterparty_first_mention_name",
            "canonical_name",
            "first_mention_name",
        ):
            if forbidden in lowered:
                issues.append(
                    self._issue(
                        "schema_jargon",
                        f"contains schema jargon: {forbidden}",
                        "Remove raw schema field names and rewrite the text in natural language.",
                        details={"term": forbidden},
                    )
                )
        if self.language == "zh" and belief and "我" not in belief:
            issues.append(
                self._issue(
                    "belief_not_first_person",
                    "belief should be first-person in zh",
                    "Rewrite belief in first person using 我.",
                    field="belief",
                )
            )
        if self.language == "en" and belief and not re.search(r"\b(i|i'm|i’ve|i'd|i'll|me|my)\b", belief.lower()):
            issues.append(
                self._issue(
                    "belief_not_first_person",
                    "belief should be first-person in en",
                    "Rewrite belief in first person using I/me/my.",
                    field="belief",
                )
            )
        if belief and self._belief_decision_leak_hits(belief):
            issues.append(
                self._issue(
                    "belief_decision_leak",
                    "belief contains action/decision content that belongs in thinking",
                    "Keep belief as pre-decision background only; move any decision, next-step, or response conclusion wording into thinking.",
                    field="belief",
                )
            )
        if self.language == "zh" and any(address in combined for address in ("你", "您")):
            issues.append(
                self._issue(
                    "counterparty_direct_address",
                    "zh output should not address the counterparty with 你/您",
                    "Do not address the counterparty directly; refer to the person by the provided name instead.",
                )
            )
        if self.language == "zh" and ZH_COUNTERPARTY_PRONOUN_RE.search(combined):
            issues.append(
                self._issue(
                    "counterparty_pronoun",
                    "zh output should not use gendered third-person pronouns for the counterparty",
                    "Replace all counterparty pronouns with the provided name or mention.",
                )
            )
        if self.language == "zh" and ZH_COUNTERPARTY_ROMANIZED_PRONOUN_RE.search(combined):
            issues.append(
                self._issue(
                    "counterparty_pronoun",
                    "zh output should not use ta/TA as a pronoun for the counterparty",
                    "Replace ta/TA with the provided counterparty name or mention.",
                )
            )
        if self.language == "zh" and any(term in combined for term in GENERIC_COUNTERPARTY_TERMS_ZH):
            issues.append(
                self._issue(
                    "counterparty_generic_placeholder",
                    "zh output should use the provided counterparty name instead of generic placeholders",
                    "Replace generic placeholders like 对方 with the provided counterparty name.",
                )
            )
        if self.language == "en" and re.search(r"\b(?:you|your)\b", combined.lower()):
            issues.append(
                self._issue(
                    "counterparty_direct_address",
                    "en output should not address the counterparty with standalone you/your",
                    "Do not address the counterparty as you/your; use the provided name instead.",
                )
            )
        if self.language == "en" and EN_COUNTERPARTY_PRONOUN_RE.search(combined.lower()):
            issues.append(
                self._issue(
                    "counterparty_pronoun",
                    "en output should not use pronouns for the counterparty; repeat the provided name instead",
                    "Replace counterparty pronouns with the provided name or mention.",
                )
            )
        if self.language == "en" and self._contains_any(combined, GENERIC_COUNTERPARTY_TERMS_EN):
            issues.append(
                self._issue(
                    "counterparty_generic_placeholder",
                    "en output should use the provided counterparty name instead of generic placeholders",
                    "Replace generic labels like 'the other person' with the provided counterparty name.",
                )
            )
        immediate_help_cues = self._immediate_help_cues()
        must_have_cues, must_not_have_cues = self._intent_cues(intent_spec)
        if not intent_spec.will_help_now and self._contains_affirmative_any(thinking, immediate_help_cues):
            issues.append(
                self._issue(
                    "intent_immediate_help_mismatch",
                    "thinking implies immediate help while will_help_now=false",
                    "Rewrite thinking so it does not imply taking the request on right now.",
                    field="thinking",
                )
            )
        if intent_spec.will_help_now and not self._contains_affirmative_any(thinking, immediate_help_cues):
            issues.append(
                self._issue(
                    "intent_immediate_help_mismatch",
                    "help_now intent missing immediate-help cue",
                    "Make thinking explicitly indicate taking the request on now.",
                    field="thinking",
                )
            )
        if must_have_cues and not self._contains_any(thinking, must_have_cues):
            issues.append(
                self._issue(
                    "intent_missing_cue",
                    f"{intent_spec.response_intent} intent missing cue",
                    f"Use wording that clearly reads as {intent_spec.response_intent}.",
                    field="thinking",
                    details={"response_intent": intent_spec.response_intent},
                )
            )
        if must_not_have_cues and self._contains_forbidden_cues(thinking, must_not_have_cues, immediate_help_cues):
            issues.append(
                self._issue(
                    "intent_conflicting_cue",
                    f"{intent_spec.response_intent} intent contains conflicting cue",
                    f"Remove wording that makes the text sound like a different intent than {intent_spec.response_intent}.",
                    field="thinking",
                    details={"response_intent": intent_spec.response_intent},
                )
            )
        return issues

    @staticmethod
    def _issue(
        code: str,
        message: str,
        repair_instruction: str,
        *,
        field: str | None = None,
        details: dict[str, str | bool] | None = None,
    ) -> PolicyTextIssue:
        return PolicyTextIssue(
            code=code,
            origin="rule_validator",
            field=field,
            message=message,
            repair_instruction=repair_instruction,
            details=details or {},
        )

    @staticmethod
    def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
        lowered = text.lower()
        return any(cue.lower() in lowered for cue in cues)

    def _contains_affirmative_any(self, text: str, cues: tuple[str, ...]) -> bool:
        return any(self._contains_affirmative_phrase(text, cue) for cue in cues)

    def _contains_forbidden_cues(
        self,
        text: str,
        cues: tuple[str, ...],
        immediate_help_cues: tuple[str, ...],
    ) -> bool:
        immediate_set = {cue.lower() for cue in immediate_help_cues}
        for cue in cues:
            if cue.lower() in immediate_set:
                if self._contains_affirmative_phrase(text, cue):
                    return True
                continue
            if cue.lower() in text.lower():
                return True
        return False

    def _contains_affirmative_phrase(self, text: str, phrase: str) -> bool:
        lowered = text.lower()
        phrase_lower = phrase.lower()
        start = 0
        while True:
            index = lowered.find(phrase_lower, start)
            if index < 0:
                return False
            if not self._is_negated_near_phrase(lowered, index):
                return True
            start = index + len(phrase_lower)

    def _is_negated_near_phrase(self, lowered: str, index: int) -> bool:
        if self.language == "zh":
            window = lowered[max(0, index - 8):index]
            return any(token in window for token in ("不", "没", "別", "别", "勿"))
        window = lowered[max(0, index - 24):index]
        return any(token in window for token in (" not ", "don't ", "dont ", "can't ", "cannot ", "won't ", "never "))

    @staticmethod
    def _contains_counterparty_name(text: str, counterparty_mention: CounterpartyMention) -> bool:
        return (
            counterparty_mention.first_mention_name in text
            or counterparty_mention.canonical_name in text
        )

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
                    "- thinking 应自然包含下面任一表达："
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
                "- thinking should naturally include at least one of these phrasing cues: "
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

    def _belief_decision_leak_hits(self, text: str) -> tuple[str, ...]:
        patterns = ZH_BELIEF_DECISION_LEAK_PATTERNS if self.language == "zh" else EN_BELIEF_DECISION_LEAK_PATTERNS
        return tuple(pattern.pattern for pattern in patterns if pattern.search(text))

    def _system_prompt(self) -> str:
        if self.language == "zh":
            return (
                "你要把结构化的社交决策记录，改写成自然、简短、可读的中文文本。"
                "最终结构化结果必须通过提供的函数工具提交。"
                "把它理解成两个时间切片：belief 是做出回应结论之前就已经成立的第一人称背景快照；"
                "thinking 才是此刻形成的内部独白、简短理由和行动结论，不是发给对方的消息。"
                "不要在 belief 里提前写我决定什么、我先做什么、我之后怎么处理。"
                "除提供的 counterparty mention 外，不要输出长链路推理、字段名或额外模板标签。"
            )
        return (
            "Rewrite a structured social decision record into short natural text."
            " Submit the final structured result through the provided function tool."
            " Treat the two fields as two time slices: belief is the first-person pre-decision context snapshot,"
            " while thinking is the in-the-moment internal monologue with a short reason plus action conclusion,"
            " not a direct message to the counterparty."
            " Do not put what I decide or what I will do next into belief."
            " Except for the provided counterparty mention, do not expose schema labels or long chain-of-thought."
        )

    def _user_prompt(
        self,
        realization_input: PolicyTextRealizationInput,
        *,
        intent_spec: IntentSpec,
        retry_feedback: tuple[PolicyTextIssue, ...],
    ) -> str:
        retry_block = self._retry_feedback_block(retry_feedback)
        if self.language == "zh":
            thinking_target = (
                "thinking 的结论必须明确表示：现在不接下处理。"
                if not intent_spec.will_help_now
                else "thinking 的结论必须明确表示：现在接下并处理。"
            )
            intent_cue_lines = "".join(self._intent_cue_prompt_lines(intent_spec))
            return (
                f"Language: {self.language}\n"
                f"decision: {intent_spec.decision}\n"
                f"thinking_response_intent: {intent_spec.response_intent}\n"
                f"thinking_will_help_now: {json.dumps(intent_spec.will_help_now)}\n"
                f"thinking_intent_description: {intent_spec.prompt_description_zh}\n"
                f"thinking_target: {thinking_target}\n\n"
                "Realization input:\n"
                f"{json.dumps(realization_input.model_dump(), ensure_ascii=False, indent=2)}\n\n"
                "Requirements:\n"
                # This synthetic-data task intentionally keeps `belief` and
                # `thinking` semantically separated: belief teaches stable
                # background framing, while thinking teaches explicit
                # decision/output style.
                "- belief 必须是第一人称，基于 realization input 自然表达，不要像字段翻译。\n"
                "- belief 必须自然使用 counterparty_mention.first_mention_name 或 counterparty_mention.canonical_name。\n"
                "- belief 应自然提到关系背景和我当前状态，不必覆盖每个字段。\n"
                "- belief 只写做出回应结论之前就已经成立的背景与主观状态，像“我为什么会走到这个判断前”的静态快照。\n"
                "- belief 可以写“我现在精力低、时间紧、不适合马上处理”这类背景，但不要写“所以我决定…… / 还是先…… / 我先…… / 我之后再……”这类行动结论。\n"
                "- 所有“我接下来怎么做”“我最后怎么定”的内容，只能放进 thinking。\n"
                "- thinking 必须是 1-3 句短句，给出可见理由和行动结论。\n"
                "- thinking 必须自然使用 counterparty_mention.first_mention_name 或 counterparty_mention.canonical_name。\n"
                "- thinking 是内部独白，不要写成发给 counterparty 的直接消息。\n"
                "- thinking 才承担 response_intent、will_help_now 和结论落点，不要把这些分支信号扩散进 belief。\n"
                "- counterparty 必须用提供的姓名或 mention 指代；宁可重复姓名，也不要改用代词或泛称。\n"
                "- 如果再次提到 counterparty，继续重复姓名，例如“叶怀和……叶怀和……”；不要把后续提及改成“他/她/ta”。\n"
                f"- 这是硬性校验项：只要再次提到 counterparty，就继续写 {realization_input.counterparty_mention.canonical_name} 或 {realization_input.counterparty_mention.first_mention_name}，绝对不要写成他、她、他们、她们、ta、TA。\n"
                "- 不要用 对方、这个人、那个人 这类泛称替代名字。\n"
                "- 不要用 他、她、他们、她们、ta、TA 这类代词指代 counterparty。\n"
                "- thinking 必须符合 thinking_response_intent，不要只满足二分类分支。\n"
                "- reason_tags 只是可参考线索，不是逐条复述清单。\n"
                "- 不要编造名字、性别、具体任务细节或场景细节。\n"
                f"{intent_cue_lines}"
                f"- defer 类表达应包含这类推迟感：{', '.join(DEFER_CUES_ZH)}。\n"
                f"- help_now 类表达应包含明确立即帮忙感：{', '.join(IMMEDIATE_HELP_CUES_ZH)}。\n"
                "- 除提供的 counterparty mention 外，不要输出原始字段名，不要写成长链路推理。\n"
                f"{retry_block}"
                "- 只通过提供的函数工具提交最终结构化结果，不要在正文里重复结构化字段。\n"
            )

        response_rule = (
            "thinking should clearly indicate taking this on now."
            if intent_spec.will_help_now
            else "thinking should clearly indicate not taking this on right now."
        )
        intent_cue_lines = "".join(self._intent_cue_prompt_lines(intent_spec))
        return (
            f"Language: {self.language}\n"
            f"decision: {intent_spec.decision}\n"
            f"thinking_response_intent: {intent_spec.response_intent}\n"
            f"thinking_will_help_now: {json.dumps(intent_spec.will_help_now)}\n"
            f"thinking_intent_description: {intent_spec.prompt_description_en}\n"
            f"thinking_target: {response_rule}\n\n"
            "Realization input:\n"
            f"{json.dumps(realization_input.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            "Requirements:\n"
            "- belief must be first-person and grounded in the realization input.\n"
            "- belief must naturally use counterparty_mention.first_mention_name or counterparty_mention.canonical_name.\n"
            "- belief should mention relationship context and current state naturally.\n"
            "- belief should stay in the pre-decision frame: only background facts and subjective state that are already true before the conclusion lands.\n"
            "- belief may say things like low energy, time pressure, or not being in a good state to handle this now, but it must not say what I decide, what I will do next, or when I will reply.\n"
            "- Any next-step, branch outcome, or response conclusion belongs only in thinking.\n"
            "- thinking must be 1-3 short sentences.\n"
            "- thinking should give a visible reason and action conclusion.\n"
            "- thinking must naturally use counterparty_mention.first_mention_name or counterparty_mention.canonical_name.\n"
            "- thinking is internal monologue, not a direct message to the counterparty.\n"
            "- thinking is the only field that should verbalize thinking_response_intent, thinking_will_help_now, and the final action direction.\n"
            "- Use the provided name or mention for the counterparty; repetition is better than pronouns or generic labels.\n"
            "- If you mention the counterparty again later, repeat the same provided name again instead of switching to a pronoun.\n"
            f"- Hard validation rule: every later counterparty mention must repeat exactly {realization_input.counterparty_mention.canonical_name} or {realization_input.counterparty_mention.first_mention_name}, never a pronoun.\n"
            "- Do not refer to the counterparty as the other person, this person, or that person.\n"
            "- Do not address the counterparty as you or your.\n"
            "- Do not use he, she, him, his, her, they, them, their, or similar pronouns for the counterparty.\n"
            "- thinking should reflect the given thinking_response_intent, not just the binary branch bit.\n"
            "- reason_tags are hints, not a checklist.\n"
            "- Do not invent names, genders, exact tasks, or scene details.\n"
            f"{intent_cue_lines}"
            f"- defer-like phrasing should sound delayed, for example: {', '.join(DEFER_CUES_EN)}.\n"
            f"- help-now phrasing should sound immediate, for example: {', '.join(IMMEDIATE_HELP_CUES_EN)}.\n"
            "- Do not output raw field names or long hidden reasoning.\n"
            f"{retry_block}"
            "- Submit the final structured result only through the provided function tool.\n"
        )

    def _retry_feedback_block(self, retry_feedback: tuple[PolicyTextIssue, ...]) -> str:
        if not retry_feedback:
            return ""
        if self.language == "zh":
            lines = ["- 上一次输出存在以下问题，这次必须逐条修正：\n"]
        else:
            lines = ["- The previous attempt failed these checks; fix every item below in this retry:\n"]
        lines.extend(f"  - {issue.repair_instruction}\n" for issue in retry_feedback)
        if retry_feedback_needs_name_repetition(retry_feedback):
            if self.language == "zh":
                lines.append("  - 这是硬性要求：后续提及 counterparty 时，必须继续重复提供的姓名，不要写成他、她、他们、她们、ta、TA。\n")
            else:
                lines.append("  - Hard requirement: every later mention of the counterparty must repeat the provided name, never a pronoun.\n")
        return "".join(lines)


def _preview_text(text: str, *, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
