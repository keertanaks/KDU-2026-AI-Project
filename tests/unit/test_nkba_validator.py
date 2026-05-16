"""Unit tests for NKBAValidator — pure math, no API calls."""
from __future__ import annotations

import pytest


class TestScoreFormula:
    """Score formula: 1.0 + (passed/total)*0.30 - spillover*0.05 - adjacency*0.05 - rule_weights."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from pipeline.nkba_validator import NKBAValidator
        self.validator = NKBAValidator()

    def test_perfect_score(self):
        score = self.validator._compute_score(31, 31, 0, 0, [])
        assert score == pytest.approx(1.30, abs=0.001)

    def test_zero_rules_passed(self):
        score = self.validator._compute_score(0, 31, 0, 0, [])
        assert score == pytest.approx(1.0, abs=0.001)

    def test_spillover_penalty(self):
        base = self.validator._compute_score(31, 31, 0, 0, [])
        with_spill = self.validator._compute_score(31, 31, 1, 0, [])
        assert base - with_spill == pytest.approx(0.05, abs=0.001)

    def test_workflow03_violation_penalty(self):
        score = self.validator._compute_score(31, 31, 0, 0, ["WORKFLOW-03"])
        assert score == pytest.approx(1.30 - 0.15, abs=0.001)

    def test_nkba_cl01_violation_penalty(self):
        score = self.validator._compute_score(31, 31, 0, 0, ["NKBA-CL-01"])
        assert score == pytest.approx(1.30 - 0.10, abs=0.001)

    def test_score_clamped_to_zero(self):
        score = self.validator._compute_score(0, 31, 10, 10, ["WORKFLOW-03", "NKBA-CL-01"])
        assert score >= 0.0

    def test_score_clamped_to_max(self):
        score = self.validator._compute_score(31, 31, 0, 0, [])
        assert score <= 1.30


class TestWorkTriangle:
    """WORKFLOW-03: perimeter must be 3962–6600mm."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from pipeline.nkba_validator import NKBAValidator
        self.validator = NKBAValidator()

    def test_perimeter_at_minimum_passes(self):
        violations = self.validator._check_work_triangle_perimeter(3962)
        assert violations == []

    def test_perimeter_below_minimum_fails(self):
        violations = self.validator._check_work_triangle_perimeter(3000)
        assert any(v["rule_id"] == "WORKFLOW-03" for v in violations)

    def test_perimeter_at_maximum_passes(self):
        violations = self.validator._check_work_triangle_perimeter(6600)
        assert violations == []

    def test_perimeter_above_maximum_fails(self):
        violations = self.validator._check_work_triangle_perimeter(7000)
        assert any(v["rule_id"] == "WORKFLOW-03" for v in violations)

    def test_old_wrong_minimum_3600_would_fail(self):
        """Guard against regression — 3600mm is NOT the minimum (design doc was wrong)."""
        violations = self.validator._check_work_triangle_perimeter(3800)
        assert any(v["rule_id"] == "WORKFLOW-03" for v in violations), (
            "3800mm is below NKBA minimum 3962mm — must be a violation"
        )


class TestModelSelector:
    """Model selection — Opus used only for retry escalation."""

    def test_prompt_parser_uses_haiku(self):
        from utils.model_selector import for_agent, Models
        assert for_agent("prompt_parser") == Models.HAIKU

    def test_layout_strategist_uses_sonnet(self):
        from utils.model_selector import for_agent, Models
        assert for_agent("layout_strategist") == Models.SONNET

    def test_layout_strategist_retry_uses_opus(self):
        from utils.model_selector import for_agent, Models
        assert for_agent("layout_strategist", is_retry=True) == Models.OPUS

    def test_catalog_selector_retry_still_haiku(self):
        """Catalog selector never escalates to Opus — only layout_strategist does."""
        from utils.model_selector import for_agent, Models
        assert for_agent("catalog_selector", is_retry=True) == Models.HAIKU

    def test_should_use_opus_on_low_score(self):
        from utils.model_selector import should_use_opus
        assert should_use_opus(0.50, []) is True

    def test_should_use_opus_on_workflow03(self):
        from utils.model_selector import should_use_opus
        assert should_use_opus(0.75, ["WORKFLOW-03"]) is True

    def test_no_opus_on_good_score(self):
        from utils.model_selector import should_use_opus
        assert should_use_opus(0.85, ["LAYOUT-03"]) is False

    def test_unknown_agent_raises(self):
        from utils.model_selector import for_agent
        with pytest.raises(ValueError, match="Unknown agent"):
            for_agent("nonexistent_agent")
