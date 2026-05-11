#!/usr/bin/env python3
"""Shared implementation for the QA corpus task main.

Phases:
  0. Domain discovery — list all major knowledge domains
  1. Catalog discovery (BFS) — build a taxonomy tree for each domain
  2. Question generation — create questions for each leaf node
  3. Answer generation — answer every question

Concrete entrypoint:
  python qa_main.py ...
"""

import argparse
from contextlib import closing
from dataclasses import dataclass
import json
import logging
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from api import LLMClient
from answers import AnswerGenerator
from catalog import CatalogBuilder
from exporter import DatasetExporter
from models import Checkpoint, Phase, to_slug
from prompts import get_prompts
from questions import QuestionGenerator
from run_paths import QA_TASK_FAMILY, ensure_run_dirs, qa_domains_dir, qa_view_dir, resolve_qa_run_root, system_dir
from run_metadata import (
    atomic_write_json,
    build_run_doc,
    build_run_manifest,
    load_run_doc,
    load_run_manifest,
    set_run_status,
    utc_now_iso,
    write_root_metadata,
    write_run_manifest,
)
from storage import StorageManager
from task_contracts import QA_VIEW_ID, make_artifact_ref, qa_view_relpath

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
        help="Explicit QA run root (default: ./output/{lang}/runs/qa_corpus--<run_id>)",
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
    parser.add_argument(
        "--max-workers", type=int, default=1,
        help="Maximum concurrent top-level domain workers",
    )
    parser.add_argument(
        "--question-max-attempts", type=int, default=3,
        help="Maximum attempts per leaf before question generation dead-letters it",
    )
    parser.add_argument(
        "--answer-max-attempts", type=int, default=3,
        help="Maximum attempts per question before answer generation dead-letters it",
    )
    parser.add_argument(
        "--fail-fast", action="store_true",
        help="Stop all workers as soon as any worker exits with an error",
    )
    parser.add_argument(
        "--worker", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--worker-domain-name", default="", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--worker-domain-slug", default="", help=argparse.SUPPRESS
    )
    return parser.parse_args()


def get_env() -> tuple[str, str]:
    # Real pipeline runs expect DeepSeek credentials from the environment.
    # In this workspace, `DEEPSEEK_BASE_URL` and `DEEPSEEK_API_KEY` are
    # intended to be configured so developers can run end-to-end flows
    # against the live API instead of treating the pipeline as dry-run only.
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
    result = client.chat_json(messages)
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
        atomic_write_json(self.path, {"domains": domains})


def resolve_run_id(args: argparse.Namespace, out_base: str) -> str:
    if args.run_id:
        return args.run_id
    basename = os.path.basename(os.path.abspath(out_base.rstrip(os.sep))) or args.language
    if "--" in basename:
        return basename.split("--", 1)[1]
    return basename


def save_run_metadata(out_base: str, run_id: str, args: argparse.Namespace) -> None:
    root = Path(out_base)
    ensure_run_dirs(root)
    existing_run_doc = load_run_doc(root)
    existing_manifest = load_run_manifest(root)
    created_at = existing_run_doc.get("created_at") if existing_run_doc else utc_now_iso()
    updated_at = utc_now_iso()
    run_doc = build_run_doc(
        task_family=QA_TASK_FAMILY,
        run_id=run_id,
        language=args.language,
        language_scope="language",
        status="running",
        created_at=created_at,
        updated_at=updated_at,
        spec_version="qa_corpus.v1",
        produces=[
            {
                "kind": "view",
                "name": QA_VIEW_ID,
                "path": str(qa_view_relpath()),
            }
        ],
        extra_fields={"output_dir": os.path.abspath(out_base)},
    )
    config_doc = {
        "seed_domain": args.seed_domain,
        "max_depth": args.max_depth,
        "questions_per_node": args.questions_per_node,
        "model_catalog": args.model_catalog,
        "model_questions": args.model_questions,
        "model_answers": args.model_answers,
        "question_max_attempts": args.question_max_attempts,
        "answer_max_attempts": args.answer_max_attempts,
        "max_workers": args.max_workers,
        "temperature": args.temperature,
    }
    write_root_metadata(root, run_doc=run_doc, config_doc=config_doc, lineage_doc={"sources": []})
    summary = {"domains_total": 0, "domains_completed": 0, "dead_letter_domains": 0}
    outputs = {}
    if args.resume and existing_manifest is not None:
        summary = existing_manifest.get("summary", summary)
        outputs = existing_manifest.get("outputs", outputs)
    write_run_manifest(
        root,
        build_run_manifest(
            task_family=QA_TASK_FAMILY,
            run_id=run_id,
            language=args.language,
            language_scope="language",
            status="running",
            updated_at=updated_at,
            summary=summary,
            outputs=outputs,
        ),
    )


