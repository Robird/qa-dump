"""Models and helpers for language-specific policy text records."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

from entity_catalog import (
    CounterpartyMention,
    counterparty_mention_for,
    first_mention_name_for,
    make_counterparty_entity_id,
)
from policy_models import PolicyRecord
from policy_text_contracts import (
    LanguageCode,
    PolicyDecisionName,
    RelationKind,
    ResponseIntent,
)
from relation_catalog import canonical_relation_kind


TEXT_SCHEMA_VERSION = "1.2"


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
    contract_name: str,
) -> object:
    if not isinstance(raw, dict):
        return raw
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"missing required {contract_name} contract fields: {', '.join(missing)}")
    return raw


class PolicyTextRecordBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TEXT_SCHEMA_VERSION
    record_id: str
    language: LanguageCode
    source_policy_record_id: str
    relation_kind: RelationKind
    counterparty_entity_id: str
    counterparty_canonical_name: str
    counterparty_first_mention_name: str
    will_help_now: bool
    policy_decision: PolicyDecisionName
    response_intent: ResponseIntent
    belief: str
    thinking: str


class PolicyTextArtifactRecord(PolicyTextRecordBase):
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
                "counterparty_entity_id",
                "counterparty_canonical_name",
                "counterparty_first_mention_name",
                "will_help_now",
                "policy_decision",
                "response_intent",
                "text_profile",
                "belief",
                "thinking",
                "source_policy",
            },
            contract_name="artifact",
        )

    text_profile: str
    source_policy: PolicyRecord


class PolicyTextExportRecord(PolicyTextRecordBase):
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
                "counterparty_entity_id",
                "counterparty_canonical_name",
                "counterparty_first_mention_name",
                "will_help_now",
                "policy_decision",
                "response_intent",
                "belief",
                "thinking",
            },
            contract_name="export",
        )


def validate_policy_text_artifact(
    raw: dict | PolicyTextArtifactRecord,
    *,
    expected_item_key: str | None = None,
) -> PolicyTextArtifactRecord:
    artifact = raw if isinstance(raw, PolicyTextArtifactRecord) else PolicyTextArtifactRecord.model_validate(raw)
    _validate_policy_text_record_base(artifact, contract_name="artifact")
    if expected_item_key is not None and artifact.record_id != expected_item_key:
        raise ValueError(
            f"artifact record_id {artifact.record_id!r} does not match item key {expected_item_key!r}"
        )

    expected_record_id = make_policy_text_record_id(
        artifact.source_policy_record_id,
    )
    if artifact.record_id != expected_record_id:
        raise ValueError(
            f"artifact record_id {artifact.record_id!r} does not match expected {expected_record_id!r}"
        )

    if artifact.source_policy.record_id != artifact.source_policy_record_id:
        raise ValueError(
            "artifact source_policy_record_id does not match embedded source_policy.record_id"
        )

    if artifact.policy_decision != artifact.source_policy.policy.decision:
        raise ValueError("artifact policy_decision does not match embedded source_policy.policy.decision")

    intent_spec = intent_spec_from_decision(artifact.source_policy.policy.decision)
    if artifact.will_help_now != intent_spec.will_help_now:
        raise ValueError("artifact will_help_now does not match policy_decision mapping")
    if artifact.response_intent != intent_spec.response_intent:
        raise ValueError("artifact response_intent does not match policy_decision mapping")

    expected_relation_kind = canonical_relation_kind(artifact.source_policy.relation.relation_label)
    if artifact.relation_kind != expected_relation_kind:
        raise ValueError("artifact relation_kind does not match embedded source_policy relation label")

    expected_mention = counterparty_mention_for(artifact.source_policy.counterparty, expected_relation_kind)
    actual_counterparty_fields = {
        "entity_id": artifact.counterparty_entity_id,
        "canonical_name": artifact.counterparty_canonical_name,
        "first_mention_name": artifact.counterparty_first_mention_name,
    }
    if actual_counterparty_fields != expected_mention.model_dump():
        raise ValueError("artifact counterparty fields do not match embedded source_policy counterparty mention")

    if not artifact.belief.strip():
        raise ValueError("artifact belief is empty")
    if not artifact.thinking.strip():
        raise ValueError("artifact thinking is empty")
    return artifact


def validate_policy_text_export(
    raw: dict | PolicyTextExportRecord,
) -> PolicyTextExportRecord:
    record = raw if isinstance(raw, PolicyTextExportRecord) else PolicyTextExportRecord.model_validate(raw)
    _validate_policy_text_record_base(record, contract_name="export")
    return record


def project_policy_text_export(artifact: PolicyTextArtifactRecord) -> PolicyTextExportRecord:
    validated_artifact = validate_policy_text_artifact(artifact)
    return validate_policy_text_export(
        validated_artifact.model_dump(
            include={
                "schema_version",
                "record_id",
                "language",
                "source_policy_record_id",
                "relation_kind",
                "counterparty_entity_id",
                "counterparty_canonical_name",
                "counterparty_first_mention_name",
                "will_help_now",
                "policy_decision",
                "response_intent",
                "belief",
                "thinking",
            }
        )
    )


def _validate_policy_text_record_base(
    record: PolicyTextRecordBase,
    *,
    contract_name: str,
) -> None:
    if record.schema_version != TEXT_SCHEMA_VERSION:
        raise ValueError(
            f"{contract_name} schema_version {record.schema_version!r} does not match expected {TEXT_SCHEMA_VERSION!r}"
        )
    if not record.record_id:
        raise ValueError(f"{contract_name} record_id is empty")
    if not record.source_policy_record_id:
        raise ValueError(f"{contract_name} source_policy_record_id is empty")
    for field_name in (
        "counterparty_entity_id",
        "counterparty_canonical_name",
        "counterparty_first_mention_name",
    ):
        if not getattr(record, field_name).strip():
            raise ValueError(f"{contract_name} {field_name} is empty")
    expected_entity_id = make_counterparty_entity_id(record.source_policy_record_id)
    if record.counterparty_entity_id != expected_entity_id:
        raise ValueError(
            f"{contract_name} counterparty_entity_id does not match deterministic source policy entity id"
        )
    expected_first_mention = first_mention_name_for(
        record.relation_kind,
        record.counterparty_canonical_name,
    )
    if record.counterparty_first_mention_name != expected_first_mention:
        raise ValueError(
            f"{contract_name} counterparty_first_mention_name does not match controlled mention template"
        )
    if not record.belief.strip():
        raise ValueError(f"{contract_name} belief is empty")
    if not record.thinking.strip():
        raise ValueError(f"{contract_name} thinking is empty")
