# Security Checklist: Local Development vs Production

## Overview

This document outlines the current security posture for local development and deferred production requirements. The system is **HIPAA-aware** (implements PHI detection, role-based masking, and audit logging) but is **NOT HIPAA-certified**. Use for demo/development purposes only.

---

## Local Development Setup

### What's Implemented ✓

| Item | Status | Details |
|------|--------|---------|
| **HTTP Access** | ✓ | API runs on `http://localhost:8000` for local development |
| **Local Docker Storage** | ✓ | PostgreSQL and OpenSearch run in local containers without TLS |
| **Document Storage** | ✓ | `USE_LOCAL_STORAGE=true` stores PDFs as plain files on disk |
| **PHI Detection** | ✓ | Presidio + Spacy extract PHI entities (PERSON, LOCATION, DATE_TIME, ID, PHONE, EMAIL, DIAGNOSIS, MEDICATION) |
| **PHI Masking** | ✓ | Placeholders `[[PHI_TYPE_N]]` replace raw PHI in context sent to LLM |
| **Role-Based Redaction** | ✓ | `treating_clinician` gets original values; others get `<TYPE_REDACTED>` |
| **Session Cookies** | ✓ | `httponly=True`, `samesite="lax"`, `secure=False` (HTTP safe) |
| **Audit Logging** | ✓ | PostgreSQL immutable audit table tracks user actions without raw PHI |
| **No API Key Logging** | ✓ | OPENROUTER_API_KEY, OPENAI_API_KEY never logged or exposed |
| **No Placeholder Leaks** | ✓ | Mapping from `[[PHI_*]]` tokens to original PHI cleared immediately after LLM response |

### What's NOT Encrypted ⚠

- **Encryption-at-Rest**: PostgreSQL and OpenSearch in local Docker do NOT encrypt data at rest
- **Document Files**: PDF files stored locally are plain files (no file-system encryption)
- **Database Contents**: PostgreSQL stores data in plaintext on disk (no encryption-at-rest)
- **Credentials**: API keys in `.env` are plaintext (standard for local development)

---

## Production Requirements (Deferred)

### TLS/HTTPS

| Component | Local | Production | Notes |
|-----------|-------|-----------|-------|
| **FastAPI Backend** | HTTP | HTTPS (real certificate) | Self-signed not acceptable; real certificate required |
| **Frontend ↔ Backend** | `http://localhost:5173` | `https://api.example.com` | All API calls must use HTTPS |
| **Session Cookies** | `secure=False` | `secure=True` | Only transmitted over HTTPS in production |
| **OpenSearch** | HTTP `localhost:9200` | HTTPS with real certificate | TLS 1.2+ required |
| **PostgreSQL** | Plain connection | TLS 1.2+ with `sslmode=require` | All DB queries encrypted in transit |

### Data Encryption at Rest

| Layer | Local | Production | Notes |
|-------|-------|-----------|-------|
| **Document Storage** | Local disk | AWS S3 with SSE-KMS | Documents encrypted with customer-managed KMS key |
| **Database** | Plaintext PostgreSQL | Encrypted PostgreSQL instance (AWS RDS) | RDS encryption-at-rest enabled |
| **OpenSearch** | Plaintext local container | Encrypted OpenSearch (AWS OpenSearch service) | Encryption at rest enabled |
| **Audit Logs** | Local PostgreSQL | CloudWatch Logs encrypted | Immutable audit trail stored securely |
| **Credentials** | `.env` file | AWS Secrets Manager | No plaintext credentials in code/config |

### AWS Security (Deferred)

| Service | Status | Purpose |
|---------|--------|---------|
| **S3** | Deferred | Replaces `USE_LOCAL_STORAGE=true`; requires `S3_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| **KMS** | Deferred | Manages S3 object encryption keys; requires `KMS_KEY_ID` and IAM permissions |
| **RDS PostgreSQL** | Deferred | Encrypted database instance with automated backups |
| **OpenSearch Service** | Deferred | Managed OpenSearch with encryption at rest and in transit |

---

## Secure Cookie Configuration

### Current Implementation

```python
# app/main.py: /api/auth/login endpoint

