# evaluation/harness/eval_runner.py
#
# Project 3 — Phase 5: Evaluation runner CLI.
#
# Usage:
#   python -m evaluation.harness.eval_runner \
#       --model lora \
#       --adapter_path models/adapters/lora_v1 \
#       --test_file data/processed/test.jsonl \
#       --output_dir evaluation/reports
#
# NOTE: Requires GPU. Will exit(1) if torch.cuda.is_available() is False.

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import torch


def _check_gpu() -> None:
    """Exit with code 1 if no CUDA GPU is available."""
    if not torch.cuda.is_available():
        print(
            "ERROR: No CUDA GPU detected. eval_runner.py requires a GPU to run inference.\n"
            "If you intended to run unit tests, use: pytest tests/test_metrics.py -v",
            file=sys.stderr,
        )
        sys.exit(1)


def _load_model_and_tokenizer(
    model_type: str,
    adapter_path: Optional[str],
    use_4bit: bool,
):
    """Load base model + optional LoRA/QLoRA adapter.

    Args:
        model_type: One of "baseline", "lora", "qlora".
        adapter_path: Path to PEFT adapter directory (ignored for baseline).
        use_4bit: Whether to use 4-bit quantization (for qlora).

    Returns:
        (model, tokenizer) tuple.
    """
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    base_model_path = "Qwen/Qwen2.5-7B-Instruct"

    print(f"Loading tokenizer from {base_model_path} ...")
    tokenizer = AutoTokenizer.from_pretrained(base_model_path, trust_remote_code=True)

    if model_type == "baseline":
        print("Loading baseline model (no adapter) ...")
        model = AutoModelForCausalLM.from_pretrained(
            base_model_path,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True,
        )

    elif model_type == "lora":
        from peft import PeftModel

        print(f"Loading LoRA model with adapter from {adapter_path} ...")
        model = AutoModelForCausalLM.from_pretrained(
            base_model_path,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True,
        )
        model = PeftModel.from_pretrained(model, adapter_path)

    elif model_type == "qlora":
        from peft import PeftModel

        print(f"Loading QLoRA model (4-bit) with adapter from {adapter_path} ...")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,
        )
        model = AutoModelForCausalLM.from_pretrained(
            base_model_path,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True,
        )
        model = PeftModel.from_pretrained(model, adapter_path)

    else:
        raise ValueError(f"Unknown model type: {model_type}")

    model.eval()
    return model, tokenizer


def _run_inference(model, tokenizer, user_content: str) -> tuple[str, float]:
    """Run inference on a single example.

    Args:
        model: Loaded model.
        tokenizer: Loaded tokenizer.
        user_content: Full user turn content string.

    Returns:
        (raw_output_string, latency_seconds) tuple.
    """
    messages = [{"role": "user", "content": user_content}]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    t0 = time.perf_counter()
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=512,
            repetition_penalty=1.05,
        )
    t1 = time.perf_counter()

    raw_output = tokenizer.decode(
        output_ids[0][inputs.input_ids.shape[1]:],
        skip_special_tokens=True,
    )
    return raw_output, t1 - t0


def _parse_raw_output(raw_output: str, record_id: str):
    """Attempt to parse model output into an ExtractionResult.

    Uses json-repair for robustness. Returns (result, json_valid_pre_repair, error_type).
    """
    import json_repair
    from app.ingestion.validator import build_empty_result, validate_extraction

    # Pre-repair JSON validity
    json_valid_pre = True
    try:
        json.loads(raw_output)
    except (json.JSONDecodeError, ValueError):
        json_valid_pre = False

    # Full parse via validator (handles repair + Pydantic)
    result, error_type = _safe_validate(raw_output, record_id)
    return result, json_valid_pre, error_type


def _safe_validate(raw_output: str, record_id: str):
    """Wrap validator call to avoid import errors if validator module differs.

    Returns (ExtractionResult or None, error_type_str).
    """
    try:
        from app.ingestion.validator import validate_extraction

        result = validate_extraction(raw_output, record_id=record_id)
        return result, None
    except Exception:
        # Fall back to manual parse + inject
        return _manual_validate(raw_output, record_id)


