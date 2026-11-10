"""Command line entry point: ``scrapagents <command>`` (also wrapped by the Makefile)."""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from scrapagents.bronze import check_files as check_bronze_files
from scrapagents.bronze import generate as generate_bronze_files
from scrapagents.bronze import write_files as write_bronze_files
from scrapagents.bronze.generator import BRONZE_DIR
from scrapagents.contracts import iter_contract_files, validate_contract_file
from scrapagents.dags import check_dags, generate, write_dags
from scrapagents.dbt import check_files as check_dbt_files
from scrapagents.dbt import generate as generate_dbt_files
from scrapagents.dbt import write_files as write_dbt_files
from scrapagents.dbt.generator import DBT_DIR
from scrapagents.design import WorkflowError, advance, sign, status
from scrapagents.design.probes import append_rows, probe
from scrapagents.design.review import write_review
from scrapagents.dossier import (
    SOURCE_TYPES,
    TEAMS,
    DossierError,
    check_dossiers,
    check_producto_oi,
    create_dossier,
    load_dossier,
)
from scrapagents.paths import INGESTIONS_DIR, REPO_ROOT
from scrapagents.runtime_client import HttpRuntimeClient


def _new_ingestion(args: argparse.Namespace) -> int:
    try:
        path = create_dossier(args.id, args.team, dataset=args.dataset, source_type=args.type)
    except DossierError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    dossier = load_dossier(path)
    print(f"created {path} (phase: {dossier.state['phase']})")
    print("next: fill discovery.md, then assessment.md, then ask a human for gate H1.")
    return 0


def _report(errors: list[str], ok_message: str) -> int:
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(ok_message)
    return 0


def _check_gates(_: argparse.Namespace) -> int:
    return _report([*check_dossiers(), *check_producto_oi()], "gates ok")


def _check_contracts(_: argparse.Namespace) -> int:
    errors: list[str] = []
    count = 0
    for path in iter_contract_files():
        count += 1
        errors.extend(validate_contract_file(path))
    drafts = 0
    for dossier_dir in sorted(p for p in INGESTIONS_DIR.glob("*") if not p.name.startswith("_")):
        draft = dossier_dir / "contract.yml"
        if draft.is_file():
            drafts += 1
            errors.extend(validate_contract_file(draft, check_location=False))
    for path in sorted((INGESTIONS_DIR / "_fixture" / "contracts").glob("*.yml")):
        drafts += 1
        errors.extend(validate_contract_file(path, check_location=False))
    for path in sorted(INGESTIONS_DIR.glob("[!_]*/contracts/*.yml")):
        drafts += 1
        errors.extend(validate_contract_file(path, check_location=False))
    return _report(errors, f"{count} contracts and {drafts} draft contracts valid")


def _generate_dags(args: argparse.Namespace) -> int:
    dags, errors = generate(args.id, [Path(c) for c in args.config])
    if errors:
        return _report(errors, "")
    out_dir = Path(args.out)
    if args.check:
        return _report(check_dags(dags, out_dir), f"{len(dags)} DAGs match their sources")
    written = write_dags(dags, out_dir)
    print(f"generated {len(dags)} DAGs in {out_dir} ({len(written)} files)")
    return 0


def _generate_dbt(args: argparse.Namespace) -> int:
    catalog = [tuple(item.split("/", 1)) for item in args.catalog]
    if any(len(pair) != 2 for pair in catalog):
        return _report(["--catalog expects <source_system>/<dataset>"], "")
    files, errors = generate_dbt_files([Path(c) for c in args.contract], catalog)
    if errors:
        return _report(errors, "")
    dbt_dir = Path(args.out)
    if args.check:
        return _report(check_dbt_files(files, dbt_dir), f"{len(files)} dbt files match contracts")
    write_dbt_files(files, dbt_dir)
    print(f"generated {len(files)} dbt files in {dbt_dir}")
    return 0


