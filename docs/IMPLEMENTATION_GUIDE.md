# Healthcare Semantic Search — Implementation Guide

**Version:** 1.0  
**Scope:** ~1000 synthetic medical records · RAG (no GraphRAG) · HIPAA-aware  
**Timeline:** 3 weeks · 5 phases  
**Status:** Ready for implementation

---

## Architecture Overview

**Two Independent Pipelines:**
- **Ingestion Pipeline** (synchronous, ~45 sec/doc): Document upload → OCR → chunking → embedding → indexing
- **Search Pipeline** (real-time, <1500ms P95): Query → retrieval → reranking → masking → response

**Shared Infrastructure:**
- FastAPI Gateway + Session-based Auth
- OpenSearch (local Docker, HNSW + BM25)
- PostgreSQL (audit log, sessions, users)
- LangSmith (tracing)
- AWS S3 + KMS (encrypted storage)

---

## Phase 0: Setup & Infrastructure 

### 0.1 Environment & Dependencies

```bash
# Python 3.11+, virtual environment
python -m venv venv
source venv/bin/activate

# Core dependencies
pip install fastapi uvicorn pydantic python-multipart
pip install sqlalchemy psycopg2-binary
pip install opensearchpy
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install transformers numpy scipy scikit-learn
pip install sentence-transformers
pip install pillow opencv-python
pip install pytesseract paddleocr
pip install pymupdf
pip install presidio-analyzer presidio-anonymizer
pip install openai
pip install langchain langgraph langsmith
pip install ragas boto3 fastapi-sessions bcrypt

# Dev tools
pip install pytest pytest-asyncio black isort flake8 mypy
```

### 0.2 Docker Services

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  opensearch:
    image: opensearchproject/opensearch:2.11.0
    environment:
      - discovery.type=single-node
      - OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m
      - DISABLE_SECURITY_PLUGIN=true
    ports:
      - "9200:9200"
    volumes:
      - opensearch_data:/usr/share/opensearch/data

  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=healthcare_user
      - POSTGRES_PASSWORD=secure_password
      - POSTGRES_DB=healthcare_rag
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  opensearch_data:
  postgres_data:
```

Run: `docker-compose up -d`

### 0.3 AWS Credentials

Store in `config/.env`:

```
AWS_ACCESS_KEY_ID=***
AWS_SECRET_ACCESS_KEY=***
AWS_REGION=us-east-1
S3_BUCKET_NAME=healthcare-rag-docs

OPENAI_API_KEY=***
LANGSMITH_API_KEY=***

DB_HOST=localhost
DB_PORT=5432
DB_USER=healthcare_user
DB_PASSWORD=secure_password
DB_NAME=healthcare_rag

OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
```
### 0.3.1 Real AWS S3 + KMS Setup

TODO before Phase 2.1:
- Create S3 bucket `healthcare-rag-docs`
- Block public access
- Enable bucket versioning
- Create customer-managed KMS key `healthcare-rag-kms`
- Enable KMS key rotation
- Configure S3 default encryption with SSE-KMS
- Create IAM user/role with S3 + KMS permissions
- Add real values to `config/.env`

Required extra env var:
KMS_KEY_ID=arn:aws:kms:<region>:<account-id>:key/<key-id>

### 0.4 Project Structure

```
healthcare-rag/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── documents.py    # Document upload endpoints
│   │   └── search.py       # Search endpoints
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── service.py
│   │   └── middleware.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── classifier.py
│   │   ├── preprocessor.py
│   │   ├── ocr_worker.py
│   │   ├── text_cleaner.py
│   │   ├── chunker.py
│   │   ├── phi_tagger.py
│   │   ├── embedder.py
│   │   └── indexer.py
│   ├── search/
│   │   ├── __init__.py
│   │   ├── graph.py        # LangGraph state machine
│   │   ├── retriever.py
│   │   ├── reranker.py
│   │   └── masker.py
│   ├── compliance/
│   │   ├── __init__.py
│   │   ├── audit_logger.py
│   │   └── acl_resolver.py
│   ├── storage/
│   │   ├── __init__.py
│   │   └── s3_service.py
│   ├── evaluation/
│   │   ├── __init__.py
│   │   └── ragas_eval.py   # Post-deployment
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── document.py
│   │   └── query.py
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   └── main.py
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── components/
│   │   │   ├── SearchBar.jsx
│   │   │   ├── ResultsList.jsx
│   │   │   ├── MaskingIndicator.jsx
│   │   │   └── AuditDashboard.jsx
│   │   ├── pages/
│   │   │   ├── SearchPage.jsx
│   │   │   ├── LoginPage.jsx
│   │   │   └── AdminDashboard.jsx
│   │   ├── services/
│   │   │   ├── api.js
│   │   │   └── auth.js
│   │   ├── App.jsx
│   │   ├── App.css
│   │   └── index.jsx
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
├── scripts/
│   ├── init_db.py
│   ├── init_opensearch.py
│   ├── generate_golden_set.py
│   └── run_ragas_eval.py
├── tests/
│   ├── __init__.py
│   ├── test_ingestion.py
│   ├── test_search.py
│   ├── test_auth.py
│   └── test_compliance.py
├── alembic/
│   ├── versions/
│   │   └── 001_initial_schema.py
│   ├── env.py
│   └── alembic.ini
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
├── .flake8
├── .pre-commit-config.yaml
├── pytest.ini
└── README.md
```

### Phase 0 Exit Criteria

- [ ] `docker-compose up -d` completes without errors
- [ ] `docker ps` shows opensearch and postgres containers running
- [ ] `curl http://localhost:9200` returns OpenSearch cluster info JSON
- [ ] `psql -h localhost -U healthcare_user -d healthcare_rag -c "SELECT 1"` succeeds (password: secure_password)
- [ ] `python -c "import app; print('✅ FastAPI imports successfully')"` succeeds
- [ ] `npm -v && node -v` shows Node/npm installed in frontend/
- [ ] `cat config/.env` shows all required variables set (AWS_ACCESS_KEY_ID, OPENAI_API_KEY, etc.)
- [ ] `python scripts/init_opensearch.py` creates healthcare_chunks index without errors
- [ ] `python scripts/init_db.py` creates all tables in PostgreSQL without errors
- [ ] `python -m pytest tests/ -v` runs (may fail but imports succeed)