response.set_cookie(
    "session_id",
    session_id,
    httponly=True,        # ✓ Prevents JavaScript access (blocks XSS theft)
    samesite="lax",       # ✓ Prevents CSRF attacks (allows top-level navigation)
    secure=IS_HTTPS or APP_ENV == "production"  # False for local dev, True for production
)
```

### Cookie Flags Explained

| Flag | Purpose | Local Dev | Production |
|------|---------|-----------|-----------|
| **httponly** | Prevents JS access to session token | `True` | `True` |
| **samesite** | Prevents CSRF attacks | `"lax"` | `"lax"` |
| **secure** | Only transmit over HTTPS | `False` | `True` |

---

## PHI Logging Safety

### Verified Safe ✓

| File | Check | Result |
|------|-------|--------|
| `app/search/answer_generator.py` | No raw PHI logged; mapping cleared before return | ✓ Safe |
| `app/ingestion/ocr_worker.py` | No raw OCR text printed; uses logging instead of print | ✓ Safe |
| `app/api/documents.py` | No raw document content logged | ✓ Safe |
| `app/ingestion/phi_tagger.py` | PHI spans stored as offsets, not text | ✓ Safe |
| `app/compliance/audit_logger.py` | Audit logs track actions, not raw PHI | ✓ Safe |

### What's Never Logged

- Raw OCR text extracted from documents
- Raw search queries from users
- API keys or credentials (OPENROUTER_API_KEY, OPENAI_API_KEY, AWS credentials)
- PHI placeholder mappings (cleared from memory immediately after use)
- Patient names, dates of birth, MRN, SSN, or other sensitive identifiers

---

## Recommendations for Production

Before moving to production, complete these items:

1. **Obtain Real Certificates**: Get TLS certificates from a trusted CA (e.g., Let's Encrypt, DigiCert)
2. **Enable HTTPS**: Update FastAPI and frontend to use real certificates
3. **Configure S3 + KMS**: Set up AWS S3 bucket, KMS key, and IAM roles
4. **Update Environment**: Set `APP_ENV=production` and `IS_HTTPS=true` in production
5. **Database Encryption**: Migrate PostgreSQL to AWS RDS with encryption at rest
6. **OpenSearch Encryption**: Migrate to AWS OpenSearch with encryption enabled
7. **Audit Trail**: Ensure CloudWatch Logs are encrypted and retained long-term
8. **Testing**: Run full security audit and penetration testing before deployment
9. **Compliance Review**: Have legal/compliance review HIPAA requirements (system is HIPAA-aware, not HIPAA-certified)

---

## Disclaimer

**This system is HIPAA-aware but NOT HIPAA-certified.**

The implementation includes:
- ✓ PHI detection and masking
- ✓ Role-based access control
- ✓ Immutable audit logging
- ✓ Secure session handling

The implementation does NOT include:
- ✗ Business Associate Agreement (BAA) with cloud providers
- ✗ Full encryption-at-rest in local dev environment
- ✗ HIPAA-certified backup and disaster recovery
- ✗ Signed off compliance certification

**For demo and development purposes only. Do not use with real patient data in production without proper HIPAA certification.**

---

## Quick Reference: What Needs Doing Before Production

- [ ] Real TLS certificates for FastAPI
- [ ] Real TLS certificates for OpenSearch and PostgreSQL
- [ ] AWS account setup with S3, KMS, RDS, OpenSearch
- [ ] Update environment variables: `APP_ENV=production`, `IS_HTTPS=true`
- [ ] Security audit and penetration testing
- [ ] Legal review for HIPAA compliance
- [ ] Document data retention and disaster recovery policies
