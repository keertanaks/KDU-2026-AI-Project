"""
demo/error_dashboard.py — Error analysis dashboard.

Streamlit app that loads evaluation report JSON files and visualizes:
- Validation failure breakdown by error type
- Entity-level F1 per entity type with drill-down
- Specific error examples grouped by failure mode
- OOD vs in-distribution performance comparison

Usage:
    streamlit run demo/error_dashboard.py

Requires:
    pip install streamlit
    evaluation/reports/lora_v1.json and evaluation/reports/lora_v1_ood.json
"""

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

REPORTS_DIR = Path(__file__).parent.parent / "evaluation" / "reports"

st.set_page_config(
    page_title="Harmony — Error Dashboard",
    page_icon="🔍",
    layout="wide",
)

st.title("Extraction Error Dashboard")
st.caption("Drill into where the model fails and why.")


@st.cache_data
def load_report(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


lora_report = load_report(REPORTS_DIR / "lora_v1.json")
ood_report = load_report(REPORTS_DIR / "lora_v1_ood.json")
baseline_report = load_report(REPORTS_DIR / "baseline.json")

if lora_report is None:
    st.error(
        "lora_v1.json not found in evaluation/reports/. "
        "Run the evaluation harness to generate it."
    )
    st.stop()

lm = lora_report["metrics"]

# ── Report selector ──────────────────────────────────────────────────────────
report_options = ["LoRA lora_v1 (in-distribution)"]
if ood_report:
    report_options.append("LoRA lora_v1 (OOD synthetic)")
if baseline_report:
    report_options.append("Baseline (zero-shot)")

selected_report_label = st.sidebar.selectbox("Report", report_options)

if selected_report_label == "LoRA lora_v1 (in-distribution)":
    active_report = lora_report
    label = "lora_v1 (in-dist)"
elif selected_report_label == "LoRA lora_v1 (OOD synthetic)":
    active_report = ood_report
    label = "lora_v1 (OOD)"
else:
    active_report = baseline_report
    label = "baseline"

am = active_report["metrics"]
errors = active_report.get("error_analysis", [])

# ── Overview metrics ─────────────────────────────────────────────────────────
st.header(f"Overview — {label}")
st.caption(f"n = {active_report['n_examples']} examples")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Drug F1", f"{am['drug_f1']:.3f}", help="Target: ≥0.75")
c2.metric("ADE F1", f"{am['ade_f1']:.3f}", help="Target: ≥0.65")
c3.metric("Hallucination Rate", f"{am['hallucination_rate']:.2%}", help="Target: ≤5%")
c4.metric("Evidence Accuracy", f"{am['evidence_accuracy']:.1%}", help="Target: ≥90%")

c5, c6, c7, c8 = st.columns(4)
c5.metric("JSON valid (pre-repair)", f"{am['json_valid_pre_repair']:.1%}")
c6.metric("Schema valid", f"{am['schema_valid']:.1%}")
c7.metric("Enum Accuracy", f"{am['enum_accuracy']:.1%}")
c8.metric("Relation F1", f"{am['relation_f1']:.3f}")

# ── Precision / Recall breakdown ─────────────────────────────────────────────
st.divider()
st.header("Entity F1 Breakdown")

col_med, col_ade = st.columns(2)

with col_med:
    st.subheader("Medications")
    st.metric("Precision", f"{am['drug_precision']:.3f}")
    st.metric("Recall", f"{am['drug_recall']:.3f}")
    st.metric("F1", f"{am['drug_f1']:.3f}")
    st.progress(am["drug_f1"], text=f"Drug F1: {am['drug_f1']:.1%} (target 75%)")

with col_ade:
    st.subheader("Adverse Events")
    st.metric("Precision", f"{am['ade_precision']:.3f}")
    st.metric("Recall", f"{am['ade_recall']:.3f}")
    st.metric("F1", f"{am['ade_f1']:.3f}")
    st.progress(am["ade_f1"], text=f"ADE F1: {am['ade_f1']:.1%} (target 65%)")

# Interpret the gap
if am["ade_f1"] < 0.65:
    prec = am["ade_precision"]
    rec = am["ade_recall"]
    if prec > rec:
        bottleneck = "recall-limited (model misses ADEs that are present)"
    elif rec > prec:
        bottleneck = "precision-limited (model predicts ADEs that aren't there)"
    else:
        bottleneck = "balanced precision/recall gap"
    st.info(
        f"ADE F1 below target ({am['ade_f1']:.3f} < 0.65). "
        f"Gap is {bottleneck}: precision={prec:.3f}, recall={rec:.3f}."
    )

# ── Span metrics ─────────────────────────────────────────────────────────────
st.divider()
st.header("Span Boundary Accuracy")

span_strict = am.get("span_f1_strict", 0)
span_lenient = am.get("span_f1_lenient", 0)

cs, cl = st.columns(2)
cs.metric("Strict Span F1 (exact match)", f"{span_strict:.3f}", help="Target: ≥0.65")
cl.metric("Lenient Span F1 (IoU ≥ 0.5)", f"{span_lenient:.3f}", help="Target: ≥0.75")

if span_strict < span_lenient * 0.5:
    st.warning(
        f"Large strict vs lenient gap ({span_strict:.3f} vs {span_lenient:.3f}). "
        "The model finds the right spans approximately but has systematic off-by-one "
        "errors on start_char. This is common when training data has inconsistent "
        "whitespace-boundary annotations."
    )

# ── OOD vs in-distribution comparison ────────────────────────────────────────
if ood_report and active_report is not ood_report:
    st.divider()
    st.header("OOD vs In-Distribution Comparison")
    st.caption("60 synthetic examples vs 2,376 held-out test examples.")

    oom = ood_report["metrics"]

    compare_rows = []
    for label_str, key in [
        ("Drug F1", "drug_f1"),
        ("Drug Precision", "drug_precision"),
        ("Drug Recall", "drug_recall"),
        ("ADE F1", "ade_f1"),
        ("ADE Precision", "ade_precision"),
        ("ADE Recall", "ade_recall"),
        ("Relation F1", "relation_f1"),
        ("Hallucination Rate", "hallucination_rate"),
        ("Evidence Accuracy", "evidence_accuracy"),
        ("Span F1 lenient", "span_f1_lenient"),
    ]:
        id_val = lm.get(key)
        ood_val = oom.get(key)
        delta = (ood_val - id_val) if (id_val is not None and ood_val is not None) else None
        compare_rows.append({
            "Metric": label_str,
            "In-Dist (2376)": f"{id_val:.3f}" if id_val is not None else "—",
            "OOD (60)": f"{ood_val:.3f}" if ood_val is not None else "—",
            "Delta": (f"+{delta:.3f}" if delta >= 0 else f"{delta:.3f}") if delta is not None else "—",
        })
    st.table(compare_rows)

    st.markdown(
        "**Key observation:** Drug recall drops on OOD (0.470 vs 0.817 in-dist) — "
        "the model misses multi-word drug names not seen in training. "
        "ADE F1 is actually higher on OOD (0.676 vs 0.542), suggesting the "
        "in-dist ADE failures are corpus-specific, not a generalization failure."
    )

# ── Error examples ────────────────────────────────────────────────────────────
st.divider()
st.header(f"Error Examples ({len(errors)} logged)")

if not errors:
    st.info("No errors logged in this report.")
else:
    error_types = sorted(set(e.get("error_type", "unknown") for e in errors))
    selected_type = st.selectbox(
        "Filter by error type",
        ["all"] + error_types,
    )

    filtered = errors if selected_type == "all" else [
        e for e in errors if e.get("error_type") == selected_type
    ]

    st.caption(f"Showing {len(filtered)} of {len(errors)} errors.")

    for i, err in enumerate(filtered[:10]):
        etype = err.get("error_type", "unknown")
        eid = err.get("id", f"error_{i}")
        with st.expander(f"{eid} — type: `{etype}`"):
            st.markdown("**Input text (truncated to 300 chars):**")
            st.code(err.get("input", "")[:300], language=None)

            c_pred, c_gold = st.columns(2)
            c_pred.markdown("**Predicted (truncated):**")
            pred_str = err.get("predicted", "")[:400]
            try:
                c_pred.code(pred_str, language="json")
            except Exception:
                c_pred.code(pred_str, language=None)

            c_gold.markdown("**Gold label (truncated):**")
            gold_str = err.get("gold", "")[:400]
            try:
                c_gold.code(gold_str, language="json")
            except Exception:
                c_gold.code(gold_str, language=None)

    if len(filtered) > 10:
        st.caption(f"... and {len(filtered) - 10} more (showing first 10).")

# ── Error type distribution ────────────────────────────────────────────────────
if errors:
    st.divider()
    st.header("Error Type Distribution")

    type_counts: dict[str, int] = {}
    for e in errors:
        t = e.get("error_type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    for etype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = count / len(errors) * 100
        st.markdown(f"**{etype}** — {count} examples ({pct:.0f}%)")
        st.progress(count / len(errors))

    st.markdown("""
**Error type guide:**
- `hallucination` — predicted mention not found as substring in input text
- `schema_invalid` — Pydantic validation failed on model output
- `json_invalid` — JSON parse failed even after json_repair
- `enum_error` — invalid entity_type or relation_status value
""")
