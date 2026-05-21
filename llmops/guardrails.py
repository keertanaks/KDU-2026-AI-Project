"""Guardrails — validate input JSON, semantic hints, and output JSON.

Importing agents.layout_strategist would pull in the anthropic package which
can have import-time side effects on some CI environments. We therefore use
a local static copy of VALID_TERM_PATTERNS to keep this module CI-safe.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

import logging

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local copy of semantic vocabulary patterns — kept here for CI safety.
# The canonical source is agents.layout_strategist.VALID_TERM_PATTERNS.
# Keep in sync if the agent vocabulary changes.
# ---------------------------------------------------------------------------
_VALID_TERM_PATTERNS: list[str] = [
    r"at north-west corner",
    r"at north-east corner",
    r"at south-west corner",
    r"at south-east corner",
    r"near \w+ window",
    r"centre of \w+",
    r"left end of \w+",
    r"right end of \w+",
    r"next to [\w\s]+",
    r"above [\w\s]+",
    r"leave gap before [\w\s]+",
]

VALID_BUDGET_TIERS: frozenset[str] = frozenset({"low", "mid", "high", "premium"})
MIN_WALL_LENGTH_MM: float = 1000.0
MIN_WALL_LENGTH_WARNING_MM: float = 1000.0

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class GuardrailViolation:
    """Single guardrail rule violation."""

    def __init__(
        self,
        rule_id: str,
        severity: Literal["error", "warning"],
        field: str,
        message: str,
        actual_value: Any = None,
    ) -> None:
        self.rule_id = rule_id
        self.severity = severity
        self.field = field
        self.message = message
        self.actual_value = actual_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
            "actual_value": self.actual_value,
        }


class GuardrailResult:
    """Aggregated result of one guardrail pass."""

    def __init__(self, passed: bool, violations: list[GuardrailViolation]) -> None:
        self.passed = passed
        self.violations = violations
        self.checked_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# InputGuardrail
# ---------------------------------------------------------------------------


class InputGuardrail:
    """Validate kitchen input JSON before sending to the pipeline."""

    def validate(self, input_json: dict[str, Any]) -> GuardrailResult:
        violations: list[GuardrailViolation] = []
        env = input_json.get("environment", {}) if isinstance(input_json, dict) else {}
        walls = env.get("wall", []) if isinstance(env, dict) else []
        prefs = input_json.get("preferences", {}) if isinstance(input_json, dict) else {}

        # GUARD-IN-01: environment.wall is a non-empty list
        if not isinstance(walls, list) or len(walls) == 0:
            violations.append(GuardrailViolation(
                "GUARD-IN-01", "error", "environment.wall",
                "environment.wall must be a non-empty list",
                actual_value=walls,
            ))

        # GUARD-IN-02 & IN-06 & IN-07: per-wall checks
        has_any_cabinet_wall = False
        for wall in (walls if isinstance(walls, list) else []):
            if not isinstance(wall, dict):
                continue
            w_name = wall.get("name", "<unnamed>")
            dims = wall.get("dimensions", {}) or {}
            length_mm = dims.get("length_mm")
            has_cabs = wall.get("has_cabinets")

            if wall.get("name") is None or length_mm is None or has_cabs is None:
                violations.append(GuardrailViolation(
                    "GUARD-IN-02", "error", f"wall[{w_name}]",
                    f"Wall '{w_name}' missing required fields: name, dimensions.length_mm, has_cabinets",
                    actual_value=wall,
                ))
            else:
                if has_cabs:
                    has_any_cabinet_wall = True
                if isinstance(length_mm, (int, float)) and length_mm <= 0:
                    violations.append(GuardrailViolation(
                        "GUARD-IN-06", "error", f"wall[{w_name}].dimensions.length_mm",
                        f"Wall '{w_name}' has length_mm <= 0",
                        actual_value=length_mm,
                    ))
                elif isinstance(length_mm, (int, float)) and length_mm < MIN_WALL_LENGTH_WARNING_MM:
                    violations.append(GuardrailViolation(
                        "GUARD-IN-07", "warning", f"wall[{w_name}].dimensions.length_mm",
                        f"Wall '{w_name}' has length_mm={length_mm} < {MIN_WALL_LENGTH_WARNING_MM}mm (unusually short)",
                        actual_value=length_mm,
                    ))

        # GUARD-IN-03: at least one wall has has_cabinets=True
        if isinstance(walls, list) and len(walls) > 0 and not has_any_cabinet_wall:
            violations.append(GuardrailViolation(
                "GUARD-IN-03", "error", "environment.wall",
                "No wall has has_cabinets=True — cannot place any cabinets",
            ))

        # GUARD-IN-04: preferences.budget_tier
        budget_tier = prefs.get("budget_tier") if isinstance(prefs, dict) else None
        if budget_tier is not None and budget_tier not in VALID_BUDGET_TIERS:
            violations.append(GuardrailViolation(
                "GUARD-IN-04", "error", "preferences.budget_tier",
                f"budget_tier '{budget_tier}' must be one of {sorted(VALID_BUDGET_TIERS)}",
                actual_value=budget_tier,
            ))

        # GUARD-IN-05: preferences.prompt is a non-empty string
        prompt = prefs.get("prompt") if isinstance(prefs, dict) else None
        if not isinstance(prompt, str) or not prompt.strip():
            violations.append(GuardrailViolation(
                "GUARD-IN-05", "error", "preferences.prompt",
                "preferences.prompt must be a non-empty string",
                actual_value=prompt,
            ))

        errors = [v for v in violations if v.severity == "error"]
        return GuardrailResult(passed=len(errors) == 0, violations=violations)


# ---------------------------------------------------------------------------
# OutputGuardrail
# ---------------------------------------------------------------------------


class OutputGuardrail:
    """Validate pipeline output JSON before rendering."""

    def validate(self, output_json: dict[str, Any]) -> GuardrailResult:
        violations: list[GuardrailViolation] = []

        layouts = output_json.get("layouts") if isinstance(output_json, dict) else None

        # GUARD-OUT-01: layouts is a non-empty list
        if not isinstance(layouts, list) or len(layouts) == 0:
            violations.append(GuardrailViolation(
                "GUARD-OUT-01", "error", "layouts",
                "layouts must be a non-empty list",
                actual_value=type(layouts).__name__,
            ))
            return GuardrailResult(passed=False, violations=violations)

        any_above_threshold = False
        for variant in layouts:
            if not isinstance(variant, dict):
                continue
            v_id = variant.get("id", "<unknown>")
            score = variant.get("score")
            layout = variant.get("layout")

            # GUARD-OUT-02: each layout has id, score, layout
            missing = [f for f in ("id", "score", "layout") if f not in variant]
            if missing:
                violations.append(GuardrailViolation(
                    "GUARD-OUT-02", "error", f"layouts[{v_id}]",
                    f"Variant '{v_id}' missing required fields: {missing}",
                    actual_value=missing,
                ))
                continue

            if isinstance(score, (int, float)) and score >= 0.60:
                any_above_threshold = True

            if not isinstance(layout, dict):
                continue

            item_count = 0
            for item_key, item in layout.items():
                if not isinstance(item, dict):
                    continue
                if item.get("is_wall") or item.get("is_floor") or item.get("is_door") or item.get("is_window"):
                    continue
                item_count += 1
                pos = item.get("position_mm", {}) or {}

                # GUARD-OUT-03: position_mm has x, y, z
                if not all(k in pos for k in ("x", "y", "z")):
                    violations.append(GuardrailViolation(
                        "GUARD-OUT-03", "error", f"layouts[{v_id}].layout[{item_key}].position_mm",
                        f"Item '{item_key}' in variant '{v_id}' missing x/y/z in position_mm",
                        actual_value=pos,
                    ))

                # GUARD-OUT-04: product_id is non-empty
                product_id = item.get("product_id") or item.get("sku") or item.get("id") or item.get("item_id")
                if not product_id:
                    violations.append(GuardrailViolation(
                        "GUARD-OUT-04", "error", f"layouts[{v_id}].layout[{item_key}].product_id",
                        f"Item '{item_key}' in variant '{v_id}' has empty/missing product_id",
                        actual_value=product_id,
                    ))

                # GUARD-OUT-05: no z < 0
                z_val = pos.get("z")
                if isinstance(z_val, (int, float)) and z_val < 0:
                    violations.append(GuardrailViolation(
                        "GUARD-OUT-05", "warning", f"layouts[{v_id}].layout[{item_key}].position_mm.z",
                        f"Item '{item_key}' in variant '{v_id}' has z < 0 ({z_val})",
                        actual_value=z_val,
                    ))

            # GUARD-OUT-07: at least 5 placed items
            if item_count < 5:
                violations.append(GuardrailViolation(
                    "GUARD-OUT-07", "warning", f"layouts[{v_id}].layout",
                    f"Variant '{v_id}' has only {item_count} placed items (expected >= 5)",
                    actual_value=item_count,
                ))

        # GUARD-OUT-06: at least one layout has score >= 0.60
        if not any_above_threshold:
            violations.append(GuardrailViolation(
                "GUARD-OUT-06", "error", "layouts[*].score",
                "No layout has score >= 0.60",
            ))

        errors = [v for v in violations if v.severity == "error"]
        return GuardrailResult(passed=len(errors) == 0, violations=violations)


# ---------------------------------------------------------------------------
# SemanticGuardrail
# ---------------------------------------------------------------------------


class SemanticGuardrail:
    """Validate Agent 3 item_hints semantic vocabulary."""

    def validate(self, item_hints: dict[str, str]) -> GuardrailResult:
        """Validate flat item_hints dict (item_name -> position_string)."""
        violations: list[GuardrailViolation] = []

        if not isinstance(item_hints, dict):
            violations.append(GuardrailViolation(
                "GUARD-SEM-01", "error", "item_hints",
                "item_hints must be a dict",
                actual_value=type(item_hints).__name__,
            ))
            return GuardrailResult(passed=False, violations=violations)

        # GUARD-SEM-01: each hint value matches a valid semantic pattern
        for item_name, position in item_hints.items():
            if not isinstance(position, str):
                continue
            if not self._is_valid_term(position):
                violations.append(GuardrailViolation(
                    "GUARD-SEM-01", "error", f"item_hints[{item_name}]",
                    f"Invalid semantic term '{position}' for item '{item_name}'",
                    actual_value=position,
                ))

        # GUARD-SEM-02: no two items have identical position terms on same wall
        wall_position_counts: dict[str, int] = {}
        for position in item_hints.values():
            if isinstance(position, str):
                wall_position_counts[position] = wall_position_counts.get(position, 0) + 1
        for pos, count in wall_position_counts.items():
            if count > 1:
                violations.append(GuardrailViolation(
                    "GUARD-SEM-02", "warning", "item_hints",
                    f"Position term '{pos}' used by {count} items",
                    actual_value=pos,
                ))

        # GUARD-SEM-03: stove and fridge should not be on the same wall
        # For flat hints (position string only), check if both contain same wall name
        fridge_pos = item_hints.get("fridge") or item_hints.get("fridge_1") or ""
        stove_pos = item_hints.get("stove") or item_hints.get("stove_1") or ""
        if fridge_pos and stove_pos:
            fridge_wall = self._extract_wall(fridge_pos)
            stove_wall = self._extract_wall(stove_pos)
            if fridge_wall and stove_wall and fridge_wall == stove_wall:
                violations.append(GuardrailViolation(
                    "GUARD-SEM-03", "warning", "item_hints",
                    f"Stove and fridge appear to share wall '{fridge_wall}'",
                    actual_value={"fridge": fridge_pos, "stove": stove_pos},
                ))

        errors = [v for v in violations if v.severity == "error"]
        return GuardrailResult(passed=len(errors) == 0, violations=violations)

    @staticmethod
    def _is_valid_term(term: str) -> bool:
        return any(
            re.fullmatch(pattern, term, re.IGNORECASE)
            for pattern in _VALID_TERM_PATTERNS
        )

    @staticmethod
    def _extract_wall(position: str) -> str | None:
        """Try to extract wall name from a position string like 'left end of north_wall'."""
        m = re.search(r"\b(\w+_wall)\b", position)
        return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def run_all_guardrails(
    input_json: dict[str, Any] | None = None,
    item_hints: dict[str, str] | None = None,
    output_json: dict[str, Any] | None = None,
) -> dict[str, GuardrailResult]:
    """Run all applicable guardrails and return results keyed by name.

    Skips any guardrail whose corresponding argument is None.
    Returns dict with keys: "input", "semantic", "output".
    """
    results: dict[str, GuardrailResult] = {}

    if input_json is not None:
        results["input"] = InputGuardrail().validate(input_json)

    if item_hints is not None:
        results["semantic"] = SemanticGuardrail().validate(item_hints)

    if output_json is not None:
        results["output"] = OutputGuardrail().validate(output_json)

    return results
