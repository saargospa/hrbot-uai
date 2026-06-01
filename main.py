"""
main.py
Punto de entrada de HRBot — Agente Multi-LLM de Políticas de RRHH.
Modos: API REST (uvicorn), CLI interactiva, demo automático, indexación.
"""
import argparse
import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

load_dotenv()

from agents.orchestrator import HROrchestrator
from services import redis_rag

console = Console()

# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None
    fiscalize: bool = True
    use_realtime: bool = True


class ChatResponseSchema(BaseModel):
    session_id: str
    response: str
    was_corrected: bool
    fiscalization_ok: bool
    issues: list[str]
    rag_hits: int
    realtime_available: bool


class IndexRequest(BaseModel):
    force_reindex: bool = False


# ── FastAPI App ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestiona el ciclo de vida de la aplicación FastAPI.

    Muestra un mensaje al iniciar y otro al apagar el servidor.
    """
    console.print("[bold green]✓ HRBot iniciado correctamente[/bold green]")
    yield
    console.print("[bold yellow]HRBot apagado.[/bold yellow]")


app = FastAPI(
    title="HRBot — Agente de Políticas de RRHH",
    description="Sistema Multi-LLM para consulta de reglamentos y políticas internas de la empresa.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Web UI ────────────────────────────────────────────────────────────────────

WEB_UI_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HRBot — Políticas de RRHH</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, sans-serif; background: #f4f5f7; color: #1a1a2e; height: 100vh; display: flex; flex-direction: column; }
        header { background: #1a1a2e; color: white; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
        header h1 { font-size: 18px; font-weight: 600; }
        header span { font-size: 13px; opacity: 0.6; }
        #chat { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 16px; }
        .bubble { max-width: 75%; padding: 12px 16px; border-radius: 12px; line-height: 1.5; font-size: 15px; }
        .user { background: #1a1a2e; color: white; align-self: flex-end; border-radius: 12px 12px 2px 12px; }
        .bot  { background: white; color: #1a1a2e; align-self: flex-start; border-radius: 12px 12px 12px 2px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        .meta { font-size: 11px; color: #888; margin-top: 4px; }
        .corrected { border-left: 3px solid #f59e0b; padding-left: 8px; }
        footer { background: white; padding: 16px 24px; border-top: 1px solid #e5e7eb; display: flex; gap: 12px; }
        footer input { flex: 1; padding: 10px 14px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 15px; outline: none; }
        footer input:focus { border-color: #1a1a2e; }
        footer button { padding: 10px 20px; background: #1a1a2e; color: white; border: none; border-radius: 8px; font-size: 15px; cursor: pointer; }
        footer button:hover { background: #2d2d4e; }
        .typing { opacity: 0.5; font-style: italic; }
    </style>
</head>
<body>
    <header>
        <div>
            <h1>🤝 HRBot</h1>
            <span>Consultas de Políticas de Recursos Humanos</span>
        </div>
    </header>
    <div id="chat">
        <div class="bubble bot">
            ¡Hola! Soy HRBot, tu asistente de Recursos Humanos. Puedo responder preguntas sobre
            <strong>vacaciones, teletrabajo, permisos, beneficios y onboarding</strong>.
            ¿En qué te puedo ayudar hoy?
        </div>
    </div>
    <footer>
        <input id="msg" type="text" placeholder="Escribe tu pregunta sobre políticas de RRHH..."
               onkeydown="if(event.key==='Enter') sendMessage()">
        <button onclick="sendMessage()">Enviar</button>
    </footer>
    <script>
        const sessionId = Math.random().toString(36).substring(2);
        async function sendMessage() {
            const input = document.getElementById('msg');
            const msg = input.value.trim();
            if (!msg) return;
            input.value = '';
            appendBubble(msg, 'user');
            const typing = appendBubble('Consultando políticas...', 'bot typing');
            try {
                const res = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: msg, session_id: sessionId, fiscalize: true, use_realtime: true })
                });
                const data = await res.json();
                typing.remove();
                const bubble = appendBubble(data.response, 'bot' + (data.was_corrected ? ' corrected' : ''));
                const meta = document.createElement('div');
                meta.className = 'meta';
                meta.textContent = `RAG hits: ${data.rag_hits} · Fiscalización: ${data.fiscalization_ok ? '✓' : '⚠'} ${data.was_corrected ? '(corregido)' : ''}`;
                bubble.parentElement.appendChild(meta);
            } catch(e) {
                typing.textContent = 'Error al conectar con el servidor.';
            }
        }
        function appendBubble(text, cls) {
            const chat = document.getElementById('chat');
            const wrapper = document.createElement('div');
            wrapper.style.display = 'flex';
            wrapper.style.flexDirection = 'column';
            wrapper.style.alignItems = cls.includes('user') ? 'flex-end' : 'flex-start';
            const bubble = document.createElement('div');
            bubble.className = 'bubble ' + cls;
            bubble.textContent = text;
            wrapper.appendChild(bubble);
            chat.appendChild(wrapper);
            chat.scrollTop = chat.scrollHeight;
            return bubble;
        }
    </script>
</body>
</html>
"""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def web_ui():
    """Sirve la interfaz web de chat embebida en HTML.

    Returns:
        Página HTML completa con el cliente de chat interactivo.
    """
    return WEB_UI_HTML


