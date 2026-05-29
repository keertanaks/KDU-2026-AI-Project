# evaluation/harness/metrics.py
#
# Project 3 — Phase 5: Metrics computation for clinical extraction evaluation.
#
# All functions operate on app.schemas.extraction types.
# No model loading here — pure computation on already-generated predictions.

from __future__ import annotations

from typing import Optional

from app.schemas.extraction import Entity, ExtractionResult, SourceSpan


# ---------------------------------------------------------------------------
# Entity-level F1
# ---------------------------------------------------------------------------

def compute_entity_f1(
    predicted: list[Entity],
    gold: list[Entity],
    entity_type: str,
) -> dict:
    """Compute precision, recall, F1 for a single entity type.

    Matching criterion: same entity_type AND case-insensitive mention match.

    Args:
        predicted: List of predicted Entity objects.
        gold: List of gold Entity objects.
        entity_type: One of "medication" or "adverse_event".

    Returns:
        {"precision": float, "recall": float, "f1": float,
         "tp": int, "fp": int, "fn": int}
    """
    pred_filtered = [e for e in predicted if e.entity_type == entity_type]
    gold_filtered = [e for e in gold if e.entity_type == entity_type]

    pred_mentions = [e.mention.lower().strip() for e in pred_filtered]
    gold_mentions = [e.mention.lower().strip() for e in gold_filtered]

    # Count TPs greedily (each gold can only be matched once)
    gold_remaining = list(gold_mentions)
    tp = 0
    for pm in pred_mentions:
        if pm in gold_remaining:
            tp += 1
            gold_remaining.remove(pm)

    fp = len(pred_mentions) - tp
    fn = len(gold_mentions) - tp

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


# ---------------------------------------------------------------------------
# Span metrics
# ---------------------------------------------------------------------------

def compute_span_iou(pred_span: SourceSpan, gold_span: SourceSpan) -> float:
    """Character-level Intersection over Union.

    Args:
        pred_span: Predicted SourceSpan.
        gold_span: Gold SourceSpan.

    Returns:
        IoU in [0.0, 1.0].
    """
    intersection_start = max(pred_span.start_char, gold_span.start_char)
    intersection_end = min(pred_span.end_char, gold_span.end_char)
    intersection = max(0, intersection_end - intersection_start)

    union_start = min(pred_span.start_char, gold_span.start_char)
    union_end = max(pred_span.end_char, gold_span.end_char)
    union = max(0, union_end - union_start)

    if union == 0:
        return 0.0
    return intersection / union


def compute_span_f1_strict(pred_span: SourceSpan, gold_span: SourceSpan) -> bool:
    """Strict span match: exact start_char and end_char.

    Args:
        pred_span: Predicted SourceSpan.
        gold_span: Gold SourceSpan.

    Returns:
        True if spans are identical.
    """
    return (
        pred_span.start_char == gold_span.start_char
        and pred_span.end_char == gold_span.end_char
    )


def compute_span_f1_lenient(
    pred_span: SourceSpan,
    gold_span: SourceSpan,
    threshold: float = 0.5,
) -> bool:
    """Lenient span match: IoU >= threshold.

    Args:
        pred_span: Predicted SourceSpan.
        gold_span: Gold SourceSpan.
        threshold: Minimum IoU required (default 0.5).

    Returns:
        True if IoU >= threshold.
    """
    return compute_span_iou(pred_span, gold_span) >= threshold


# ---------------------------------------------------------------------------
# Relation F1
# ---------------------------------------------------------------------------

def compute_relation_f1(
    predicted_statuses: list[str],
    gold_statuses: list[str],
) -> dict:
    """Macro-averaged F1 across relation status classes.

    Args:
        predicted_statuses: List of predicted relation_status strings.
        gold_statuses: List of gold relation_status strings.

    Returns:
        {"macro_f1": float, "per_class": {"related": f1, "not_related": f1, "none": f1}}
    """
    classes = ["related", "not_related", "none"]
    per_class: dict[str, float] = {}

    for cls in classes:
        tp = sum(
            1
            for p, g in zip(predicted_statuses, gold_statuses)
            if p == cls and g == cls
        )
        fp = sum(
            1
            for p, g in zip(predicted_statuses, gold_statuses)
            if p == cls and g != cls
        )
        fn = sum(
            1
            for p, g in zip(predicted_statuses, gold_statuses)
            if p != cls and g == cls
        )

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        per_class[cls] = f1

    macro_f1 = sum(per_class.values()) / len(classes)

    return {"macro_f1": macro_f1, "per_class": per_class}


