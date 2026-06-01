"""
agents/anthropic_fiscalizador.py
Agente Fiscalizador: Claude Sonnet (Anthropic) audita cada respuesta
del agente conversador antes de entregarla al empleado, detectando
errores, PII y alucinaciones en el contexto de políticas de RRHH.
"""
import json
import os

from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

FISCALIZADOR_SYSTEM_PROMPT = """
Eres un Agente Fiscalizador especializado en políticas de Recursos Humanos corporativas.
Tu rol es AUDITAR y VALIDAR respuestas de otro agente de IA antes de entregarlas a empleados.

CRITERIOS DE VALIDACIÓN (verifica todos):
1. EXACTITUD: ¿Los datos (días, montos, procesos, plazos) coinciden con el contexto de políticas?
2. GEOGRAFÍA ORGANIZACIONAL: ¿No se confunden beneficios/reglas de distintos países o sedes?
3. PII / DATOS SENSIBLES: ¿La respuesta expone datos personales innecesarios?
4. ALUCINACIONES: ¿Se inventan políticas, beneficios o procedimientos no presentes en el contexto?
5. INFORMACIÓN PELIGROSA: ¿Se da asesoría legal o médica sin la advertencia adecuada?
6. PERTINENCIA: ¿La respuesta efectivamente responde la pregunta del empleado?

INSTRUCCIONES DE RESPUESTA:
- Responde ÚNICAMENTE con un JSON válido, sin texto antes ni después.
- Si la respuesta es correcta: {"ok": true, "issues": [], "corrected": null}
- Si hay problemas: {"ok": false, "issues": ["descripción del problema 1", ...], "corrected": "versión corregida"}
- En "corrected" incluye la respuesta completa corregida, no solo el fragmento erróneo.
- Sé conservador: si no tienes suficiente contexto para verificar algo, márcalo como issue.
"""

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


class FiscalizacionResult:
    """Resultado de la fiscalización realizada por Claude Sonnet."""

    def __init__(self, ok: bool, issues: list[str], corrected: str | None):
        """Inicializa el resultado de fiscalización.

        Args:
            ok:        True si la respuesta pasó la auditoría sin problemas.
            issues:    Lista de problemas detectados (vacía si ok=True).
            corrected: Versión corregida de la respuesta, o None si no requiere corrección.
        """
        self.ok = ok
        self.issues = issues
        self.corrected = corrected

    def __repr__(self) -> str:
        """Representación legible del resultado de fiscalización."""
        return f"FiscalizacionResult(ok={self.ok}, issues={len(self.issues)})"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fiscalizar(
    user_question: str,
    agent_response: str,
    policy_context: str,
) -> FiscalizacionResult:
    """Audita la respuesta del agente conversacional usando Claude Sonnet.

    Envía a Claude Sonnet el trío {pregunta, respuesta, contexto} y recibe
    un JSON estructurado con la evaluación de calidad.

    Args:
        user_question:  Pregunta original del empleado.
        agent_response: Respuesta generada por el agente conversador (GPT-4o).
        policy_context: Contexto RAG + MCP usado para generar la respuesta.

    Returns:
        FiscalizacionResult con ok, lista de issues y versión corregida si aplica.
    """
    audit_prompt = f"""
PREGUNTA DEL EMPLEADO:
{user_question}

RESPUESTA DEL AGENTE (a auditar):
{agent_response}

CONTEXTO DE POLÍTICAS DISPONIBLE:
{policy_context}

Audita la respuesta según los criterios indicados y responde solo con JSON válido.
"""

    response = await client.messages.create(
        model=ANTHROPIC_MODEL,
        system=FISCALIZADOR_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": audit_prompt},
        ],
        temperature=0.0,
        max_tokens=1_000,
    )

    raw_text = response.content[0].text if response.content else "{}"

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return FiscalizacionResult(ok=True, issues=[], corrected=None)

    return FiscalizacionResult(
        ok=data.get("ok", True),
        issues=data.get("issues", []),
        corrected=data.get("corrected"),
    )
