# Healthcare Semantic Search

Healthcare RAG system with HIPAA-aware semantic search over ~1000 synthetic medical records.

## Quick Start

```bash
docker-compose up -d
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python scripts/init_db.py
python scripts/init_opensearch.py
uvicorn app.main:app --reload
```