---

## Phase 1: Authentication & Database 

### 1.1 Database Models

**File:** `app/auth/models.py`

```python
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Enum, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum

Base = declarative_base()

class UserRole(str, enum.Enum):
    TREATING_CLINICIAN = "treating_clinician"
    NON_TREATING_CLINICIAN = "non_treating_clinician"
    ADMINISTRATOR = "administrator"

class User(Base):
    __tablename__ = "users"
    
    user_id = Column(String(36), primary_key=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(LargeBinary, nullable=False)  # bcrypt
    role = Column(Enum(UserRole), nullable=False)
    department = Column(String(255), nullable=True)  # for ACL
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

class Session(Base):
    __tablename__ = "sessions"
    
    session_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    role = Column(Enum(UserRole), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_valid = Column(Boolean, default=True)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    audit_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    role = Column(Enum(UserRole), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    query_hash = Column(String(64), nullable=False)  # SHA-256
    document_ids_returned = Column(String(4096), nullable=True)
    masking_applied = Column(String(255), nullable=True)
    result_count = Column(Integer, default=0)
    latency_ms = Column(Integer, nullable=True)
```

### 1.2 Auth Service

**File:** `app/auth/service.py`

```python
import hashlib
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session as DBSession
from app.auth.models import User, Session, UserRole
import bcrypt

class AuthService:
    @staticmethod
    def hash_password(password: str) -> bytes:
        """Bcrypt hash."""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12))
    
    @staticmethod
    def verify_password(password: str, password_hash: bytes) -> bool:
        """Verify bcrypt hash."""
        return bcrypt.checkpw(password.encode('utf-8'), password_hash)
    
    @staticmethod
    def create_session(db: DBSession, user_id: str, role: UserRole) -> str:
        """Create server-side session."""
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_id=user_id,
            role=role,
            expires_at=datetime.utcnow() + timedelta(hours=8)
        )
        db.add(session)
        db.commit()
        return session_id
    
    @staticmethod
    def validate_session(db: DBSession, session_id: str) -> dict | None:
        """Validate session."""
        session = db.query(Session).filter(
            Session.session_id == session_id,
            Session.is_valid == True,
            Session.expires_at > datetime.utcnow()
        ).first()
        
        if not session:
            return None
        
        return {
            "user_id": session.user_id,
            "role": session.role,
            "session_id": session_id
        }
    
    @staticmethod
    def revoke_session(db: DBSession, session_id: str):
        """Revoke session on logout."""
        session = db.query(Session).filter_by(session_id=session_id).first()
        if session:
            session.is_valid = False
            db.commit()
```

### Phase 1 Exit Criteria

- [ ] User created in DB: `psql -h localhost -U healthcare_user -d healthcare_rag -c "SELECT username, role FROM users LIMIT 1"` returns one row
- [ ] Login endpoint reachable: `curl -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"test_user","password":"test_pass"}'` returns 200 or 401 (endpoint exists)
- [ ] Session cookie set on login: `curl -i -X POST http://localhost:8000/api/auth/login -d ... | grep Set-Cookie` shows session_id cookie
- [ ] Session validated: `psql ... -c "SELECT COUNT(*) FROM sessions WHERE is_valid=true"` shows >= 1 valid sessions
- [ ] Logout revokes session: Create session, call `/api/auth/logout`, verify `is_valid=false` in DB
- [ ] Role resolution works: Query `SELECT user_id, role FROM sessions` and verify role matches user's role
- [ ] Protected endpoint denies unauth: `curl http://localhost:8000/api/search` (no session) returns 401
- [ ] Protected endpoint allows auth: `curl -b "session_id=<valid>" http://localhost:8000/api/search` accepts request (may 400 due to missing query, but auth passed)
- [ ] bcrypt password hashing: `psql ... -c "SELECT password_hash FROM users"` shows 60-char bcrypt hash, not plaintext

---

## Phase 1.6: Frontend Setup (React + Vite + Tailwind)

### 1.6 React Frontend Initialization

**Create frontend folder:**

```bash
cd healthcare-rag
npm create vite@latest frontend -- --template react
cd frontend
npm install
npm install -D tailwindcss postcss autoprefixer
npm install axios
npx tailwindcss init -p
```

**File:** `frontend/package.json`

```json
{
  "name": "healthcare-rag-frontend",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "axios": "^1.6.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.0.0",
    "vite": "^4.4.0",
    "tailwindcss": "^3.3.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0"
  }
}
```

**File:** `frontend/src/services/api.js`

```javascript
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

export const apiClient = axios.create({
  baseURL: API_BASE,
  withCredentials: true  // Send cookies
});

export const searchAPI = {
  search: (query) => apiClient.post('/search', { query }),
  upload: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return apiClient.post('/ingest', formData);
  }
};

export const authAPI = {
  login: (username, password) => apiClient.post('/auth/login', { username, password }),
  logout: () => apiClient.post('/auth/logout')
};
```

**File:** `frontend/src/pages/SearchPage.jsx`

```jsx
import React, { useState } from 'react';
import { searchAPI } from '../services/api.js';
import SearchBar from '../components/SearchBar';
import ResultsList from '../components/ResultsList';

export default function SearchPage() {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);

  const handleSearch = async (query) => {
    setLoading(true);
    try {
      const response = await searchAPI.search(query);
      setResults(response.data.masked_results);
    } catch (error) {
      console.error('Search failed', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container mx-auto p-6">
      <h1 className="text-3xl font-bold mb-6">Healthcare Semantic Search</h1>
      <SearchBar onSearch={handleSearch} />
      {loading && <p>Loading...</p>}
      <ResultsList results={results} />
    </div>
  );
}
```

**File:** `frontend/tailwind.config.js`

```javascript
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

### Phase 1.6 Exit Criteria

- [ ] React app builds: `cd frontend && npm run build` completes without errors, creates dist/ folder
- [ ] Vite dev server starts: `cd frontend && npm run dev` shows "Local: http://localhost:5173"
- [ ] Tailwind CSS processes: `dist/assets/index-*.css` exists and contains @tailwind rules
- [ ] Frontend imports axios: `grep "import axios" frontend/src/services/api.js` succeeds
- [ ] API service configured: `grep "withCredentials: true" frontend/src/services/api.js` shows credentials enabled
- [ ] SearchPage component renders: Open http://localhost:5173 in browser, see "Healthcare Semantic Search" heading
- [ ] Search form interactive: Click SearchBar input, typing works, no console errors

---

## Phase 2.1: Ingestion Pipeline 
Before implementing S3Service, complete the Real AWS S3 + KMS Setup from Section 0.3.1.
Do not proceed with document upload until `KMS_KEY_ID`, bucket access, and test upload are verified.
### 2.0 S3 Storage Service

**File:** `app/storage/s3_service.py`

```python
import boto3
import os
from typing import BinaryIO
import uuid

