#!/usr/bin/env python3
"""QA-Dump: LLM-driven tree-of-knowledge QA dataset generator.

Phases:
  0. Domain discovery — list all major knowledge domains
  1. Catalog discovery (BFS) — build a taxonomy tree for each domain
  2. Question generation — create questions for each leaf node
  3. Answer generation — answer every question

Without --seed-domain: discovers all domains and processes each one.
With --seed-domain X: processes only domain X.
Resume from a checkpoint at any phase with --resume.
"""

import argparse
from dataclasses import dataclass
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from api import LLMClient
from answers import AnswerGenerator
from catalog import CatalogBuilder
from exporter import DatasetExporter
from models import Checkpoint, Phase, to_slug
from prompts import get_prompts
from questions import QuestionGenerator
from storage import StorageManager

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a tree-structured QA dataset via LLM.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--seed-domain", default="",
        help="Single domain to process (empty = discover all domains)",
    )
    parser.add_argument(
        "--max-depth", type=int, default=3,
        help="Maximum tree depth (root=0)",
    )
    parser.add_argument(
        "--questions-per-node", type=int, default=5,
        help="Questions per leaf node",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Output directory (default: ./output/{lang})",
    )
    parser.add_argument(
        "--run-id", default="",
        help="Explicit run identifier used in exported sample IDs",
    )
    parser.add_argument(
        "--model-catalog", default="deepseek-v4-flash",
        help="Model for catalog discovery",
    )
    parser.add_argument(
        "--model-questions", default="deepseek-v4-flash",
        help="Model for question generation",
    )
    parser.add_argument(
        "--model-answers", default="deepseek-v4-pro",
        help="Model for answer generation",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from existing checkpoint",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.3,
        help="LLM temperature",
    )
    parser.add_argument(
        "--language", default="zh", choices=["zh", "en"],
        help="Language for prompts and catalog content",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging",
    )
    return parser.parse_args()


def get_env() -> tuple[str, str]:
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: DEEPSEEK_API_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)
    return base_url, api_key


def make_client(base_url: str, api_key: str, model: str) -> LLMClient:
    return LLMClient(base_url=base_url, api_key=api_key, model=model)


# ---------------------------------------------------------------------------
# Phase 0: discover all top-level knowledge domains
# ---------------------------------------------------------------------------

def discover_domains(client: LLMClient, prompts: dict) -> list[dict]:
    """Ask the LLM for all major knowledge domains. Returns list of {name, slug, description}."""
    messages = [
        {"role": "system", "content": prompts["domain_system"]},
        {"role": "user", "content": prompts["domain_user"]},
    ]
    result = client.chat_json(messages, max_tokens=4096)
    domains = []
    for item in result.get("categories", []):
        slug = item.get("slug", "") or to_slug(item.get("name", ""))
        domains.append({
            "name": item.get("name", "Untitled"),
            "slug": slug,
            "description": item.get("description", ""),
        })
    logger.info("Discovered %d top-level domains", len(domains))
    return domains


# ---------------------------------------------------------------------------
# Meta-checkpoint: persists domain ordering across Phase-0 → all domains
# ---------------------------------------------------------------------------

class MetaCheckpoint:
    """Persists discovered domain ordering for run-level resume."""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> list[dict]:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                domains = raw.get("domains", [])
                return domains if isinstance(domains, list) else []
            return raw if isinstance(raw, list) else []
        return []

    def save(self, domains: list[dict]) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"domains": domains}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)


