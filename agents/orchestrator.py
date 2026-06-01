"""
agents/orchestrator.py
Orquestador principal de HRBot.
Implementa el pipeline de 7 pasos: Redis → RAG → MCP → GPT-4o → Claude → Redis → Response.
Registra cada interacción en PostgreSQL para trazabilidad y auditoría.
"""
import json
import time
import uuid
from dataclasses import dataclass, field

from agents.anthropic_fiscalizador import fiscalizar
from agents.openai_agent import generate_hr_response
from services.mcp_hr_client import HRPoliciesMCPClient
from services.redis_rag import load_history, save_turn, search


@dataclass
class ChatResponse:
    """Respuesta estructurada del pipeline de HRBot.

    Contiene la respuesta final, metadatos de fiscalización y métricas
    de la consulta para el cliente y para la persistencia en PostgreSQL.
    """

    session_id: str
    response: str
    was_corrected: bool = False
    fiscalization_ok: bool = True
    issues: list[str] = field(default_factory=list)
    rag_hits: int = 0
    realtime_available: bool = True
    tokens_used: int = 0
    latency_ms: int = 0


class HROrchestrator:
    """Orquesta el pipeline completo de consulta de políticas de RRHH.

    Pipeline de 7 pasos:
      1. Cargar historial de Redis (últimos 20 turnos)
      2. Búsqueda KNN semántica en Redis RAG (top-5 documentos)
      3. Consulta en tiempo real a políticas vía MCP
      4. GPT-4o genera respuesta con contexto RAG + MCP + historial
      5. Claude Sonnet fiscaliza: verifica datos, PII y alucinaciones
      6. Si hay issues → Claude corrige; si está OK → respuesta original
      7. Persiste turno en Redis y registra interacción en PostgreSQL
    """

    def __init__(self, enable_fiscalization: bool = True, use_realtime: bool = True):
        """Inicializa el orquestador con las opciones de fiscalización y MCP.

        Args:
            enable_fiscalization: Activa la fiscalización con Claude Sonnet.
            use_realtime:        Activa la consulta de contexto en tiempo real vía MCP.
        """
        self.enable_fiscalization = enable_fiscalization
        self.use_realtime = use_realtime
        self.mcp_client = HRPoliciesMCPClient()

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
    ) -> ChatResponse:
        """Ejecuta el pipeline completo de 7 pasos para una consulta del empleado.

        Args:
            message:    Pregunta del empleado sobre políticas de RRHH.
            session_id: Identificador de sesión (se genera uno si no se provee).

        Returns:
            ChatResponse con la respuesta final, metadatos de fiscalización y métricas.
        """
        session_id = session_id or str(uuid.uuid4())
        start_time = time.perf_counter()

        # ── Paso 1: Historial de sesión desde Redis ────────────────────────
        history = await load_history(session_id, max_turns=20)

        # ── Paso 2: Búsqueda KNN semántica (RAG) ──────────────────────────
        rag_docs = await search(message, top_k=5)
        rag_context = self._format_rag_context(rag_docs)

        # ── Paso 3: Contexto en tiempo real vía MCP ────────────────────────
        realtime_context = ""
        realtime_ok = True
        if self.use_realtime:
            try:
                rt_raw = await self.mcp_client.build_context(message)
                rt_data = json.loads(rt_raw)
                realtime_context = self._format_realtime_context(rt_data)
            except Exception as exc:
                print(f"[MCP] Error obteniendo contexto en tiempo real: {exc}")
                realtime_ok = False
                realtime_context = "(contexto en tiempo real no disponible)"

        # ── Paso 4: GPT-4o genera respuesta ───────────────────────────────
        draft_response, tokens_used = await generate_hr_response(
            user_message=message,
            history=history,
            rag_context=rag_context,
            realtime_context=realtime_context,
        )

        # ── Paso 5 & 6: Claude fiscaliza (y corrige si es necesario) ──────
        fiscal_ok = True
        issues: list[str] = []
        final_response = draft_response
        was_corrected = False

        if self.enable_fiscalization:
            combined_context = f"{rag_context}\n\n{realtime_context}"
            fiscal_result = await fiscalizar(
                user_question=message,
                agent_response=draft_response,
                policy_context=combined_context,
            )
            fiscal_ok = fiscal_result.ok
            issues = fiscal_result.issues

            if not fiscal_result.ok and fiscal_result.corrected:
                final_response = fiscal_result.corrected
                was_corrected = True

        # ── Paso 7: Persistir turno en Redis ──────────────────────────────
        await save_turn(session_id, "user", message)
        await save_turn(session_id, "assistant", final_response)

        # ── Registrar interacción en PostgreSQL ───────────────────────────
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        try:
            from services.db import save_interaction
            await save_interaction(
                session_id=session_id,
                query=message,
                response=final_response,
                tokens_used=tokens_used,
                latency_ms=elapsed_ms,
                was_corrected=was_corrected,
                fiscalization_ok=fiscal_ok,
                issues=issues,
            )
        except Exception as exc:
            print(f"[DB] Error registrando interacción en PostgreSQL: {exc}")

        return ChatResponse(
            session_id=session_id,
            response=final_response,
            was_corrected=was_corrected,
            fiscalization_ok=fiscal_ok,
            issues=issues,
            rag_hits=len(rag_docs),
            realtime_available=realtime_ok,
            tokens_used=tokens_used,
            latency_ms=elapsed_ms,
        )

    def _format_rag_context(self, docs: list[dict]) -> str:
        """Formatea los documentos recuperados por RAG como texto de contexto.

        Args:
            docs: Lista de documentos con metadatos y puntuación de similitud.

        Returns:
            Texto formateado con los extractos y puntuaciones de cada documento.
        """
        if not docs:
            return "No se encontraron documentos relevantes en el índice semántico."
        parts = []
        for doc in docs:
            sim = doc.get("similarity_score", 0)
            parts.append(
                f"[{doc.get('source_file', 'unknown')}] (similitud: {sim:.2f})\n"
                f"Título: {doc.get('title', 'Sin título')}\n"
                f"Extracto: {doc.get('excerpt', '')}\n"
            )
        return "\n---\n".join(parts)

    def _format_realtime_context(self, rt_data: dict) -> str:
        """Formatea el contexto en tiempo real obtenido vía MCP.

        Args:
            rt_data: Diccionario con la respuesta del tool build_realtime_hr_context.

        Returns:
            Texto formateado con los extractos de cada fuente de contexto.
        """
        context_items = rt_data.get("context", [])
        if not context_items:
            return "No se encontró contexto en tiempo real para esta consulta."
        parts = []
        for item in context_items:
            parts.append(
                f"[Fuente: {item.get('source', 'desconocida')}]\n{item.get('excerpt', '')}"
            )
        return "\n---\n".join(parts)
