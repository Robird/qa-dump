"""Shared relation catalog for policy semantics and help-gate projection."""

from __future__ import annotations

from dataclasses import dataclass

from policy_text_contracts import LANGUAGE_VALUES, RELATION_KIND_VALUES, LanguageCode, RelationKind


@dataclass(frozen=True)
class RelationSpec:
    accepted_labels: tuple[str, ...]
    policy_label: str | None
    relation_direction: str | None
    typical_closeness: str | None
    observation_wrappers: dict[LanguageCode, str]


RELATION_SPECS: dict[RelationKind, RelationSpec] = {
    "mentor": RelationSpec(
        accepted_labels=("导师",),
        policy_label="导师",
        relation_direction="target_is_my_relation",
        typical_closeness="medium",
        observation_wrappers={
            "zh": "这位导师对我说：",
            "en": "A mentor says to me: ",
        },
    ),
    "student": RelationSpec(
        accepted_labels=("学生",),
        policy_label="学生",
        relation_direction="i_am_targets_relation",
        typical_closeness="medium",
        observation_wrappers={
            "zh": "这位学生对我说：",
            "en": "A student says to me: ",
        },
    ),
    "coworker": RelationSpec(
        accepted_labels=("同事",),
        policy_label="同事",
        relation_direction="equal",
        typical_closeness="medium",
        observation_wrappers={
            "zh": "这位同事对我说：",
            "en": "A coworker says to me: ",
        },
    ),
    "boss": RelationSpec(
        accepted_labels=("上司",),
        policy_label="上司",
        relation_direction="target_is_my_relation",
        typical_closeness="low",
        observation_wrappers={
            "zh": "这位上司对我说：",
            "en": "A boss says to me: ",
        },
    ),
    "subordinate": RelationSpec(
        accepted_labels=("下属",),
        policy_label="下属",
        relation_direction="i_am_targets_relation",
        typical_closeness="low",
        observation_wrappers={
            "zh": "这位下属对我说：",
            "en": "A subordinate says to me: ",
        },
    ),
    "family": RelationSpec(
        accepted_labels=("家人",),
        policy_label="家人",
        relation_direction="target_is_my_relation",
        typical_closeness="high",
        observation_wrappers={
            "zh": "家里人对我说：",
            "en": "A family member says to me: ",
        },
    ),
    "friend": RelationSpec(
        accepted_labels=("朋友", "老朋友"),
        policy_label="老朋友",
        relation_direction="equal",
        typical_closeness="high",
        observation_wrappers={
            "zh": "这位朋友对我说：",
            "en": "A friend says to me: ",
        },
    ),
    "stranger": RelationSpec(
        accepted_labels=("陌生人",),
        policy_label="陌生人",
        relation_direction="target_is_my_relation",
        typical_closeness="low",
        observation_wrappers={
            "zh": "一个陌生人问我：",
            "en": "A stranger asks me: ",
        },
    ),
    "client": RelationSpec(
        accepted_labels=("客户",),
        policy_label="客户",
        relation_direction="target_is_my_relation",
        typical_closeness="low",
        observation_wrappers={
            "zh": "这位客户对我说：",
            "en": "A client says to me: ",
        },
    ),
    "partner": RelationSpec(
        accepted_labels=("合作伙伴",),
        policy_label="合作伙伴",
        relation_direction="equal",
        typical_closeness="medium",
        observation_wrappers={
            "zh": "这位合作伙伴问我：",
            "en": "A partner asks me: ",
        },
    ),
    "neighbor": RelationSpec(
        accepted_labels=("邻居",),
        policy_label="邻居",
        relation_direction="equal",
        typical_closeness="low",
        observation_wrappers={
            "zh": "这位邻居对我说：",
            "en": "A neighbor says to me: ",
        },
    ),
    "classmate": RelationSpec(
        accepted_labels=("同学",),
        policy_label="同学",
        relation_direction="equal",
        typical_closeness="medium",
        observation_wrappers={
            "zh": "这位同学对我说：",
            "en": "A classmate says to me: ",
        },
    ),
    "teacher": RelationSpec(
        accepted_labels=("老师",),
        policy_label="老师",
        relation_direction="target_is_my_relation",
        typical_closeness="medium",
        observation_wrappers={
            "zh": "这位老师对我说：",
            "en": "A teacher says to me: ",
        },
    ),
    "junior": RelationSpec(
        accepted_labels=("晚辈",),
        policy_label="晚辈",
        relation_direction="i_am_targets_relation",
        typical_closeness="medium",
        observation_wrappers={
            "zh": "这位晚辈对我说：",
            "en": "A junior says to me: ",
        },
    ),
    "elder": RelationSpec(
        accepted_labels=("长辈",),
        policy_label="长辈",
        relation_direction="target_is_my_relation",
        typical_closeness="high",
        observation_wrappers={
            "zh": "这位长辈对我说：",
            "en": "An elder says to me: ",
        },
    ),
    "other": RelationSpec(
        accepted_labels=(),
        policy_label=None,
        relation_direction=None,
        typical_closeness=None,
        observation_wrappers={
            "zh": "对方对我说：",
            "en": "Someone says to me: ",
        },
    ),
}


if set(RELATION_SPECS) != set(RELATION_KIND_VALUES):
    raise RuntimeError("relation_catalog does not cover every canonical relation kind")


RELATION_KIND_BY_LABEL: dict[str, RelationKind] = {}
POLICY_RELATION_PROFILES: list[dict[str, str]] = []
OBSERVATION_WRAPPERS: dict[LanguageCode, dict[RelationKind, str]] = {
    language: {}
    for language in LANGUAGE_VALUES
}

for relation_kind, spec in RELATION_SPECS.items():
    if set(spec.observation_wrappers) != set(LANGUAGE_VALUES):
        raise RuntimeError(f"relation_catalog wrappers are incomplete for {relation_kind!r}")
    for language, wrapper in spec.observation_wrappers.items():
        OBSERVATION_WRAPPERS[language][relation_kind] = wrapper
    if spec.policy_label is not None:
        if not spec.relation_direction or not spec.typical_closeness:
            raise RuntimeError(
                f"relation_catalog policy-backed relation is missing policy metadata: {relation_kind!r}"
            )
        POLICY_RELATION_PROFILES.append(
            {
                "label": spec.policy_label,
                "direction": spec.relation_direction,
                "typical_closeness": spec.typical_closeness,
            }
        )
    for label in spec.accepted_labels:
        existing = RELATION_KIND_BY_LABEL.get(label)
        if existing is not None and existing != relation_kind:
            raise RuntimeError(f"relation label {label!r} maps to multiple kinds: {existing!r}, {relation_kind!r}")
        RELATION_KIND_BY_LABEL[label] = relation_kind


def canonical_relation_kind(label: str) -> RelationKind:
    normalized = label.strip() if label else ""
    try:
        return RELATION_KIND_BY_LABEL[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported policy relation label: {label!r}") from exc


def observation_wrapper_for(language: LanguageCode, relation_kind: RelationKind) -> str:
    return OBSERVATION_WRAPPERS[language][relation_kind]
