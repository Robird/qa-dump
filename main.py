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
import json
import logging
import os
import signal
import sys
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
# Meta-checkpoint: tracks domain-level progress across Phase-0 → all domains
# ---------------------------------------------------------------------------

class MetaCheckpoint:
    """Tracks which domains have been fully processed."""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        return {"domains": [], "done": []}

    def save(self, domains: list[dict], done_slugs: list[str]) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"domains": domains, "done": done_slugs}, f, indent=2, ensure_ascii=False)
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

    # ---- Determine domains to process ----
    if args.seed_domain:
        domains = [{"name": args.seed_domain, "slug": to_slug(args.seed_domain), "description": ""}]
    else:
        print("Phase 0 — discovering top-level knowledge domains ...")
        client = make_client(base_url, api_key, args.model_catalog)
        domains = discover_domains(client, prompts)
        print(f"Found {len(domains)} domains:")
        for d in domains:
            print(f"  - {d['name']} ({d['slug']})")

    # Meta-checkpoint for domain-level progress
    meta_cp = MetaCheckpoint(os.path.join(out_base, ".meta_checkpoint.json"))
    meta_state = meta_cp.load() if args.resume else {"domains": [], "done": []}
    done_slugs: set[str] = set(meta_state.get("done", []))

    # Persist discovered domains so resume doesn't need to re-discover
    if not args.seed_domain:
        meta_cp.save(domains, list(done_slugs))

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
        meta_cp.save(domains, list(done_slugs))

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
