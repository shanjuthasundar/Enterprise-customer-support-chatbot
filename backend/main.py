from __future__ import annotations

import io
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from docx import Document as WordDocument
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer


DATA_DIR = Path(__file__).resolve().parent / "data"
KNOWLEDGE_FILE = DATA_DIR / "knowledge_base.json"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120

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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_lock = threading.RLock()
_model: SentenceTransformer | None = None
_index: faiss.IndexFlatIP | None = None
_chunks: list[dict[str, str]] = []
_indexed_document_ids: tuple[str, ...] = ()


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
def list_documents() -> dict[str, Any]:
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
def chat(request: ChatRequest) -> ChatResponse:
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
async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:
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
def delete_document(document_id: str) -> dict[str, str]:
    with _lock:
        records = _load_documents()
        remaining = [record for record in records if record["id"] != document_id]
        if len(remaining) == len(records):
            raise HTTPException(status_code=404, detail="That document could not be found.")
        _save_documents(remaining)
        global _index
        _index = None
    return {"status": "deleted"}