@dataclass(frozen=True)
class DomainScanState:
    slug: str
    name: str
    checkpoint: Checkpoint

    @property
    def is_complete(self) -> bool:
        return self.checkpoint.completed

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
    base = qa_domains_dir(out_base)
    if not base.exists():
        return scan

    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        storage = StorageManager(str(child))
        try:
            checkpoint = storage.load_checkpoint()
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Skipping unreadable checkpoint at %s: %s", storage.checkpoint_path, exc)
            continue

        if checkpoint is None:
            continue

        domain_name = child.name
        tree = checkpoint.knowledge_tree or storage.load_catalog()
        if tree is not None:
            domain_name = tree.domain or domain_name

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
    with closing(make_client(base_url, api_key, model)) as client:
        domains = discover_domains(client, prompts)
    print(f"Found {len(domains)} domains:")
    for domain in domains:
        print(f"  - {domain['name']} ({domain['slug']})")
    return domains


def resolve_domains_to_process(
    args: argparse.Namespace,
    out_base: str,
    prompts: dict,
    base_url: str,
    api_key: str,
) -> tuple[list[dict], set[str]]:
    meta_cp_path = system_dir(out_base) / "meta_checkpoint.json"
    meta_cp_path.parent.mkdir(parents=True, exist_ok=True)
    meta_cp = MetaCheckpoint(str(meta_cp_path))
    meta_domains = meta_cp.load() if args.resume else []
    checkpoint_scan = scan_domain_checkpoints(out_base) if args.resume else {}
    done_slugs: set[str] = {slug for slug, state in checkpoint_scan.items() if state.is_complete}

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

    if not args.seed_domain:
        meta_cp.save(domains)

    return domains, done_slugs


def build_worker_command(
    args: argparse.Namespace,
    out_base: str,
    domain: dict,
    resume: bool,
) -> list[str]:
    qa_main_path = Path(__file__).resolve().with_name("qa_main.py")
    cmd = [
        sys.executable,
        str(qa_main_path),
        "--worker",
        "--worker-domain-name",
        domain["name"],
        "--worker-domain-slug",
        domain["slug"],
        "--output-dir",
        out_base,
        "--language",
        args.language,
        "--max-depth",
        str(args.max_depth),
        "--questions-per-node",
        str(args.questions_per_node),
        "--model-catalog",
        args.model_catalog,
        "--model-questions",
        args.model_questions,
        "--model-answers",
        args.model_answers,
        "--temperature",
        str(args.temperature),
        "--question-max-attempts",
        str(args.question_max_attempts),
        "--answer-max-attempts",
        str(args.answer_max_attempts),
        "--max-workers",
        "1",
    ]
    if args.run_id:
        cmd.extend(["--run-id", args.run_id])
    if args.verbose:
        cmd.append("--verbose")
    if resume:
        cmd.append("--resume")
    return cmd


def has_existing_qa_run_content(out_base: str) -> bool:
    domains_dir = qa_domains_dir(out_base)
    if domains_dir.exists():
        for child in domains_dir.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                return True

    view_dir = qa_view_dir(out_base)
    if view_dir.exists():
        for child in view_dir.iterdir():
            if not child.name.startswith("."):
                return True

    for filename in ("run.json", "manifest.json", "config.json", "lineage.json"):
        if (Path(out_base) / filename).exists():
            return True

    return False