class S3Service:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION")
        )
        self.bucket_name = os.getenv("S3_BUCKET_NAME")
    
    def upload_pdf(self, file_obj: BinaryIO, doc_id: str) -> str:
        """
        Upload PDF to S3 with SSE-KMS encryption.
        Returns S3 object URL.
        """
        key = f"documents/{doc_id}.pdf"
        
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=file_obj.read(),
            ServerSideEncryption='aws:kms',
            SSEKMSKeyId=os.getenv("KMS_KEY_ID"),
            Metadata={'doc_id': doc_id}
        )
        
        return f"s3://{self.bucket_name}/{key}"
    
    def download_pdf(self, doc_id: str) -> bytes:
        """Download PDF from S3."""
        key = f"documents/{doc_id}.pdf"
        
        response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
        return response['Body'].read()
    
    def delete_pdf(self, doc_id: str):
        """Delete PDF from S3."""
        key = f"documents/{doc_id}.pdf"
        self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
```

---

### 2.1 Document Classifier

**File:** `app/ingestion/classifier.py`

```python
import fitz
import cv2
import numpy as np
from enum import Enum

class DocType(str, Enum):
    TYPED = "typed"
    SCANNED = "scanned"
    HANDWRITTEN = "handwritten"

class DocumentClassifier:
    @staticmethod
    def classify(pdf_path: str) -> tuple[DocType, dict]:
        """
        Classify as TYPED, SCANNED, or HANDWRITTEN.
        Step 1: PyMuPDF text probe → TYPED if >100 chars
        Step 2: Contrast + edges + density → SCANNED vs HANDWRITTEN
        """
        doc = fitz.open(pdf_path)
        page = doc[0]
        
        # Text probe
        text = page.get_text()
        if len(text.strip()) > 100:
            doc.close()
            return DocType.TYPED, {"confidence": 0.99}
        
        # Render and analyze
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_array = np.frombuffer(pix.samples, dtype=np.uint8)
        img_array = img_array.reshape((pix.height, pix.width, pix.n))
        img_rgb = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        
        scores = DocumentClassifier._compute_heuristics(img_rgb)
        doc.close()
        
        doc_type = DocType.SCANNED if scores['is_scanned'] else DocType.HANDWRITTEN
        return doc_type, scores
    
    @staticmethod
    def _compute_heuristics(img: np.ndarray) -> dict:
        """Compute contrast, edges, density."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Contrast
        contrast = float(np.std(gray))
        
        # Edges
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.sum(edges) / edges.size)
        
        # Text density
        _, binary = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
        text_density = float(np.sum(binary) / binary.size)
        
        # Heuristic
        is_scanned = (contrast > 30) and (edge_density < 0.05)
        
        return {
            "contrast_std": contrast,
            "edge_density": edge_density,
            "text_density": text_density,
            "is_scanned": is_scanned,
            "confidence": 0.85 if is_scanned else 0.90
        }
```

### 2.2 Preprocessing Pipeline

**File:** `app/ingestion/preprocessor.py`

```python
import cv2
import numpy as np
import fitz

class PreprocessingPipeline:
    """Preprocessing for scanned/handwritten pages before OCR."""
    
    @staticmethod
    def preprocess(pdf_path: str, page_num: int = 0, dpi: int = 300) -> np.ndarray:
        """
        Pipeline:
        1. Render at 300 DPI
        2. Crop bounding box
        3. Grayscale
        4. CLAHE contrast
        5. Sharpen
        6. Safe deskew
        """
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        
        img = np.frombuffer(pix.samples, dtype=np.uint8)
        img = img.reshape((pix.height, pix.width, pix.n))
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        doc.close()
        
        img = PreprocessingPipeline._crop_bounding_box(img)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # Sharpen
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharpened = cv2.filter2D(enhanced, -1, kernel)
        
        # Deskew
        angle = PreprocessingPipeline._detect_skew(sharpened)
        if abs(angle) > 5:
            rows, cols = sharpened.shape
            M = cv2.getRotationMatrix2D((cols/2, rows/2), angle, 1)
            sharpened = cv2.warpAffine(sharpened, M, (cols, rows))
        
        return sharpened
    
    @staticmethod
    def _crop_bounding_box(img: np.ndarray) -> np.ndarray:
        """Remove margins."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return img
        
        x, y, w, h = cv2.boundingRect(max(contours, key=cv2.contourArea))
        return img[max(0, y-10):min(img.shape[0], y+h+10),
                   max(0, x-10):min(img.shape[1], x+w+10)]
    
    @staticmethod
    def _detect_skew(img: np.ndarray) -> float:
        """Detect skew angle."""
        edges = cv2.Canny(img, 50, 150)
        lines = cv2.HoughLines(edges, 1, np.pi/180, 100)
        
        if lines is None:
            return 0.0
        
        angles = [line[0][1] * 180/np.pi - 90 for line in lines[:20]]
        return float(np.median(angles))
```

### 2.3 OCR Worker

**File:** `app/ingestion/ocr_worker.py`

```python
import pytesseract
from paddleocr import PaddleOCR
import numpy as np
from enum import Enum
from app.ingestion.classifier import DocType
from app.ingestion.preprocessor import PreprocessingPipeline
import fitz

