"""
services/mcp_hr_client.py
Cliente MCP para el servidor de políticas de RRHH.
Soporta transporte stdio, SSE y fallback directo (httpx) para Windows.
Abstrae la comunicación con el servidor MCP y provee métodos
de conveniencia para consultar políticas específicas.
"""
import json
import os
import sys

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "direct")
POLICIES_DIR = os.getenv("POLICIES_DIR", "docs/policies")


class HRPoliciesMCPClient:
    """
    Abstrae las llamadas al servidor MCP de políticas HR.
    En modo 'direct' (Windows/producción simple), lee los archivos
    directamente sin subprocess, garantizando el mismo resultado sin bloqueos.
    """

    def __init__(self):
        """Inicializa el cliente MCP con el transporte configurado en la variable de entorno."""
        self.transport = MCP_TRANSPORT

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> str:
        """Invoca un tool MCP y retorna la respuesta como string."""
        if self.transport == "direct":
            return await self._direct_call(tool_name, arguments or {})
        elif self.transport == "sse":
            return await self._sse_call(tool_name, arguments or {})
        else:
            # stdio — útil en desarrollo Linux/Mac
            return await self._stdio_call(tool_name, arguments or {})

    async def _direct_call(self, tool_name: str, arguments: dict) -> str:
        """
        Modo directo: importa y llama las funciones del servidor MCP
        directamente sin subprocess. Evita el bloqueo de uvicorn en Windows.
        """
        from pathlib import Path

        policies_path = Path(POLICIES_DIR)

        def load_policy(filename: str) -> dict:
            path = policies_path / filename
            if not path.exists():
                return {"error": f"Política '{filename}' no encontrada.", "content": ""}
            return {"filename": filename, "content": path.read_text(encoding="utf-8")}

        file_map = {
            "get_vacation_policy":            "vacaciones.md",
            "get_remote_work_policy":         "teletrabajo.md",
            "get_leave_and_permissions_policy": "permisos.md",
            "get_benefits_policy":            "beneficios.md",
            "get_onboarding_guide":           "onboarding.md",
        }

        if tool_name in file_map:
            return json.dumps(load_policy(file_map[tool_name]), ensure_ascii=False)

        elif tool_name == "list_available_policies":
            policies = []
            descriptions = {
                "vacaciones.md":  "Política de vacaciones y días libres",
                "teletrabajo.md": "Reglamento de teletrabajo y trabajo remoto",
                "permisos.md":    "Permisos, licencias y ausencias justificadas",
                "beneficios.md":  "Catálogo de beneficios para empleados",
                "onboarding.md":  "Guía de incorporación para nuevos empleados",
            }
            for f in policies_path.glob("*.md"):
                policies.append({
                    "filename": f.name,
                    "description": descriptions.get(f.name, "Política corporativa"),
                })
            return json.dumps({"policies": policies, "total": len(policies)}, ensure_ascii=False)

        elif tool_name == "search_policy_by_topic":
            topic = arguments.get("topic", "")
            topic_lower = topic.lower()
            results = []
            for policy_file in policies_path.glob("*.md"):
                content = policy_file.read_text(encoding="utf-8")
                if topic_lower in content.lower():
                    paragraphs = [
                        p.strip()
                        for p in content.split("\n\n")
                        if topic_lower in p.lower() and p.strip()
                    ]
                    results.append({"source": policy_file.name, "matches": paragraphs[:3]})
            return json.dumps({"found": bool(results), "topic": topic, "results": results}, ensure_ascii=False)

        elif tool_name == "build_realtime_hr_context":
            query = arguments.get("query", "")
            query_lower = query.lower()
            keywords_map = {
                "vacaciones.md":  ["vacacion", "días libres", "descanso", "anuales", "feriado"],
                "teletrabajo.md": ["remoto", "teletrabajo", "home office", "trabajo desde casa", "híbrido"],
                "permisos.md":    ["permiso", "licencia", "médico", "maternidad", "paternidad", "ausencia"],
                "beneficios.md":  ["beneficio", "seguro", "bono", "capacitación", "convenio", "descuento"],
                "onboarding.md":  ["nuevo", "ingreso", "incorporación", "onboarding", "primer día", "acceso"],
            }
            context_parts = []
            for filename, keywords in keywords_map.items():
                if any(kw in query_lower for kw in keywords):
                    data = load_policy(filename)
                    if data.get("content"):
                        context_parts.append({"source": filename, "excerpt": data["content"][:800]})
            if not context_parts:
                context_parts = [{"source": "index", "excerpt": "Políticas: vacaciones, teletrabajo, permisos, beneficios, onboarding."}]
            return json.dumps({"query": query, "context": context_parts}, ensure_ascii=False)

        return json.dumps({"error": f"Tool '{tool_name}' no reconocida."})

    async def _sse_call(self, tool_name: str, arguments: dict) -> str:
        """Llamada vía HTTP SSE al servidor MCP en producción."""
        mcp_url = os.getenv("MCP_SERVER_URL", "http://localhost:8081")
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{mcp_url}/tools/call",
                json={"name": tool_name, "arguments": arguments},
            )
            resp.raise_for_status()
            return resp.text

    async def _stdio_call(self, tool_name: str, arguments: dict) -> str:
        """Llamada vía subprocess stdio (desarrollo Linux/Mac)."""
        # En producción real esto se haría con mcp.client.stdio
        # Aquí usamos fallback directo para simplicidad
        return await self._direct_call(tool_name, arguments)

    # ── Métodos de conveniencia ──────────────────────────────────────────────

    async def get_policy(self, policy_type: str) -> str:
        """Obtiene el contenido de una política específica por su tipo.

        Args:
            policy_type: Tipo de política (vacaciones, teletrabajo, permisos, beneficios, onboarding).

        Returns:
            JSON con el contenido de la política solicitada.
        """
        tool_map = {
            "vacaciones": "get_vacation_policy",
            "teletrabajo": "get_remote_work_policy",
            "permisos": "get_leave_and_permissions_policy",
            "beneficios": "get_benefits_policy",
            "onboarding": "get_onboarding_guide",
        }
        tool = tool_map.get(policy_type, "list_available_policies")
        return await self.call_tool(tool)

    async def build_context(self, query: str) -> str:
        """Construye un contexto enriquecido con las políticas relevantes para la consulta.

        Args:
            query: Pregunta o tema del empleado para filtrar las políticas.

        Returns:
            JSON con los extractos de políticas más relevantes para la consulta.
        """
        return await self.call_tool("build_realtime_hr_context", {"query": query})

    async def search_topic(self, topic: str) -> str:
        """Busca en todas las políticas las secciones relacionadas con un tema.

        Args:
            topic: Tema a buscar en los documentos de política.

        Returns:
            JSON con los fragmentos encontrados en cada documento que coincide.
        """
        return await self.call_tool("search_policy_by_topic", {"topic": topic})
