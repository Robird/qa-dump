"""Shared entity identity and mention helpers for derived data."""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from policy_text_contracts import RELATION_KIND_VALUES, RelationKind


COUNTERPARTY_ENTITY_TYPE = "person"
NAME_SLOT_MODULUS = 10_000
NAME_KEY_PREFIX = "name_slot_"

NEUTRAL_COUNTERPARTY_SURNAMES: tuple[str, ...] = (
    "周",
    "林",
    "陈",
    "许",
    "沈",
    "顾",
    "唐",
    "陆",
    "宋",
    "韩",
    "叶",
    "赵",
    "钱",
    "孙",
    "李",
    "吴",
    "郑",
    "王",
    "冯",
    "蒋",
    "程",
    "薛",
    "魏",
    "何",
    "马",
    "罗",
    "高",
    "梁",
    "董",
    "于",
    "余",
    "杜",
)

NEUTRAL_COUNTERPARTY_GIVEN_PREFIXES: tuple[str, ...] = (
    "安",
    "知",
    "清",
    "景",
    "初",
    "闻",
    "序",
    "怀",
    "向",
    "若",
    "以",
    "可",
    "言",
    "亦",
    "书",
    "映",
    "思",
    "临",
    "照",
    "承",
)

NEUTRAL_COUNTERPARTY_GIVEN_SUFFIXES: tuple[str, ...] = (
    "宁",
    "和",
    "远",
    "白",
    "舟",
    "川",
    "南",
    "北",
    "遥",
    "衡",
    "微",
    "乔",
    "念",
    "允",
    "朗",
    "平",
)

_NAME_KEY_RE = re.compile(r"^name_slot_(\d{4})$")
_ID_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_]+")


class CounterpartyIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    entity_type: str
    name_key: str

    @field_validator("entity_id", "entity_type", "name_key")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("counterparty identity fields must be non-empty")
        return value

    @field_validator("name_key")
    @classmethod
    def _validate_name_key(cls, value: str) -> str:
        if _NAME_KEY_RE.fullmatch(value) is None:
            raise ValueError(f"counterparty name_key must look like {NAME_KEY_PREFIX}0000")
        return value


class CounterpartyMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    canonical_name: str
    first_mention_name: str

    @field_validator("entity_id", "canonical_name", "first_mention_name")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("counterparty mention fields must be non-empty")
        return value

    @model_validator(mode="after")
    def _validate_first_mention_shape(self) -> "CounterpartyMention":
        if not self.first_mention_name.startswith(f"{self.canonical_name}["):
            raise ValueError("first_mention_name must start with canonical_name followed by '['")
        if not self.first_mention_name.endswith("]"):
            raise ValueError("first_mention_name must end with ']'")
        return self


def _require_text(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _stable_int(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _stable_id_component(value: str) -> str:
    cleaned = _ID_COMPONENT_RE.sub("_", value.strip()).strip("_")
    if cleaned:
        return cleaned
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def make_counterparty_entity_id(record_id: str) -> str:
    record_id = _require_text(record_id, "record_id")
    return f"{COUNTERPARTY_ENTITY_TYPE}__{record_id}__primary"


def make_counterparty_name_key(record_id: str) -> str:
    record_id = _require_text(record_id, "record_id")
    slot = _stable_int(record_id) % NAME_SLOT_MODULUS
    return f"{NAME_KEY_PREFIX}{slot:04d}"


def make_counterparty_identity(record_id: str) -> CounterpartyIdentity:
    return CounterpartyIdentity(
        entity_id=make_counterparty_entity_id(record_id),
        entity_type=COUNTERPARTY_ENTITY_TYPE,
        name_key=make_counterparty_name_key(record_id),
    )


def canonical_name_for_name_key(name_key: str) -> str:
    name_key = _require_text(name_key, "name_key")
    match = _NAME_KEY_RE.fullmatch(name_key)
    if match is None:
        raise ValueError(f"counterparty name_key must look like {NAME_KEY_PREFIX}0000")
    slot = int(match.group(1))
    given_space = len(NEUTRAL_COUNTERPARTY_GIVEN_PREFIXES) * len(NEUTRAL_COUNTERPARTY_GIVEN_SUFFIXES)
    full_space = len(NEUTRAL_COUNTERPARTY_SURNAMES) * given_space
    slot = slot % full_space
    surname_index, given_index = divmod(slot, given_space)
    prefix_index, suffix_index = divmod(given_index, len(NEUTRAL_COUNTERPARTY_GIVEN_SUFFIXES))
    return (
        f"{NEUTRAL_COUNTERPARTY_SURNAMES[surname_index]}"
        f"{NEUTRAL_COUNTERPARTY_GIVEN_PREFIXES[prefix_index]}"
        f"{NEUTRAL_COUNTERPARTY_GIVEN_SUFFIXES[suffix_index]}"
    )


def first_mention_name_for(relation_kind: RelationKind | str, canonical_name: str) -> str:
    relation_kind_value = _require_text(str(relation_kind), "relation_kind")
    if relation_kind_value not in RELATION_KIND_VALUES:
        raise ValueError(f"unsupported relation_kind for counterparty mention: {relation_kind_value!r}")
    canonical_name = _require_text(canonical_name, "canonical_name")
    return f"{canonical_name}[{relation_kind_value}]"


def counterparty_mention_for(
    identity: CounterpartyIdentity,
    relation_kind: RelationKind | str,
) -> CounterpartyMention:
    canonical_name = canonical_name_for_name_key(identity.name_key)
    return CounterpartyMention(
        entity_id=identity.entity_id,
        canonical_name=canonical_name,
        first_mention_name=first_mention_name_for(relation_kind, canonical_name),
    )


def make_sample_counterparty_entity_id(sample_id: str, source_entity_id: str) -> str:
    sample_id = _require_text(sample_id, "sample_id")
    source_entity_id = _require_text(source_entity_id, "source_entity_id")
    source_digest = hashlib.sha256(f"{sample_id}\x1f{source_entity_id}".encode("utf-8")).hexdigest()[:12]
    return f"{COUNTERPARTY_ENTITY_TYPE}__sample__{_stable_id_component(sample_id)}__{source_digest}__primary"


def validate_counterparty_identity(
    raw: dict | CounterpartyIdentity,
    *,
    expected_record_id: str | None = None,
) -> CounterpartyIdentity:
    identity = CounterpartyIdentity.model_validate(
        raw.model_dump() if isinstance(raw, CounterpartyIdentity) else raw
    )
    if expected_record_id is not None:
        expected = make_counterparty_identity(expected_record_id)
        if identity != expected:
            raise ValueError(
                "counterparty identity does not match deterministic record-local identity "
                f"for {expected_record_id!r}"
            )
    return identity
