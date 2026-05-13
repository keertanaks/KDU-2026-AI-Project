from enum import Enum
from typing import List
from langchain_text_splitters import RecursiveCharacterTextSplitter


class ChunkDocType(str, Enum):
    PRESCRIPTION = "prescription"
    LAB_REPORT = "lab_report"
    CLINICAL_NOTE = "clinical_note"
    FORM = "form"


class Chunk:
    def __init__(self, child_text: str, parent_text: str, doc_type: str):
        self.child_text = child_text
        self.parent_text = parent_text
        self.doc_type = doc_type


class AdaptiveChunker:
    """Document-type-aware chunking."""

    @staticmethod
    def detect_doc_type(text: str) -> ChunkDocType:
        token_count = len(text.split())

        if token_count < 300 and any(x in text.lower() for x in ["mg", "dose", "tablet"]):
            return ChunkDocType.PRESCRIPTION

        if any(x in text.lower() for x in ["normal range", "result", "flag"]):
            return ChunkDocType.LAB_REPORT

        if any(x in text.lower() for x in ["name:", "date:", "patient:"]):
            return ChunkDocType.FORM

        return ChunkDocType.CLINICAL_NOTE

    @staticmethod
    def chunk(text: str, doc_type: ChunkDocType = None) -> List[Chunk]:
        if doc_type is None:
            doc_type = AdaptiveChunker.detect_doc_type(text)

        if doc_type == ChunkDocType.PRESCRIPTION:
            return AdaptiveChunker._chunk_prescription(text)
        elif doc_type == ChunkDocType.LAB_REPORT:
            return AdaptiveChunker._chunk_lab_report(text)
        elif doc_type == ChunkDocType.FORM:
            return AdaptiveChunker._chunk_form(text)
        else:
            return AdaptiveChunker._chunk_clinical_note(text)

    @staticmethod
    def _chunk_prescription(text: str) -> List[Chunk]:
        return [Chunk(text.strip(), text.strip(), ChunkDocType.PRESCRIPTION)]

    @staticmethod
    def _chunk_lab_report(text: str) -> List[Chunk]:
        chunks = [
            Chunk(line.strip(), text.strip(), ChunkDocType.LAB_REPORT)
            for line in text.split("\n")
            if line.strip()
        ]
        return chunks if chunks else [Chunk(text, text, ChunkDocType.LAB_REPORT)]

    @staticmethod
    def _chunk_form(text: str) -> List[Chunk]:
        chunks = [
            Chunk(section.strip(), text.strip(), ChunkDocType.FORM)
            for section in text.split("\n\n")
            if section.strip()
        ]
        return chunks if chunks else [Chunk(text, text, ChunkDocType.FORM)]

    @staticmethod
    def _chunk_clinical_note(text: str) -> List[Chunk]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=512,
            chunk_overlap=50,
            separators=["\n\n", "\n", ". ", " "],
        )
        child_chunks = splitter.split_text(text)
        return [Chunk(child, text, ChunkDocType.CLINICAL_NOTE) for child in child_chunks]
