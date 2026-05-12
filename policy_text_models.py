"""Models and helpers for language-specific policy text records."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

from entity_catalog import (
    CounterpartyMention,
    counterparty_mention_for,
    make_counterparty_entity_id,
    make_counterparty_identity,
)
from policy_text_contracts import (
    LanguageCode,
    PolicyDecisionName,
    RelationKind,
    ResponseIntent,
)


TEXT_SCHEMA_VERSION = "1.4"


@dataclass(frozen=True)
class IntentSpec:
    decision: PolicyDecisionName
    response_intent: ResponseIntent
    will_help_now: bool
    prompt_description_zh: str
    prompt_description_en: str
    must_have_any_zh: tuple[str, ...] = ()
    must_not_have_any_zh: tuple[str, ...] = ()
    must_have_any_en: tuple[str, ...] = ()
    must_not_have_any_en: tuple[str, ...] = ()


IMMEDIATE_HELP_CUES_ZH: tuple[str, ...] = (
    "现在接下",
    "马上处理",
    "立刻处理",
    "现在处理",
    "我先接下",
    "我来处理",
    "这就处理",
    "直接接下",
)

DEFER_CUES_ZH: tuple[str, ...] = (
    "晚点",
    "之后",
    "回头",
    "等我",
    "等晚上",
    "稍后",
    "改天",
    "有空了再",
)

IMMEDIATE_HELP_CUES_EN: tuple[str, ...] = (
    "take this on now",
    "handle this now",
    "work on this now",
    "deal with this now",
    "pick this up now",
    "start on this now",
    "do this now",
    "step in now",
)

DEFER_CUES_EN: tuple[str, ...] = (
    "later",
    "after this",
    "once i'm free",
    "when i have time",
    "later today",
    "tonight",
    "tomorrow",
    "get back to it later",
)

INTENT_SPECS: dict[PolicyDecisionName, IntentSpec] = {
    "engage_now": IntentSpec(
        decision="engage_now",
        response_intent="help_now",
        will_help_now=True,
        prompt_description_zh="现在就接手并开始帮忙。",
        prompt_description_en="Take it on and help right away.",
        must_have_any_zh=IMMEDIATE_HELP_CUES_ZH,
        must_have_any_en=IMMEDIATE_HELP_CUES_EN,
    ),
    "engage_briefly": IntentSpec(
        decision="engage_briefly",
        response_intent="brief_non_help",
        will_help_now=False,
        prompt_description_zh="现在只做简短回应，不真正接下帮忙动作。",
        prompt_description_en="Give a brief reply now without actually taking on the helping action.",
        must_have_any_zh=("先回", "简单回", "先回应", "先答一句", "先说一声"),
        must_not_have_any_zh=IMMEDIATE_HELP_CUES_ZH,
        must_have_any_en=("quick reply", "brief reply", "respond briefly", "just reply", "answer briefly"),
        must_not_have_any_en=IMMEDIATE_HELP_CUES_EN,
    ),
    "defer": IntentSpec(
        decision="defer",
        response_intent="defer",
        will_help_now=False,
        prompt_description_zh="明确推迟到之后处理，让“稍后/晚点”可见。",
        prompt_description_en="Clearly defer it until later, making the delay explicit.",
        must_have_any_zh=DEFER_CUES_ZH,
        must_not_have_any_zh=IMMEDIATE_HELP_CUES_ZH,
        must_have_any_en=DEFER_CUES_EN,
        must_not_have_any_en=IMMEDIATE_HELP_CUES_EN,
    ),
    "decline": IntentSpec(
        decision="decline",
        response_intent="decline",
        will_help_now=False,
        prompt_description_zh="明确拒绝，不要写成稍后再帮。",
        prompt_description_en="Clearly decline, and do not frame it as helping later.",
        must_have_any_zh=("不帮", "不接", "拒绝", "不方便接", "没法接", "不想接"),
        must_not_have_any_zh=DEFER_CUES_ZH + IMMEDIATE_HELP_CUES_ZH,
        must_have_any_en=("can't help", "won't take this", "have to decline", "can't take this on", "need to say no"),
        must_not_have_any_en=DEFER_CUES_EN + IMMEDIATE_HELP_CUES_EN,
    ),
    "minimal_acknowledgment": IntentSpec(
        decision="minimal_acknowledgment",
        response_intent="acknowledge_only",
        will_help_now=False,
        prompt_description_zh="只简短确认收到，不承诺后续帮忙时间。",
        prompt_description_en="Only acknowledge receipt briefly without promising later help.",
        must_have_any_zh=("收到", "知道了", "先回应", "简单回应", "应一声", "表示收到"),
        must_not_have_any_zh=DEFER_CUES_ZH + IMMEDIATE_HELP_CUES_ZH,
        must_have_any_en=("got it", "noted", "i saw this", "message received", "acknowledged"),
        must_not_have_any_en=DEFER_CUES_EN + IMMEDIATE_HELP_CUES_EN,
    ),
    "set_boundary": IntentSpec(
        decision="set_boundary",
        response_intent="set_boundary",
        will_help_now=False,
        prompt_description_zh="明确表达边界、限制或不适合继续接这个请求。",
        prompt_description_en="State a clear boundary, limit, or unsuitability for taking this request.",
        must_have_any_zh=("边界", "不方便", "我只能", "不适合", "不想再", "先说清"),
        must_not_have_any_zh=IMMEDIATE_HELP_CUES_ZH,
        must_have_any_en=("boundary", "not available for this", "i can only", "not a fit for me", "doesn't work for me"),
        must_not_have_any_en=IMMEDIATE_HELP_CUES_EN,
    ),
    "redirect_channel_or_time": IntentSpec(
        decision="redirect_channel_or_time",
        response_intent="redirect",
        will_help_now=False,
        prompt_description_zh="把对方引导到另一个时间点或沟通渠道。",
        prompt_description_en="Redirect the person to another time or communication channel.",
        must_have_any_zh=("换个时间", "之后再聊", "发到", "邮件", "群里", "明天再", "回头再"),
        must_not_have_any_zh=IMMEDIATE_HELP_CUES_ZH,
        must_have_any_en=("another time", "email channel", "group channel", "move this to email", "tomorrow"),
        must_not_have_any_en=IMMEDIATE_HELP_CUES_EN,
    ),
}


def make_policy_text_record_id(
    source_policy_record_id: str,
) -> str:
    return f"policy_text__{source_policy_record_id}__r01"


def intent_spec_from_decision(decision: PolicyDecisionName) -> IntentSpec:
    try:
        return INTENT_SPECS[decision]
    except KeyError as exc:
        raise ValueError(f"Unsupported policy decision for text realization: {decision!r}") from exc


class PolicyTextRealization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    belief: str
    thinking: str


class PolicyTextRelationInput(BaseModel):
    label: str = ""
    closeness: str = ""
    trust: str = ""
    obligation: str = ""
    tension: str = ""
    reciprocity: str = ""
    power: str = ""


class PolicyTextStateInput(BaseModel):
    energy: str = ""
    time_pressure: str = ""
    clarity: str = ""
    emotional_activation: str = ""
    social_readiness: str = ""
    confidence: str = ""


class PolicyTextRequestContextInput(BaseModel):
    is_doable_now: bool = True


class PolicyTextDecisionInput(BaseModel):
    will_help_now: bool
    response_intent: ResponseIntent
    policy_decision: PolicyDecisionName
    policy_strategy: str


class PolicyTextRealizationInput(BaseModel):
    counterparty_mention: CounterpartyMention
    relation: PolicyTextRelationInput = Field(default_factory=PolicyTextRelationInput)
    state: PolicyTextStateInput = Field(default_factory=PolicyTextStateInput)
    request_context: PolicyTextRequestContextInput = Field(default_factory=PolicyTextRequestContextInput)
    decision: PolicyTextDecisionInput
    reason_tags: list[str] = Field(default_factory=list)


def _require_explicit_contract_fields(
    raw: object,
    *,
    required: set[str],
) -> object:
    if not isinstance(raw, dict):
        return raw
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"missing required policy_text fields: {', '.join(missing)}")
    return raw


class PolicyTextRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TEXT_SCHEMA_VERSION
    record_id: str
    language: LanguageCode
    source_policy_record_id: str
    relation_kind: RelationKind
    policy_decision: PolicyDecisionName
    belief: str
    thinking: str

    @model_validator(mode="before")
    @classmethod
    def _require_explicit_contract_fields(cls, raw: object) -> object:
        return _require_explicit_contract_fields(
            raw,
            required={
                "schema_version",
                "record_id",
                "language",
                "source_policy_record_id",
                "relation_kind",
                "policy_decision",
                "belief",
                "thinking",
            },
        )

    @property
    def intent_spec(self) -> IntentSpec:
        return intent_spec_from_decision(self.policy_decision)

    @property
    def will_help_now(self) -> bool:
        return self.intent_spec.will_help_now

    @property
    def response_intent(self) -> ResponseIntent:
        return self.intent_spec.response_intent

    @property
    def counterparty_entity_id(self) -> str:
        return make_counterparty_entity_id(self.source_policy_record_id)

    @property
    def counterparty_mention(self) -> CounterpartyMention:
        return counterparty_mention_for(
            make_counterparty_identity(self.source_policy_record_id),
            self.relation_kind,
        )

    @property
    def counterparty_canonical_name(self) -> str:
        return self.counterparty_mention.canonical_name

    @property
    def counterparty_first_mention_name(self) -> str:
        return self.counterparty_mention.first_mention_name


def validate_policy_text_record(
    raw: dict | PolicyTextRecord,
    *,
    expected_item_key: str | None = None,
) -> PolicyTextRecord:
    record = raw if isinstance(raw, PolicyTextRecord) else PolicyTextRecord.model_validate(raw)
    if record.schema_version != TEXT_SCHEMA_VERSION:
        raise ValueError(
            f"policy_text schema_version {record.schema_version!r} does not match expected {TEXT_SCHEMA_VERSION!r}"
        )
    if expected_item_key is not None and record.record_id != expected_item_key:
        raise ValueError(
            f"policy_text record_id {record.record_id!r} does not match item key {expected_item_key!r}"
        )
    expected_record_id = make_policy_text_record_id(record.source_policy_record_id)
    if record.record_id != expected_record_id:
        raise ValueError(
            f"policy_text record_id {record.record_id!r} does not match expected {expected_record_id!r}"
        )
    if not record.source_policy_record_id:
        raise ValueError("policy_text source_policy_record_id is empty")
    if not record.belief.strip():
        raise ValueError("policy_text belief is empty")
    if not record.thinking.strip():
        raise ValueError("policy_text thinking is empty")
    return record