@app.get("/health")
async def health():
    """Endpoint de verificación de salud básica del servicio.

    Returns:
        Diccionario con el estado del servicio: {status: ok, service: hrbot}.
    """
    return {"status": "ok", "service": "hrbot"}


@app.get("/status")
async def status():
    """Verifica el estado de todos los componentes del sistema."""
    import redis.asyncio as aioredis
    redis_ok = False
    try:
        r = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD", ""),
            socket_connect_timeout=3,
        )
        await r.ping()
        await r.aclose()
        redis_ok = True
    except Exception:
        pass

    policies_path = Path(os.getenv("POLICIES_DIR", "docs/policies"))
    policies_found = list(policies_path.glob("*.md")) if policies_path.exists() else []

    return {
        "redis": "ok" if redis_ok else "error",
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        "mcp_transport": os.getenv("MCP_TRANSPORT", "direct"),
        "policies_indexed": len(policies_found),
        "policy_files": [f.name for f in policies_found],
    }


@app.post("/chat", response_model=ChatResponseSchema)
async def chat(request: ChatRequest):
    """Procesa una consulta del empleado a través del pipeline de 7 pasos.

    Recibe la pregunta, la envía al orquestador y retorna la respuesta
    junto con metadatos de fiscalización y métricas RAG.

    Args:
        request: Cuerpo de la petición con message, session_id, fiscalize y use_realtime.

    Returns:
        ChatResponseSchema con la respuesta final y metadatos del pipeline.
    """
    orchestrator = HROrchestrator(
        enable_fiscalization=request.fiscalize,
        use_realtime=request.use_realtime,
    )
    result = await orchestrator.chat(
        message=request.message,
        session_id=request.session_id,
    )
    return ChatResponseSchema(
        session_id=result.session_id,
        response=result.response,
        was_corrected=result.was_corrected,
        fiscalization_ok=result.fiscalization_ok,
        issues=result.issues,
        rag_hits=result.rag_hits,
        realtime_available=result.realtime_available,
    )


@app.post("/index")
async def index_policies(request: IndexRequest):
    """Indexa todos los documentos de política en Redis RAG."""
    indexed = await _run_indexing()
    return {"indexed": indexed, "status": "ok"}


@app.get("/history/{session_id}")
async def get_history(session_id: str):
    """Recupera el historial de conversación de una sesión específica.

    Args:
        session_id: Identificador único de la sesión del empleado.

    Returns:
        Diccionario con el session_id, cantidad de turnos y la lista de mensajes.
    """
    history = await redis_rag.load_history(session_id, max_turns=100)
    return {"session_id": session_id, "turns": len(history), "history": history}


@app.delete("/history/{session_id}")
async def delete_history(session_id: str):
    """Elimina el historial de conversación de una sesión específica.

    Args:
        session_id: Identificador único de la sesión a borrar.

    Returns:
        Diccionario confirmando la eliminación del historial.
    """
    await redis_rag.clear_history(session_id)
    return {"session_id": session_id, "status": "cleared"}


# ── Indexación ────────────────────────────────────────────────────────────────