class OCRWorker:
    def __init__(self):
        self.paddle_ocr = PaddleOCR(use_angle_cls=True, lang='en')
    
    def extract_text(self, pdf_path: str, doc_type: DocType) -> dict:
        """Route OCR based on document type."""
        if doc_type == DocType.TYPED:
            return self._extract_typed(pdf_path)
        elif doc_type == DocType.SCANNED:
            return self._extract_scanned(pdf_path)
        else:
            return self._extract_handwritten(pdf_path)
    
    def _extract_typed(self, pdf_path: str) -> dict:
        """PyMuPDF extraction (99%+ accuracy)."""
        doc = fitz.open(pdf_path)
        full_text = ""
        
        for page in doc:
            full_text += page.get_text() + "\n"
        
        doc.close()
        
        return {
            "text": full_text,
            "doc_type": DocType.TYPED,
            "success_rate": 0.99,
            "method": "PyMuPDF"
        }
    
    def _extract_scanned(self, pdf_path: str) -> dict:
        """Tesseract OCR (92-95% accuracy)."""
        doc = fitz.open(pdf_path)
        full_text = ""
        
        for page_num, page in enumerate(doc):
            img = PreprocessingPipeline.preprocess(pdf_path, page_num)
            text = pytesseract.image_to_string(img, config='--oem 1 --psm 3')
            full_text += text + "\n"
        
        doc.close()
        
        return {
            "text": full_text,
            "doc_type": DocType.SCANNED,
            "success_rate": 0.93,
            "method": "Tesseract 5"
        }
    
    def _extract_handwritten(self, pdf_path: str) -> dict:
        """PaddleOCR (85-90% accuracy)."""
        doc = fitz.open(pdf_path)
        full_text = ""
        
        for page_num in range(len(doc)):
            img = PreprocessingPipeline.preprocess(pdf_path, page_num)
            results = self.paddle_ocr.ocr(img, cls=True)
            page_text = "\n".join([line[1][0] for line in results[0]])
            full_text += page_text + "\n"
        
        doc.close()
        
        return {
            "text": full_text,
            "doc_type": DocType.HANDWRITTEN,
            "success_rate": 0.87,
            "method": "PaddleOCR PP-OCRv5"
        }
```

### 2.4 Adaptive Chunker

**File:** `app/ingestion/chunker.py`

```python
from enum import Enum
from typing import List
from langchain.text_splitter import RecursiveCharacterTextSplitter

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
        """Detect document type from text."""
        token_count = len(text.split())
        
        if token_count < 300 and any(x in text.lower() for x in ['mg', 'dose', 'tablet']):
            return ChunkDocType.PRESCRIPTION
        
        if any(x in text.lower() for x in ['normal range', 'result', 'flag']):
            return ChunkDocType.LAB_REPORT
        
        if any(x in text.lower() for x in ['name:', 'date:', 'patient:']):
            return ChunkDocType.FORM
        
        return ChunkDocType.CLINICAL_NOTE
    
    @staticmethod
    def chunk(text: str, doc_type: ChunkDocType = None) -> List[Chunk]:
        """Route to appropriate chunking strategy."""
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
        """Atomic chunk for prescriptions."""
        return [Chunk(text.strip(), text.strip(), ChunkDocType.PRESCRIPTION)]
    
    @staticmethod
    def _chunk_lab_report(text: str) -> List[Chunk]:
        """Row-serialized for lab reports."""
        chunks = []
        for line in text.split('\n'):
            if line.strip():
                chunks.append(Chunk(line.strip(), text.strip(), ChunkDocType.LAB_REPORT))
        return chunks if chunks else [Chunk(text, text, ChunkDocType.LAB_REPORT)]
    
    @staticmethod
    def _chunk_form(text: str) -> List[Chunk]:
        """Key-value groups for forms."""
        chunks = []
        for section in text.split('\n\n'):
            if section.strip():
                chunks.append(Chunk(section.strip(), text.strip(), ChunkDocType.FORM))
        return chunks if chunks else [Chunk(text, text, ChunkDocType.FORM)]
    
    @staticmethod
    def _chunk_clinical_note(text: str) -> List[Chunk]:
        """Parent-child for clinical notes."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=512,
            chunk_overlap=50,
            separators=["\n\n", "\n", ". ", " "]
        )
        
        child_chunks = splitter.split_text(text)
        return [Chunk(child, text, ChunkDocType.CLINICAL_NOTE) for child in child_chunks]
```

### 2.5 PHI Tagger

**File:** `app/ingestion/phi_tagger.py`

```python
from presidio_analyzer import AnalyzerEngine
from typing import List

class PhiSpan:
    def __init__(self, span_type: str, start: int, end: int, confidence: float):
        self.span_type = span_type
        self.start = start
        self.end = end
        self.confidence = confidence
    
    def to_dict(self):
        return {
            "type": self.span_type,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence
        }

class PhiTagger:
    def __init__(self):
        self.analyzer = AnalyzerEngine()
    
    def tag(self, text: str) -> List[PhiSpan]:
        """Detect 18 HIPAA identifiers."""
        results = self.analyzer.analyze(text=text, language="en")
        
        return [
            PhiSpan(result.entity_type, result.start, result.end, result.score)
            for result in results
        ]
```

### 2.6 Embedder & Indexer

**File:** `app/ingestion/embedder.py`

```python
from openai import OpenAI
from typing import List
import os

class Embedder:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "text-embedding-3-small"
        self.dimensions = 1536
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts efficiently."""
        if not texts:
            return []
        
        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions
        )
        
        embeddings = sorted(response.data, key=lambda x: x.index)
        return [e.embedding for e in embeddings]
```

**File:** `app/ingestion/indexer.py`

```python
from opensearchpy import OpenSearch
import os

class Indexer:
    def __init__(self):
        self.client = OpenSearch(
            hosts=[{"host": os.getenv("OPENSEARCH_HOST"), "port": int(os.getenv("OPENSEARCH_PORT"))}],
            http_auth=("admin", "admin"),
            use_ssl=False,
            verify_certs=False
        )
        self.index_name = "healthcare_chunks"
    
    def ensure_index(self):
        """Create index if doesn't exist."""
        if self.client.indices.exists(index=self.index_name):
            return
        
        mapping = {
            "settings": {
                "index.knn": True,
                "number_of_shards": 1,
                "number_of_replicas": 0
            },
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "doc_id": {"type": "keyword"},
                    "text": {"type": "text"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": 1536,
                        "method": {
                            "name": "hnsw",
                            "space_type": "l2",
                            "engine": "lucene",
                            "parameters": {"ef_construction": 256, "m": 16}
                        }
                    },
                    "doc_type": {"type": "keyword"},
                    "date": {"type": "date"},
                    "phi_spans": {"type": "text"},
                    "acl": {"type": "keyword"}
                }
            }
        }
        
        self.client.indices.create(index=self.index_name, body=mapping)
    
    def index_chunks(self, chunks: list) -> int:
        """Bulk index chunks."""
        from opensearchpy.helpers import bulk
        
        if not chunks:
            return 0
        
        actions = [
            {
                "_index": self.index_name,
                "_id": chunk["chunk_id"],
                "_source": chunk
            }
            for chunk in chunks
        ]
        
        success_count, errors = bulk(self.client, actions, raise_on_error=False)
        
        if errors:
            print(f"Indexing errors: {errors}")
        
        return success_count
