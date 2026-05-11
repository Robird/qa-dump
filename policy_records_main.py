#!/usr/bin/env python3
"""Task main for standalone policy-record generation."""

from derived_common import build_policy_records_parser, configure_logging, run_generate_policy_records


def main() -> None:
    parser = build_policy_records_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)
    run_generate_policy_records(args)


if __name__ == "__main__":
    main()
