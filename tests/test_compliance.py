"""
Tests for compliance components: AuditLogger, ACLResolver, and PHI safety.

DB tests require a running PostgreSQL instance (Docker).
PHI safety tests verify end-to-end masking contracts (no _REDACTED> in treating
clinician output, presence of _REDACTED> in non-treating output).
"""

import hashlib
import json
import unittest.mock as mock

from app.auth.models import AuditLog
from app.compliance.audit_logger import AuditLogger
from app.compliance.acl_resolver import ACLResolver
from app.search.masker import ResponseMasker
from app.search.answer_generator import _build_placeholder_context, AnswerGenerator


# ---------------------------------------------------------------------------
# Fixtures and shared test data (from conftest)
# ---------------------------------------------------------------------------

SAMPLE_TEXT_WITH_PHI = (
    "Patient: Emily Moore\n"
    "DOB: 1972-03-14\n"
    "MRN: MRN100003\n"
    "Diagnosis: Asthma (ICD: J45)\n"
    "Prescribing physician: Dr. David Thompson\n"
    "Date: 2025-04-22"
)

PHI_SPANS_PERSON = [{"type": "PERSON", "start": 9, "end": 20, "confidence": 0.85}]
PHI_SPANS_JSON = '[{"type": "PERSON", "start": 9, "end": 20, "confidence": 0.85}]'


# ---------------------------------------------------------------------------
# AuditLogger (integration — requires DB)
# ---------------------------------------------------------------------------

class TestAuditLogger:
    def test_query_hash_is_sha256_hex(self, db, test_user):
        AuditLogger.log_query(
            db, test_user.user_id, test_user.role,
            "What medications is the patient on?",
            ["doc-1", "doc-2"], "non_treating", 350,
        )
        row = db.query(AuditLog).filter_by(user_id=test_user.user_id).first()
        assert len(row.query_hash) == 64
        assert all(c in "0123456789abcdef" for c in row.query_hash)

    def test_query_hash_does_not_contain_raw_text(self, db, test_user):
        raw_query = "What medications is the patient on?"
        AuditLogger.log_query(
            db, test_user.user_id, test_user.role,
            raw_query, ["doc-1"], "non_treating", 200,
        )
        row = db.query(AuditLog).filter_by(user_id=test_user.user_id).first()
        assert raw_query not in row.query_hash

    def test_hash_is_deterministic(self, db, test_user):
        query = "Consistent query text for determinism check"
        AuditLogger.log_query(
            db, test_user.user_id, test_user.role, query, [], "none", 100,
        )
        expected = hashlib.sha256(query.encode()).hexdigest()
        row = db.query(AuditLog).filter_by(user_id=test_user.user_id).first()
        assert row.query_hash == expected

    def test_audit_row_created_in_db(self, db, test_user):
        uid = test_user.user_id
        before_count = db.query(AuditLog).filter_by(user_id=uid).count()
        AuditLogger.log_query(
            db, uid, test_user.role, "test query", ["doc-A"], "full", 500,
        )
        after_count = db.query(AuditLog).filter_by(user_id=uid).count()
        assert after_count == before_count + 1

    def test_document_ids_stored_as_json(self, db, test_user):
        doc_ids = ["doc-X", "doc-Y", "doc-Z"]
        AuditLogger.log_query(
            db, test_user.user_id, test_user.role, "query", doc_ids, "full", 100,
        )
        row = db.query(AuditLog).filter_by(user_id=test_user.user_id).first()
        stored_ids = json.loads(row.document_ids_returned)
        assert stored_ids == doc_ids

    def test_result_count_matches_doc_id_list(self, db, test_user):
        doc_ids = ["doc-1", "doc-2", "doc-3"]
        AuditLogger.log_query(
            db, test_user.user_id, test_user.role, "q", doc_ids, "none", 0,
        )
        row = db.query(AuditLog).filter_by(user_id=test_user.user_id).first()
        assert row.result_count == 3


# ---------------------------------------------------------------------------
# ACLResolver (integration — requires DB)
# ---------------------------------------------------------------------------