def atomic_write_json(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def resolve_run_id(args: argparse.Namespace, out_base: str) -> str:
    if args.run_id:
        return args.run_id
    return os.path.basename(os.path.abspath(out_base.rstrip(os.sep))) or args.language


def save_run_metadata(out_base: str, run_id: str, args: argparse.Namespace) -> None:
    atomic_write_json(
        os.path.join(out_base, "run.json"),
        {
            "run_id": run_id,
            "output_dir": os.path.abspath(out_base),
            "language": args.language,
            "seed_domain": args.seed_domain,
            "max_depth": args.max_depth,
            "questions_per_node": args.questions_per_node,
            "model_catalog": args.model_catalog,
            "model_questions": args.model_questions,
            "model_answers": args.model_answers,
        },
    )


@dataclass(frozen=True)
class DomainScanState:
    slug: str
    name: str
    checkpoint: Checkpoint

    @property
    def is_complete(self) -> bool:
        return self.checkpoint.phase == Phase.ANSWER_GENERATION and not self.checkpoint.answer_queue

    def as_domain_entry(self) -> dict:
        return {
            "name": self.name,
            "slug": self.slug,
            "description": "",
        }


@dataclass(frozen=True)
class ResumePlan:
    domains: list[dict]
    done_slugs: set[str]
    source: Optional[str]


def scan_domain_checkpoints(out_base: str) -> dict[str, DomainScanState]:
    scan: dict[str, DomainScanState] = {}
    base = Path(out_base)
    if not base.exists():
        return scan

    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name == "exports" or child.name.startswith("."):
            continue
        checkpoint_path = child / ".checkpoint.json"
        if not checkpoint_path.exists():
            continue

        try:
            checkpoint = Checkpoint(**json.loads(checkpoint_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Skipping unreadable checkpoint at %s: %s", checkpoint_path, exc)
            continue

        domain_name = child.name
        if checkpoint.knowledge_tree is not None:
            domain_name = checkpoint.knowledge_tree.domain or domain_name

        scan[child.name] = DomainScanState(
            slug=child.name,
            name=domain_name,
            checkpoint=checkpoint,
        )
    return scan


def build_resume_plan(meta_domains: list[dict], scan: dict[str, DomainScanState]) -> ResumePlan:
    done_slugs = {slug for slug, state in scan.items() if state.is_complete}
    scan_domains = [scan[slug].as_domain_entry() for slug in sorted(scan)]

    if meta_domains:
        if not scan:
            return ResumePlan(meta_domains, done_slugs, "saved meta checkpoint")

        meta_slugs = {domain.get("slug", "") for domain in meta_domains}
        scan_slugs = set(scan)
        if scan_slugs.issubset(meta_slugs):
            return ResumePlan(meta_domains, done_slugs, "saved meta checkpoint")

        logger.warning(
            "Meta checkpoint domains do not match checkpoint directories; "
            "resuming from checkpoint directories instead."
        )
        return ResumePlan(scan_domains, done_slugs, "checkpoint directories")

    if scan_domains:
        return ResumePlan(scan_domains, done_slugs, "checkpoint directories")

    return ResumePlan([], done_slugs, None)


def resolve_seed_domain_entry(seed_domain: str, scan: dict[str, DomainScanState], resume: bool) -> dict:
    default = {"name": seed_domain, "slug": to_slug(seed_domain), "description": ""}
    if not resume:
        return default

    for state in scan.values():
        if state.name == seed_domain or state.slug == seed_domain or state.slug == default["slug"]:
            return state.as_domain_entry()

    return default


def discover_and_print_domains(base_url: str, api_key: str, model: str, prompts: dict) -> list[dict]:
    print("Phase 0 — discovering top-level knowledge domains ...")
    client = make_client(base_url, api_key, model)
    domains = discover_domains(client, prompts)
    print(f"Found {len(domains)} domains:")
    for domain in domains:
        print(f"  - {domain['name']} ({domain['slug']})")
    return domains


# ---------------------------------------------------------------------------
# Per-domain pipeline (Phases 1–3)
# ---------------------------------------------------------------------------

def run_domain(
    seed_domain: str,
    storage: StorageManager,
    prompts: dict,
    args: argparse.Namespace,
    base_url: str,
    api_key: str,
) -> None:
    """Run the full 3-phase pipeline for a single domain into storage.base."""

    # Snapshot config
    storage.setup()
    storage.save_config({k: str(v) for k, v in vars(args).items()})

    checkpoint: Optional[Checkpoint] = None
    if args.resume:
        checkpoint = storage.load_checkpoint()
        if checkpoint is None:
            print("  (no checkpoint found; starting fresh)", file=sys.stderr)
        else:
            print(f"  Resuming from phase: {checkpoint.phase.value}")

    # Phase 1: Catalog Discovery
    if checkpoint is None or checkpoint.phase == Phase.CATALOG_DISCOVERY:
        print("  Phase 1 — catalog discovery (BFS)")
        client = make_client(base_url, api_key, args.model_catalog)
        builder = CatalogBuilder(
            llm=client,
            max_depth=args.max_depth,
            storage=storage,
            prompts=prompts,
            checkpoint=checkpoint,
        )
        tree = builder.run(seed_domain)
        checkpoint = Checkpoint(phase=Phase.QUESTION_GENERATION, knowledge_tree=tree)
        storage.save_checkpoint(checkpoint)

    # Phase 2: Question Generation
    if checkpoint and checkpoint.phase == Phase.QUESTION_GENERATION:
        print("  Phase 2 — question generation")
        client = make_client(base_url, api_key, args.model_questions)
        qgen = QuestionGenerator(
            llm=client,
            count=args.questions_per_node,
            storage=storage,
            prompts=prompts,
            checkpoint=checkpoint,
        )
        qgen.run()

    checkpoint = storage.load_checkpoint()

    # Phase 3: Answer Generation
    if checkpoint and checkpoint.phase == Phase.ANSWER_GENERATION:
        print("  Phase 3 — answer generation")
        client = make_client(base_url, api_key, args.model_answers)
        agen = AnswerGenerator(
            llm=client,
            storage=storage,
            prompts=prompts,
            checkpoint=checkpoint,
        )
        agen.run()

    print(f"  Done — {seed_domain}")


def export_domain_if_complete(
    storage: StorageManager,
    exporter: DatasetExporter,
    language: str,
) -> Optional[dict]:
    checkpoint = storage.load_checkpoint()
    if checkpoint is None or checkpoint.knowledge_tree is None:
        return None
    if checkpoint.phase != Phase.ANSWER_GENERATION or checkpoint.answer_queue:
        return None
    return exporter.export_domain(storage, checkpoint.knowledge_tree, language)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace, base_url: str, api_key: str) -> None:
    lang = args.language
    out_base = args.output_dir or f"./output/{lang}"
    prompts = get_prompts(lang)
    run_id = resolve_run_id(args, out_base)
    os.makedirs(out_base, exist_ok=True)
    save_run_metadata(out_base, run_id, args)
    exporter = DatasetExporter(os.path.join(out_base, "exports"), run_id)
    meta_cp = MetaCheckpoint(os.path.join(out_base, ".meta_checkpoint.json"))
    meta_domains = meta_cp.load() if args.resume else []
    checkpoint_scan = scan_domain_checkpoints(out_base) if args.resume else {}
    done_slugs: set[str] = {slug for slug, state in checkpoint_scan.items() if state.is_complete}

    # ---- Determine domains to process ----
    if args.seed_domain:
        domains = [resolve_seed_domain_entry(args.seed_domain, checkpoint_scan, args.resume)]
    elif args.resume:
        resume_plan = build_resume_plan(meta_domains, checkpoint_scan)
        domains = resume_plan.domains
        done_slugs = resume_plan.done_slugs
        if domains:
            source = resume_plan.source or "checkpoint directories"
            print(f"Resume mode — loaded {len(domains)} domains from {source}")
        else:
            print("Resume mode — no saved domains found, falling back to fresh discovery")
    else:
        domains = discover_and_print_domains(base_url, api_key, args.model_catalog, prompts)

    if not args.seed_domain and not domains:
        domains = discover_and_print_domains(base_url, api_key, args.model_catalog, prompts)

    # Persist discovered domains so resume doesn't need to re-discover
    if not args.seed_domain:
        meta_cp.save(domains)

    domain_summaries: list[dict] = []

    # Process each domain
    for i, dom in enumerate(domains):
        slug = dom["slug"]
        domain_output = os.path.join(out_base, slug)
        storage = StorageManager(domain_output)
        storage.setup()

        if slug in done_slugs:
            print(f"\n[{i + 1}/{len(domains)}] {dom['name']} — already done, skipping")
            summary = export_domain_if_complete(storage, exporter, lang)
            if summary is not None:
                domain_summaries.append(summary)
            continue

        print(f"\n{'=' * 60}")
        print(f"[{i + 1}/{len(domains)}] {dom['name']}")
        print(f"{'=' * 60}")

        run_domain(dom["name"], storage, prompts, args, base_url, api_key)
        summary = export_domain_if_complete(storage, exporter, lang)
        if summary is not None:
            domain_summaries.append(summary)

        done_slugs.add(slug)

    exporter.export_run(domain_summaries, lang)
    print(f"\nAll done. Output: {os.path.abspath(out_base)}")
    print(f"Run ID: {run_id}")
    print(f"Dataset export: {os.path.abspath(os.path.join(out_base, 'exports', 'dataset.jsonl'))}")
    print(f"Dataset manifest: {os.path.abspath(os.path.join(out_base, 'exports', 'manifest.json'))}")


def main() -> None:
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    base_url, api_key = get_env()

    def _on_sigint(signum, frame):
        print("\nInterrupted. Checkpoint saved. Resume with:", file=sys.stderr)
        out = args.output_dir or f"./output/{args.language}"
        cmd = f"python main.py --resume --output-dir {out} --language {args.language}"
        if args.run_id:
            cmd += f" --run-id {args.run_id}"
        print(f"  {cmd}", file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGINT, _on_sigint)

    run(args, base_url, api_key)


if __name__ == "__main__":
    main()