def _manual_validate(raw_output: str, record_id: str):
    """Manual validate fallback: repair JSON, inject system fields, Pydantic validate."""
    import json_repair
    from pydantic import ValidationError

    from app.schemas.extraction import ExtractionResult, ValidationFlags

    error_type = None

    # Attempt JSON repair
    try:
        repaired_str = json_repair.repair(raw_output)
        parsed = json.loads(repaired_str)
        json_valid = True
    except Exception:
        json_valid = False
        parsed = {}
        error_type = "json_invalid"

    # Inject system fields
    parsed["record_id"] = record_id
    parsed.setdefault("validation", {
        "json_valid": json_valid,
        "schema_valid": False,
        "enum_valid": False,
        "evidence_present": False,
    })
    parsed["validation"]["json_valid"] = json_valid

    if not json_valid:
        parsed.setdefault("schema_version", "v1")
        parsed.setdefault("entities", [])
        parsed.setdefault("relation_status", "none")
        parsed["validation"].update({
            "schema_valid": False,
            "enum_valid": False,
            "evidence_present": False,
        })
        try:
            return ExtractionResult(**parsed), error_type
        except Exception:
            return None, error_type

    # Pydantic validation
    try:
        # Validate enums manually
        valid_entity_types = {"medication", "adverse_event"}
        valid_relation_statuses = {"related", "not_related", "none"}
        enum_valid = True
        for ent in parsed.get("entities", []):
            if ent.get("entity_type") not in valid_entity_types:
                enum_valid = False
                break
        if parsed.get("relation_status") not in valid_relation_statuses:
            enum_valid = False

        parsed["validation"]["enum_valid"] = enum_valid

        result = ExtractionResult.model_validate(parsed)
        parsed["validation"]["schema_valid"] = True

        if not enum_valid:
            error_type = "enum_error"

        return result, error_type

    except ValidationError:
        parsed["validation"]["schema_valid"] = False
        if error_type is None:
            error_type = "schema_invalid"
        try:
            return ExtractionResult.model_validate(parsed), error_type
        except Exception:
            return None, error_type


def _extract_input_text(user_content: str) -> str:
    """Extract clinical text from user turn content."""
    if "Clinical text:\n" in user_content:
        return user_content.split("Clinical text:\n", 1)[1].strip()
    return user_content.strip()