# ---------------------------------------------------------------------------
# Hallucination and evidence
# ---------------------------------------------------------------------------

def compute_hallucination_rate(entities: list[Entity], input_text: str) -> float:
    """Fraction of entity mentions NOT found as substring in input_text.

    An entity is considered hallucinated if its mention string is not a
    case-insensitive substring of the input text.

    Args:
        entities: List of Entity objects.
        input_text: Original clinical text.

    Returns:
        Hallucination rate in [0.0, 1.0]. Returns 0.0 if entities is empty.
    """
    if not entities:
        return 0.0

    input_lower = input_text.lower()
    hallucinated = sum(
        1 for e in entities if e.mention.lower() not in input_lower
    )
    return hallucinated / len(entities)


def compute_evidence_accuracy(entities: list[Entity], input_text: str) -> float:
    """Fraction of entity evidence strings that ARE substrings of input_text.

    Args:
        entities: List of Entity objects.
        input_text: Original clinical text.

    Returns:
        Evidence accuracy in [0.0, 1.0]. Returns 1.0 if entities is empty.
    """
    if not entities:
        return 1.0

    correct = sum(1 for e in entities if e.evidence in input_text)
    return correct / len(entities)


# ---------------------------------------------------------------------------
# Validity rates (operate on ExtractionResult lists)
# ---------------------------------------------------------------------------

def compute_enum_accuracy(results: list[ExtractionResult]) -> float:
    """Fraction of results where validation.enum_valid is True.

    Args:
        results: List of ExtractionResult objects.

    Returns:
        Enum accuracy in [0.0, 1.0]. Returns 1.0 if results is empty.
    """
    if not results:
        return 1.0
    return sum(1 for r in results if r.validation.enum_valid) / len(results)


def compute_json_validity_rate(results: list[ExtractionResult]) -> float:
    """Fraction of results where validation.json_valid is True.

    Args:
        results: List of ExtractionResult objects.

    Returns:
        JSON validity rate in [0.0, 1.0]. Returns 1.0 if results is empty.
    """
    if not results:
        return 1.0
    return sum(1 for r in results if r.validation.json_valid) / len(results)


def compute_schema_validity_rate(results: list[ExtractionResult]) -> float:
    """Fraction of results where validation.schema_valid is True.

    Args:
        results: List of ExtractionResult objects.

    Returns:
        Schema validity rate in [0.0, 1.0]. Returns 1.0 if results is empty.
    """
    if not results:
        return 1.0
    return sum(1 for r in results if r.validation.schema_valid) / len(results)


# ---------------------------------------------------------------------------
# Aggregate span metrics
# ---------------------------------------------------------------------------

def compute_aggregate_span_metrics(
    pred_result: ExtractionResult,
    gold_entities: list[Entity],
    input_text: str,
) -> dict:
    """For each predicted entity, find matching gold entity and check span.

    Matching is by entity_type + mention (case-insensitive). Each gold entity
    can only be matched once. Unmatched predictions contribute to span_total
    but not to strict/lenient correct counts.

    Args:
        pred_result: Predicted ExtractionResult.
        gold_entities: List of gold Entity objects.
        input_text: Original clinical text (unused here, kept for API consistency).

    Returns:
        {
            "strict_span_correct": int,
            "lenient_span_correct": int,
            "span_total": int,
        }
    """
    strict_correct = 0
    lenient_correct = 0
    span_total = 0

    # Build mutable list of gold for greedy matching
    gold_remaining = list(gold_entities)

    for pred_entity in pred_result.entities:
        span_total += 1
        pred_key = (pred_entity.entity_type, pred_entity.mention.lower().strip())

        # Find first matching gold entity
        matched_gold: Optional[Entity] = None
        matched_idx: int = -1
        for i, gold_entity in enumerate(gold_remaining):
            gold_key = (gold_entity.entity_type, gold_entity.mention.lower().strip())
            if pred_key == gold_key:
                matched_gold = gold_entity
                matched_idx = i
                break

        if matched_gold is not None:
            gold_remaining.pop(matched_idx)
            if compute_span_f1_strict(pred_entity.source_span, matched_gold.source_span):
                strict_correct += 1
            if compute_span_f1_lenient(pred_entity.source_span, matched_gold.source_span):
                lenient_correct += 1

    return {
        "strict_span_correct": strict_correct,
        "lenient_span_correct": lenient_correct,
        "span_total": span_total,
    }
