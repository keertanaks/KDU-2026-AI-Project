"""Prompt registry evaluator — verify all versioned prompts load correctly.

Default mode only (registry reads local files, no LLM calls).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

import logging

from evals.metrics.collector import EvalMetrics
from llmops.prompt_registry import PromptRegistry

_log = logging.getLogger(__name__)

REGISTRY_LOAD_THRESHOLD: float = 1.0
METADATA_COMPLETE_THRESHOLD: float = 1.0
PROMPTS_NON_EMPTY_THRESHOLD: float = 1.0

KNOWN_AGENTS: list[str] = ["agent1", "agent2", "agent3"]
REQUIRED_METADATA_KEYS: frozenset[str] = frozenset({"version", "agent", "model", "created", "description"})


class PromptRegistryEvaluator:
    """Evaluate PromptRegistry correctness and prompt completeness."""

    def run_default(self) -> EvalMetrics:
        """Run registry checks against local prompt files. No LLM calls."""
        start = time.monotonic()
        failures: list[str] = []
        suite_name = "prompt_registry"
        eval_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        registry = PromptRegistry()
        load_results: list[bool] = []
        metadata_results: list[bool] = []
        non_empty_results: list[bool] = []

        for agent_name in KNOWN_AGENTS:
            # Check that at least one version exists
            versions = registry.list_versions(agent_name)
            if not versions:
                load_results.append(False)
                metadata_results.append(False)
                non_empty_results.append(False)
                failures.append(f"{agent_name}: no prompt versions found")
                continue

            # Load latest version
            try:
                prompt_text, metadata = registry.load(agent_name)
                load_results.append(True)
            except Exception as exc:
                load_results.append(False)
                metadata_results.append(False)
                non_empty_results.append(False)
                failures.append(f"{agent_name}: load() raised {exc}")
                continue

            # Metadata completeness
            missing_keys = [k for k in REQUIRED_METADATA_KEYS if k not in metadata]
            metadata_ok = len(missing_keys) == 0
            metadata_results.append(metadata_ok)
            if not metadata_ok:
                failures.append(f"{agent_name}: metadata missing keys {missing_keys}")

            # Prompt non-empty
            non_empty_ok = bool(prompt_text and prompt_text.strip())
            non_empty_results.append(non_empty_ok)
            if not non_empty_ok:
                failures.append(f"{agent_name}: prompt text is empty")

        registry_load_rate = sum(load_results) / len(load_results) if load_results else 0.0
        metadata_complete_rate = (
            sum(metadata_results) / len(metadata_results) if metadata_results else 0.0
        )
        prompts_non_empty_rate = (
            sum(non_empty_results) / len(non_empty_results) if non_empty_results else 0.0
        )

        # Also verify get_hash() is deterministic
        hash_ok = self._check_hashes_deterministic(registry, failures)

        if registry_load_rate < REGISTRY_LOAD_THRESHOLD:
            failures.append(
                f"registry_load_rate={registry_load_rate:.2f} < {REGISTRY_LOAD_THRESHOLD}"
            )
        if metadata_complete_rate < METADATA_COMPLETE_THRESHOLD:
            failures.append(
                f"metadata_complete_rate={metadata_complete_rate:.2f} < {METADATA_COMPLETE_THRESHOLD}"
            )
        if prompts_non_empty_rate < PROMPTS_NON_EMPTY_THRESHOLD:
            failures.append(
                f"prompts_non_empty_rate={prompts_non_empty_rate:.2f} < {PROMPTS_NON_EMPTY_THRESHOLD}"
            )

        passed = (
            registry_load_rate >= REGISTRY_LOAD_THRESHOLD
            and metadata_complete_rate >= METADATA_COMPLETE_THRESHOLD
            and prompts_non_empty_rate >= PROMPTS_NON_EMPTY_THRESHOLD
            and hash_ok
        )

        return EvalMetrics(
            eval_id=eval_id,
            suite_name=suite_name,
            is_live=False,
            timestamp=timestamp,
            passed=passed,
            metrics={
                "registry_load_rate": registry_load_rate,
                "metadata_complete_rate": metadata_complete_rate,
                "prompts_non_empty_rate": prompts_non_empty_rate,
                "hash_deterministic_ok": 1.0 if hash_ok else 0.0,
            },
            failures=failures,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    @staticmethod
    def _check_hashes_deterministic(
        registry: PromptRegistry, failures: list[str]
    ) -> bool:
        """Verify that get_hash() is stable across two calls for each agent."""
        ok = True
        for agent_name in KNOWN_AGENTS:
            try:
                h1 = registry.get_hash(agent_name)
                h2 = registry.get_hash(agent_name)
                if h1 != h2:
                    failures.append(f"{agent_name}: get_hash() is not deterministic")
                    ok = False
                if len(h1) != 64:
                    failures.append(f"{agent_name}: get_hash() length {len(h1)} != 64 (SHA256 hex)")
                    ok = False
            except Exception as exc:
                failures.append(f"{agent_name}: get_hash() raised {exc}")
                ok = False
        return ok
