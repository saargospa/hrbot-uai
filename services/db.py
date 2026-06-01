"""
services/db.py
Capa de persistencia en PostgreSQL para trazabilidad de interacciones.
Define el engine asíncrono, la sesión, el modelo Interaction y la
función auxiliar para registrar cada interacción del orquestador.
"""
import json
import os

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://hrbot:hrbot@localhost:5432/hrbot",
)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Clase base declarativa para todos los modelos SQLAlchemy del proyecto."""
    pass


class Interaction(Base):
    """Modelo que representa una interacción completa del pipeline.

    Almacena la pregunta del empleado, la respuesta generada, métricas
    de rendimiento (latencia, tokens) y el resultado de la fiscalización
    para auditoría y análisis posterior.
    """

    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    query = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    tokens_used = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    was_corrected = Column(Boolean, default=False)
    fiscalization_ok = Column(Boolean, default=True)
    issues = Column(Text, default="[]")


async def save_interaction(
    session_id: str,
    query: str,
    response: str,
    tokens_used: int = 0,
    latency_ms: int = 0,
    was_corrected: bool = False,
    fiscalization_ok: bool = True,
    issues: list[str] | None = None,
) -> None:
    """Registra una interacción completa en la tabla interactions de PostgreSQL.

    Args:
        session_id:      Identificador único de la sesión del empleado.
        query:           Pregunta original del empleado.
        response:        Respuesta final entregada al empleado.
        tokens_used:     Total de tokens consumidos en la generación.
        latency_ms:      Latencia total del pipeline en milisegundos.
        was_corrected:   True si el fiscalizador corrigió la respuesta.
        fiscalization_ok: True si la respuesta pasó la fiscalización sin problemas.
        issues:          Lista de problemas detectados por el fiscalizador.
    """
    async with async_session() as session:
        interaction = Interaction(
            session_id=session_id,
            query=query,
            response=response,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            was_corrected=was_corrected,
            fiscalization_ok=fiscalization_ok,
            issues=json.dumps(issues or [], ensure_ascii=False),
        )
        session.add(interaction)
        await session.commit()