async def _run_indexing() -> int:
    """Lee los archivos .md de políticas y los indexa en Redis RAG."""
    policies_dir = Path(os.getenv("POLICIES_DIR", "docs/policies"))
    if not policies_dir.exists():
        console.print(f"[red]Directorio de políticas no encontrado: {policies_dir}[/red]")
        return 0

    indexed = 0
    for policy_file in sorted(policies_dir.glob("*.md")):
        content = policy_file.read_text(encoding="utf-8")
        sections = content.split("\n## ")
        base_title = policy_file.stem.replace("_", " ").title()

        for i, section in enumerate(sections):
            if not section.strip():
                continue
            lines = section.strip().split("\n")
            section_title = lines[0].replace("#", "").strip() if lines else base_title
            section_content = "\n".join(lines[1:]).strip() if len(lines) > 1 else section

            doc_id = f"{policy_file.stem}_{i}"
            await redis_rag.index_document(
                doc_id=doc_id,
                title=f"{base_title} — {section_title}",
                content=section_content,
                source_file=policy_file.name,
                tags=[policy_file.stem, section_title.lower()],
            )
            indexed += 1

    console.print(f"[bold green]✓ {indexed} fragmentos de política indexados en Redis RAG[/bold green]")
    return indexed


# ── CLI Interactiva ───────────────────────────────────────────────────────────

async def run_cli():
    """Ejecuta el modo chat interactivo en la terminal.

    Permite al usuario escribir preguntas sobre políticas de RRHH
    y recibir respuestas del pipeline completo con fiscalización.
    La sesión se mantiene hasta que el usuario escriba 'salir'.
    """
    console.print(Panel.fit(
        "[bold]HRBot — Consultas de Políticas de RRHH[/bold]\n"
        "Escribe tu pregunta o 'salir' para terminar.",
        border_style="blue",
    ))
    session_id = str(uuid.uuid4())
    orchestrator = HROrchestrator()

    while True:
        try:
            user_input = console.input("[bold blue]Tú:[/bold blue] ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not user_input or user_input.lower() in {"salir", "exit", "quit"}:
            console.print("[dim]Hasta luego.[/dim]")
            break

        with console.status("[dim]Consultando políticas...[/dim]"):
            result = await orchestrator.chat(message=user_input, session_id=session_id)

        console.print(f"\n[bold green]HRBot:[/bold green]")
        console.print(Markdown(result.response))
        meta = f"RAG hits: {result.rag_hits} · Fiscal: {'✓' if result.fiscalization_ok else '⚠'}"
        if result.was_corrected:
            meta += " · [yellow]Respuesta corregida por fiscalizador[/yellow]"
        if result.issues:
            meta += f"\n[red]Issues: {', '.join(result.issues)}[/red]"
        console.print(f"[dim]{meta}[/dim]\n")


async def run_demo():
    """Ejecuta una demostración automática con preguntas predefinidas.

    Envía cinco preguntas de ejemplo al pipeline y muestra las respuestas
    junto con métricas de RAG y fiscalización para verificación rápida.
    """
    demo_questions = [
        "¿Cuántos días de vacaciones tengo disponibles al año?",
        "¿Puedo trabajar desde casa todos los días?",
        "¿Cómo solicito un permiso médico?",
        "¿Qué beneficios de salud ofrece la empresa?",
        "Soy nuevo empleado, ¿qué tengo que hacer el primer día?",
    ]
    session_id = str(uuid.uuid4())
    orchestrator = HROrchestrator()

    console.print(Panel.fit("[bold]HRBot Demo — Preguntas de ejemplo[/bold]", border_style="green"))

    for question in demo_questions:
        console.print(f"\n[bold blue]Q:[/bold blue] {question}")
        with console.status("[dim]Procesando...[/dim]"):
            result = await orchestrator.chat(message=question, session_id=session_id)
        console.print(f"[bold green]A:[/bold green] {result.response[:200]}...")
        console.print(f"[dim]RAG: {result.rag_hits} | Corrected: {result.was_corrected}[/dim]")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HRBot — Agente de Políticas de RRHH")
    parser.add_argument("--index", action="store_true", help="Indexar políticas en Redis RAG")
    parser.add_argument("--demo",  action="store_true", help="Ejecutar demo automático")
    parser.add_argument("--cli",   action="store_true", help="Chat interactivo en terminal")
    parser.add_argument("--port",  type=int, default=8080, help="Puerto del servidor API")
    args = parser.parse_args()

    if args.index:
        asyncio.run(_run_indexing())
    elif args.demo:
        asyncio.run(run_demo())
    elif args.cli:
        asyncio.run(run_cli())
    else:
        # Modo por defecto: levantar el servidor API
        uvicorn.run("main:app", host="0.0.0.0", port=args.port, reload=False)