def _generate_bronze(args: argparse.Namespace) -> int:
    catalog = [tuple(item.split("/", 1)) for item in args.catalog]
    if any(len(pair) != 2 for pair in catalog):
        return _report(["--catalog expects <source_system>/<dataset>"], "")
    files, errors = generate_bronze_files([Path(c) for c in args.contract], catalog)
    if errors:
        return _report(errors, "")
    out_dir = Path(args.out)
    if args.check:
        return _report(check_bronze_files(files, out_dir), "bronze tables and registry match")
    write_bronze_files(files, out_dir)
    print(f"generated {len(files)} bronze files in {out_dir}")
    return 0


def _dossier(ingestion_id: str) -> Path:
    path = INGESTIONS_DIR / ingestion_id
    if ingestion_id.startswith("_") or not (path / "state.yml").is_file():
        raise DossierError(f"no dossier ingestions/{ingestion_id}/ (make new-ingestion)")
    return path


def make_router():
    """The stealth browser session (playwright + obscura.sh); replaced by tests."""

    from scrapagents.stealth import PlaywrightObscuraRouter  # noqa: PLC0415

    return PlaywrightObscuraRouter()


def _probe(args: argparse.Namespace) -> int:
    try:
        dossier = _dossier(args.id)
        with make_router() as router:
            rows, robots = probe(
                router,
                args.url,
                today=datetime.date.today().isoformat(),
                robots=not args.no_robots,
                timeout_seconds=args.timeout,
            )
    except (DossierError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for row in rows:
        print(row.markdown())
    for host, text in robots.items():
        print(f"\n--- robots.txt of {host} (first 2000 characters) ---\n{text[:2000]}")
    if args.dry_run:
        return 0
    added = append_rows(dossier / "discovery.md", rows)
    print(f"\n{added} new row(s) added to {dossier / 'discovery.md'}")
    return 0


def _status(args: argparse.Namespace) -> int:
    try:
        current = status(_dossier(args.id))
    except DossierError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    gates = ", ".join(f"{g}={s}" for g, s in current.gates.items())
    print(f"{current.ingestion_id}: phase {current.phase} ({gates})")
    for blocker in current.blockers:
        print(f"  missing: {blocker}")
    if current.waiting_for_human:
        print(f"  waiting for a human: {current.waiting_for_human}")
    if current.note:
        print(f"  {current.note}")
    if current.can_advance:
        print(f"  ready: `make advance ID={current.ingestion_id}` moves to {current.next_phase}")
    return 1 if current.blockers else 0


def _advance(args: argparse.Namespace) -> int:
    try:
        phase = advance(_dossier(args.id))
    except (DossierError, WorkflowError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{args.id}: now in phase {phase}")
    return 0


def _review(args: argparse.Namespace) -> int:
    try:
        findings = write_review(_dossier(args.id))
    except DossierError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for error in findings.errors:
        print(f"error: {error}", file=sys.stderr)
    for warning in findings.warnings:
        print(f"warning: {warning}")
    print(f"review written to ingestions/{args.id}/review.md")
    return 1 if findings.errors else 0


# Environment variables set by coding agents' shells: a gate is never signed from one of them.
AGENT_ENVIRONMENT = ("CLAUDECODE", "CURSOR_AGENT", "CURSOR_CONVERSATION_ID")


def _sign(args: argparse.Namespace) -> int:
    agent = next((v for v in AGENT_ENVIRONMENT if os.environ.get(v)), None)
    if agent:
        print(f"error: refusing to sign from an agent shell ({agent} is set)", file=sys.stderr)
        return 1
    if not sys.stdin.isatty():
        print("error: signing needs an interactive terminal operated by a person", file=sys.stderr)
        return 1
    try:
        dossier = _dossier(args.id)
        print(f"You are about to sign gate {args.gate.upper()} of '{args.id}' as '{args.by}'.")
        print(f"Review ingestions/{args.id}/ first; this records your approval in state.yml.")
        if input(f"Type {args.gate} to confirm: ").strip() != args.gate:
            print("not confirmed; nothing changed", file=sys.stderr)
            return 1
        sign(dossier, args.gate, args.by)
    except (DossierError, WorkflowError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"gate {args.gate} of {args.id} signed by {args.by}")
    return 0


def _check_runtime(args: argparse.Namespace) -> int:
    url = args.url or os.environ.get("RUNTIME_URL", "http://127.0.0.1:8088")
    if HttpRuntimeClient(url).healthy():
        print(f"source_runtime at {url} is ready")
        return 0
    print(f"source_runtime at {url} is not ready", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scrapagents", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new-ingestion", help="create the design-time dossier of a source")
    new.add_argument("--id", required=True)
    new.add_argument("--team", required=True, choices=TEAMS)
    new.add_argument("--dataset", default="records")
    new.add_argument("--type", default="api", choices=SOURCE_TYPES)
    new.set_defaults(func=_new_ingestion)

    sub.add_parser("check-gates", help="verify human gates of every dossier").set_defaults(
        func=_check_gates
    )
    sub.add_parser(
        "check-contracts", help="validate configs/contracts and the dossier draft contracts"
    ).set_defaults(func=_check_contracts)

    gen = sub.add_parser(
        "generate-dags", help="generate declarative Airflow YAML DAGs from ingestion configs"
    )
    gen.add_argument(
        "--id", action="append", default=[], help="configs/ingestions entry or approved dossier"
    )
    gen.add_argument("--config", action="append", default=[], help="source config file path")
    gen.add_argument("--out", default=str(REPO_ROOT / "dags"))
    gen.add_argument("--check", action="store_true", help="fail if --out differs from the output")
    gen.set_defaults(func=_generate_dags)

    dbt = sub.add_parser("generate-dbt", help="generate dbt models and tests from data contracts")
    dbt.add_argument("--contract", action="append", default=[], help="contract file path")
    dbt.add_argument("--catalog", action="append", default=[], help="<source_system>/<dataset>")
    dbt.add_argument("--out", default=str(DBT_DIR))
    dbt.add_argument("--check", action="store_true", help="fail if --out differs from the output")
    dbt.set_defaults(func=_generate_dbt)

    bronze = sub.add_parser(
        "generate-bronze", help="generate typed bronze tables and the runtime registry"
    )
    bronze.add_argument("--contract", action="append", default=[], help="contract file path")
    bronze.add_argument("--catalog", action="append", default=[], help="<source_system>/<dataset>")
    bronze.add_argument("--out", default=str(BRONZE_DIR))
    bronze.add_argument("--check", action="store_true", help="fail if --out differs from output")
    bronze.set_defaults(func=_generate_bronze)

    probe_cmd = sub.add_parser("probe", help="stealth probe of URLs; evidence goes to discovery.md")
    probe_cmd.add_argument("--id", required=True)
    probe_cmd.add_argument("--url", action="append", required=True)
    probe_cmd.add_argument("--no-robots", action="store_true", help="skip robots.txt")
    probe_cmd.add_argument("--dry-run", action="store_true", help="print, do not write")
    probe_cmd.add_argument("--timeout", type=float, default=30.0)
    probe_cmd.set_defaults(func=_probe)

    state = sub.add_parser("status", help="phase, missing evidence and pending human gate")
    state.add_argument("--id", required=True)
    state.set_defaults(func=_status)

    adv = sub.add_parser("advance", help="next phase, only if evidence is complete and signed")
    adv.add_argument("--id", required=True)
    adv.set_defaults(func=_advance)

    rev = sub.add_parser("review", help="mechanical architecture review into review.md")
    rev.add_argument("--id", required=True)
    rev.set_defaults(func=_review)

    sig = sub.add_parser("sign", help="HUMAN ONLY: record the approval of a gate")
    sig.add_argument("--id", required=True)
    sig.add_argument("--gate", required=True, choices=("h1", "h2", "pr"))
    sig.add_argument("--by", required=True, help="your own name")
    sig.set_defaults(func=_sign)

    ready = sub.add_parser("check-runtime", help="exit 0 when source_runtime answers /healthz")
    ready.add_argument("--url", help="default: $RUNTIME_URL or http://127.0.0.1:8088")
    ready.set_defaults(func=_check_runtime)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
