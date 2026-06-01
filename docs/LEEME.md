# HRBot — Cómo levantar en Docker

## Lo único que necesitas antes de empezar

- **Docker Desktop** instalado y corriendo → https://www.docker.com/products/docker-desktop/
- **Tu API key de OpenAI**

---

## Paso 1 — Crear el archivo .env

En la raíz del proyecto crea un archivo llamado `.env` con este contenido:

```
OPENAI_API_KEY=sk-proj-aqui-va-tu-key
OPENAI_MODEL=gpt-4o
EMBEDDING_MODEL=text-embedding-3-small
RAG_TOP_K=5
```

Solo tienes que cambiar el valor de `OPENAI_API_KEY`. El resto lo puedes dejar igual.

---

## Paso 2 — Levantar el proyecto

Desde la carpeta raíz del proyecto ejecuta:

```bash
docker compose up --build
```

Docker hará todo automáticamente en este orden:
1. Descarga la imagen de Redis
2. Construye la imagen de HRBot
3. Espera a que Redis esté listo
4. Indexa los documentos de política en Redis
5. Levanta el servidor en el puerto 8080

Cuando veas esta línea en los logs, ya está listo:

```
hrbot_app  | 🚀 Iniciando HRBot en el puerto 8080...
```

---

## Paso 3 — Abrir la app

→ **http://localhost:8080**

---

## Comandos del día a día

```bash
# Levantar
docker compose up --build

# Detener (mantiene los datos de Redis)
docker compose down

# Detener y borrar todos los datos
docker compose down -v

# Ver logs en vivo
docker compose logs -f hrbot

# Reindexar si agregas nuevos documentos .md
docker compose exec hrbot python main.py --index
```

---

## Agregar nuevas políticas

1. Agrega un archivo `.md` dentro de `docs/policies/`
2. Ejecuta: `docker compose exec hrbot python main.py --index`

No hace falta reconstruir la imagen.

---

## Estructura del proyecto

```
hrbot/
├── .env                          ← TÚ LO CREAS (no está en el repo)
├── .env.example                  ← plantilla para crear el .env
├── .dockerignore
├── docker-compose.yml            ← orquesta hrbot + redis
├── Dockerfile                    ← imagen de la app
├── docker-entrypoint.sh          ← espera Redis → indexa → levanta uvicorn
├── main.py                       ← FastAPI + endpoints
├── mcp_server_hr.py              ← servidor MCP con 8 tools de políticas
├── requirements.txt
│
├── agents/
│   ├── orchestrator.py           ← pipeline de 7 pasos
│   ├── openai_agent.py           ← GPT-4o conversador
│   └── anthropic_fiscalizador.py ← GPT-4o fiscalizador
│
├── services/
│   ├── redis_rag.py              ← embeddings KNN + sesiones
│   └── mcp_hr_client.py          ← cliente MCP (lee archivos de política)
│
└── docs/policies/
    ├── vacaciones.md
    ├── teletrabajo.md
    ├── permisos.md
    ├── beneficios.md
    └── onboarding.md
```
