"""
demo/reviewer.py — Interactive extraction reviewer.

Streamlit app that lets you paste any clinical text, run extraction through
ClinicalExtractor, and review the structured output with entity highlighting.

Usage:
    streamlit run demo/reviewer.py

Requires:
    pip install streamlit
    EXTRACTION_REMOTE_URL=https://<hf-space-url> in config/.env
    (or a local model at EXTRACTION_ADAPTER_PATH if running on GPU)
"""

import json
import sys
from pathlib import Path

import streamlit as st

# Allow running from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

from app.ingestion.extractor import ClinicalExtractor

st.set_page_config(
    page_title="Harmony — Extraction Reviewer",
    page_icon="💊",
    layout="wide",
)

st.title("Harmony Clinical Extraction Reviewer")
st.caption(
    "Paste clinical text and review what the fine-tuned Qwen2.5-7B+LoRA model extracts. "
    "Extraction runs via the HF Space remote endpoint (or locally if configured)."
)

EXAMPLES = [
    "The patient developed severe hepatotoxicity after 3 months of isoniazid therapy.",
    "Warfarin therapy was initiated; patient subsequently reported GI bleeding episodes.",
    "Methotrexate 15mg weekly was initiated; the patient developed oral mucositis and elevated liver enzymes.",
    "Ibuprofen 400mg was prescribed. Two days later the patient developed acute renal failure.",
    "Patient was prescribed metformin 500mg BID for type 2 diabetes. No adverse events noted.",
    "Lisinopril 10mg daily was started for hypertension. Patient experienced a persistent dry cough.",
    "Amoxicillin 500mg TID was prescribed. The patient developed a diffuse maculopapular rash.",
    "Clozapine therapy was associated with agranulocytosis in this patient.",
]

# Sidebar: example selector and settings
with st.sidebar:
    st.header("Examples")
    selected = st.selectbox("Load an example", ["(paste your own text)"] + EXAMPLES)
    st.divider()
    st.header("Settings")
    record_id = st.text_input("Record ID", value="demo_001")
    st.caption("Used as chunk_id in the extraction result.")
    st.divider()
    st.markdown(
        "**Model:** Qwen2.5-7B-Instruct + LoRA adapter  \n"
        "**Schema:** v1  \n"
        "**Drug F1:** 0.798  \n"
        "**ADE F1:** 0.542  \n"
        "**Hallucination rate:** 0.04%"
    )

# Main input area
default_text = "" if selected == "(paste your own text)" else selected
text_input = st.text_area(
    "Clinical text",
    value=default_text,
    height=120,
    placeholder="Enter a clinical sentence or paragraph...",
)

col1, col2 = st.columns([1, 4])
run_btn = col1.button("Extract", type="primary", use_container_width=True)
clear_btn = col2.button("Clear", use_container_width=False)

if clear_btn:
    st.rerun()

if run_btn:
    if not text_input.strip():
        st.error("Please enter some clinical text.")
        st.stop()

    with st.spinner("Running extraction..."):
        extractor = ClinicalExtractor.get()
        result = extractor.extract(text=text_input.strip(), record_id=record_id)

    st.divider()

    # Validation status banner
    v = result.validation
    all_valid = v.json_valid and v.schema_valid and v.enum_valid and v.evidence_present
    if result.error_reason:
        st.error(f"Extraction failed: `{result.error_reason}`")
    elif all_valid:
        st.success("Extraction successful — all validation checks passed.")
    else:
        flags = []
        if not v.json_valid:
            flags.append("json_valid=False")
        if not v.schema_valid:
            flags.append("schema_valid=False")
        if not v.enum_valid:
            flags.append("enum_valid=False")
        if not v.evidence_present:
            flags.append("evidence_present=False")
        st.warning(f"Extraction completed with warnings: {', '.join(flags)}")

    # Entity summary
    meds = [e for e in result.entities if e.entity_type == "medication"]
    ades = [e for e in result.entities if e.entity_type == "adverse_event"]
    relations = [
        e for e in result.entities
        if e.entity_type == "adverse_event" and e.linked_medication
    ]

    c1, c2, c3 = st.columns(3)
    c1.metric("Medications", len(meds))
    c2.metric("Adverse Events", len(ades))
    c3.metric("Relations", len(relations))

    st.markdown(f"**Relation status:** `{result.relation_status}`")

    # Entity table
    if result.entities:
        st.subheader("Extracted Entities")
        rows = []
        for e in result.entities:
            rows.append({
                "Type": "💊 Medication" if e.entity_type == "medication" else "⚠️ ADE",
                "Mention": e.mention,
                "Dosage": e.dosage or "—",
                "Linked Med": e.linked_medication or "—",
                "Span": f"{e.source_span.start_char}–{e.source_span.end_char}",
                "Evidence": e.evidence[:80] + "..." if len(e.evidence) > 80 else e.evidence,
            })
        st.table(rows)
    else:
        st.info("No entities extracted from this text.")

    # Span highlighting
    if result.entities:
        st.subheader("Span Highlighting")
        text = text_input.strip()
        annotations = []
        for e in result.entities:
            start = e.source_span.start_char
            end = e.source_span.end_char
            if 0 <= start < end <= len(text):
                label = "MED" if e.entity_type == "medication" else "ADE"
                annotations.append((start, end, label))

        if annotations:
            annotations.sort(key=lambda x: x[0])
            highlighted = ""
            prev = 0
            for start, end, label in annotations:
                highlighted += text[prev:start]
                color = "#d4edda" if label == "MED" else "#f8d7da"
                border = "#28a745" if label == "MED" else "#dc3545"
                highlighted += (
                    f'<span style="background:{color};border:1px solid {border};'
                    f'border-radius:3px;padding:1px 3px;font-weight:bold;">'
                    f'{text[start:end]} <sup style="font-size:9px">{label}</sup></span>'
                )
                prev = end
            highlighted += text[prev:]
            st.markdown(highlighted, unsafe_allow_html=True)
        else:
            st.caption("No valid spans to highlight (spans may be out of bounds).")

    # Raw JSON output
    with st.expander("Raw ExtractionResult JSON"):
        st.json(json.loads(result.model_dump_json()))