class TestACLResolver:
    def test_treating_clinician_sees_dept_and_admin(self, db, test_user):
        # test_user is TREATING_CLINICIAN, department="testdept"
        labels = ACLResolver.resolve_acl(db, test_user.user_id)
        assert "dept_testdept" in labels
        assert "admin_only" in labels

    def test_treating_clinician_not_in_research_allowed(self, db, test_user):
        labels = ACLResolver.resolve_acl(db, test_user.user_id)
        assert "research_allowed" not in labels

    def test_non_treating_clinician_sees_research_and_admin(self, db, test_nontreating_user):
        labels = ACLResolver.resolve_acl(db, test_nontreating_user.user_id)
        assert "research_allowed" in labels
        assert "admin_only" in labels

    def test_non_treating_clinician_not_in_dept_labels(self, db, test_nontreating_user):
        labels = ACLResolver.resolve_acl(db, test_nontreating_user.user_id)
        dept_labels = [l for l in labels if l.startswith("dept_")]
        assert dept_labels == []

    def test_administrator_has_full_access_set(self, db, test_admin_user):
        labels = ACLResolver.resolve_acl(db, test_admin_user.user_id)
        assert "admin_only" in labels
        assert "research_allowed" in labels
        assert "dept_cardiology" in labels

    def test_missing_user_returns_empty_list(self, db):
        labels = ACLResolver.resolve_acl(db, "nonexistent-user-id")
        assert labels == []


# ---------------------------------------------------------------------------
# PHI safety — masking role contracts
# ---------------------------------------------------------------------------

class TestPhiMaskingRoleContracts:
    def test_treating_clinician_sees_no_redacted_tokens(self):
        result = ResponseMasker.mask(SAMPLE_TEXT_WITH_PHI, PHI_SPANS_PERSON, "treating_clinician")
        assert "_REDACTED>" not in result

    def test_non_treating_clinician_sees_redacted_tokens(self):
        result = ResponseMasker.mask(SAMPLE_TEXT_WITH_PHI, PHI_SPANS_PERSON, "non_treating_clinician")
        assert "<PERSON_REDACTED>" in result

    def test_non_treating_clinician_original_phi_absent(self):
        result = ResponseMasker.mask(SAMPLE_TEXT_WITH_PHI, PHI_SPANS_PERSON, "non_treating_clinician")
        assert "Emily Moore" not in result

    def test_treating_clinician_original_phi_present(self):
        result = ResponseMasker.mask(SAMPLE_TEXT_WITH_PHI, PHI_SPANS_PERSON, "treating_clinician")
        assert "Emily Moore" in result

    def test_json_string_spans_handled_correctly(self):
        result = ResponseMasker.mask(SAMPLE_TEXT_WITH_PHI, PHI_SPANS_JSON, "non_treating_clinician")
        assert "<PERSON_REDACTED>" in result


# ---------------------------------------------------------------------------
# PHI safety — placeholder mapping cleared after generate()
# ---------------------------------------------------------------------------

class TestPlaceholderMappingLifecycle:
    def _chunk(self, text, phi_spans):
        return {"_source": {"text": text, "phi_spans": phi_spans, "doc_id": "test-doc"}}

    def test_mapping_cleared_after_build_and_use(self):
        """_build_placeholder_context returns a mapping that is callers' responsibility to clear."""
        chunks = [self._chunk("Emily Moore is the patient.", PHI_SPANS_PERSON)]
        _, mapping = _build_placeholder_context(chunks)
        assert len(mapping) > 0
        mapping.clear()
        assert len(mapping) == 0

    def test_generate_with_placeholder_key_does_not_expose_phi(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-placeholder")
        chunks = [self._chunk(SAMPLE_TEXT_WITH_PHI, PHI_SPANS_PERSON)]
        gen = AnswerGenerator()
        answer, status, _ = gen.generate("Who is the patient?", chunks, "treating_clinician")
        assert status == "skipped"
        assert "Emily Moore" not in answer

    def test_generate_with_placeholder_key_non_treating_no_phi(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-placeholder")
        chunks = [self._chunk(SAMPLE_TEXT_WITH_PHI, PHI_SPANS_PERSON)]
        gen = AnswerGenerator()
        answer, status, _ = gen.generate("Who is the patient?", chunks, "non_treating_clinician")
        assert status == "skipped"
        assert "Emily Moore" not in answer
        assert "_REDACTED>" not in answer

    def test_failed_api_call_does_not_expose_phi(self, monkeypatch):
        """Even when the API fails, no PHI should appear in the returned answer."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-realkey")
        monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

        with mock.patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.side_effect = Exception("connection refused")
            chunks = [self._chunk(SAMPLE_TEXT_WITH_PHI, PHI_SPANS_PERSON)]
            gen = AnswerGenerator()
            answer, status, _ = gen.generate("query", chunks, "treating_clinician")

        assert status == "failed"
        assert answer == ""
        assert "Emily Moore" not in answer
