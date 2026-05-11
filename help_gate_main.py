#!/usr/bin/env python3
"""Task main for help-gate augmentation family commands."""

import argparse

from derived_common import (
    add_help_gate_preflight_arguments,
    configure_logging,
    run_help_gate_preflight,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run help-gate augmentation task-family commands.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser(
        "preflight",
        help="Inspect QA and policy runs and write a composition preflight report.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_help_gate_preflight_arguments(preflight)
    preflight.set_defaults(func=run_help_gate_preflight)

    args = parser.parse_args()
    configure_logging(getattr(args, "verbose", False))
    args.func(args)


if __name__ == "__main__":
    main()