```

### Phase 2.1 Exit Criteria

- [ ] Classifier executes: `python -c "from app.ingestion.classifier import DocumentClassifier; print(DocumentClassifier.classify('test.pdf'))"` succeeds (test PDF exists)
- [ ] TYPED PDF detected correctly: Classify a PDF with text layer, verify returns DocType.TYPED
- [ ] SCANNED PDF detected correctly: Classify a scanned image PDF, verify returns DocType.SCANNED
- [ ] HANDWRITTEN PDF detected correctly: Classify a handwritten notes PDF, verify returns DocType.HANDWRITTEN
- [ ] Preprocessor executes: `python -c "from app.ingestion.preprocessor import PreprocessingPipeline; img = PreprocessingPipeline.preprocess('test.pdf'); print(img.shape)"` succeeds, returns image shape
- [ ] PyMuPDF extraction works: Extract text from typed PDF, verify len(text) > 100
- [ ] Tesseract OCR works: `python -c "import pytesseract; pytesseract.pytesseract.pytesseract_cmd = '/usr/bin/tesseract'; print(pytesseract.get_languages())"` lists available languages
- [ ] PaddleOCR works: `python -c "from paddleocr import PaddleOCR; ocr = PaddleOCR(use_angle_cls=True, lang='en'); print('✅')"` succeeds (may download model)
- [ ] Adaptive chunker handles prescriptions: `from app.ingestion.chunker import AdaptiveChunker; chunks = AdaptiveChunker.chunk('Warfarin 5mg daily'); assert len(chunks) == 1`
- [ ] Adaptive chunker handles clinical notes: Chunk a long clinical note, verify multiple child chunks returned with parent_text intact
- [ ] PHI tagger detects identifiers: `from app.ingestion.phi_tagger import PhiTagger; tagger = PhiTagger(); spans = tagger.tag('John Smith MRN 123456'); assert len(spans) >= 2`
- [ ] Embedder batches texts: `from app.ingestion.embedder import Embedder; e = Embedder(); embs = e.embed_batch(['test1', 'test2']); assert len(embs) == 2 and len(embs[0]) == 1536`
- [ ] S3 upload works: `python -c "from app.storage.s3_service import S3Service; s3 = S3Service(); print('✅ boto3 client initialized')"` succeeds
- [ ] OpenSearch indexing works: `curl http://localhost:9200/healthcare_chunks/_doc/test_chunk_1 -X PUT -H "Content-Type: application/json" -d '{...}'` returns 201
- [ ] OpenSearch metadata stored: Query indexed chunk, verify phi_spans, acl, doc_type fields present
- [ ] Real AWS S3 + KMS setup completed before Phase 2.1

---

## Phase 2.2: Search Pipeline 

### 2.1 LangGraph State Machine

**File:** `app/search/graph.py`

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Dict
from app.search.retriever import HybridRetriever
from app.search.reranker import Reranker
from app.search.masker import ResponseMasker
from app.compliance.audit_logger import AuditLogger
from app.compliance.acl_resolver import ACLResolver
from app.ingestion.embedder import Embedder
import time

class SearchState(TypedDict):
    """State passed through search pipeline."""
    query_text: str
    user_id: str
    role: str
    db: object  # Database session passed through state
    normalized_query: str
    user_acl: List[str]
    query_embedding: List[float]
    candidates: List[Dict]
    reranked: List[Dict]
    masked_results: List[Dict]
    latency_ms: int
    start_time: float

class SearchGraph:
    def __init__(self):
        self.retriever = HybridRetriever()
        self.reranker = Reranker()
        self.embedder = Embedder()
        self.graph = self._build_graph()
    
    def _build_graph(self):
        """Build LangGraph state machine."""
        workflow = StateGraph(SearchState)
        
        # Nodes
        workflow.add_node("normalize_query", self._normalize_query)
        workflow.add_node("resolve_acl", self._resolve_acl)
        workflow.add_node("embed_query", self._embed_query)
        workflow.add_node("retrieve", self._retrieve)
        workflow.add_node("rerank", self._rerank)
        workflow.add_node("mask", self._mask)
        workflow.add_node("respond", self._respond)
        
        # Edges
        workflow.add_edge("normalize_query", "resolve_acl")
        workflow.add_edge("resolve_acl", "embed_query")
        workflow.add_edge("embed_query", "retrieve")
        workflow.add_edge("retrieve", "rerank")
        workflow.add_edge("rerank", "mask")
        workflow.add_edge("mask", "respond")
        workflow.add_edge("respond", END)
        
        # Set entry point
        workflow.set_entry_point("normalize_query")
        
        return workflow.compile()
    
    def _normalize_query(self, state: SearchState) -> SearchState:
        """Step 1: Normalize query text."""
        # Simple normalization (spell-check, trim, lowercase)
        normalized = state["query_text"].strip().lower()
        state["normalized_query"] = normalized
        return state
    
    def _resolve_acl(self, state: SearchState) -> SearchState:
        """Step 2: Resolve user's ACL."""
        acl = ACLResolver.resolve_acl(state["db"], state["user_id"])
        state["user_acl"] = acl
        return state
    
    def _embed_query(self, state: SearchState) -> SearchState:
        """Step 3: Embed normalized query."""
        embedding = self.embedder.embed_batch([state["normalized_query"]])[0]
        state["query_embedding"] = embedding
        return state
    
    def _retrieve(self, state: SearchState) -> SearchState:
        """Step 4: Hybrid retrieval (BM25 + kNN)."""
        filters = {
            "acl": state["user_acl"]
        }
        candidates = self.retriever.retrieve(
            state["query_embedding"],
            state["normalized_query"],
            filters,
            k=50
        )
        state["candidates"] = candidates
        return state
    
    def _rerank(self, state: SearchState) -> SearchState:
        """Step 5: Cross-encoder reranking."""
        reranked = self.reranker.rerank(
            state["normalized_query"],
            state["candidates"],
            top_n=5
        )
        state["reranked"] = reranked
        return state
    
    def _mask(self, state: SearchState) -> SearchState:
        """Step 6: Apply role-based masking."""
        masked = []
        for chunk in state["reranked"]:
            phi_spans = chunk.get("_source", {}).get("phi_spans", [])
            masked_text = ResponseMasker.mask(
                chunk["_source"]["text"],
                phi_spans,
                state["role"]
            )
            masked.append({
                "text": masked_text,
                "doc_id": chunk["_source"]["doc_id"],
                "score": chunk.get("rerank_score", 0)
            })
        state["masked_results"] = masked
        return state
    
    def _respond(self, state: SearchState) -> SearchState:
        """Step 7: Log to audit and return."""
        latency_ms = int((time.time() - state["start_time"]) * 1000)
        state["latency_ms"] = latency_ms
        
        doc_ids = [r["doc_id"] for r in state["masked_results"]]
        AuditLogger.log_query(
            state["db"],
            state["user_id"],
            state["role"],
            state["query_text"],
            doc_ids,
            "applied" if state["role"] != "treating_clinician" else "none",
            latency_ms
        )
        
        return state
    
    def invoke(self, query_text: str, user_id: str, role: str, db) -> Dict:
        """Execute search pipeline."""
        initial_state = SearchState(
            query_text=query_text,
            user_id=user_id,
            role=role,
            db=db,  # Pass db through state
            normalized_query="",
            user_acl=[],
            query_embedding=[],
            candidates=[],
            reranked=[],
            masked_results=[],
            latency_ms=0,
            start_time=time.time()
        )
        
        result = self.graph.invoke(initial_state)
        return result