def _evaluate_dataset(
    model,
    tokenizer,
    data_path: str,
    max_samples: Optional[int],
    dataset_label: str,
) -> tuple[dict, list[dict]]:
    """Run evaluation on a JSONL dataset.

    Args:
        model: Loaded model.
        tokenizer: Loaded tokenizer.
        data_path: Path to JSONL file.
        max_samples: Optional limit on number of examples.
        dataset_label: Label for progress messages.

    Returns:
        (metrics_dict, error_analysis_list) tuple.
    """
    from app.schemas.extraction import Entity, SourceSpan

    from evaluation.harness.metrics import (
        compute_aggregate_span_metrics,
        compute_entity_f1,
        compute_evidence_accuracy,
        compute_hallucination_rate,
        compute_relation_f1,
    )

    rows = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
            if max_samples and len(rows) >= max_samples:
                break

    print(f"\nEvaluating {dataset_label}: {len(rows)} examples ...")

    per_example_drug_f1 = []
    per_example_ade_f1 = []
    per_example_drug_prec = []
    per_example_drug_rec = []
    per_example_ade_prec = []
    per_example_ade_rec = []
    per_example_halluc = []
    per_example_evidence = []
    predicted_statuses = []
    gold_statuses = []
    json_valid_pre_list = []
    json_valid_post_list = []
    schema_valid_list = []
    enum_valid_list = []
    latencies = []

    strict_span_total = 0
    strict_span_correct = 0
    lenient_span_correct = 0

    # Dosage coverage
    gold_has_dosage_count = 0
    pred_has_dosage_count = 0

    error_analysis: list[dict] = []
    MAX_ERRORS = 20

    for idx, row in enumerate(rows):
        example_id = row.get("id", f"{dataset_label}_{idx:04d}")
        user_content = row["messages"][0]["content"]
        gold_raw = row["messages"][1]["content"]
        input_text = _extract_input_text(user_content)

        # Parse gold
        try:
            gold_dict = json.loads(gold_raw)
            gold_entities_raw = gold_dict.get("entities", [])
            gold_entities: list[Entity] = []
            for ge in gold_entities_raw:
                try:
                    gold_entities.append(Entity.model_validate(ge))
                except Exception:
                    pass
            gold_relation = gold_dict.get("relation_status", "none")
        except Exception:
            gold_entities = []
            gold_relation = "none"

        # Run inference
        raw_output, latency = _run_inference(model, tokenizer, user_content)
        latencies.append(latency)

        # Parse prediction
        result, json_valid_pre, error_type = _parse_raw_output(raw_output, example_id)

        json_valid_pre_list.append(json_valid_pre)

        if result is None:
            # Complete failure
            json_valid_post_list.append(False)
            schema_valid_list.append(False)
            enum_valid_list.append(False)
            predicted_statuses.append("none")
            gold_statuses.append(gold_relation)
            per_example_drug_f1.append(0.0)
            per_example_ade_f1.append(0.0)
            per_example_drug_prec.append(0.0)
            per_example_drug_rec.append(0.0)
            per_example_ade_prec.append(0.0)
            per_example_ade_rec.append(0.0)
            per_example_halluc.append(1.0)
            per_example_evidence.append(0.0)

            if len(error_analysis) < MAX_ERRORS:
                error_analysis.append({
                    "id": example_id,
                    "input": input_text[:200],
                    "predicted": raw_output[:300],
                    "gold": gold_raw[:300],
                    "error_type": "json_invalid",
                })
            continue

        # Collect validity flags
        json_valid_post_list.append(result.validation.json_valid)
        schema_valid_list.append(result.validation.schema_valid)
        enum_valid_list.append(result.validation.enum_valid)

        pred_entities = result.entities
        pred_relation = result.relation_status

        # Entity F1
        drug_metrics = compute_entity_f1(pred_entities, gold_entities, "medication")
        ade_metrics = compute_entity_f1(pred_entities, gold_entities, "adverse_event")
        per_example_drug_f1.append(drug_metrics["f1"])
        per_example_ade_f1.append(ade_metrics["f1"])
        per_example_drug_prec.append(drug_metrics["precision"])
        per_example_drug_rec.append(drug_metrics["recall"])
        per_example_ade_prec.append(ade_metrics["precision"])
        per_example_ade_rec.append(ade_metrics["recall"])

        # Relation
        predicted_statuses.append(pred_relation)
        gold_statuses.append(gold_relation)

        # Hallucination and evidence
        halluc = compute_hallucination_rate(pred_entities, input_text)
        evidence = compute_evidence_accuracy(pred_entities, input_text)
        per_example_halluc.append(halluc)
        per_example_evidence.append(evidence)

        # Span metrics
        span_metrics = compute_aggregate_span_metrics(result, gold_entities, input_text)
        strict_span_total += span_metrics["span_total"]
        strict_span_correct += span_metrics["strict_span_correct"]
        lenient_span_correct += span_metrics["lenient_span_correct"]

        # Dosage coverage
        for ge in gold_entities:
            if ge.entity_type == "medication" and ge.dosage is not None:
                gold_has_dosage_count += 1
                # Check if prediction has dosage for matching entity
                for pe in pred_entities:
                    if (
                        pe.entity_type == "medication"
                        and pe.mention.lower().strip() == ge.mention.lower().strip()
                        and pe.dosage is not None
                    ):
                        pred_has_dosage_count += 1
                        break

        # Error analysis
        if len(error_analysis) < MAX_ERRORS and error_type is not None:
            error_analysis.append({
                "id": example_id,
                "input": input_text[:200],
                "predicted": raw_output[:300],
                "gold": gold_raw[:300],
                "error_type": error_type,
            })

        if (idx + 1) % 100 == 0:
            print(f"  Processed {idx + 1}/{len(rows)} examples ...")

    # Aggregate metrics
    n = len(rows)

    rel_metrics = compute_relation_f1(predicted_statuses, gold_statuses)

    latencies_arr = np.array(latencies) if latencies else np.array([0.0])

    span_f1_strict = strict_span_correct / strict_span_total if strict_span_total > 0 else 0.0
    span_f1_lenient = lenient_span_correct / strict_span_total if strict_span_total > 0 else 0.0

    dosage_coverage = (
        pred_has_dosage_count / gold_has_dosage_count
        if gold_has_dosage_count > 0
        else 0.0
    )

    metrics = {
        "n_examples": n,
        "json_valid_pre_repair": float(np.mean(json_valid_pre_list)) if json_valid_pre_list else 0.0,
        "json_valid_post_repair": float(np.mean(json_valid_post_list)) if json_valid_post_list else 0.0,
        "schema_valid": float(np.mean(schema_valid_list)) if schema_valid_list else 0.0,
        "drug_f1": float(np.mean(per_example_drug_f1)) if per_example_drug_f1 else 0.0,
        "drug_precision": float(np.mean(per_example_drug_prec)) if per_example_drug_prec else 0.0,
        "drug_recall": float(np.mean(per_example_drug_rec)) if per_example_drug_rec else 0.0,
        "ade_f1": float(np.mean(per_example_ade_f1)) if per_example_ade_f1 else 0.0,
        "ade_precision": float(np.mean(per_example_ade_prec)) if per_example_ade_prec else 0.0,
        "ade_recall": float(np.mean(per_example_ade_rec)) if per_example_ade_rec else 0.0,
        "relation_f1": rel_metrics["macro_f1"],
        "relation_per_class": rel_metrics["per_class"],
        "hallucination_rate": float(np.mean(per_example_halluc)) if per_example_halluc else 0.0,
        "evidence_accuracy": float(np.mean(per_example_evidence)) if per_example_evidence else 0.0,
        "enum_accuracy": float(np.mean(enum_valid_list)) if enum_valid_list else 0.0,
        "span_f1_strict": span_f1_strict,
        "span_f1_lenient": span_f1_lenient,
        "dosage_coverage": dosage_coverage,
        "latency_p50_s": float(np.percentile(latencies_arr, 50)),
        "latency_p95_s": float(np.percentile(latencies_arr, 95)),
    }

    return metrics, error_analysis


