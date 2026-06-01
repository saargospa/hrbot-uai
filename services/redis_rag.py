"""
services/redis_rag.py
Vector store semántico (KNN coseno) + memoria de sesión sobre Redis.
Indexa los documentos de política de RRHH como embeddings OpenAI
y permite búsqueda por similitud coseno para el pipeline RAG.
"""
import json
import os
import struct

import numpy as np
import redis.asyncio as aioredis
from openai import AsyncOpenAI

REDIS_HOST     = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
RAG_TOP_K      = int(os.getenv("RAG_TOP_K", 5))

# Prefijos de claves Redis
PREFIX_DOC = "hr:doc:"
PREFIX_EMB = "hr:emb:"
INDEX_KEY  = "hr:index"
CHAT_KEY   = "hr:chat:{sid}:history"
CHAT_TTL   = 3600

openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _get_redis() -> aioredis.Redis:
    """Crea y retorna una conexión asíncrona a Redis con timeout explícito.

    Returns:
        Instancia de Redis asíncrono configurada con host, puerto y contraseña.
    """
    kwargs = dict(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    if REDIS_PASSWORD:
        kwargs["password"] = REDIS_PASSWORD
    return aioredis.Redis(**kwargs)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calcula la similitud coseno entre dos vectores.

    Args:
        a: Primer vector de embedding (numpy array).
        b: Segundo vector de embedding (numpy array).

    Returns:
        Valor de similitud entre 0.0 (sin relación) y 1.0 (idénticos).
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _emb_to_bytes(vector: list[float]) -> bytes:
    """Convierte un vector de embedding a bytes para almacenamiento en Redis.

    Args:
        vector: Lista de flotantes que representan el embedding.

    Returns:
        Representación binaria del vector en formato float32.
    """
    return struct.pack(f"{len(vector)}f", *vector)


def _bytes_to_emb(data: bytes) -> np.ndarray:
    """Convierte bytes almacenados en Redis a un vector numpy de embedding.

    Args:
        data: Bytes en formato float32 almacenados en Redis.

    Returns:
        Array numpy float32 con el vector de embedding reconstruido.
    """
    count = len(data) // 4
    return np.array(struct.unpack(f"{count}f", data), dtype=np.float32)


async def embed_text(text: str) -> list[float]:
    """Genera el embedding de un texto usando el modelo de OpenAI.

    Args:
        text: Texto a convertir en vector de embedding.

    Returns:
        Lista de flotantes con el embedding de 1536 dimensiones.
    """
    response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text.replace("\n", " "),
    )
    return response.data[0].embedding


async def index_document(
    doc_id: str,
    title: str,
    content: str,
    source_file: str,
    tags: list[str] | None = None,
) -> None:
    """Indexa un documento de política en Redis como embedding vectorial.

    Genera el embedding del texto enriquecido (título + tags + contenido)
    y lo almacena en Redis junto con los metadatos del documento.

    Args:
        doc_id:      Identificador único del documento.
        title:       Título del documento o sección.
        content:     Contenido textual del documento.
        source_file: Nombre del archivo fuente (.md).
        tags:        Lista de etiquetas para enriquecer la búsqueda.
    """
    tags = tags or []
    enriched_text = f"{title}. {' '.join(tags)}. {content[:1000]}"

    vector = await embed_text(enriched_text)
    metadata = {
        "id": doc_id,
        "title": title,
        "source_file": source_file,
        "tags": tags,
        "excerpt": content[:400],
    }

    r = _get_redis()
    async with r:
        pipe = r.pipeline()
        pipe.set(f"{PREFIX_DOC}{doc_id}", json.dumps(metadata, ensure_ascii=False))
        pipe.set(f"{PREFIX_EMB}{doc_id}", _emb_to_bytes(vector))
        pipe.sadd(INDEX_KEY, doc_id)
        await pipe.execute()

    print(f"  ✓ Indexado: {title[:60]}")


async def search(query: str, top_k: int = RAG_TOP_K) -> list[dict]:
    """Busca los documentos más similares a la consulta usando KNN coseno.

    Genera el embedding de la consulta, calcula la similitud coseno
    contra todos los embeddings indexados y retorna los top-K más relevantes.

    Args:
        query: Texto de la consulta del empleado.
        top_k: Cantidad de documentos a retornar (por defecto RAG_TOP_K).

    Returns:
        Lista de diccionarios con metadatos y puntuación de similitud.
    """
    query_vector = np.array(await embed_text(query), dtype=np.float32)

    r = _get_redis()
    async with r:
        doc_ids = await r.smembers(INDEX_KEY)
        if not doc_ids:
            return []

        pipe = r.pipeline()
        for did in doc_ids:
            pipe.get(f"{PREFIX_EMB}{did.decode()}")
        emb_bytes_list = await pipe.execute()

        scores: list[tuple[float, str]] = []
        for did, emb_bytes in zip(doc_ids, emb_bytes_list):
            if emb_bytes is None:
                continue
            sim = _cosine_similarity(query_vector, _bytes_to_emb(emb_bytes))
            scores.append((sim, did.decode()))

        scores.sort(key=lambda x: x[0], reverse=True)
        top_ids    = [did for _, did in scores[:top_k]]
        top_scores = {did: sim for sim, did in scores[:top_k]}

        pipe = r.pipeline()
        for did in top_ids:
            pipe.get(f"{PREFIX_DOC}{did}")
        meta_bytes_list = await pipe.execute()

    results = []
    for did, meta_bytes in zip(top_ids, meta_bytes_list):
        if meta_bytes is None:
            continue
        meta = json.loads(meta_bytes.decode())
        meta["similarity_score"] = round(top_scores[did], 4)
        results.append(meta)

    return results


# ── Memoria de sesión ──────────────────────────────────────────────────────────

async def save_turn(session_id: str, role: str, content: str) -> None:
    """Persiste un turno de conversación en el historial de Redis.

    Args:
        session_id: Identificador único de la sesión del empleado.
        role:       Rol del mensaje ('user' o 'assistant').
        content:    Contenido textual del mensaje.
    """
    r = _get_redis()
    key = CHAT_KEY.format(sid=session_id)
    turn = json.dumps({"role": role, "content": content}, ensure_ascii=False)
    async with r:
        await r.rpush(key, turn)
        await r.expire(key, CHAT_TTL)


async def load_history(session_id: str, max_turns: int = 20) -> list[dict]:
    """Carga los últimos turnos del historial de conversación desde Redis.

    Args:
        session_id: Identificador único de la sesión del empleado.
        max_turns:  Cantidad máxima de turnos a recuperar (por defecto 20).

    Returns:
        Lista de diccionarios con los turnos {role, content} más recientes.
    """
    r = _get_redis()
    key = CHAT_KEY.format(sid=session_id)
    async with r:
        raw_turns = await r.lrange(key, -max_turns, -1)
    return [json.loads(t.decode()) for t in raw_turns]


async def clear_history(session_id: str) -> None:
    """Elimina el historial de conversación de una sesión en Redis.

    Args:
        session_id: Identificador único de la sesión a borrar.
    """
    r = _get_redis()
    async with r:
        await r.delete(CHAT_KEY.format(sid=session_id))
