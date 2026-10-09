from __future__ import annotations

import io
import json
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from docx import Document as WordDocument
from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer


DATA_DIR = Path(__file__).resolve().parent / "data"
KNOWLEDGE_FILE = DATA_DIR / "knowledge_base.json"
ACCOUNT_DATABASE = DATA_DIR / "accounts.sqlite3"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
SESSION_COOKIE = "kindred_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
COOKIE_SECURE = os.getenv(
    "KINDRED_COOKIE_SECURE",
    "true" if os.getenv("KINDRED_ENV") == "production" else "false",
).lower() == "true"
ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "KINDRED_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
PASSWORD_HASH_N = 2**14
PASSWORD_HASH_R = 8
PASSWORD_HASH_P = 1

SEED_DOCUMENTS = [
    {
        "title": "Returns & Refunds Policy",
        "category": "Policies",
        "text": (
            "To return an order, customers can return unused items within 30 days of delivery. "
            "Items must be in their original packaging with proof of purchase. "
            "To start a return, open Orders in your account, choose the item, and select Request a return. "
            "Refunds are issued to the original payment method within 5–7 business days after the returned "
            "item passes inspection. Final-sale items and gift cards cannot be refunded."
        ),
    },
    {
        "title": "Shipping & Delivery",
        "category": "Orders",
        "text": (
            "Standard shipping takes 3–5 business days and costs $5.99. "
            "Express shipping takes 1–2 business days and costs $14.99. "
            "Your order will arrive in 3–5 business days with standard shipping or in 1–2 business days with express shipping. "
            "Orders over $75 qualify for free standard shipping. "
            "Tracking details are sent by email when an order leaves our warehouse. "
            "If your package has not arrived within 7 days of its estimated delivery date, contact support "
            "with your order number so our team can investigate."
        ),
    },
    {
        "title": "Account & Password Help",
        "category": "Account",
        "text": (
            "To reset your password, select Forgot password on the sign-in page and enter your account email. "
            "A reset link will arrive by email within a few minutes and expires after 60 minutes. "
            "If you no longer have access to your email address, contact support for an identity verification. "
            "For your security, never share your password or one-time verification code with anyone."
        ),
    },
    {
        "title": "Warranty & Product Support",
        "category": "Products",
        "text": (
            "Most products include a one-year limited warranty starting from the purchase date. "
            "The warranty covers defects in materials and workmanship during normal use. "
            "Accidental damage, normal wear, and unauthorized repairs are not covered. "
            "To make a warranty claim, provide your order number, product serial number, and a description "
            "of the issue to our support team. We typically respond to warranty requests within two business days."
        ),
    },
    {
        "title": "Contact & Support Hours",
        "category": "Support",
        "text": (
            "Our support team is available Monday through Friday, 9:00 AM–6:00 PM Eastern Time. "
            "You can reach us by email at support@example.com or by phone at 1-800-555-0198. "
            "We aim to respond to email requests within one business day. "
            "Please include your order number when contacting us about an order."
        ),
    },
]

STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "can", "could", "does",
    "for", "from", "have", "help", "how", "into", "its", "need", "our",
    "please", "that", "the", "their", "them", "there", "this", "what",
    "when", "where", "which", "with", "you", "your",
}