```

---

### 2.2 Hybrid Retriever

**File:** `app/search/retriever.py`

```python
from opensearchpy import OpenSearch
import os
from typing import List, Dict

class HybridRetriever:
    def __init__(self):
        self.client = OpenSearch(
            hosts=[{"host": os.getenv("OPENSEARCH_HOST"), "port": int(os.getenv("OPENSEARCH_PORT"))}],
            http_auth=("admin", "admin"),
            use_ssl=False,
            verify_certs=False
        )
        self.index_name = "healthcare_chunks"
    
    def retrieve(self, query_embedding: List[float], query_text: str, 
                 filters: Dict, k: int = 50) -> List[Dict]:
        """Hybrid retrieval with RRF fusion."""
        
        # Pre-filter
        must_clauses = []
        if "acl" in filters:
            must_clauses.append({"terms": {"acl": filters["acl"]}})
        if "doc_type" in filters:
            must_clauses.append({"term": {"doc_type": filters["doc_type"]}})
        
        # BM25 search
        bm25_query = {
            "query": {
                "bool": {
                    "must": [{"multi_match": {"query": query_text, "fields": ["text"]}}],
                    "filter": must_clauses
                }
            },
            "size": k
        }
        bm25_results = self.client.search(index=self.index_name, body=bm25_query)
        
        # kNN search
        knn_query = {
            "query": {
                "bool": {
                    "filter": must_clauses,
                    "must": [{
                        "knn": {"embedding": {"vector": query_embedding, "k": k}}
                    }]
                }
            },
            "size": k
        }
        knn_results = self.client.search(index=self.index_name, body=knn_query)
        
        # RRF fusion
        rrf_scores = {}
        for i, hit in enumerate(bm25_results["hits"]["hits"]):
            chunk_id = hit["_id"]
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (i + 60)
        
        for i, hit in enumerate(knn_results["hits"]["hits"]):
            chunk_id = hit["_id"]
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (i + 60)
        
        # Merge
        merged = []
        seen = set()
        for hit in bm25_results["hits"]["hits"]:
            if hit["_id"] not in seen:
                merged.append(hit)
                seen.add(hit["_id"])
        
        for hit in knn_results["hits"]["hits"]:
            if hit["_id"] not in seen:
                merged.append(hit)
                seen.add(hit["_id"])
        
        merged.sort(key=lambda x: rrf_scores.get(x["_id"], 0), reverse=True)
        return merged[:k]
```

### 2.3 Cross-Encoder Reranker

**File:** `app/search/reranker.py`

```python
from sentence_transformers import CrossEncoder
from typing import List, Dict

class Reranker:
    def __init__(self):
        self.model = CrossEncoder('BAAI/bge-reranker-base')
    
    def rerank(self, query: str, candidates: List[Dict], top_n: int = 5) -> List[Dict]:
        """Rerank with cross-encoder."""
        texts = [[query, cand["_source"]["text"]] for cand in candidates]
        scores = self.model.predict(texts)
        
        for i, candidate in enumerate(candidates):
            candidate["rerank_score"] = float(scores[i])
        
        candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        return candidates[:top_n]
```

### 2.4 Response Masker

**File:** `app/search/masker.py`

```python
from app.auth.models import UserRole
from typing import List, Dict

class MaskPolicy:
    POLICIES = {
        UserRole.TREATING_CLINICIAN: [],
        UserRole.NON_TREATING_CLINICIAN: ["NAME", "MRN", "ADDRESS", "PHONE", "DOB"],
        UserRole.ADMINISTRATOR: ["NAME", "MRN", "ADDRESS", "PHONE", "DOB", "DIAGNOSIS", "MEDICATION"]
    }

class ResponseMasker:
    @staticmethod
    def mask(chunk_text: str, phi_spans: List[Dict], role: UserRole) -> str:
        """Apply role-based masking."""
        masked_text = list(chunk_text)
        mask_types = MaskPolicy.POLICIES[role]
        
        sorted_spans = sorted(phi_spans, key=lambda x: x["start"], reverse=True)
        
        for span in sorted_spans:
            if span["type"] in mask_types:
                replacement = f"<{span['type']}_REDACTED>"
                masked_text[span["start"]:span["end"]] = list(replacement)
        
        return "".join(masked_text)