def export_completed_domains(
    out_base: str,
    run_id: str,
    language: str,
    update_run_bundle: bool,
) -> dict:
    exporter = DatasetExporter(str(qa_view_dir(out_base)), run_id)
    domain_summaries: list[dict] = []
    for slug, state in sorted(scan_domain_checkpoints(out_base).items()):
        if not state.is_complete:
            continue
        storage = StorageManager(str(qa_domains_dir(out_base) / slug))
        summary = export_domain_if_complete(storage, exporter, language)
        if summary is not None:
            domain_summaries.append(summary)
    if update_run_bundle:
        return exporter.export_run(domain_summaries, language)
    return {"domains": domain_summaries}


def count_completed_domains(out_base: str) -> int:
    return sum(1 for state in scan_domain_checkpoints(out_base).values() if state.is_complete)


def update_qa_manifest_and_status(
    out_base: str,
    run_id: str,
    language: str,
    *,
    status: str,
    domains_total: int,
    dead_letter_domains: int,
    view_output: Optional[dict] = None,
) -> None:
    updated_at = utc_now_iso()
    outputs = {}
    if view_output:
        outputs["views"] = {
            QA_VIEW_ID: {
                "artifact_ref": make_artifact_ref(QA_TASK_FAMILY, run_id, "view", QA_VIEW_ID),
                "summary": view_output,
            }
        }
    write_run_manifest(
        out_base,
        build_run_manifest(
            task_family=QA_TASK_FAMILY,
            run_id=run_id,
            language=language,
            language_scope="language",
            status=status,
            updated_at=updated_at,
            summary={
                "domains_total": domains_total,
                "domains_completed": count_completed_domains(out_base),
                "dead_letter_domains": dead_letter_domains,
            },
            outputs=outputs,
        ),
    )
    set_run_status(out_base, status, updated_at=updated_at)


def terminate_processes(processes: list[subprocess.Popen]) -> None:
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()

    deadline = time.time() + 5
    for proc in processes:
        if proc.poll() is not None:
            continue
        timeout = max(0.0, deadline - time.time())
        if timeout == 0:
            break
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass

    for proc in processes:
        if proc.poll() is None:
            proc.kill()


