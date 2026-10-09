# Kindred — Enterprise Customer Support AI

A local-first customer-support assistant with a React workspace, a FastAPI backend, Sentence Transformers embeddings, and FAISS semantic retrieval. Answers are assembled from retrieved knowledge-base text and include source excerpts so agents can see where the answer came from.

## What’s included

- Polished, responsive React chat workspace with conversation starters, source citations, a knowledge-base drawer, upload progress, and clear API error states.
- A responsive sign-in and sign-up experience that opens the workspace in UI preview mode. Authentication is not connected: submissions are not sent, stored, or used to create accounts.
- FastAPI endpoints for health checks, chat, and knowledge-base document management.
- Semantic search with `sentence-transformers/all-MiniLM-L6-v2` and normalized FAISS inner-product similarity.
- Persistent local document storage, chunking for longer documents, and PDF, DOCX, TXT, and Markdown ingestion.
- Five sample support policies on first run so the experience is ready to explore.

## Run locally

### 1. Start the API

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

The first chat request downloads the embedding model and can take a little longer. The model runs locally after download. API documentation is available at `http://localhost:8000/docs`.

### 2. Start the web app

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. To point the UI at a different API host, set `VITE_API_URL` to the API base URL (for example, `https://api.example.com/api`) before starting or building Vite.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | API status |
| `GET` | `/api/documents` | List indexed knowledge sources |
| `POST` | `/api/documents` | Upload a PDF, DOCX, TXT, or Markdown file (`file` form field) |
| `DELETE` | `/api/documents/{document_id}` | Remove a knowledge source |
| `POST` | `/api/chat` | Ask a grounded question (`{"message": "..."}`) |

Uploaded source documents are stored in `backend/data/knowledge_base.json`. Restrict CORS, add authentication, and use a managed persistent store before exposing this starter app to the public internet.
