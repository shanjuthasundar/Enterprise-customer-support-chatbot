# Kindred — Enterprise Customer Support AI

A local-first customer-support assistant with a React workspace, a FastAPI backend, Sentence Transformers embeddings, and FAISS semantic retrieval. Answers are assembled from retrieved knowledge-base text and include source excerpts so agents can see where the answer came from.

## What’s included

- Polished, responsive React chat workspace with conversation starters, source citations, a knowledge-base drawer, upload progress, and clear API error states.
- A responsive sign-in and sign-up experience backed by persistent accounts, protected workspace APIs, and secure, HTTP-only session cookies.
- Account profiles are stored in a local SQLite database; passwords are stored only as salted scrypt hashes.
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

Accounts are stored in `backend/data/accounts.sqlite3`. Use a strong, unique password (at least 12 characters). A sign-in session lasts up to seven days. Password reset and account deletion are not yet available.

Run the account and session tests from the repository root:

```powershell
python -m unittest discover -s backend -p "test_auth.py" -v
```

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
| `POST` | `/api/auth/signup` | Create an account (`display_name`, `email`, and `password`) |
| `POST` | `/api/auth/login` | Sign in (`email` and `password`) |
| `GET` | `/api/auth/me` | Return the signed-in user's profile |
| `POST` | `/api/auth/logout` | End the current session |
| `GET` | `/api/documents` | List indexed knowledge sources (signed-in session required) |
| `POST` | `/api/documents` | Upload a PDF, DOCX, TXT, or Markdown file (`file` form field; signed in) |
| `DELETE` | `/api/documents/{document_id}` | Remove a knowledge source (signed in) |
| `POST` | `/api/chat` | Ask a grounded question (`{"message": "..."}`; signed in) |

Uploaded source documents are stored in `backend/data/knowledge_base.json`. Accounts and sessions are stored in `backend/data/accounts.sqlite3`; keep both files out of version control and configure durable, access-controlled storage for deployment. Before deployment, set `KINDRED_CORS_ORIGINS` to the exact frontend origins, set `KINDRED_ENV=production` (which enables secure cookies), use HTTPS, and run behind a properly configured trusted proxy. The included accounts are application accounts; document and knowledge-base data is still shared by this single-workspace starter rather than isolated per user.
