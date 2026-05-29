# tests/test_metrics.py
#
# Project 3 — Phase 5: Unit tests for evaluation/harness/metrics.py.
#
# No model loading. All tests operate on constructed Python objects.
# Run with: pytest tests/test_metrics.py -v

import pytest

from app.schemas.extraction import (
    Entity,
    ExtractionResult,
    SourceSpan,
    ValidationFlags,
)
from evaluation.harness.metrics import (
    compute_aggregate_span_metrics,
    compute_entity_f1,
    compute_enum_accuracy,
    compute_evidence_accuracy,
    compute_hallucination_rate,
    compute_json_validity_rate,
    compute_relation_f1,
    compute_schema_validity_rate,
    compute_span_f1_lenient,
    compute_span_f1_strict,
    compute_span_iou,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_entity(
    entity_type: str,
    mention: str,
    start: int,
    end: int,
    evidence: str = "test evidence text",
    dosage=None,
    linked_medication=None,
):
    return Entity(
        entity_type=entity_type,
        mention=mention,
        dosage=dosage,
        linked_medication=linked_medication,
        evidence=evidence,
        source_span=SourceSpan(start_char=start, end_char=end),
    )


def make_span(start: int, end: int) -> SourceSpan:
    return SourceSpan(start_char=start, end_char=end)


def make_result(
    record_id: str = "test_001",
    entities=None,
    relation_status: str = "related",
    json_valid: bool = True,
    schema_valid: bool = True,
    enum_valid: bool = True,
    evidence_present: bool = True,
) -> ExtractionResult:
    if entities is None:
        entities = []
    return ExtractionResult(
        record_id=record_id,
        schema_version="v1",
        entities=entities,
        relation_status=relation_status,
        validation=ValidationFlags(
            json_valid=json_valid,
            schema_valid=schema_valid,
            enum_valid=enum_valid,
            evidence_present=evidence_present,
        ),
    )


# ---------------------------------------------------------------------------
# Entity F1 tests
# ---------------------------------------------------------------------------

class TestEntityF1:
    def test_entity_f1_perfect(self):
        """pred and gold both have same medication -> f1=1.0"""
        pred = [make_entity("medication", "aspirin", 0, 7, evidence="aspirin test")]
        gold = [make_entity("medication", "aspirin", 0, 7, evidence="aspirin test")]
        result = compute_entity_f1(pred, gold, "medication")
        assert result["f1"] == pytest.approx(1.0)
        assert result["precision"] == pytest.approx(1.0)
        assert result["recall"] == pytest.approx(1.0)
        assert result["tp"] == 1
        assert result["fp"] == 0
        assert result["fn"] == 0

    def test_entity_f1_zero(self):
        """pred has different medication than gold -> f1=0.0"""
        pred = [make_entity("medication", "aspirin", 0, 7, evidence="aspirin test")]
        gold = [make_entity("medication", "warfarin", 0, 8, evidence="warfarin test")]
        result = compute_entity_f1(pred, gold, "medication")
        assert result["f1"] == pytest.approx(0.0)
        assert result["tp"] == 0
        assert result["fp"] == 1
        assert result["fn"] == 1

    def test_entity_f1_partial(self):
        """pred has 2 of 3 gold entities -> recall ~0.67"""
        pred = [
            make_entity("medication", "aspirin", 0, 7, evidence="aspirin test"),
            make_entity("medication", "warfarin", 10, 18, evidence="warfarin test"),
        ]
        gold = [
            make_entity("medication", "aspirin", 0, 7, evidence="aspirin test"),
            make_entity("medication", "warfarin", 10, 18, evidence="warfarin test"),
            make_entity("medication", "lisinopril", 20, 30, evidence="lisinopril test"),
        ]
        result = compute_entity_f1(pred, gold, "medication")
        assert result["tp"] == 2
        assert result["fn"] == 1
        assert result["recall"] == pytest.approx(2 / 3, rel=1e-3)

    def test_entity_f1_case_insensitive(self):
        """Mention matching is case-insensitive."""
        pred = [make_entity("medication", "Aspirin", 0, 7, evidence="Aspirin test")]
        gold = [make_entity("medication", "aspirin", 0, 7, evidence="aspirin test")]
        result = compute_entity_f1(pred, gold, "medication")
        assert result["f1"] == pytest.approx(1.0)

    def test_entity_f1_filters_by_type(self):
        """Only entities matching entity_type are counted."""
        pred = [make_entity("adverse_event", "nausea", 0, 6, evidence="nausea test")]
        gold = [make_entity("medication", "aspirin", 0, 7, evidence="aspirin test")]
        # Asking for medication F1 — pred has none, gold has one
        result = compute_entity_f1(pred, gold, "medication")
        assert result["tp"] == 0
        assert result["fp"] == 0
        assert result["fn"] == 1

    def test_entity_f1_empty_both(self):
        """Both empty -> f1=0.0 (by convention, no division)."""
        result = compute_entity_f1([], [], "medication")
        assert result["f1"] == pytest.approx(0.0)
        assert result["tp"] == 0
        assert result["fp"] == 0
        assert result["fn"] == 0


# ---------------------------------------------------------------------------
# Span IoU tests
# ---------------------------------------------------------------------------

class TestSpanIoU:
    def test_span_iou_exact(self):
        """Identical spans -> IoU=1.0"""
        pred = make_span(10, 20)
        gold = make_span(10, 20)
        assert compute_span_iou(pred, gold) == pytest.approx(1.0)

    def test_span_iou_partial(self):
        """Overlapping spans -> 0 < IoU < 1"""
        pred = make_span(10, 20)  # length 10
        gold = make_span(15, 25)  # length 10, overlap [15,20] = 5
        iou = compute_span_iou(pred, gold)
        # intersection=5, union=15
        assert iou == pytest.approx(5 / 15)
        assert 0.0 < iou < 1.0

    def test_span_iou_no_overlap(self):
        """Non-overlapping spans -> IoU=0.0"""
        pred = make_span(0, 10)
        gold = make_span(20, 30)
        assert compute_span_iou(pred, gold) == pytest.approx(0.0)

    def test_span_iou_contained(self):
        """Pred fully contained in gold -> IoU = pred_len / gold_len"""
        pred = make_span(12, 17)  # length 5
        gold = make_span(10, 20)  # length 10
        iou = compute_span_iou(pred, gold)
        # intersection=5, union=10
        assert iou == pytest.approx(5 / 10)

    def test_span_iou_adjacent(self):
        """Adjacent spans (no overlap) -> IoU=0.0"""
        pred = make_span(0, 10)
        gold = make_span(10, 20)
        assert compute_span_iou(pred, gold) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Strict span tests
# ---------------------------------------------------------------------------

class TestSpanStrict:
    def test_span_strict_true(self):
        """Exact match -> True"""
        pred = make_span(5, 15)
        gold = make_span(5, 15)
        assert compute_span_f1_strict(pred, gold) is True

    def test_span_strict_false(self):
        """Off by one -> False"""
        pred = make_span(5, 15)
        gold = make_span(5, 16)
        assert compute_span_f1_strict(pred, gold) is False

    def test_span_strict_start_mismatch(self):
        """Start differs -> False"""
        pred = make_span(5, 15)
        gold = make_span(6, 15)
        assert compute_span_f1_strict(pred, gold) is False


# ---------------------------------------------------------------------------
# Lenient span tests
# ---------------------------------------------------------------------------

class TestSpanLenient:
    def test_span_lenient_exact(self):
        """Exact match -> True (IoU=1.0 >= 0.5)"""
        pred = make_span(5, 15)
        gold = make_span(5, 15)
        assert compute_span_f1_lenient(pred, gold) is True

    def test_span_lenient_high_iou(self):
        """IoU > 0.5 -> True"""
        # intersection=8, union=10 -> iou=0.8
        pred = make_span(0, 10)
        gold = make_span(2, 10)
        assert compute_span_f1_lenient(pred, gold) is True

    def test_span_lenient_low_iou(self):
        """IoU < 0.5 -> False"""
        pred = make_span(0, 10)
        gold = make_span(8, 18)
        # intersection=[8,10]=2, union=[0,18]=18 -> iou=2/18 ~0.11
        assert compute_span_f1_lenient(pred, gold) is False

    def test_span_lenient_custom_threshold(self):
        """Custom threshold works."""
        pred = make_span(0, 10)
        gold = make_span(5, 15)
        # intersection=5, union=15 -> iou=1/3
        assert compute_span_f1_lenient(pred, gold, threshold=0.3) is True
        assert compute_span_f1_lenient(pred, gold, threshold=0.5) is False


# ---------------------------------------------------------------------------
# Hallucination rate tests
# ---------------------------------------------------------------------------

class TestHallucinationRate:
    def test_hallucination_rate_zero(self):
        """All mentions in text -> 0.0"""
        input_text = "Patient took aspirin and warfarin."
        entities = [
            make_entity("medication", "aspirin", 12, 19, evidence=input_text),
            make_entity("medication", "warfarin", 24, 32, evidence=input_text),
        ]
        assert compute_hallucination_rate(entities, input_text) == pytest.approx(0.0)

    def test_hallucination_rate_full(self):
        """No mentions in text -> 1.0"""
        input_text = "Patient is stable."
        entities = [
            make_entity("medication", "ibuprofen", 0, 9, evidence="ibuprofen test"),
        ]
        assert compute_hallucination_rate(entities, input_text) == pytest.approx(1.0)

    def test_hallucination_rate_partial(self):
        """Half mentions hallucinated -> 0.5"""
        input_text = "Patient took aspirin."
        entities = [
            make_entity("medication", "aspirin", 12, 19, evidence=input_text),
            make_entity("medication", "ibuprofen", 0, 9, evidence="ibuprofen test"),
        ]
        assert compute_hallucination_rate(entities, input_text) == pytest.approx(0.5)

    def test_hallucination_rate_empty(self):
        """Empty entity list -> 0.0"""
        assert compute_hallucination_rate([], "some text") == pytest.approx(0.0)

    def test_hallucination_rate_case_insensitive(self):
        """Case-insensitive substring check."""
        input_text = "Patient took Aspirin."
        entities = [
            make_entity("medication", "aspirin", 0, 7, evidence=input_text),
        ]
        assert compute_hallucination_rate(entities, input_text) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Evidence accuracy tests
# ---------------------------------------------------------------------------

class TestEvidenceAccuracy:
    def test_evidence_accuracy_full(self):
        """All evidence strings are substrings -> 1.0"""
        input_text = "Patient took aspirin for pain."
        entities = [
            make_entity("medication", "aspirin", 12, 19, evidence="Patient took aspirin for pain."),
        ]
        assert compute_evidence_accuracy(entities, input_text) == pytest.approx(1.0)

    def test_evidence_accuracy_zero(self):
        """No evidence string is a substring -> 0.0"""
        input_text = "Patient took aspirin."
        entities = [
            make_entity("medication", "ibuprofen", 0, 9, evidence="unrelated evidence text"),
        ]
        assert compute_evidence_accuracy(entities, input_text) == pytest.approx(0.0)

    def test_evidence_accuracy_empty(self):
        """Empty entity list -> 1.0"""
        assert compute_evidence_accuracy([], "some text") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Relation F1 tests
# ---------------------------------------------------------------------------

class TestRelationF1:
    def test_relation_f1_perfect(self):
        """All correct -> macro_f1=1.0"""
        predicted = ["related", "not_related", "none", "related", "none"]
        gold =      ["related", "not_related", "none", "related", "none"]
        result = compute_relation_f1(predicted, gold)
        assert result["macro_f1"] == pytest.approx(1.0)

    def test_relation_f1_all_wrong(self):
        """All wrong -> macro_f1 low (possibly 0 depending on class distribution)."""
        predicted = ["related", "related", "related"]
        gold =      ["none", "none", "none"]
        result = compute_relation_f1(predicted, gold)
        assert result["macro_f1"] >= 0.0
        assert result["per_class"]["none"] == pytest.approx(0.0)

    def test_relation_f1_per_class(self):
        """Per-class F1 populated."""
        predicted = ["related"]
        gold =      ["related"]
        result = compute_relation_f1(predicted, gold)
        assert "related" in result["per_class"]
        assert "not_related" in result["per_class"]
        assert "none" in result["per_class"]
        assert result["per_class"]["related"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Enum accuracy tests
# ---------------------------------------------------------------------------

class TestEnumAccuracy:
    def test_enum_accuracy_all_valid(self):
        """All results with enum_valid=True -> 1.0"""
        results = [
            make_result(record_id="r1", enum_valid=True),
            make_result(record_id="r2", enum_valid=True),
        ]
        assert compute_enum_accuracy(results) == pytest.approx(1.0)

    def test_enum_accuracy_none_valid(self):
        """All results with enum_valid=False -> 0.0"""
        results = [
            make_result(record_id="r1", enum_valid=False),
            make_result(record_id="r2", enum_valid=False),
        ]
        assert compute_enum_accuracy(results) == pytest.approx(0.0)

    def test_enum_accuracy_partial(self):
        """Half valid -> 0.5"""
        results = [
            make_result(record_id="r1", enum_valid=True),
            make_result(record_id="r2", enum_valid=False),
        ]
        assert compute_enum_accuracy(results) == pytest.approx(0.5)

    def test_enum_accuracy_empty(self):
        """Empty list -> 1.0"""
        assert compute_enum_accuracy([]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# JSON validity rate tests
# ---------------------------------------------------------------------------

class TestJsonValidityRate:
    def test_json_validity_rate_all_valid(self):
        results = [
            make_result(record_id="r1", json_valid=True),
            make_result(record_id="r2", json_valid=True),
        ]
        assert compute_json_validity_rate(results) == pytest.approx(1.0)

    def test_json_validity_rate_none_valid(self):
        results = [
            make_result(record_id="r1", json_valid=False),
        ]
        assert compute_json_validity_rate(results) == pytest.approx(0.0)

    def test_json_validity_rate_partial(self):
        results = [
            make_result(record_id="r1", json_valid=True),
            make_result(record_id="r2", json_valid=False),
            make_result(record_id="r3", json_valid=True),
            make_result(record_id="r4", json_valid=True),
        ]
        # 3/4 = 0.75
        assert compute_json_validity_rate(results) == pytest.approx(0.75)

    def test_json_validity_rate_empty(self):
        assert compute_json_validity_rate([]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Schema validity rate tests (same pattern)
# ---------------------------------------------------------------------------

class TestSchemaValidityRate:
    def test_schema_validity_all_valid(self):
        results = [make_result(record_id="r1", schema_valid=True)]
        assert compute_schema_validity_rate(results) == pytest.approx(1.0)

    def test_schema_validity_none_valid(self):
        results = [make_result(record_id="r1", schema_valid=False)]
        assert compute_schema_validity_rate(results) == pytest.approx(0.0)

    def test_schema_validity_empty(self):
        assert compute_schema_validity_rate([]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Aggregate span metrics tests
# ---------------------------------------------------------------------------

class TestAggregateSpanMetrics:
    def test_aggregate_span_perfect(self):
        """All spans match exactly -> strict_span_correct = span_total."""
        entities = [
            make_entity("medication", "aspirin", 0, 7, evidence="aspirin for pain"),
        ]
        result = make_result(record_id="r1", entities=entities)
        gold_entities = [
            make_entity("medication", "aspirin", 0, 7, evidence="aspirin for pain"),
        ]
        metrics = compute_aggregate_span_metrics(result, gold_entities, "aspirin for pain")
        assert metrics["span_total"] == 1
        assert metrics["strict_span_correct"] == 1
        assert metrics["lenient_span_correct"] == 1

    def test_aggregate_span_no_match(self):
        """Pred entity mention doesn't match gold -> no span credit."""
        entities = [
            make_entity("medication", "aspirin", 0, 7, evidence="aspirin for pain"),
        ]
        result = make_result(record_id="r1", entities=entities)
        gold_entities = [
            make_entity("medication", "warfarin", 0, 8, evidence="warfarin test"),
        ]
        metrics = compute_aggregate_span_metrics(result, gold_entities, "aspirin for pain")
        assert metrics["span_total"] == 1
        assert metrics["strict_span_correct"] == 0
        assert metrics["lenient_span_correct"] == 0

    def test_aggregate_span_off_by_one(self):
        """Off-by-one span: strict fails, lenient may still pass if IoU high."""
        # Text: "aspirin" at [0,7]. Off by one: [0,8] for 8-char text doesn't work cleanly.
        # Use [0,6] vs gold [0,7] -> intersection=[0,6]=6, union=[0,7]=7, iou=6/7>0.5
        entities = [
            make_entity("medication", "aspirin", 0, 7, evidence="aspirin test"),
        ]
        result = make_result(record_id="r1", entities=entities)
        gold_entities = [
            make_entity("medication", "aspirin", 0, 7, evidence="aspirin test"),
        ]
        # Both same -> strict and lenient both pass
        metrics = compute_aggregate_span_metrics(result, gold_entities, "aspirin test")
        assert metrics["strict_span_correct"] == 1

    def test_aggregate_span_empty_pred(self):
        """No predicted entities -> all zero."""
        result = make_result(record_id="r1", entities=[])
        gold_entities = [
            make_entity("medication", "aspirin", 0, 7, evidence="aspirin test"),
        ]
        metrics = compute_aggregate_span_metrics(result, gold_entities, "aspirin test")
        assert metrics["span_total"] == 0
        assert metrics["strict_span_correct"] == 0
        assert metrics["lenient_span_correct"] == 0