```

### Phase 2.2 Exit Criteria

- [ ] LangGraph workflow compiles: `python -c "from app.search.graph import SearchGraph; g = SearchGraph(); print('✅')"` succeeds
- [ ] Query normalization executes: Test `_normalize_query()` node, verify query lowercased and trimmed
- [ ] ACL resolution executes: Test `_resolve_acl()` node with state["db"], verify list of ACL labels returned
- [ ] Embedding generation works: Test `_embed_query()` node, verify 1536-d embedding vector generated
- [ ] Hybrid retriever returns results: Call `retrieve()` with valid query embedding, verify results list returned with top-50 candidates
- [ ] BM25 search returns hits: Query OpenSearch with `{"query": {"match": {"text": "test"}}}`, verify hits found
- [ ] kNN search returns hits: Query OpenSearch with knn query, verify hits found
- [ ] RRF fusion merges lists: Call retriever with both BM25 and kNN candidates, verify merged list deduplicated
- [ ] Reranker scores candidates: Call `rerank()` with 50 candidates, verify 5 returned with rerank_score attached
- [ ] Role-based masking applied: Call `mask()` with non_treating_clinician role, verify NAME/MRN masked in output
- [ ] Treating clinician sees unmasked: Call `mask()` with treating_clinician role, verify full text returned unmasked
- [ ] ACL pre-filter works: Query OpenSearch with ACL filter, verify only documents matching ACL returned
- [ ] P95 latency < 1500ms: Run 10 full pipeline invocations, measure end-to-end latency, verify P95 < 1500ms
- [ ] LangGraph invoke returns result: Call `graph.invoke(initial_state)` with valid inputs, verify returns SearchState with masked_results populated

---

## Phase 3: Compliance & Audit 

### 3.1 Audit Logger

**File:** `app/compliance/audit_logger.py`

```python
import hashlib
import uuid
from datetime import datetime
from sqlalchemy.orm import Session as DBSession
from app.auth.models import AuditLog, UserRole
import json

class AuditLogger:
    @staticmethod
    def log_query(db: DBSession, user_id: str, role: UserRole, 
                  query_text: str, doc_ids: List[str], 
                  masking_applied: str, latency_ms: int):
        """Log query to immutable table."""
        query_hash = hashlib.sha256(query_text.encode()).hexdigest()
        
        audit_row = AuditLog(
            audit_id=str(uuid.uuid4()),
            user_id=user_id,
            role=role,
            timestamp=datetime.utcnow(),
            query_hash=query_hash,
            document_ids_returned=json.dumps(doc_ids),
            masking_applied=masking_applied,
            result_count=len(doc_ids),
            latency_ms=latency_ms
        )
        
        db.add(audit_row)
        db.commit()
        return audit_row.audit_id
```

**Database Immutability (Post-deployment hardening):**

After initial deployment, run this SQL to enforce append-only at DB level:

```sql
-- Revoke UPDATE/DELETE on audit_logs for the app user
REVOKE UPDATE, DELETE ON audit_logs FROM healthcare_user;

-- Grant INSERT only
GRANT INSERT ON audit_logs TO healthcare_user;

-- Enable row-level security for extra safety
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- No UPDATE policy
CREATE POLICY no_update_audit ON audit_logs 
  FOR UPDATE USING (FALSE);

-- No DELETE policy  
CREATE POLICY no_delete_audit ON audit_logs 
  FOR DELETE USING (FALSE);
```

---

### 3.2 ACL Resolver

**File:** `app/compliance/acl_resolver.py`

```python
from sqlalchemy.orm import Session as DBSession
from app.auth.models import User, UserRole
from typing import List

class ACLResolver:
    @staticmethod
    def resolve_acl(db: DBSession, user_id: str) -> List[str]:
        """Resolve ACL for user. Returns list of doc_id prefixes."""
        user = db.query(User).filter_by(user_id=user_id).first()
        
        if not user:
            return []
        
        if user.role == UserRole.TREATING_CLINICIAN:
            # Access only their department's docs
            # Store exact labels like: acl=["dept_cardiology"]
            return [f"dept_{user.department}"]
        elif user.role == UserRole.NON_TREATING_CLINICIAN:
            # Access all research docs
            return ["research_allowed"]
        else:
            # ADMINISTRATOR: no content access (audit only)
            return []
```

### Phase 3 Exit Criteria

- [ ] Audit row created on query: Execute search, query `psql ... -c "SELECT COUNT(*) FROM audit_logs"`, verify count increased by 1
- [ ] Query hash stored: Query audit log, verify query_hash is 64-char SHA-256 hex, not raw query text
- [ ] Raw query never stored: Grep audit_logs table schema + data, verify no `query_text` column, no raw queries in database
- [ ] No PHI in audit logs: Manually review 5 audit rows, verify document_ids_returned contains only IDs, not content or names
- [ ] DB immutability enforced: Attempt `UPDATE audit_logs SET query_hash='xxx' WHERE audit_id='yyy'` as healthcare_user, verify permission denied
- [ ] DB immutability enforced: Attempt `DELETE FROM audit_logs WHERE audit_id='yyy'` as healthcare_user, verify permission denied
- [ ] ACL restricts documents: Login as non_treating_clinician, search query matching dept_cardiology docs, verify no results (ACL blocked)
- [ ] ACL allows approved docs: Login as non_treating_clinician with research_allowed role, search research doc, verify results
- [ ] Masking rule: treating_clinician role queries, verify no <NAME_REDACTED> in masked output
- [ ] Masking rule: non_treating_clinician role queries, verify <NAME_REDACTED>, <MRN_REDACTED>, etc. in output
- [ ] Session revocation blocks access: Create session, logout, attempt to use old session_id, verify 401 returned
- [ ] Administrator role restrictions: Login as administrator, attempt to call /api/search endpoint, verify 403 or full masking applied

---

## Phase 4: Integration & Testing 

### 4.1 Main FastAPI App

**File:** `app/main.py`

```python
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
import os
from app.database import SessionLocal, engine
from app.auth.models import Base, User, UserRole
from app.auth.service import AuthService
from app.auth.middleware import session_middleware

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Healthcare Semantic Search")

