"""
agents/openai_agent.py
Worker conversacional: GPT-4o actuando como asistente de RRHH.
Genera respuestas cálidas, precisas y basadas en el contexto de políticas.
"""
import os

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

HR_SYSTEM_PROMPT = """
Eres HRBot, un asistente virtual especializado en las políticas internas de Recursos Humanos
de la empresa. Tu misión es ayudar a los empleados a entender sus derechos, beneficios y
procesos internos con respuestas claras, precisas y amigables.

DIRECTRICES:
- Responde SIEMPRE basándote en el contexto de políticas provisto (RAG + MCP).
- Si el contexto no cubre la pregunta, indícalo con honestidad y sugiere contactar a RRHH.
- Usa un tono cálido, empático y profesional — hablas con colegas, no con clientes.
- Cita la fuente (nombre del documento) cuando des información específica.
- Nunca inventes datos, fechas, montos o procedimientos que no estén en el contexto.
- Cuando la respuesta sea compleja, usa listas numeradas o bullets para mayor claridad.
- Responde en el mismo idioma en que se formula la pregunta.

EJEMPLO DE INICIO DE RESPUESTA:
"Según la Política de Vacaciones de la empresa, tienes derecho a..."
"De acuerdo con el Reglamento de Teletrabajo..."
"El proceso para solicitar un permiso médico se describe en..."
"""

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def generate_hr_response(
    user_message: str,
    history: list[dict],
    rag_context: str,
    realtime_context: str,
) -> tuple[str, int]:
    """Genera una respuesta de RRHH usando GPT-4o con contexto RAG + MCP.

    Construye el bloque de contexto combinando los documentos recuperados
    por búsqueda semántica y el contexto en tiempo real obtenido vía MCP,
    y lo envía junto con el historial de la sesión a GPT-4o.

    Args:
        user_message:     Pregunta del empleado.
        history:          Historial de la sesión (hasta 20 turnos).
        rag_context:      Top-K documentos recuperados por búsqueda semántica.
        realtime_context: Extractos de política obtenidos vía MCP en tiempo real.

    Returns:
        Tupla con el texto de respuesta generado por GPT-4o y la cantidad
        total de tokens consumidos en la llamada.
    """
    context_block = f"""
=== CONTEXTO DE POLÍTICAS (RAG semántico) ===
{rag_context}

=== CONTEXTO EN TIEMPO REAL (MCP) ===
{realtime_context}
"""

    messages = [
        {"role": "system", "content": HR_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": f"Usa el siguiente contexto para responder:\n{context_block}",
        },
        *history,
        {"role": "user", "content": user_message},
    ]

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=1_200,
    )
    text = response.choices[0].message.content or ""
    tokens = response.usage.total_tokens if response.usage else 0
    return text, tokens
