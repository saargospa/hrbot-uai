"""
mcp_server_hr.py
Servidor MCP de políticas de Recursos Humanos.
Expone 8 tools que abstraen la capa de documentos corporativos
y permiten a los LLMs acceder a las políticas de forma estructurada.
"""
import json
import os
from pathlib import Path
from mcp.server import FastMCP

POLICIES_DIR = Path(os.getenv("POLICIES_DIR", "docs/policies"))

mcp = FastMCP(
    name="hr-policies",
    instructions=(
        "Servidor MCP de políticas internas de Recursos Humanos. "
        "Provee acceso estructurado a reglamentos, beneficios, vacaciones, "
        "permisos, teletrabajo y onboarding de la empresa."
    ),
)


def _load_policy(filename: str) -> dict:
    """Carga y retorna el contenido de un archivo de política desde el disco.

    Args:
        filename: Nombre del archivo de política (ej: 'vacaciones.md').

    Returns:
        Diccionario con el nombre del archivo y su contenido textual,
        o un mensaje de error si el archivo no existe.
    """
    path = POLICIES_DIR / filename
    if not path.exists():
        return {"error": f"Política '{filename}' no encontrada.", "content": ""}
    return {"filename": filename, "content": path.read_text(encoding="utf-8")}


@mcp.tool()
async def get_vacation_policy() -> str:
    """
    Retorna la política completa de vacaciones de la empresa.
    Incluye días disponibles, procedimiento de solicitud y restricciones.
    """
    data = _load_policy("vacaciones.md")
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
async def get_remote_work_policy() -> str:
    """
    Retorna el reglamento de teletrabajo/trabajo remoto.
    Incluye elegibilidad, modalidades, equipamiento y expectativas.
    """
    data = _load_policy("teletrabajo.md")
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
async def get_leave_and_permissions_policy() -> str:
    """
    Retorna la política de permisos y licencias (médica, maternidad,
    paternidad, estudio, emergencias, etc.).
    """
    data = _load_policy("permisos.md")
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
async def get_benefits_policy() -> str:
    """
    Retorna el catálogo completo de beneficios para empleados:
    seguro médico, bonos, capacitación, convenios y otros.
    """
    data = _load_policy("beneficios.md")
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
async def get_onboarding_guide() -> str:
    """
    Retorna la guía de onboarding para nuevos empleados.
    Incluye primeros pasos, accesos, contactos clave y checklist.
    """
    data = _load_policy("onboarding.md")
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
async def search_policy_by_topic(topic: str) -> str:
    """
    Busca en todos los documentos de política las secciones
    relevantes para el tema indicado.

    Args:
        topic: Tema a buscar (ej: 'días libres', 'home office', 'seguro médico')

    Returns:
        JSON con fragmentos relevantes de cada documento que menciona el tema.
    """
    results = []
    topic_lower = topic.lower()
    for policy_file in POLICIES_DIR.glob("*.md"):
        content = policy_file.read_text(encoding="utf-8")
        if topic_lower in content.lower():
            # Extrae párrafos que contienen el término
            paragraphs = [
                p.strip()
                for p in content.split("\n\n")
                if topic_lower in p.lower() and p.strip()
            ]
            results.append({
                "source": policy_file.name,
                "matches": paragraphs[:3],  # máximo 3 párrafos por documento
            })
    if not results:
        return json.dumps({"found": False, "topic": topic, "results": []}, ensure_ascii=False)
    return json.dumps({"found": True, "topic": topic, "results": results}, ensure_ascii=False)


@mcp.tool()
async def list_available_policies() -> str:
    """
    Lista todos los documentos de política disponibles en el sistema.
    Retorna nombre, descripción breve y fecha de última modificación.
    """
    policies = []
    descriptions = {
        "vacaciones.md": "Política de vacaciones y días libres",
        "teletrabajo.md": "Reglamento de teletrabajo y trabajo remoto",
        "permisos.md": "Permisos, licencias y ausencias justificadas",
        "beneficios.md": "Catálogo de beneficios para empleados",
        "onboarding.md": "Guía de incorporación para nuevos empleados",
    }
    for policy_file in POLICIES_DIR.glob("*.md"):
        stat = policy_file.stat()
        policies.append({
            "filename": policy_file.name,
            "description": descriptions.get(policy_file.name, "Política corporativa"),
            "size_chars": stat.st_size,
            "last_modified": stat.st_mtime,
        })
    return json.dumps({"policies": policies, "total": len(policies)}, ensure_ascii=False)


@mcp.tool()
async def build_realtime_hr_context(query: str) -> str:
    """
    Construye un contexto enriquecido con las políticas más relevantes
    para la query dada. Útil como input directo para los LLMs.

    Args:
        query: Pregunta o tema del usuario

    Returns:
        JSON con contexto combinado de las políticas más relevantes.
    """
    # Cargar todas las políticas y filtrar por relevancia básica
    keywords_map = {
        "vacaciones.md": ["vacacion", "días libres", "descanso", "anuales", "feriado"],
        "teletrabajo.md": ["remoto", "teletrabajo", "home office", "trabajo desde casa", "híbrido"],
        "permisos.md": ["permiso", "licencia", "médico", "maternidad", "paternidad", "ausencia"],
        "beneficios.md": ["beneficio", "seguro", "bono", "capacitación", "convenio", "descuento"],
        "onboarding.md": ["nuevo", "ingreso", "incorporación", "onboarding", "primer día", "acceso"],
    }
    query_lower = query.lower()
    context_parts = []

    for filename, keywords in keywords_map.items():
        if any(kw in query_lower for kw in keywords):
            data = _load_policy(filename)
            if "content" in data and data["content"]:
                # Incluir primeros 800 caracteres como contexto
                context_parts.append({
                    "source": filename,
                    "excerpt": data["content"][:800],
                })

    # Si no hubo matches específicos, incluir lista de políticas disponibles
    if not context_parts:
        context_parts = [{"source": "index", "excerpt": "Políticas disponibles: vacaciones, teletrabajo, permisos, beneficios, onboarding."}]

    return json.dumps({"query": query, "context": context_parts}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
