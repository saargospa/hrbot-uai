# HRBot — Agente Multi-LLM de Políticas de RRHH

Sistema de agentes de inteligencia artificial que combina **GPT-4o** (conversación) y **Claude Sonnet** (fiscalización) para responder consultas sobre políticas internas de Recursos Humanos con validación automática, memoria de sesión y trazabilidad completa.

> **Universidad Adolfo Ibáñez · Máster en Inteligencia Artificial**
> Simulaciones Basadas en Agentes · 2025

---

## Arquitectura

```
┌───────────────────────────────────────────────────────────────┐
│                    USUARIO / CLIENTE                          │
│               Web UI  ·  REST API  ·  CLI                     │
└──────────────────────────┬────────────────────────────────────┘
                           │ HTTP POST /chat
                           ▼
┌───────────────────────────────────────────────────────────────┐
│                 FastAPI + Uvicorn (main.py)                    │
│                   Puerto 8080  ·  CORS                        │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│            ORCHESTRATOR (agents/orchestrator.py)               │
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │Redis RAG │  │ MCP      │  │ OpenAI   │  │   Claude     │ │
│  │  (KNN)   │  │Políticas │  │ GPT-4o   │  │   Sonnet     │ │
│  │          │  │          │  │(Conversa)│  │(Fiscalizador)│ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘ │
│                                                               │
│  PostgreSQL ← registro de cada interacción (Paso 07)          │
└───────────────────────────────────────────────────────────────┘
```

### Pipeline de 7 pasos

| Paso | Descripción |
|------|-------------|
| 1 | Cargar historial de Redis (últimos 20 turnos de la sesión) |
| 2 | Búsqueda KNN semántica en Redis (top-5 documentos relevantes) |
| 3 | Contexto en tiempo real vía MCP (políticas filtradas por query) |
| 4 | GPT-4o genera respuesta con contexto RAG + MCP + historial |
| 5 | Claude Sonnet fiscaliza: verifica datos, detecta PII y alucinaciones |
| 6 | Si hay issues → Claude corrige; si está OK → respuesta original |
| 7 | Persiste turno en Redis + registra interacción en PostgreSQL |

---

## Arquitectura Multi-LLM

| Atributo | Agente Conversador | Agente Fiscalizador |
|----------|--------------------|---------------------|
| **Modelo** | OpenAI GPT-4o | Anthropic Claude Sonnet |
| **SDK** | `openai` | `anthropic` |
| **Rol** | Generar respuesta empática y precisa | Auditar exactitud, PII y alucinaciones |
| **Temperatura** | 0.7 (creativo) | 0.0 (determinista) |
| **Max tokens** | 1,200 | 1,000 |
| **Respuesta** | Texto libre en español | JSON: `{ok, issues, corrected}` |

---

## MCP — Model Context Protocol

Servidor MCP (`mcp_server_hr.py`) con **8 tools** que abstraen el acceso a los documentos de política:

| Tool | Descripción |
|------|-------------|
| `get_vacation_policy` | Política completa de vacaciones |
| `get_remote_work_policy` | Reglamento de teletrabajo |
| `get_leave_and_permissions_policy` | Permisos y licencias |
| `get_benefits_policy` | Catálogo de beneficios |
| `get_onboarding_guide` | Guía de onboarding |
| `search_policy_by_topic` | Búsqueda por tema en todas las políticas |
| `list_available_policies` | Lista de políticas disponibles |
| `build_realtime_hr_context` | Contexto enriquecido filtrado por query |

Transportes soportados: **stdio**, **SSE** y **direct** (fallback para Windows).

---

## Redis RAG — Búsqueda Semántica KNN

- **Modelo de embeddings:** `text-embedding-3-small` (1,536 dimensiones)
- **Similitud:** coseno sobre todos los embeddings indexados
- **Top-K:** 5 documentos por consulta (configurable vía `RAG_TOP_K`)
- **Almacenamiento:** `hr:doc:<id>` (metadata JSON), `hr:emb:<id>` (vector float32), `hr:index` (SET de IDs)
- **Memoria de sesión:** `hr:chat:{session_id}:history` con TTL de 3,600 segundos

---

## PostgreSQL — Trazabilidad (Paso 07)

Cada interacción se registra en la tabla `interactions`:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | Integer PK | Autoincremental |
| `session_id` | String(64) | Sesión del empleado (indexado) |
| `timestamp` | DateTime TZ | Fecha y hora del registro |
| `query` | Text | Pregunta original del empleado |
| `response` | Text | Respuesta final entregada |
| `tokens_used` | Integer | Tokens consumidos (GPT-4o) |
| `latency_ms` | Integer | Latencia total del pipeline |
| `was_corrected` | Boolean | Si el fiscalizador corrigió la respuesta |
| `fiscalization_ok` | Boolean | Si pasó la auditoría sin issues |
| `issues` | Text (JSON) | Lista de problemas detectados |

Migraciones automáticas con **Alembic** al iniciar el contenedor.

---

## API REST

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/` | GET | Interfaz web de chat (HTML embebido) |
| `/health` | GET | Health check: `{status: ok}` |
| `/status` | GET | Estado de Redis, modelos y políticas |
| `/chat` | POST | Enviar mensaje y recibir respuesta |
| `/index` | POST | Indexar políticas en Redis RAG |
| `/history/{id}` | GET | Historial de una sesión |
| `/history/{id}` | DELETE | Borrar historial de una sesión |
| `/docs` | GET | Swagger UI (autogenerado por FastAPI) |

### Request / Response de `/chat`

```json
// REQUEST — POST /chat
{
  "message": "¿Cuántos días de vacaciones tengo?",
  "session_id": "abc123",
  "fiscalize": true,
  "use_realtime": true
}

