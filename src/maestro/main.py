import asyncio
import subprocess
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from maestro.api.routes.callback import router as callback_router
from maestro.api.routes.orchestrator import router as orchestrator_router
from maestro.api.routes.ui import router as ui_router
from maestro.config.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Aqui será inicializada a conexão assíncrona com o Postgres (SQLAlchemy + asyncpg)
    logger.info("Iniciando o Maestro - Orquestrador de Releases!")

    logger.info("Executando migrations do banco de dados (Alembic)...")
    try:
        # Executa as migrations via subprocesso para evitar conflitos de event loop
        # (já que FastAPI tem o próprio loop rodando e o Alembic async cria o dele)
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
        logger.info("Migrations executadas com sucesso!")
    except subprocess.CalledProcessError as e:
        logger.error(f"Erro ao rodar migrations: {e}")

    # Inicia o checker de timeout em background
    from maestro.services.timeout_checker import start_timeout_checker

    timeout_task = asyncio.create_task(start_timeout_checker())

    # Inicia o checker de agendamentos em background
    from maestro.services.scheduler import start_scheduler_checker

    scheduler_task = asyncio.create_task(start_scheduler_checker())

    yield

    # Cancela os checkers ao encerrar
    timeout_task.cancel()
    scheduler_task.cancel()
    try:
        await timeout_task
    except asyncio.CancelledError:
        pass
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    logger.info("Encerrando o Maestro.")


app = FastAPI(
    title="Maestro",
    description="Orquestrador de releases em Python",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(orchestrator_router)
app.include_router(callback_router)
app.include_router(ui_router)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "message": "Maestro is running!"}


def main():
    """Entrypoint para rodar a API localmente via script"""
    uvicorn.run("maestro.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
