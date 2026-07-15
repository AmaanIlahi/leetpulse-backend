import gc
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from openai import AsyncOpenAI

from app.utils.logger import get_logger, log_event

logger = get_logger(__name__)

CHROMA_PATH = os.getenv("CHROMA_PATH", "/data/chroma")

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(
    name="leetcode_problems",
    metadata={"hnsw:space": "cosine"},
)

_openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_EMBED_MODEL  = "text-embedding-3-small"
_BATCH_SIZE   = 50
_COST_PER_TOK = 0.00000002  # text-embedding-3-small pricing
_META_FILE    = Path(CHROMA_PATH) / "meta.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_embedding_text(problem: dict) -> str:
    tags = ", ".join(problem.get("tags") or [])
    return f"{problem['title']} | {problem['difficulty']} | {tags} | {problem['company']}"


def _write_meta(total: int) -> None:
    _META_FILE.parent.mkdir(parents=True, exist_ok=True)
    _META_FILE.write_text(json.dumps({
        "total_problems": total,
        "last_updated": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def embed_and_store(problems: list[dict]) -> None:
    if not problems:
        log_event(logger, "warning", "embed_skipped", reason="empty problem list")
        return

    try:
        # Delete all existing docs before rebuild
        existing_ids = collection.get(include=[])["ids"]
        if existing_ids:
            collection.delete(ids=existing_ids)

        total_tokens = 0

        for i in range(0, len(problems), _BATCH_SIZE):
            batch = problems[i : i + _BATCH_SIZE]

            texts = [build_embedding_text(p) for p in batch]
            response = await _openai.embeddings.create(model=_EMBED_MODEL, input=texts)
            total_tokens += response.usage.total_tokens

            collection.upsert(
                ids=[f"{p['slug']}-{p['company']}" for p in batch],
                embeddings=[item.embedding for item in response.data],
                documents=texts,
                metadatas=[
                    {
                        "title":      p["title"],
                        "slug":       p["slug"],
                        "difficulty": p["difficulty"],
                        "tags":       ", ".join(p.get("tags") or []),
                        "company":    p["company"],
                        "freq_bar":   float(p["freq_bar"]) if p.get("freq_bar") is not None else 0.0,
                    }
                    for p in batch
                ],
            )

            log_event(logger, "debug", "embed_batch_complete",
                      batch=i // _BATCH_SIZE + 1,
                      total_batches=(len(problems) + _BATCH_SIZE - 1) // _BATCH_SIZE,
                      batch_size=len(batch))

            del batch, texts, response
            gc.collect()

        _write_meta(len(problems))

        log_event(
            logger, "info", "embed_complete",
            total_problems=len(problems),
            total_tokens=total_tokens,
            estimated_cost_usd=round(total_tokens * _COST_PER_TOK, 6),
        )

    except Exception as e:
        log_event(logger, "error", "embed_error", error=repr(e))
        raise


def get_collection_stats() -> dict:
    try:
        meta: dict = json.loads(_META_FILE.read_text()) if _META_FILE.exists() else {}
    except Exception:
        meta = {}

    return {
        "total_problems": meta.get("total_problems", collection.count()),
        "last_updated":   meta.get("last_updated", "never"),
    }