from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

import subprocess
import sys

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Aqui será inicializada a conexão assíncrona com o Postgres (SQLAlchemy + asyncpg)
    print("Iniciando o Maestro - Orquestrador de Releases!")
    
    print("Executando migrations do banco de dados (Alembic)...")
    try:
        # Executa as migrations via subprocesso para evitar conflitos de event loop (já que FastAPI tem o próprio loop rodando e o Alembic async cria o dele)
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
        print("Migrations executadas com sucesso!")
    except subprocess.CalledProcessError as e:
        print(f"Erro ao rodar migrations: {e}")
        
    yield
    print("Encerrando o Maestro.")

from maestro.api.routes.orchestrator import router as orchestrator_router

app = FastAPI(
    title="Maestro",
    description="Orquestrador de releases em Python",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(orchestrator_router)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "message": "Maestro is running!"}

def main():
    """Entrypoint para rodar a API localmente via script"""
    uvicorn.run("maestro.main:app", host="0.0.0.0", port=8000, reload=True)

if __name__ == "__main__":
    main()