def print_resume_hint(args: argparse.Namespace, heading: str = "Interrupted") -> None:
    out = args.output_dir or str(resolve_qa_run_root(args.language, args.run_id or "default"))
    cmd = ["python", "qa_main.py", "--resume", "--output-dir", out, "--language", args.language]
    if args.seed_domain:
        cmd.extend(["--seed-domain", args.seed_domain])
    if args.max_depth != 3:
        cmd.extend(["--max-depth", str(args.max_depth)])
    if args.questions_per_node != 5:
        cmd.extend(["--questions-per-node", str(args.questions_per_node)])
    if args.model_catalog != "deepseek-v4-flash":
        cmd.extend(["--model-catalog", args.model_catalog])
    if args.model_questions != "deepseek-v4-flash":
        cmd.extend(["--model-questions", args.model_questions])
    if args.model_answers != "deepseek-v4-pro":
        cmd.extend(["--model-answers", args.model_answers])
    if args.temperature != 0.3:
        cmd.extend(["--temperature", str(args.temperature)])
    if args.question_max_attempts != 3:
        cmd.extend(["--question-max-attempts", str(args.question_max_attempts)])
    if args.answer_max_attempts != 3:
        cmd.extend(["--answer-max-attempts", str(args.answer_max_attempts)])
    if args.run_id:
        cmd.extend(["--run-id", args.run_id])
    if args.max_workers != 1:
        cmd.extend(["--max-workers", str(args.max_workers)])
    if args.fail_fast:
        cmd.append("--fail-fast")
    if args.verbose:
        cmd.append("--verbose")
    print(f"\n{heading}. Resume with:", file=sys.stderr)
    print(f"  {shlex.join(cmd)}", file=sys.stderr)


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
        with closing(make_client(base_url, api_key, args.model_catalog)) as client:
            builder = CatalogBuilder(
                llm=client,
                max_depth=args.max_depth,
                storage=storage,
                prompts=prompts,
                checkpoint=checkpoint,
            )
            tree = builder.run(seed_domain)
        checkpoint = Checkpoint(phase=Phase.QUESTION_GENERATION)
        storage.save_checkpoint(checkpoint)

    # Phase 2: Question Generation
    if checkpoint and checkpoint.phase == Phase.QUESTION_GENERATION:
        print("  Phase 2 — question generation")
        with closing(make_client(base_url, api_key, args.model_questions)) as client:
            qgen = QuestionGenerator(
                llm=client,
                count=args.questions_per_node,
                max_attempts=args.question_max_attempts,
                storage=storage,
                prompts=prompts,
                checkpoint=checkpoint,
            )
            qgen.run()

    checkpoint = storage.load_checkpoint()

    # Phase 3: Answer Generation
    if checkpoint and checkpoint.phase == Phase.ANSWER_GENERATION and not checkpoint.completed:
        print("  Phase 3 — answer generation")
        with closing(make_client(base_url, api_key, args.model_answers)) as client:
            agen = AnswerGenerator(
                llm=client,
                max_attempts=args.answer_max_attempts,
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
    if checkpoint is None:
        return None
    tree = storage.load_catalog()
    if tree is None or not checkpoint.completed:
        return None
    return exporter.export_domain(storage, tree, language, checkpoint=checkpoint)


def summarize_dead_letters(out_base: str) -> list[dict]:
    summaries: list[dict] = []
    for slug, state in sorted(scan_domain_checkpoints(out_base).items()):
        question_count = len(state.checkpoint.question_dead_letters)
        answer_count = len(state.checkpoint.answer_dead_letters)
        if not question_count and not answer_count:
            continue
        summaries.append({
            "slug": slug,
            "name": state.name,
            "question_dead_letters": question_count,
            "answer_dead_letters": answer_count,
        })
    return summaries


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_worker(args: argparse.Namespace, base_url: str, api_key: str) -> None:
    if not args.worker_domain_name or not args.worker_domain_slug:
        raise ValueError("Worker mode requires both worker domain name and slug")

    out_base = args.output_dir or str(resolve_qa_run_root(args.language, args.run_id or "default"))
    prompts = get_prompts(args.language)
    domain_output = str(qa_domains_dir(out_base) / args.worker_domain_slug)
    storage = StorageManager(domain_output)

    print(f"\n{'=' * 60}")
    print(f"[worker] {args.worker_domain_name} ({args.worker_domain_slug})")
    print(f"{'=' * 60}")
    run_domain(args.worker_domain_name, storage, prompts, args, base_url, api_key)


def run_controller(args: argparse.Namespace, base_url: str, api_key: str) -> None:
    lang = args.language
    initial_root = args.output_dir or str(resolve_qa_run_root(lang, args.run_id or "default"))
    prompts = get_prompts(lang)
    run_id = resolve_run_id(args, initial_root)
    out_base = args.output_dir or str(resolve_qa_run_root(lang, run_id))
    if not args.resume and has_existing_qa_run_content(out_base):
        print(
            f"QA run directory already contains content: {out_base}\n"
            "Use --resume to continue this run, or choose a new --run-id / --output-dir.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    ensure_run_dirs(out_base)
    save_run_metadata(out_base, run_id, args)
    domains, done_slugs = resolve_domains_to_process(args, out_base, prompts, base_url, api_key)

    pending_domains = [dom for dom in domains if dom["slug"] not in done_slugs]
    for i, dom in enumerate(domains):
        if dom["slug"] in done_slugs:
            print(f"\n[{i + 1}/{len(domains)}] {dom['name']} — already done, skipping")
    if done_slugs:
        export_completed_domains(out_base, run_id, lang, update_run_bundle=False)

    max_workers = max(1, args.max_workers)
    active: list[tuple[subprocess.Popen, dict]] = []
    pending_index = 0
    worker_failures: list[tuple[dict, int]] = []

    try:
        while pending_index < len(pending_domains) or active:
            while pending_index < len(pending_domains) and len(active) < max_workers:
                domain = pending_domains[pending_index]
                pending_index += 1
                cmd = build_worker_command(args, out_base, domain, args.resume)
                print(
                    f"\nLaunching worker {pending_index}/{len(pending_domains)} "
                    f"for {domain['name']} ({domain['slug']})"
                )
                proc = subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parent), start_new_session=True)
                active.append((proc, domain))

            if not active:
                continue

            time.sleep(0.2)
            still_active: list[tuple[subprocess.Popen, dict]] = []
            for proc, domain in active:
                code = proc.poll()
                if code is None:
                    still_active.append((proc, domain))
                    continue
                if code != 0:
                    if args.fail_fast:
                        remaining = [p for p, _ in still_active]
                        remaining.extend(p for p, _ in active if p is not proc and p not in remaining)
                        terminate_processes(remaining)
                        partial_bundle = export_completed_domains(out_base, run_id, lang, update_run_bundle=False)
                        update_qa_manifest_and_status(
                            out_base,
                            run_id,
                            lang,
                            status="failed",
                            domains_total=len(domains),
                            dead_letter_domains=len(summarize_dead_letters(out_base)),
                            view_output=partial_bundle,
                        )
                        print(
                            f"Worker failed: {domain['name']} ({domain['slug']})",
                            file=sys.stderr,
                        )
                        print_resume_hint(args)
                        raise SystemExit(code)

                    worker_failures.append((domain, code))
                    print(
                        f"Worker failed, continuing: {domain['name']} ({domain['slug']}), exit code {code}",
                        file=sys.stderr,
                    )
                    continue
                print(f"Worker finished: {domain['name']} ({domain['slug']})")
                export_completed_domains(out_base, run_id, lang, update_run_bundle=False)
            active = still_active
    except KeyboardInterrupt:
        terminate_processes([proc for proc, _ in active])
        partial_bundle = export_completed_domains(out_base, run_id, lang, update_run_bundle=False)
        update_qa_manifest_and_status(
            out_base,
            run_id,
            lang,
            status="interrupted",
            domains_total=len(domains),
            dead_letter_domains=len(summarize_dead_letters(out_base)),
            view_output=partial_bundle,
        )
        print_resume_hint(args)
        raise SystemExit(1)

    final_bundle = export_completed_domains(out_base, run_id, lang, update_run_bundle=True)
    dead_letter_summaries = summarize_dead_letters(out_base)
    if dead_letter_summaries:
        print("\nCompleted with dead-lettered items:")
        for summary in dead_letter_summaries:
            print(
                "  "
                f"- {summary['name']} ({summary['slug']}): "
                f"question_dead_letters={summary['question_dead_letters']}, "
                f"answer_dead_letters={summary['answer_dead_letters']}"
            )

    if worker_failures:
        update_qa_manifest_and_status(
            out_base,
            run_id,
            lang,
            status="failed",
            domains_total=len(domains),
            dead_letter_domains=len(dead_letter_summaries),
            view_output=final_bundle,
        )
        print("\nRun finished with worker failures:", file=sys.stderr)
        for domain, code in worker_failures:
            print(
                f"  - {domain['name']} ({domain['slug']}), exit code {code}",
                file=sys.stderr,
            )
        print_resume_hint(args, heading="Run finished with worker failures")
        raise SystemExit(1)

    update_qa_manifest_and_status(
        out_base,
        run_id,
        lang,
        status="completed",
        domains_total=len(domains),
        dead_letter_domains=len(dead_letter_summaries),
        view_output=final_bundle,
    )

    print(f"\nAll done. Output: {os.path.abspath(out_base)}")
    print(f"Run ID: {run_id}")
    print(f"Dataset export: {os.path.abspath(os.path.join(out_base, 'views', QA_VIEW_ID, 'dataset.jsonl'))}")
    print(f"Dataset manifest: {os.path.abspath(os.path.join(out_base, 'views', QA_VIEW_ID, 'manifest.json'))}")


def main() -> None:
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    base_url, api_key = get_env()

    if args.worker:
        run_worker(args, base_url, api_key)
    else:
        run_controller(args, base_url, api_key)


if __name__ == "__main__":
    main()
