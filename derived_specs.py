"""Derived-task specifications for first-class run contracts."""

from __future__ import annotations

from derived_lifecycle import DerivedTaskSpec
from task_contracts import HELP_GATE_TASK_FAMILY, POLICY_TASK_FAMILY

POLICY_RECORDS_SPEC = DerivedTaskSpec(
    task_name="policy_records",
    task_family=POLICY_TASK_FAMILY,
    outputs={
        "artifacts": {
            "items": {"path": "artifacts/items"},
        },
        "views": {
            "export": {"path": "views/export.jsonl"},
        },
    },
)

HELP_GATE_PREFLIGHT_SPEC = DerivedTaskSpec(
    task_name="help_gate_preflight",
    task_family=HELP_GATE_TASK_FAMILY,
    outputs={
        "artifacts": {
            "preflight": {"path": "artifacts/preflight/composition_preflight.json"},
        },
    },
)
