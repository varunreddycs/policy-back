from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import load_settings
from .discover import discover_documents
from .ingest import ingest_documents
from .models import ManifestItem
from .utils import make_run_id, read_json, setup_logging


logger = logging.getLogger("ohio_docs_ingestor.cli")


def _tool_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_manifest(path: Path) -> list[ManifestItem]:
    payload = read_json(path, [])
    items: list[ManifestItem] = []
    for entry in payload:
        items.append(
            ManifestItem(
                source_url=str(entry.get("source_url", "")).strip(),
                title=str(entry.get("title", "")).strip() or "Untitled",
                doc_type=str(entry.get("doc_type", "html")).strip().lower(),
                external_id=str(entry.get("external_id", "")).strip(),
                suggested_policy_type=entry.get("suggested_policy_type"),
                effective_date=entry.get("effective_date"),
                agency=str(entry.get("agency", "")).strip().upper(),
            )
        )
    return [item for item in items if item.source_url and item.external_id]


def cmd_discover(args: argparse.Namespace) -> int:
    settings = load_settings(tool_root=_tool_root(), agency_override=args.agency, max_docs_override=args.max_docs)
    items, manifest_path = discover_documents(settings, max_docs=args.max_docs)
    print(f"Discovered {len(items)} documents for {settings.agency}")
    print(f"Manifest: {manifest_path}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = load_settings(tool_root=_tool_root(), agency_override=args.agency, max_docs_override=args.max_docs)
    manifest_path = settings.manifests_dir / f"{settings.agency.lower()}-discovered.json"
    if not manifest_path.exists():
        items, manifest_path = discover_documents(settings, max_docs=args.max_docs)
    else:
        items = _load_manifest(manifest_path)

    if settings.max_docs > 0:
        items = items[: settings.max_docs]

    run_id = make_run_id()
    report = ingest_documents(settings, manifest_items=items, run_id=run_id)
    print(f"Run: {run_id}")
    print(f"Batch: {report['batch_id']}")
    print(f"Counts: {report['counts']}")
    print(f"Embeddings before/after: {report['embeddings']['counts_before']} -> {report['embeddings']['counts_after']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    settings = load_settings(tool_root=_tool_root(), agency_override=args.agency, max_docs_override=args.max_docs)
    items, manifest_path = discover_documents(settings, max_docs=args.max_docs)
    run_id = make_run_id()
    report = ingest_documents(settings, manifest_items=items, run_id=run_id)
    print(f"Manifest: {manifest_path}")
    print(f"Run: {run_id}")
    print(f"Batch: {report['batch_id']}")
    print(f"Batch status: {report['batch_status']} timed_out={report['timed_out']}")
    print(f"Counts: {report['counts']}")
    print(f"Embeddings before/after: {report['embeddings']['counts_before']} -> {report['embeddings']['counts_after']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ohio DAS/JFS document ingestion tool")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("discover", "ingest", "run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--agency", required=True, choices=["DAS", "JFS"]) 
        cmd.add_argument("--max-docs", type=int, default=None)

    return parser


def main() -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "discover":
            return cmd_discover(args)
        if args.command == "ingest":
            return cmd_ingest(args)
        if args.command == "run":
            return cmd_run(args)

        parser.error("Unknown command")
        return 2
    except Exception as exc:
        logger.exception("cli.failed", extra={"extra_fields": {"command": args.command, "error": str(exc)}})
        print(f"Command failed: {exc}")
        return 1