// RESPONSE — 200 OK
{
  "session_id": "abc123",
  "response": "Según la Política de Vacaciones, tienes derecho a 15 días...",
  "was_corrected": false,
  "fiscalization_ok": true,
  "issues": [],
  "rag_hits": 5,
  "realtime_available": true
}
```

---

## Stack Tecnológico

| Librería | Versión | Uso |
|----------|---------|-----|
| FastAPI | 0.136.3 | Framework web async (API REST) |
| Uvicorn | 0.48.0 | Servidor ASGI |
| OpenAI SDK | 2.38.0 | GPT-4o + text-embedding-3-small |
| Anthropic SDK | ≥0.49.0 | Claude Sonnet (fiscalizador) |
| MCP SDK | 1.27.2 | Protocolo de contexto para LLMs |
| Redis | 8.0.0 | Vector store KNN + memoria de sesión |
| SQLAlchemy | ≥2.0 | ORM async para PostgreSQL |
| asyncpg | ≥0.29 | Driver PostgreSQL asíncrono |
| Alembic | ≥1.13 | Migraciones de base de datos |
| Pydantic | 2.13.4 | Validación de datos y schemas |
| tenacity | 9.1.4 | Reintentos con backoff exponencial |
| httpx | 0.28.1 | Cliente HTTP async |
| numpy | 1.26.0 | Operaciones vectoriales (similitud coseno) |
| rich | 15.0.0 | Output enriquecido para CLI |

---

## Estructura del Proyecto

```
hrbot/
├── main.py                       ← FastAPI + endpoints + Web UI + CLI
├── mcp_server_hr.py              ← Servidor MCP con 8 tools de políticas
├── docker-compose.yml            ← Orquesta hrbot + redis + postgres
├── Dockerfile                    ← Imagen Python 3.11-slim
├── docker-entrypoint.sh          ← Redis → Postgres → Alembic → index → uvicorn
├── alembic.ini                   ← Configuración de migraciones
├── requirements.txt
├── .env.example                  ← Plantilla de variables de entorno
│
├── agents/
│   ├── orchestrator.py           ← Pipeline de 7 pasos con métricas
│   ├── openai_agent.py           ← GPT-4o conversador (temp 0.7)
│   └── anthropic_fiscalizador.py ← Claude Sonnet fiscalizador (temp 0.0)
│
├── services/
│   ├── redis_rag.py              ← Embeddings KNN + memoria de sesión
│   ├── mcp_hr_client.py          ← Cliente MCP (direct/stdio/SSE)
│   └── db.py                     ← SQLAlchemy async + modelo Interaction
│
├── alembic/
│   ├── env.py                    ← Entorno de migraciones async
│   ├── script.py.mako            ← Template de migraciones
│   └── versions/
│       └── 001_create_interactions.py ← Tabla interactions + índice
│
└── docs/policies/
    ├── vacaciones.md
    ├── teletrabajo.md
    ├── permisos.md
    ├── beneficios.md
    └── onboarding.md
```

---

## Despliegue con Docker

### Requisitos previos

- Docker Desktop instalado y corriendo
- API key de OpenAI (`OPENAI_API_KEY`)
- API key de Anthropic (`ANTHROPIC_API_KEY`)

### Paso 1 — Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con las API keys reales
```

### Paso 2 — Levantar el proyecto

```bash
docker compose up --build
```

Docker ejecuta automáticamente:
1. Levanta Redis 7 y PostgreSQL 16
2. Espera healthchecks de ambos servicios
3. Ejecuta `alembic upgrade head` (crea tabla `interactions`)
4. Indexa los documentos de política en Redis RAG
5. Inicia uvicorn en el puerto 8080

### Paso 3 — Abrir la aplicación

→ **http://localhost:8080**

### Comandos útiles

```bash
docker compose up --build         # Levantar todo
docker compose down               # Detener (mantiene datos)
docker compose down -v            # Detener y borrar datos
docker compose logs -f hrbot      # Ver logs en vivo
docker compose exec hrbot python main.py --index   # Reindexar políticas
docker compose exec hrbot python main.py --cli     # Chat interactivo
docker compose exec hrbot python main.py --demo    # Demo automático
```

---

## Variables de Entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | API key de OpenAI (GPT-4o + embeddings) | — |
| `ANTHROPIC_API_KEY` | API key de Anthropic (Claude Sonnet) | — |
| `OPENAI_MODEL` | Modelo conversador | `gpt-4o` |
| `ANTHROPIC_MODEL` | Modelo fiscalizador | `claude-sonnet-4-20250514` |
| `EMBEDDING_MODEL` | Modelo de embeddings | `text-embedding-3-small` |
| `REDIS_HOST` | Host de Redis | `localhost` |
| `REDIS_PORT` | Puerto de Redis | `6379` |
| `REDIS_PASSWORD` | Contraseña de Redis | (vacía) |
| `DATABASE_URL` | Conexión PostgreSQL | `postgresql+asyncpg://hrbot:hrbot@localhost:5432/hrbot` |
| `RAG_TOP_K` | Documentos a recuperar por consulta | `5` |
| `MCP_TRANSPORT` | Transporte MCP: `direct`, `stdio`, `sse` | `direct` |
| `POLICIES_DIR` | Ruta a documentos de política | `docs/policies` |

---

## Despliegue en Producción

El proyecto incluye configuración Apache2 (`hrbot.saargo.com.conf`) con:

- Redirect HTTP → HTTPS con Let's Encrypt
- Reverse proxy hacia uvicorn en puerto 8080
- Headers de seguridad (HSTS, X-Frame-Options, nosniff)
- Timeout de 120s para respuestas largas de LLMs

URL de producción: **https://hrbot.saargo.com**