def _generate_comparison_report(output_dir: Path) -> None:
    """Generate comparison.md if all 3 model reports exist."""
    model_names = ["baseline", "lora", "qlora"]
    reports: dict[str, dict] = {}

    for name in model_names:
        report_path = output_dir / f"{name}.json"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                reports[name] = json.load(f)

    if len(reports) < 3:
        print(
            f"Comparison report skipped: only {len(reports)}/3 model reports present "
            f"({list(reports.keys())})."
        )
        return

    print("Generating comparison.md ...")

    metric_rows = [
        ("JSON valid (pre-repair)", "json_valid_pre_repair", "≥95%", "{:.1%}"),
        ("JSON valid (post-repair)", "json_valid_post_repair", "≥99.5%", "{:.1%}"),
        ("Schema valid", "schema_valid", "≥90%", "{:.1%}"),
        ("Drug F1", "drug_f1", "≥0.75", "{:.3f}"),
        ("Drug Precision", "drug_precision", "—", "{:.3f}"),
        ("Drug Recall", "drug_recall", "—", "{:.3f}"),
        ("ADE F1", "ade_f1", "≥0.65", "{:.3f}"),
        ("ADE Precision", "ade_precision", "—", "{:.3f}"),
        ("ADE Recall", "ade_recall", "—", "{:.3f}"),
        ("Relation F1", "relation_f1", "≥0.70", "{:.3f}"),
        ("Hallucination Rate", "hallucination_rate", "≤5%", "{:.1%}"),
        ("Evidence Accuracy", "evidence_accuracy", "≥90%", "{:.1%}"),
        ("Enum Accuracy", "enum_accuracy", "≥98%", "{:.1%}"),
        ("Span F1 (strict)", "span_f1_strict", "≥0.65", "{:.3f}"),
        ("Span F1 (lenient, IoU≥0.5)", "span_f1_lenient", "≥0.75", "{:.3f}"),
        ("Dosage Coverage", "dosage_coverage", "≥0.40", "{:.3f}"),
        ("Latency P50 (s)", "latency_p50_s", "—", "{:.2f}"),
        ("Latency P95 (s)", "latency_p95_s", "—", "{:.2f}"),
    ]

    lines = [
        "# Model Comparison Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## In-Distribution Metrics (test.jsonl)",
        "",
        "| Metric | Target | Baseline | LoRA | QLoRA |",
        "|---|---|---|---|---|",
    ]

    for label, key, target, fmt in metric_rows:
        row_vals = []
        for name in model_names:
            val = reports[name].get("metrics", {}).get(key)
            if val is None:
                row_vals.append("N/A")
            else:
                try:
                    row_vals.append(fmt.format(val))
                except Exception:
                    row_vals.append(str(val))
        lines.append(
            f"| {label} | {target} | {row_vals[0]} | {row_vals[1]} | {row_vals[2]} |"
        )

    # OOD section
    lines += [
        "",
        "## Out-of-Distribution Metrics (synthetic_ade_eval.jsonl)",
        "",
        "| Metric | Target | Baseline | LoRA | QLoRA |",
        "|---|---|---|---|---|",
    ]

    ood_metric_rows = [
        ("Drug F1", "drug_f1", "≥0.75", "{:.3f}"),
        ("ADE F1", "ade_f1", "≥0.65", "{:.3f}"),
        ("Relation F1", "relation_f1", "≥0.70", "{:.3f}"),
        ("Hallucination Rate", "hallucination_rate", "≤5%", "{:.1%}"),
        ("Evidence Accuracy", "evidence_accuracy", "≥90%", "{:.1%}"),
    ]

    for label, key, target, fmt in ood_metric_rows:
        row_vals = []
        for name in model_names:
            val = reports[name].get("ood_metrics", {}).get(key)
            if val is None:
                row_vals.append("N/A")
            else:
                try:
                    row_vals.append(fmt.format(val))
                except Exception:
                    row_vals.append(str(val))
        lines.append(
            f"| {label} | {target} | {row_vals[0]} | {row_vals[1]} | {row_vals[2]} |"
        )

    lines.append("")

    comparison_path = output_dir / "comparison.md"
    with open(comparison_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Comparison report written to {comparison_path}")


def main() -> None:
    """Entry point for eval_runner CLI."""
    parser = argparse.ArgumentParser(
        description="Evaluate a clinical extraction model on test.jsonl.",
    )
    parser.add_argument(
        "--model",
        choices=["baseline", "lora", "qlora"],
        required=True,
        help="Model variant to evaluate.",
    )
    parser.add_argument(
        "--adapter_path",
        default=None,
        help="Path to PEFT adapter directory (required for lora/qlora).",
    )
    parser.add_argument(
        "--test_file",
        default="data/processed/test.jsonl",
        help="Path to test JSONL file.",
    )
    parser.add_argument(
        "--output_dir",
        default="evaluation/reports",
        help="Directory to write JSON results.",
    )
    parser.add_argument(
        "--max_samples",
        type=int,
        default=None,
        help="Limit evaluation to first N examples (for debugging).",
    )
    parser.add_argument(
        "--use_4bit",
        action="store_true",
        help="Enable 4-bit quantization (for qlora).",
    )
    parser.add_argument(
        "--synthetic_file",
        default="evaluation/synthetic_ade_eval.jsonl",
        help="Path to OOD synthetic evaluation set.",
    )

    args = parser.parse_args()

    # Validate adapter_path for non-baseline
    if args.model in ("lora", "qlora") and args.adapter_path is None:
        parser.error(f"--adapter_path is required for --model {args.model}")

    # GPU check
    _check_gpu()

    # Load model
    model, tokenizer = _load_model_and_tokenizer(
        model_type=args.model,
        adapter_path=args.adapter_path,
        use_4bit=args.use_4bit,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run in-distribution evaluation
    print(f"\n--- In-distribution evaluation: {args.test_file} ---")
    id_metrics, id_errors = _evaluate_dataset(
        model=model,
        tokenizer=tokenizer,
        data_path=args.test_file,
        max_samples=args.max_samples,
        dataset_label="test",
    )

    # Run OOD evaluation
    ood_metrics: dict = {}
    ood_errors: list[dict] = []
    synthetic_path = args.synthetic_file

    if os.path.exists(synthetic_path):
        print(f"\n--- OOD evaluation: {synthetic_path} ---")

        # Build JSONL-compatible rows from synthetic format
        synthetic_rows = []
        with open(synthetic_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    syn = json.loads(line)
                    # Convert synthetic format to messages format
                    text = syn["text"]
                    gold_obj = syn["gold"]
                    # Build user content in the same format as training
                    user_content = (
                        "You are a clinical information extractor. Given a clinical text, extract all\n"
                        "medications and adverse events as a JSON object that follows the schema below.\n"
                        "Return ONLY valid JSON. If no entity is present, return entities=[] and\n"
                        'relation_status="none".\n\n'
                        "Return ONLY this JSON structure (no record_id, no validation block — those are added by the system):\n"
                        '{\n  "schema_version": "v1",\n  "entities": [\n    {\n'
                        '      "entity_type": "medication" | "adverse_event",\n'
                        '      "mention": "<string>",\n'
                        '      "dosage": "<string>" | null,\n'
                        '      "linked_medication": "<string>" | null,\n'
                        '      "evidence": "<string>",\n'
                        '      "source_span": {"start_char": <int>, "end_char": <int>}\n'
                        "    }\n  ],\n"
                        '  "relation_status": "related" | "not_related" | "none"\n'
                        "}\n\n"
                        f"Clinical text:\n{text}"
                    )
                    synthetic_rows.append({
                        "id": syn.get("id", f"syn_{len(synthetic_rows):03d}"),
                        "messages": [
                            {"role": "user", "content": user_content},
                            {"role": "assistant", "content": json.dumps(gold_obj)},
                        ],
                    })

        # Write temp file for evaluate_dataset
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as tmp:
            for row in synthetic_rows:
                tmp.write(json.dumps(row) + "\n")
            tmp_path = tmp.name

        try:
            ood_metrics, ood_errors = _evaluate_dataset(
                model=model,
                tokenizer=tokenizer,
                data_path=tmp_path,
                max_samples=args.max_samples,
                dataset_label="synthetic_ood",
            )
        finally:
            os.unlink(tmp_path)
    else:
        print(f"WARNING: Synthetic OOD file not found at {synthetic_path}. Skipping OOD eval.")

    # Build output report
    # Merge ID errors and OOD errors, cap at 20 total
    all_errors = (id_errors + ood_errors)[:20]

    report = {
        "model": args.model,
        "adapter_path": args.adapter_path,
        "test_file": args.test_file,
        "n_examples": id_metrics.pop("n_examples"),
        "metrics": id_metrics,
        "ood_metrics": ood_metrics,
        "error_analysis": all_errors,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    report_path = output_dir / f"{args.model}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to {report_path}")

    # Print summary
    print("\n--- Metrics Summary ---")
    for key, val in report["metrics"].items():
        if isinstance(val, float):
            print(f"  {key}: {val:.4f}")
        else:
            print(f"  {key}: {val}")

    # Generate comparison report if all models done
    _generate_comparison_report(output_dir)


if __name__ == "__main__":
    main()