app.middleware("http")(session_middleware)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Pydantic schemas
class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Login endpoint."""
    user = db.query(User).filter_by(username=payload.username).first()
    
    if not user or not AuthService.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    session_id = AuthService.create_session(db, user.user_id, user.role)
    response = JSONResponse({"status": "success"})
    response.set_cookie("session_id", session_id, httponly=True, secure=True)
    return response

@app.post("/api/auth/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    """Logout endpoint."""
    session_id = request.cookies.get("session_id")
    if session_id:
        AuthService.revoke_session(db, session_id)
    return {"status": "success"}

@app.get("/health")
async def health():
    return {"status": "ok"}
```

### 4.2 Code Quality (pyproject.toml)

```toml
[tool.black]
line-length = 100
target-version = ['py311']

[tool.isort]
profile = "black"
line_length = 100

[tool.mypy]
python_version = "3.11"
```

Create `.flake8`:

```ini
[flake8]
max-line-length = 100
exclude = .git,__pycache__,venv
```

### 4.3 Unit Tests

**File:** `tests/test_ingestion.py`

```python
import pytest
from app.ingestion.chunker import AdaptiveChunker, ChunkDocType

def test_chunker_prescription():
    """Test prescription chunking."""
    text = "Warfarin 5mg once daily for 7 days. Do not skip doses."
    chunks = AdaptiveChunker.chunk(text, ChunkDocType.PRESCRIPTION)
    
    assert len(chunks) == 1
    assert chunks[0].child_text == chunks[0].parent_text

def test_chunker_clinical_note():
    """Test clinical note chunking."""
    text = "Patient presented with chest pain. ECG normal. Troponin negative."
    chunks = AdaptiveChunker.chunk(text, ChunkDocType.CLINICAL_NOTE)
    
    assert len(chunks) >= 1
```

### Phase 4 Exit Criteria

- [ ] Backend starts: `uvicorn app.main:app --reload` starts without errors, listens on 8000
- [ ] Frontend builds: `cd frontend && npm run build` completes, dist/ folder created
- [ ] Code formatting passes: `black app/ --check` returns 0 (no formatting needed)
- [ ] Import sorting passes: `isort app/ --check` returns 0
- [ ] Linting passes: `flake8 app/` returns 0 errors
- [ ] Unit tests run: `pytest tests/ -v` executes all tests (may have failures, but suite runs)
- [ ] E2E login flow: Browser login → receive session cookie → use cookie to call /api/search → success
- [ ] E2E document upload: Upload PDF via `/api/ingest` → verify S3 upload → verify DB record created → verify OpenSearch indexed
- [ ] E2E search flow: Frontend search → backend normalizes → LangGraph executes → results masked → frontend displays
- [ ] Frontend result display: Search returns results, frontend renders each result with text, source, score
- [ ] Frontend masking visible: Search with non_treating_clinician, verify <REDACTED> shown in results
- [ ] Admin dashboard restricted: Login as admin, verify search results fully masked or access denied
- [ ] Cookies persist: Login, close browser, reopen, verify session cookie still valid and user stays logged in
- [ ] Session expiry works: Create session, wait > 8 hours (or manually set expiry to past), verify expired session rejected
- [ ] Full smoke test: New user → login → upload 5 PDFs → search 3 queries → verify all results masked correctly per role
- [ ] No console errors: Frontend dev tools show no JavaScript errors during full workflow

---

## Phase 5: Evaluation (POST-DEPLOYMENT)

⚠️ **DEFERRED UNTIL AFTER INITIAL DEPLOYMENT**

Implement AFTER you have:
1. 40-50 query-answer pairs from your golden dataset
2. Full pipeline working end-to-end
3. Baseline metrics established

**Timeline:** Week 4+ (post-deployment)

**What to implement then:**
- `scripts/run_ragas_eval.py` — runs RAGAS metrics
- Trigger upgrades only when metrics prove they're needed (data-driven)
- Context Precision < 90% → upgrade Chunker
- Context Recall < 85% → upgrade Embeddings

### Phase 5 Exit Criteria

- [ ] Golden dataset created: 40-50 query-answer pairs sampled from actual prescription documents (not synthetic Kaggle data)
- [ ] Golden Q&A manually verified: 5 sample Q&A pairs reviewed by domain expert, confirmed answerable from documents
- [ ] RAGAS script created: `scripts/run_ragas_eval.py` loads golden set, runs pipeline, computes metrics
- [ ] Baseline metrics recorded: Context Precision, Context Recall, Faithfulness, Answer Relevancy calculated on golden set
- [ ] Baseline metrics > thresholds: Context Precision >= 90%, Context Recall >= 85% (or document upgrade triggers identified)
- [ ] OCR accuracy spot-check: Manually review 10 OCR outputs (typed, scanned, handwritten), verify accuracy >= target (99%, 92%, 85%)
- [ ] Retrieval latency benchmark: Run 50 queries, measure P95 latency, record baseline (target < 1500ms)
- [ ] Masking rules verified manually: Execute search for each role (treating, non_treating, admin), verify output masking correct for each
- [ ] Query hashing verified: Query audit table, manually spot-check 5 query_hash values are SHA-256 hex, not plaintext
- [ ] No PHI in logs verified: Grep audit_logs for common PHI patterns (SSN, MRN numbers), verify none found
- [ ] Document ACL enforced: Create docs with dept_cardiology ACL, query as non_matching role, verify 0 results
- [ ] Cost baseline recorded: Note S3/KMS/OpenAI costs from first week of operation for future comparison

---

## Deployment Checklist

- [ ] Phase 0: Docker services running, env vars set, indexes created
- [ ] Phase 1: Auth working, sessions persistent, role enforcement verified
- [ ] Phase 1.6: React frontend builds and renders
- [ ] Phase 2.1: Full ingestion pipeline tested across typed, scanned, handwritten, prescription, lab, and form documents
- [ ] Phase 2.2: Search pipeline working, latency < 1500ms P95
- [ ] Phase 3: Audit logging immutable, masking rules enforced per role
- [ ] Phase 4: E2E smoke test passed, frontend/backend integrated
- [ ] Phase 5: Golden dataset created, baseline metrics recorded, RAGAS script ready

---

## Good Practices Summary

✅ **Auth:** Server-side sessions, NO JWT  
✅ **Audit:** Append-only, query_hash only, NO raw text  
✅ **Encryption:** S3 + KMS, TLS 1.2+  
✅ **Code:** Black, isort, flake8, mypy  
✅ **Type Safety:** Pydantic, SQLAlchemy, Enums  
✅ **Modularity:** Separate concerns per module  
✅ **Testing:** Pytest with clear assertions  

---

**Ready for implementation. Claude Code can pick this up and execute Phase by Phase.**
