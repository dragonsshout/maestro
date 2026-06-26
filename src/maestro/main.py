import asyncio
import subprocess
import sys
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from maestro.api.routes.auth import router as auth_router
from maestro.api.routes.callback import router as callback_router
from maestro.api.routes.job_path_registry import router as job_registry_router
from maestro.api.routes.orchestrator import router as orchestrator_router
from maestro.api.routes.ui import router as ui_router
from maestro.api.routes.users import router as users_router
from maestro.auth.dependencies import RequiresAuthException
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

    # Inicia o poller de builds do Jenkins em background
    from maestro.services.build_poller import start_build_poller

    build_poller_task = asyncio.create_task(start_build_poller())

    yield

    # Cancela os checkers ao encerrar
    timeout_task.cancel()
    scheduler_task.cancel()
    build_poller_task.cancel()
    try:
        await timeout_task
    except asyncio.CancelledError:
        pass
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    try:
        await build_poller_task
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
app.include_router(job_registry_router)
app.include_router(auth_router)
app.include_router(users_router)

# Serve static assets (CSS, JS) diretamente — elimina dependência de CDN externo.
# Crítico para ambientes com proxy corporativo (NTLM) onde Chrome/Firefox
# não autenticam automaticamente e perdem acesso a CDNs como unpkg, jsdelivr, etc.
_static_dir = Path(__file__).parent / "ui" / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.exception_handler(RequiresAuthException)
async def requires_auth_exception_handler(request: Request, exc: RequiresAuthException):
    if request.headers.get("HX-Request"):
        response = RedirectResponse(url="/ui/login", status_code=303)
        response.headers["HX-Redirect"] = "/ui/login"
        return response
    return RedirectResponse(url="/ui/login", status_code=303)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "message": "Maestro is running!"}


def main():
    """Entrypoint para rodar a API localmente via script"""
    uvicorn.run("maestro.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