app = FastAPI(
    title="Kindred Support API",
    description="Grounded customer support answers powered by Sentence Transformers and FAISS.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_lock = threading.RLock()
_model: SentenceTransformer | None = None
_index: faiss.IndexFlatIP | None = None
_chunks: list[dict[str, str]] = []
_indexed_document_ids: tuple[str, ...] = ()


@contextmanager
def _auth_database() -> Any:
    ACCOUNT_DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(ACCOUNT_DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _initialize_auth_database() -> None:
    with _auth_database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS auth_rate_limits (
                scope TEXT NOT NULL,
                subject_hash TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                window_started INTEGER NOT NULL,
                blocked_until INTEGER NOT NULL,
                PRIMARY KEY (scope, subject_hash)
            );
            """
        )


@app.on_event("startup")
def initialize_auth_database() -> None:
    _initialize_auth_database()


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_HASH_N,
        r=PASSWORD_HASH_R,
        p=PASSWORD_HASH_P,
        dklen=32,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


_DUMMY_PASSWORD_HASH = _password_hash(secrets.token_urlsafe(24))


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = stored_hash.split("$")
        if algorithm != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected_digest = bytes.fromhex(digest_hex)
        actual_digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=PASSWORD_HASH_N,
            r=PASSWORD_HASH_R,
            p=PASSWORD_HASH_P,
            dklen=len(expected_digest),
            maxmem=64 * 1024 * 1024,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual_digest, expected_digest)


def _public_user(row: sqlite3.Row) -> dict[str, str]:
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "email": row["email"],
        "created_at": row["created_at"],
    }


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _rate_limit_subject(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _check_rate_limit(scope: str, subject: str, limit: int, window: int) -> None:
    now = int(time.time())
    with _auth_database() as connection:
        record = connection.execute(
            "SELECT attempts, window_started, blocked_until FROM auth_rate_limits "
            "WHERE scope = ? AND subject_hash = ?",
            (scope, _rate_limit_subject(subject)),
        ).fetchone()
    if record is None:
        return
    if record["blocked_until"] > now:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(record["blocked_until"] - now)},
        )
    if now - record["window_started"] >= window:
        with _auth_database() as connection:
            connection.execute(
                "DELETE FROM auth_rate_limits WHERE scope = ? AND subject_hash = ?",
                (scope, _rate_limit_subject(subject)),
            )


def _record_rate_limit_attempt(
    scope: str,
    subject: str,
    limit: int,
    window: int,
    block_seconds: int,
) -> None:
    now = int(time.time())
    subject_hash = _rate_limit_subject(subject)
    with _auth_database() as connection:
        connection.execute(
            """
            INSERT INTO auth_rate_limits (scope, subject_hash, attempts, window_started, blocked_until)
            VALUES (?, ?, 1, ?, 0)
            ON CONFLICT(scope, subject_hash) DO UPDATE SET
                attempts = CASE
                    WHEN excluded.window_started - auth_rate_limits.window_started >= ?
                    THEN 1 ELSE auth_rate_limits.attempts + 1
                END,
                window_started = CASE
                    WHEN excluded.window_started - auth_rate_limits.window_started >= ?
                    THEN excluded.window_started ELSE auth_rate_limits.window_started
                END,
                blocked_until = CASE
                    WHEN excluded.window_started - auth_rate_limits.window_started >= ?
                    THEN 0
                    WHEN auth_rate_limits.attempts + 1 >= ?
                    THEN excluded.window_started + ?
                    ELSE auth_rate_limits.blocked_until
                END
            """,
            (
                scope, subject_hash, now, window, window, window,
                limit, block_seconds,
            ),
        )


def _clear_rate_limit(scope: str, subject: str) -> None:
    with _auth_database() as connection:
        connection.execute(
            "DELETE FROM auth_rate_limits WHERE scope = ? AND subject_hash = ?",
            (scope, _rate_limit_subject(subject)),
        )


def _issue_session(user_id: str, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    with _auth_database() as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        connection.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (_token_hash(token), user_id, expires_at),
        )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/api",
    )


def _require_user(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict[str, str]:
    if not session:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    with _auth_database() as connection:
        row = connection.execute(
            """
            SELECT users.id, users.display_name, users.email, users.created_at
            FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """,
            (_token_hash(session), int(time.time())),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    return _public_user(row)


@app.middleware("http")
async def validate_request_origin(request: Request, call_next: Any) -> Any:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if not origin or origin.rstrip("/") not in ALLOWED_ORIGINS:
            return JSONResponse(
                status_code=403,
                content={"detail": "This request requires a trusted browser origin."},
            )
    return await call_next(request)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_documents() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if KNOWLEDGE_FILE.exists():
        try:
            records = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Could not read the knowledge base: {exc}") from exc
        if not isinstance(records, list):
            raise RuntimeError("The knowledge base file must contain a list of documents.")
        return records

    records = [
        {
            "id": str(uuid.uuid4()),
            "title": item["title"],
            "category": item["category"],
            "text": item["text"],
            "created_at": _now(),
            "is_sample": True,
        }
        for item in SEED_DOCUMENTS
    ]
    _save_documents(records)
    return records


def _save_documents(records: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary_file = KNOWLEDGE_FILE.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(records, indent=2), encoding="utf-8")
    temporary_file.replace(KNOWLEDGE_FILE)


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        try:
            _model = SentenceTransformer(MODEL_NAME)
        except Exception as exc:
            raise RuntimeError(
                f"Could not load the embedding model '{MODEL_NAME}'. "
                "Check your internet connection and try again."
            ) from exc
    return _model


def _split_text(text: str) -> list[str]:
    clean_text = re.sub(r"\s+", " ", text).strip()
    if not clean_text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean_text):
        end = min(start + CHUNK_SIZE, len(clean_text))
        if end < len(clean_text):
            boundary = clean_text.rfind(" ", start + CHUNK_SIZE // 2, end)
            if boundary > start:
                end = boundary
        chunk = clean_text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(clean_text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)
    return chunks


def _ensure_index(records: list[dict[str, Any]]) -> None:
    global _index, _chunks, _indexed_document_ids
    document_ids = tuple(record["id"] for record in records)
    if _index is not None and document_ids == _indexed_document_ids:
        return

    chunks = [
        {"document_id": record["id"], "title": record["title"], "text": text}
        for record in records
        for text in _split_text(record["text"])
    ]
    model = _get_model()
    if chunks:
        vectors = model.encode(
            [chunk["text"] for chunk in chunks],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = np.asarray(vectors, dtype=np.float32)
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
    else:
        index = None
    _chunks = chunks
    _index = index
    _indexed_document_ids = document_ids


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)


class ChatSource(BaseModel):
    document_id: str
    title: str
    excerpt: str
    relevance: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    confidence: str


class SignupRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)
    email: str = Field(
        min_length=5,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


@app.post("/api/auth/signup", status_code=201)
def signup(request: SignupRequest, response: Response, http_request: Request) -> dict[str, Any]:
    display_name = request.display_name.strip()
    email = request.email.strip().lower()
    if len(display_name) < 2:
        raise HTTPException(status_code=422, detail="Please enter your name.")
    if any(ord(character) < 32 for character in request.password):
        raise HTTPException(status_code=422, detail="The password contains unsupported characters.")
    client_ip = http_request.client.host if http_request.client else "unknown"
    _check_rate_limit("signup", client_ip, limit=10, window=3600)

    user_id = str(uuid.uuid4())
    try:
        with _auth_database() as connection:
            connection.execute(
                "INSERT INTO users (id, display_name, email, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, display_name, email, _password_hash(request.password), _now()),
            )
            user = connection.execute(
                "SELECT id, display_name, email, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="An account with that email already exists.") from exc

    _record_rate_limit_attempt("signup", client_ip, limit=10, window=3600, block_seconds=3600)
    _issue_session(user_id, response)
    return {"user": _public_user(user)}


@app.post("/api/auth/login")
def login(request: LoginRequest, response: Response, http_request: Request) -> dict[str, Any]:
    email = request.email.strip().lower()
    client_ip = http_request.client.host if http_request.client else "unknown"
    _check_rate_limit("login", client_ip, limit=10, window=900)
    with _auth_database() as connection:
        row = connection.execute(
            "SELECT id, display_name, email, password_hash, created_at FROM users WHERE email = ?",
            (email,),
        ).fetchone()

    stored_hash = row["password_hash"] if row is not None else _DUMMY_PASSWORD_HASH
    password_matches = _verify_password(request.password, stored_hash)
    if row is None or not password_matches:
        _record_rate_limit_attempt("login", client_ip, limit=10, window=900, block_seconds=900)
        raise HTTPException(status_code=401, detail="The email or password is incorrect.")

    _clear_rate_limit("login", client_ip)
    _issue_session(row["id"], response)
    return {"user": _public_user(row)}


@app.get("/api/auth/me")
def current_user(user: dict[str, str] = Depends(_require_user)) -> dict[str, Any]:
    return {"user": user}


@app.post("/api/auth/logout")
def logout(
    response: Response,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, str]:
    if session:
        with _auth_database() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(session),))
    response.delete_cookie(key=SESSION_COOKIE, path="/api", httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return {"status": "signed_out"}


def _terms(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2 and word not in STOP_WORDS
    }


def _compose_answer(message: str, results: list[dict[str, Any]]) -> str:
    query_terms = _terms(message)
    sentences: list[tuple[float, str]] = []
    for result in results:
        for sentence in re.split(r"(?<=[.!?])\s+", result["text"]):
            sentence = sentence.strip()
            if sentence:
                overlap = len(query_terms & _terms(sentence))
                sentences.append((overlap + result["score"] * 2, sentence))
    selected: list[str] = []
    for _, sentence in sorted(sentences, key=lambda item: item[0], reverse=True):
        if sentence not in selected:
            selected.append(sentence)
        if len(selected) == 3:
            break
    return " ".join(selected)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "kindred-support-api"}


@app.get("/api/documents")
def list_documents(_user: dict[str, str] = Depends(_require_user)) -> dict[str, Any]:
    with _lock:
        records = _load_documents()
        return {
            "documents": [
                {
                    "id": record["id"],
                    "title": record["title"],
                    "category": record["category"],
                    "created_at": record["created_at"],
                    "is_sample": record.get("is_sample", False),
                    "characters": len(record["text"]),
                }
                for record in records
            ],
            "total": len(records),
        }


@app.post("/api/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    _user: dict[str, str] = Depends(_require_user),
) -> ChatResponse:
    with _lock:
        records = _load_documents()
        try:
            _ensure_index(records)
            if _index is None or not _chunks:
                raise HTTPException(status_code=503, detail="Your knowledge base is empty.")
            query_vector = _get_model().encode(
                [request.message], convert_to_numpy=True, normalize_embeddings=True
            )
            scores, positions = _index.search(np.asarray(query_vector, dtype=np.float32), 4)
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        results: list[dict[str, Any]] = []
        seen_documents: set[str] = set()
        query_terms = _terms(request.message)
        for semantic_score, position in zip(scores[0], positions[0]):
            if position < 0:
                continue
            chunk = _chunks[int(position)]
            if chunk["document_id"] in seen_documents:
                continue
            seen_documents.add(chunk["document_id"])
            chunk_terms = _terms(chunk["text"])
            lexical_coverage = (
                len(query_terms & chunk_terms) / len(query_terms)
                if query_terms
                else 0.0
            )
            semantic_score = float(semantic_score)
            results.append({
                **chunk,
                "semantic_score": semantic_score,
                "score": 0.78 * semantic_score + 0.22 * lexical_coverage,
            })

        results.sort(key=lambda result: result["score"], reverse=True)
        if not results or results[0]["score"] < 0.35:
            return ChatResponse(
                answer=(
                    "I couldn't find a reliable answer in the current knowledge base. "
                    "Try rephrasing your question, or ask the support team for help."
                ),
                sources=[],
                confidence="low",
            )

        relevant_results = [
            result for result in results
            if result["score"] >= max(0.18, results[0]["score"] * 0.88)
        ]
        answer = _compose_answer(request.message, relevant_results)
        sources = [
            ChatSource(
                document_id=result["document_id"],
                title=result["title"],
                excerpt=result["text"][:260] + ("…" if len(result["text"]) > 260 else ""),
                relevance=round(max(0.0, min(1.0, result["score"])), 2),
            )
            for result in relevant_results[:3]
        ]
        confidence = "high" if results[0]["score"] >= 0.48 else "medium"
        return ChatResponse(answer=answer, sources=sources, confidence=confidence)


def _extract_file_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        return content.decode("utf-8-sig")
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        document = WordDocument(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    raise HTTPException(
        status_code=415,
        detail="Unsupported file type. Upload a PDF, DOCX, TXT, or Markdown file.",
    )


@app.post("/api/documents")
async def upload_document(
    file: UploadFile = File(...),
    _user: dict[str, str] = Depends(_require_user),
) -> dict[str, Any]:
    filename = Path(file.filename or "").name.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Please choose a file to upload.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Files must be 10 MB or smaller.")
    try:
        text = _extract_file_text(filename, content).strip()
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="The text file must use UTF-8 encoding.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read this file: {exc}") from exc
    if len(text) < 20:
        raise HTTPException(status_code=422, detail="This file does not contain enough readable text.")

    record = {
        "id": str(uuid.uuid4()),
        "title": Path(filename).stem,
        "category": "Uploaded",
        "text": text,
        "created_at": _now(),
        "is_sample": False,
    }
    with _lock:
        records = _load_documents()
        records.append(record)
        _save_documents(records)
        global _index
        _index = None
    return {
        "id": record["id"],
        "title": record["title"],
        "category": record["category"],
        "created_at": record["created_at"],
        "is_sample": False,
        "characters": len(text),
    }


@app.delete("/api/documents/{document_id}")
def delete_document(
    document_id: str,
    _user: dict[str, str] = Depends(_require_user),
) -> dict[str, str]:
    with _lock:
        records = _load_documents()
        remaining = [record for record in records if record["id"] != document_id]
        if len(remaining) == len(records):
            raise HTTPException(status_code=404, detail="That document could not be found.")
        _save_documents(remaining)
        global _index
        _index = None
    return {"status": "deleted"}
