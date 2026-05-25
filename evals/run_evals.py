"""Eval runner — run all or specific eval suites for the Kitchen Layout Visualizer.

Usage (CI-safe, no LLM calls):
    python -m evals.run_evals --suite all --no-live

Usage (live, requires RUN_LIVE_LLM_EVALS=1):
    RUN_LIVE_LLM_EVALS=1 python -m evals.run_evals --suite all --include-live

print() is allowed in this module per project coding rules (eval runner CLI).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Load .env from repo root so ANTHROPIC_API_KEY is available for live evals.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
except ImportError:
    pass

from evals.evaluators.agent1_evaluator import Agent1Evaluator
from evals.evaluators.agent2_evaluator import Agent2Evaluator
from evals.evaluators.agent3_evaluator import Agent3Evaluator
from evals.evaluators.cost_evaluator import CostEvaluator
from evals.evaluators.e2e_evaluator import E2EEvaluator
from evals.evaluators.guardrail_evaluator import GuardrailEvaluator
from evals.evaluators.prompt_registry_evaluator import PromptRegistryEvaluator
from evals.evaluators.regression_evaluator import RegressionEvaluator
from evals.evaluators.routing_evaluator import RoutingEvaluator
from evals.metrics.collector import EvalMetrics, ResultStore
from evals.metrics.reporter import EvalReporter

DEFAULT_OUTPUT_DIR: str = "eval_results"

ALL_SUITES: list[str] = [
    "agent1",
    "agent2",
    "agent3",
    "e2e",
    "guardrails",
    "prompt_registry",
    "routing",
    "cost",
]

# Suites that support a live mode (RUN_LIVE_LLM_EVALS=1 + --include-live required)
_LIVE_CAPABLE: frozenset[str] = frozenset({"agent1", "agent2", "agent3", "e2e"})


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run_evals",
        description="Run LLMOps eval suites.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Suites: all, agent1, agent2, agent3, e2e, "
            "guardrails, prompt_registry, routing, cost\n\n"
            "Default safe command (no LLM calls):\n"
            "  python -m evals.run_evals --suite all --no-live\n\n"
            "Live command (requires RUN_LIVE_LLM_EVALS=1):\n"
            "  RUN_LIVE_LLM_EVALS=1 python -m evals.run_evals --suite all --include-live"
        ),
    )
    parser.add_argument(
        "--suite",
        default="all",
        metavar="SUITE[,SUITE...]",
        help="Comma-separated suite names or 'all' (default: all).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--no-live",
        action="store_true",
        default=False,
        help="Skip live evals (default behaviour).",
    )
    group.add_argument(
        "--include-live",
        action="store_true",
        default=False,
        help="Run live LLM evals when RUN_LIVE_LLM_EVALS=1 is set.",
    )
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        default=False,
        help="Save current results as the new regression baseline.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=f"Directory for result JSON files (default: {DEFAULT_OUTPUT_DIR}).",
    )
    return parser


def _run_default(suite_name: str, store: ResultStore, results: list[EvalMetrics]) -> None:
    """Run the default (CI-safe) eval for one suite and persist it."""
    m: EvalMetrics
    if suite_name == "agent1":
        m = Agent1Evaluator().run_default()
    elif suite_name == "agent2":
        m = Agent2Evaluator().run_default()
    elif suite_name == "agent3":
        m = Agent3Evaluator().run_default()
    elif suite_name == "e2e":
        m = E2EEvaluator().run_default()
    elif suite_name == "guardrails":
        m = GuardrailEvaluator().run_default()
    elif suite_name == "prompt_registry":
        m = PromptRegistryEvaluator().run_default()
    elif suite_name == "routing":
        m = RoutingEvaluator().run_default()
    elif suite_name == "cost":
        m = CostEvaluator().run_default()
    else:
        print(f"  [WARN] Unknown suite '{suite_name}', skipping.")
        return
    results.append(m)
    store.save(m)


def _run_live(suite_name: str, store: ResultStore, results: list[EvalMetrics]) -> None:
    """Run the live eval for one suite. Only called when --include-live is active."""
    if suite_name not in _LIVE_CAPABLE:
        return
    lm: EvalMetrics
    try:
        if suite_name == "agent1":
            lm = Agent1Evaluator().run_live()
        elif suite_name == "agent2":
            lm = Agent2Evaluator().run_live()
        elif suite_name == "agent3":
            lm = Agent3Evaluator().run_live()
        elif suite_name == "e2e":
            lm = E2EEvaluator().run_live()
        else:
            return
        results.append(lm)
        store.save(lm)
    except RuntimeError as exc:
        print(f"  [SKIP] {suite_name} live: {exc}")
    except Exception as exc:
        print(f"  [ERROR] {suite_name} live raised: {exc}")


def main() -> int:
    """CLI entry point. Returns 0 on full pass, 1 on any failure or regression."""
    parser = _build_argparser()
    args = parser.parse_args()

    include_live = args.include_live and os.getenv("RUN_LIVE_LLM_EVALS") == "1"
    if args.include_live and not include_live:
        print("[WARN] --include-live passed but RUN_LIVE_LLM_EVALS!=1; live evals skipped.")

    if args.suite == "all":
        suites = list(ALL_SUITES)
    else:
        suites = [s.strip() for s in args.suite.split(",") if s.strip()]

    invalid = [s for s in suites if s not in ALL_SUITES]
    if invalid:
        print(f"[ERROR] Unknown suite(s): {invalid}")
        print(f"Valid suites: {ALL_SUITES}")
        return 2

    store = ResultStore(args.output_dir)
    baseline = store.load_baseline()
    all_results: list[EvalMetrics] = []

    live_tag = " + live" if include_live else ""
    print(f"\nRunning {len(suites)} suite(s){live_tag}: {', '.join(suites)}")

    t_start = time.monotonic()
    for suite_name in suites:
        print(f"  {suite_name} (default)...", end="", flush=True)
        try:
            _run_default(suite_name, store, all_results)
            last = all_results[-1] if all_results else None
            status = "PASS" if (last and last.passed) else "FAIL"
            print(f" {status}")
        except Exception as exc:
            print(f" ERROR: {exc}")

        if include_live and suite_name in _LIVE_CAPABLE:
            print(f"  {suite_name} (live)...", end="", flush=True)
            _run_live(suite_name, store, all_results)
            last = all_results[-1] if all_results else None
            print(f" done" if last else " skipped")

    elapsed_ms = (time.monotonic() - t_start) * 1000
    print(f"\nCompleted in {elapsed_ms:.0f} ms")

    # Regression comparison
    reg_report = RegressionEvaluator().run(all_results, baseline)

    # Human-readable report
    EvalReporter().print_report(all_results, reg_report)

    # JSON report
    report_path = f"{args.output_dir}/latest_report.json"
    EvalReporter().write_json_report(all_results, report_path)
    print(f"JSON report written to {report_path}")

    # Save baseline
    if args.save_baseline:
        store.save_baseline(all_results)
        print(f"Baseline saved to {args.output_dir}/baseline.json")

    # Exit code
    all_passed = all(m.passed for m in all_results)
    if not all_passed or reg_report.has_regression:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
