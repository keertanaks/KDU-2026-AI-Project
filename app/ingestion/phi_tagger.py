from presidio_analyzer import AnalyzerEngine
from typing import List


class PhiSpan:
    def __init__(self, span_type: str, start: int, end: int, confidence: float):
        self.span_type = span_type
        self.start = start
        self.end = end
        self.confidence = confidence

    def to_dict(self) -> dict:
        return {
            "type": self.span_type,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
        }


class PhiTagger:
    def __init__(self):
        self.analyzer = AnalyzerEngine()

    def tag(self, text: str) -> List[PhiSpan]:
        """Detect 18 HIPAA identifiers."""
        results = self.analyzer.analyze(text=text, language="en")
        return [
            PhiSpan(r.entity_type, r.start, r.end, r.score)
            for r in results
        ]
