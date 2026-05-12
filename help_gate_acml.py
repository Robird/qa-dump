"""Helpers for composing QA payloads and policy-text records into ACML samples."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from acml import parse_document, serialize_document
from acml.model import Attribute, Document, PayloadNode, TextNode
from acml.semantic_model import (
    SemanticDocument,
    SemanticEntry,
    SemanticPayload,
    SemanticText,
    semantic_document_to_document,
)

from payload_adapter import PayloadRecord
from policy_text_contracts import LanguageCode
from policy_text_models import PolicyTextExportRecord
from relation_catalog import observation_wrapper_for


HELP_GATE_ACML_TASK = "help_gate_acml_v1"
HELP_GATE_ACML_COMPOSITION_VERSION = "1.0"


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
    observation_wrapper: str
    me_text: str


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


def compose_me_text(payload: PayloadRecord, policy_text: PolicyTextExportRecord) -> str:
    thinking = policy_text.thinking.strip()
    if not _response_intent_includes_qa_answer(policy_text.response_intent):
        return thinking
    answer = payload.fulfillment_content.strip()
    if not answer:
        return thinking
    if not thinking:
        return answer
    return f"{thinking}\n{answer}"


def build_acml_composition(
    *,
    sample_id: str,
    language: LanguageCode,
    payload: PayloadRecord,
    policy_text: PolicyTextExportRecord,
) -> HelpGateACMLComposition:
    return HelpGateACMLComposition(
        sample_id=sample_id,
        language=language,
        payload=payload,
        policy_text=policy_text,
        observation_wrapper=observation_wrapper_for(language, policy_text.relation_kind),
        me_text=compose_me_text(payload, policy_text),
    )


def build_acml_document(
    *,
    composition: HelpGateACMLComposition,
) -> SemanticDocument:
    policy_text = composition.policy_text
    return SemanticDocument(
        version="0",
        attrs=(
            Attribute("task", HELP_GATE_ACML_TASK),
            Attribute("language", composition.language),
            Attribute("sample_id", composition.sample_id),
        ),
        entries=(
            SemanticEntry(
                kind="observation",
                attrs=(
                    Attribute("source", "qa"),
                    Attribute("relation", composition.policy_text.relation_kind),
                ),
                content=(
                    SemanticText(composition.observation_wrapper),
                    SemanticPayload(composition.payload.request_text),
                ),
            ),
            SemanticEntry(
                kind="belief",
                attrs=(Attribute("source", "policy_text"),),
                content=(SemanticText(policy_text.belief.strip()),),
            ),
            SemanticEntry(
                kind="me",
                attrs=(
                    Attribute("source", "policy_text+qa"),
                    Attribute("will_help_now", "true" if policy_text.will_help_now else "false"),
                    Attribute("response_intent", policy_text.response_intent),
                    Attribute("policy_decision", policy_text.policy_decision),
                ),
                content=(SemanticText(composition.me_text),),
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
    if len(observation.content) != 2:
        issues.append(f"observation should contain wrapper text plus one payload, got {len(observation.content)} nodes")
    else:
        wrapper_node, payload_node = observation.content
        if not isinstance(wrapper_node, TextNode):
            issues.append("observation wrapper is not a text node")
        else:
            if wrapper_node.text != composition.observation_wrapper:
                issues.append("observation wrapper text does not match configured relation projection")
        if not isinstance(payload_node, PayloadNode):
            issues.append("observation payload is not a payload node")
        elif payload_node.text != composition.payload.request_text:
            issues.append("observation payload text does not round-trip to original question")
    belief = document.entries[1]
    belief_attrs = {attr.name: attr.value for attr in belief.attrs}
    if belief_attrs.get("source") != "policy_text":
        issues.append(f"unexpected belief source attr: {belief_attrs.get('source')!r}")
    belief_text = _entry_text_content(belief.content, entry_kind="belief", issues=issues)
    if not belief_text.strip():
        issues.append("belief entry is empty")
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
    me_text = _entry_text_content(me.content, entry_kind="me", issues=issues)
    if not me_text.strip():
        issues.append("me entry is empty")
    answer = composition.payload.fulfillment_content.strip()
    if not composition.policy_text.will_help_now and answer and answer in me_text:
        issues.append("non-help sample leaks QA answer in me entry")
    if composition.policy_text.will_help_now and answer:
        probe = answer[: min(len(answer), 12)].strip()
        if probe and probe not in me_text:
            issues.append("help-now sample does not appear to include QA answer content")
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
    if not composition.me_text.strip():
        issues.append("composition me_text is empty")
    if composition.observation_wrapper != observation_wrapper_for(
        composition.language,
        composition.policy_text.relation_kind,
    ):
        issues.append("composition observation wrapper does not match relation projection")
    answer = composition.payload.fulfillment_content.strip()
    include_qa_answer = _response_intent_includes_qa_answer(composition.policy_text.response_intent)
    if include_qa_answer and answer and answer not in composition.me_text:
        issues.append("composition me_text is missing QA answer content")
    if not include_qa_answer and answer and answer in composition.me_text:
        issues.append("composition me_text leaks QA answer content")
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


def _response_intent_includes_qa_answer(response_intent: str) -> bool:
    return response_intent == "help_now"
