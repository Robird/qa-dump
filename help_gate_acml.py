"""Helpers for composing QA payloads and policy-text records into ACML samples."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from acml import parse_document, serialize_document
from acml.model import ActionNode, Attribute, Document, PayloadNode, TextNode
from acml.semantic_model import (
    SemanticAction,
    SemanticDocument,
    SemanticEntry,
    SemanticPayload,
    SemanticText,
    semantic_document_to_document,
)

from entity_catalog import make_sample_counterparty_entity_id
from payload_adapter import PayloadRecord
from policy_text_contracts import LanguageCode
from policy_text_models import PolicyTextExportRecord
from relation_catalog import named_observation_wrapper_for


HELP_GATE_ACML_TASK = "help_gate_acml_v1"
HELP_GATE_ACML_COMPOSITION_VERSION = "1.5"
REPLY_TOOL_DIALECT = "csharp-v0"
REPLY_TOOL_NAME_POOL: tuple[str, ...] = (
    "SendMessage",
    "SendMsg",
    "send_message",
    "Speek",
    "speek",
)

BELIEF_RUNTIME_AFFORDANCE_PRELUDE_POOL: dict[LanguageCode, tuple[tuple[str, str], ...]] = {
    "zh": (
        ("action_proto_v1", "我当前可调用的外部动作原型："),
        ("action_proto_v2", "我现在可用的对外动作原型如下："),
        ("action_proto_v3", "当前可用的外部动作原型如下："),
        ("action_proto_v4", "我这边目前能使用的对外动作接口有："),
    ),
    "en": (
        ("action_proto_v1", "Available outward action prototype:"),
        ("action_proto_v2", "Current outward interaction prototype:"),
        ("action_proto_v3", "The runtime currently exposes this outward action:"),
        ("action_proto_v4", "I can currently use the following outward action interface:"),
    ),
}


@dataclass(frozen=True)
class RenderedHelpGateACML:
    semantic_document: SemanticDocument
    parsed_document: Document
    text: str


@dataclass(frozen=True)
class HelpGateACMLComposition:
    sample_id: str
    language: LanguageCode
    payload: PayloadRecord
    policy_text: PolicyTextExportRecord
    source_counterparty_entity_id: str
    sample_counterparty_entity_id: str
    counterparty_canonical_name: str
    counterparty_first_mention_name: str
    reply_tool_name: str
    belief_runtime_affordance_variant_id: str
    belief_text: str
    observation_wrapper: str
    me_reasoning_text: str
    reply_action_text: str


def make_sample_id(
    *,
    qa_run_id: str,
    qa_view_id: str,
    qa_record_id: str,
    policy_text_run_id: str,
    policy_text_record_id: str,
    language: LanguageCode,
) -> str:
    raw = "\x1f".join(
        (
            qa_run_id,
            qa_view_id,
            qa_record_id,
            policy_text_run_id,
            policy_text_record_id,
            language,
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"acml__{digest}"


def compose_me_reasoning_text(policy_text: PolicyTextExportRecord) -> str:
    return policy_text.thinking.strip()


def _select_deterministic_pool_item(sample_id: str, *, salt: str, pool: tuple[str, ...]) -> str:
    raw = f"{sample_id}\x1f{salt}"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return pool[int.from_bytes(digest[:4], "big") % len(pool)]


def select_reply_tool_name(sample_id: str) -> str:
    return _select_deterministic_pool_item(
        sample_id,
        salt="reply_tool_name",
        pool=REPLY_TOOL_NAME_POOL,
    )


def select_belief_runtime_affordance_variant_id(
    sample_id: str,
    *,
    language: LanguageCode,
) -> str:
    variants = belief_runtime_affordance_variants_for(language)
    variant_ids = tuple(variant_id for variant_id, _ in variants)
    return _select_deterministic_pool_item(
        sample_id,
        salt=f"belief_runtime_affordance:{language}",
        pool=variant_ids,
    )


def belief_runtime_affordance_variants_for(
    language: LanguageCode,
) -> tuple[tuple[str, str], ...]:
    try:
        return BELIEF_RUNTIME_AFFORDANCE_PRELUDE_POOL[language]
    except KeyError as exc:
        raise ValueError(
            f"unsupported language for belief runtime affordance prelude: {language!r}"
        ) from exc


def compose_belief_text(
    language: LanguageCode,
    policy_text: PolicyTextExportRecord,
    *,
    reply_tool_name: str,
    belief_runtime_affordance_variant_id: str,
) -> str:
    belief = policy_text.belief.strip()
    prototype = reply_tool_prototype_text(
        language,
        reply_tool_name=reply_tool_name,
        belief_runtime_affordance_variant_id=belief_runtime_affordance_variant_id,
    )
    if not belief:
        return prototype
    return f"{prototype}\n\n{belief}"


def compose_reply_action_text(payload: PayloadRecord, policy_text: PolicyTextExportRecord) -> str:
    if not _response_intent_uses_reply_action(policy_text.response_intent):
        return ""
    return payload.fulfillment_content.strip()


def reply_tool_prototype_text(
    language: LanguageCode,
    *,
    reply_tool_name: str,
    belief_runtime_affordance_variant_id: str,
) -> str:
    intro = belief_runtime_affordance_prelude_text(
        language,
        belief_runtime_affordance_variant_id=belief_runtime_affordance_variant_id,
    )
    return f"{intro}\nvoid {reply_tool_name}(string target_entity_id, string message);"


def belief_runtime_affordance_prelude_text(
    language: LanguageCode,
    *,
    belief_runtime_affordance_variant_id: str,
) -> str:
    variants = belief_runtime_affordance_variants_for(language)
    for variant_id, intro_text in variants:
        if variant_id == belief_runtime_affordance_variant_id:
            return intro_text
    raise ValueError(
        "unknown belief runtime affordance variant "
        f"{belief_runtime_affordance_variant_id!r} for language {language!r}"
    )


def reply_action_prefix(reply_tool_name: str, target_entity_id: str) -> str:
    return f'{reply_tool_name}(target_entity_id: "{target_entity_id}", message: '


def reply_action_suffix() -> str:
    return ")"


def build_acml_composition(
    *,
    sample_id: str,
    language: LanguageCode,
    payload: PayloadRecord,
    policy_text: PolicyTextExportRecord,
) -> HelpGateACMLComposition:
    source_counterparty_entity_id = policy_text.counterparty_entity_id
    sample_counterparty_entity_id = make_sample_counterparty_entity_id(
        sample_id,
        source_counterparty_entity_id,
    )
    reply_tool_name = select_reply_tool_name(sample_id)
    belief_runtime_affordance_variant_id = select_belief_runtime_affordance_variant_id(
        sample_id,
        language=language,
    )
    counterparty_first_mention_name = policy_text.counterparty_first_mention_name
    return HelpGateACMLComposition(
        sample_id=sample_id,
        language=language,
        payload=payload,
        policy_text=policy_text,
        source_counterparty_entity_id=source_counterparty_entity_id,
        sample_counterparty_entity_id=sample_counterparty_entity_id,
        counterparty_canonical_name=policy_text.counterparty_canonical_name,
        counterparty_first_mention_name=counterparty_first_mention_name,
        reply_tool_name=reply_tool_name,
        belief_runtime_affordance_variant_id=belief_runtime_affordance_variant_id,
        belief_text=compose_belief_text(
            language,
            policy_text,
            reply_tool_name=reply_tool_name,
            belief_runtime_affordance_variant_id=belief_runtime_affordance_variant_id,
        ),
        observation_wrapper=named_observation_wrapper_for(
            language,
            policy_text.relation_kind,
            counterparty_first_mention_name,
        ),
        me_reasoning_text=compose_me_reasoning_text(policy_text),
        reply_action_text=compose_reply_action_text(payload, policy_text),
    )


def build_acml_document(
    *,
    composition: HelpGateACMLComposition,
) -> SemanticDocument:
    policy_text = composition.policy_text
    me_content: list[SemanticText | SemanticAction] = []
    if composition.me_reasoning_text:
        reasoning_text = composition.me_reasoning_text
        if composition.reply_action_text:
            reasoning_text = f"{reasoning_text}\n"
        me_content.append(SemanticText(reasoning_text))
    if composition.reply_action_text:
        me_content.append(
            SemanticAction(
                content=(
                    SemanticText(
                        reply_action_prefix(
                            composition.reply_tool_name,
                            composition.sample_counterparty_entity_id,
                        )
                    ),
                    SemanticPayload(composition.reply_action_text),
                    SemanticText(reply_action_suffix()),
                ),
                attrs=(
                    Attribute("tool", composition.reply_tool_name),
                    Attribute("dialect", REPLY_TOOL_DIALECT),
                    Attribute("target_entity_id", composition.sample_counterparty_entity_id),
                ),
            )
        )
    return SemanticDocument(
        version="0",
        attrs=(
            Attribute("task", HELP_GATE_ACML_TASK),
            Attribute("composition_version", HELP_GATE_ACML_COMPOSITION_VERSION),
            Attribute("language", composition.language),
            Attribute("sample_id", composition.sample_id),
        ),
        entries=(
            SemanticEntry(
                kind="observation",
                attrs=(
                    Attribute("source", "qa"),
                    Attribute("relation", composition.policy_text.relation_kind),
                    Attribute("entity_id", composition.sample_counterparty_entity_id),
                    Attribute("source_entity_id", composition.source_counterparty_entity_id),
                    Attribute("entity_name", composition.counterparty_canonical_name),
                    Attribute("entity_mention", composition.counterparty_first_mention_name),
                ),
                content=(
                    SemanticText(composition.observation_wrapper),
                    SemanticPayload(composition.payload.request_text),
                ),
            ),
            SemanticEntry(
                kind="belief",
                attrs=(Attribute("source", "policy_text+runtime"),),
                content=(SemanticText(composition.belief_text),),
            ),
            SemanticEntry(
                kind="me",
                attrs=(
                    Attribute("source", "policy_text+qa"),
                    Attribute("will_help_now", "true" if policy_text.will_help_now else "false"),
                    Attribute("response_intent", policy_text.response_intent),
                    Attribute("policy_decision", policy_text.policy_decision),
                ),
                content=tuple(me_content),
            ),
        ),
    )


def render_acml_document(document: SemanticDocument) -> RenderedHelpGateACML:
    syntax_document = semantic_document_to_document(document)
    text = serialize_document(syntax_document)
    parsed_document = parse_document(text)
    return RenderedHelpGateACML(
        semantic_document=document,
        parsed_document=parsed_document,
        text=text,
    )


def validate_acml_sample(
    *,
    composition: HelpGateACMLComposition,
    document: Document,
) -> list[str]:
    issues: list[str] = []
    issues.extend(_validate_composition(composition))
    if document.version != "0":
        issues.append(f"unexpected document version: {document.version!r}")
    root_attrs = {attr.name: attr.value for attr in document.attrs}
    if root_attrs.get("task") != HELP_GATE_ACML_TASK:
        issues.append(f"unexpected root task attr: {root_attrs.get('task')!r}")
    if root_attrs.get("composition_version") != HELP_GATE_ACML_COMPOSITION_VERSION:
        issues.append(
            "unexpected root composition_version attr: "
            f"{root_attrs.get('composition_version')!r}"
        )
    if root_attrs.get("language") != composition.language:
        issues.append(f"unexpected root language attr: {root_attrs.get('language')!r}")
    if root_attrs.get("sample_id") != composition.sample_id:
        issues.append(f"unexpected root sample_id attr: {root_attrs.get('sample_id')!r}")
    if len(document.entries) != 3:
        issues.append(f"expected 3 entries, got {len(document.entries)}")
        return issues
    entry_kinds = [entry.kind for entry in document.entries]
    if entry_kinds != ["observation", "belief", "me"]:
        issues.append(f"unexpected entry order: {entry_kinds}")
    observation = document.entries[0]
    observation_attrs = {attr.name: attr.value for attr in observation.attrs}
    if observation_attrs.get("source") != "qa":
        issues.append(f"unexpected observation source attr: {observation_attrs.get('source')!r}")
    if observation_attrs.get("relation") != composition.policy_text.relation_kind:
        issues.append(f"unexpected observation relation attr: {observation_attrs.get('relation')!r}")
    expected_observation_attrs = {
        "entity_id": composition.sample_counterparty_entity_id,
        "source_entity_id": composition.source_counterparty_entity_id,
        "entity_name": composition.counterparty_canonical_name,
        "entity_mention": composition.counterparty_first_mention_name,
    }
    for attr_name, expected_value in expected_observation_attrs.items():
        if observation_attrs.get(attr_name) != expected_value:
            issues.append(
                f"unexpected observation {attr_name} attr: "
                f"{observation_attrs.get(attr_name)!r}"
            )
    if len(observation.content) != 2:
        issues.append(f"observation should contain wrapper text plus one payload, got {len(observation.content)} nodes")
    else:
        wrapper_node, payload_node = observation.content
        if not isinstance(wrapper_node, TextNode):
            issues.append("observation wrapper is not a text node")
        else:
            if wrapper_node.text != composition.observation_wrapper:
                issues.append("observation wrapper text does not match counterparty first mention projection")
        if not isinstance(payload_node, PayloadNode):
            issues.append("observation payload is not a payload node")
        elif payload_node.text != composition.payload.request_text:
            issues.append("observation payload text does not round-trip to original question")
    belief = document.entries[1]
    belief_attrs = {attr.name: attr.value for attr in belief.attrs}
    if belief_attrs.get("source") != "policy_text+runtime":
        issues.append(f"unexpected belief source attr: {belief_attrs.get('source')!r}")
    belief_text = _entry_text_content(belief.content, entry_kind="belief", issues=issues)
    if not belief_text.strip():
        issues.append("belief entry is empty")
    elif belief_text != composition.belief_text:
        issues.append("belief entry text does not match composed policy_text+runtime projection")
    me = document.entries[2]
    me_attrs = {attr.name: attr.value for attr in me.attrs}
    expected_will_help = "true" if composition.policy_text.will_help_now else "false"
    if me_attrs.get("source") != "policy_text+qa":
        issues.append(f"unexpected me source attr: {me_attrs.get('source')!r}")
    if me_attrs.get("will_help_now") != expected_will_help:
        issues.append(f"unexpected me will_help_now attr: {me_attrs.get('will_help_now')!r}")
    if me_attrs.get("response_intent") != composition.policy_text.response_intent:
        issues.append(f"unexpected me response_intent attr: {me_attrs.get('response_intent')!r}")
    if me_attrs.get("policy_decision") != composition.policy_text.policy_decision:
        issues.append(f"unexpected me policy_decision attr: {me_attrs.get('policy_decision')!r}")
    me_text, me_actions = _entry_me_content(me.content, issues=issues)
    if not me_text.strip() and not me_actions:
        issues.append("me entry is empty")
    expected_reply_action = composition.reply_action_text
    if not expected_reply_action:
        if me_actions:
            issues.append("non-help sample should not contain reply action")
    else:
        if len(me_actions) != 1:
            issues.append(f"help-now sample should contain exactly one reply action, got {len(me_actions)}")
        else:
            action_node = me_actions[0]
            action_attrs = {attr.name: attr.value for attr in action_node.attrs}
            if action_attrs.get("tool") != composition.reply_tool_name:
                issues.append(f"unexpected me action tool attr: {action_attrs.get('tool')!r}")
            if action_attrs.get("dialect") != REPLY_TOOL_DIALECT:
                issues.append(f"unexpected me action dialect attr: {action_attrs.get('dialect')!r}")
            if action_attrs.get("target_entity_id") != composition.sample_counterparty_entity_id:
                issues.append(
                    "unexpected me action target_entity_id attr: "
                    f"{action_attrs.get('target_entity_id')!r}"
                )
            action_text = _action_payload_text(
                action_node,
                issues=issues,
                entry_kind="me",
                expected_prefix=reply_action_prefix(
                    composition.reply_tool_name,
                    composition.sample_counterparty_entity_id,
                ),
                expected_suffix=reply_action_suffix(),
            )
            if action_text != expected_reply_action:
                issues.append("help-now reply action does not preserve QA answer content")
    return issues


def _validate_composition(composition: HelpGateACMLComposition) -> list[str]:
    issues: list[str] = []
    if not composition.sample_id:
        issues.append("composition missing sample_id")
    if not composition.language:
        issues.append("composition missing language")
    if not composition.payload.request_text.strip():
        issues.append("composition payload request_text is empty")
    if not composition.policy_text.belief.strip():
        issues.append("composition belief is empty")
    if not composition.me_reasoning_text.strip() and not composition.reply_action_text.strip():
        issues.append("composition me content is empty")
    if not composition.source_counterparty_entity_id.strip():
        issues.append("composition missing source_counterparty_entity_id")
    elif composition.source_counterparty_entity_id != composition.policy_text.counterparty_entity_id:
        issues.append("composition source_counterparty_entity_id does not match policy_text export")
    if not composition.sample_counterparty_entity_id.strip():
        issues.append("composition missing sample_counterparty_entity_id")
    elif composition.source_counterparty_entity_id.strip():
        expected_sample_entity_id = make_sample_counterparty_entity_id(
            composition.sample_id,
            composition.source_counterparty_entity_id,
        )
        if composition.sample_counterparty_entity_id != expected_sample_entity_id:
            issues.append("composition sample_counterparty_entity_id is not derived from sample/source entity ids")
    if not composition.counterparty_canonical_name.strip():
        issues.append("composition missing counterparty_canonical_name")
    elif composition.counterparty_canonical_name != composition.policy_text.counterparty_canonical_name:
        issues.append("composition counterparty_canonical_name does not match policy_text export")
    if not composition.counterparty_first_mention_name.strip():
        issues.append("composition missing counterparty_first_mention_name")
    elif composition.counterparty_first_mention_name != composition.policy_text.counterparty_first_mention_name:
        issues.append("composition counterparty_first_mention_name does not match policy_text export")
    expected_reply_tool_name = select_reply_tool_name(composition.sample_id)
    if composition.reply_tool_name != expected_reply_tool_name:
        issues.append("composition reply_tool_name is not derived deterministically from sample_id")
    expected_belief_runtime_affordance_variant_id = select_belief_runtime_affordance_variant_id(
        composition.sample_id,
        language=composition.language,
    )
    if (
        composition.belief_runtime_affordance_variant_id
        != expected_belief_runtime_affordance_variant_id
    ):
        issues.append(
            "composition belief_runtime_affordance_variant_id is not derived "
            "deterministically from sample_id"
        )
    try:
        expected_belief = compose_belief_text(
            composition.language,
            composition.policy_text,
            reply_tool_name=composition.reply_tool_name,
            belief_runtime_affordance_variant_id=composition.belief_runtime_affordance_variant_id,
        )
    except ValueError as exc:
        issues.append(str(exc))
    else:
        if composition.belief_text != expected_belief:
            issues.append("composition belief_text does not match policy_text+runtime projection")
    try:
        expected_wrapper = named_observation_wrapper_for(
            composition.language,
            composition.policy_text.relation_kind,
            composition.counterparty_first_mention_name,
        )
    except ValueError as exc:
        issues.append(str(exc))
    else:
        if composition.observation_wrapper != expected_wrapper:
            issues.append("composition observation wrapper does not match counterparty first mention projection")
    expected_reply_action = compose_reply_action_text(composition.payload, composition.policy_text)
    if composition.reply_action_text != expected_reply_action:
        issues.append("composition reply_action_text does not match response_intent projection")
    if composition.reply_action_text and composition.reply_action_text in composition.me_reasoning_text:
        issues.append("composition me_reasoning_text should not inline reply action content")
    return issues


def _entry_text_content(
    content: tuple[object, ...],
    *,
    entry_kind: str,
    issues: list[str],
) -> str:
    text_parts: list[str] = []
    for item in content:
        if not isinstance(item, TextNode):
            issues.append(f"{entry_kind} entry contains non-text node {type(item).__name__}")
            continue
        text_parts.append(item.text)
    return "".join(text_parts)


def _entry_me_content(
    content: tuple[object, ...],
    *,
    issues: list[str],
) -> tuple[str, list[ActionNode]]:
    text_parts: list[str] = []
    actions: list[ActionNode] = []
    for item in content:
        if isinstance(item, TextNode):
            text_parts.append(item.text)
            continue
        if isinstance(item, ActionNode):
            actions.append(item)
            continue
        issues.append(f"me entry contains unsupported node {type(item).__name__}")
    return "".join(text_parts), actions


def _action_payload_text(
    action: ActionNode,
    *,
    issues: list[str],
    entry_kind: str,
    expected_prefix: str,
    expected_suffix: str,
) -> str:
    text_parts: list[str] = []
    payload_parts: list[str] = []
    for item in action.content:
        if isinstance(item, TextNode):
            text_parts.append(item.text)
            continue
        if isinstance(item, PayloadNode):
            payload_parts.append(item.text)
            continue
        issues.append(f"{entry_kind} action contains unsupported node {type(item).__name__}")
    if len(text_parts) != 2:
        issues.append(f"{entry_kind} action should contain exactly two text nodes, got {len(text_parts)}")
    else:
        if text_parts[0] != expected_prefix:
            issues.append(f"{entry_kind} action prefix does not match reply-tool invocation")
        if text_parts[1] != expected_suffix:
            issues.append(f"{entry_kind} action suffix does not match reply-tool invocation")
    if len(payload_parts) != 1:
        issues.append(f"{entry_kind} action should contain exactly one payload node, got {len(payload_parts)}")
        return ""
    return payload_parts[0]


def _response_intent_uses_reply_action(response_intent: str) -> bool:
    return response_intent == "help_now"
