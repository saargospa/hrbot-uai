#!/bin/sh
set -e

# Asegurar que siempre trabajamos desde /app
cd /app

REDIS_HOST="${REDIS_HOST:-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

# ── Esperar Redis ─────────────────────────────────────────────────────────────
echo "⏳ Esperando a que Redis esté disponible en ${REDIS_HOST}:${REDIS_PORT}..."

MAX_WAIT=30
COUNT=0
until python -c "
import socket, sys
try:
    s = socket.create_connection(('${REDIS_HOST}', ${REDIS_PORT}), timeout=1)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    COUNT=$((COUNT + 1))
    if [ $COUNT -ge $MAX_WAIT ]; then
        echo "❌ Redis no respondió después de ${MAX_WAIT} segundos. Abortando."
        exit 1
    fi
    echo "   Reintentando... (${COUNT}/${MAX_WAIT})"
    sleep 1
done

echo "✅ Redis disponible."

# ── Esperar PostgreSQL ────────────────────────────────────────────────────────
echo "⏳ Esperando a que PostgreSQL esté disponible en ${POSTGRES_HOST}:${POSTGRES_PORT}..."

COUNT=0
until python -c "
import socket, sys
try:
    s = socket.create_connection(('${POSTGRES_HOST}', ${POSTGRES_PORT}), timeout=1)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    COUNT=$((COUNT + 1))
    if [ $COUNT -ge $MAX_WAIT ]; then
        echo "❌ PostgreSQL no respondió después de ${MAX_WAIT} segundos. Abortando."
        exit 1
    fi
    echo "   Reintentando... (${COUNT}/${MAX_WAIT})"
    sleep 1
done

echo "✅ PostgreSQL disponible."

# ── Ejecutar migraciones de Alembic ──────────────────────────────────────────
echo "🔄 Ejecutando migraciones de base de datos (Alembic)..."
PYTHONPATH=/app alembic upgrade head

echo "✅ Migraciones aplicadas correctamente."

# ── Indexar políticas en Redis RAG ────────────────────────────────────────────
echo "📚 Indexando documentos de política en Redis RAG..."
PYTHONPATH=/app python /app/main.py --index

# ── Iniciar HRBot ─────────────────────────────────────────────────────────────
echo "🚀 Iniciando HRBot en el puerto 8080..."
exec uvicorn main:app --host 0.0.0.0 --port 8080 --app-dir /app
