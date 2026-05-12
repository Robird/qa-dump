#!/usr/bin/env python3
"""Task main for help-gate ACML runs."""

import argparse

from derived_common import configure_logging
from help_gate_tasks import add_help_gate_acml_arguments, run_help_gate_acml


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run help-gate ACML generation.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_help_gate_acml_arguments(parser)
    args = parser.parse_args()
    configure_logging(args.verbose)
    run_help_gate_acml(args)


if __name__ == "__main__":
    main()
