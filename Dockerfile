# ---------------------------------------------------
# STAGE 1: Builder
# Utilizamos o uv para criar um ambiente virtual otimizado
# ---------------------------------------------------
FROM python:3.14-slim AS builder

# Copiar os binários do uv diretamente da imagem oficial para facilitar a instalação
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Configurações do uv para otimizar a criação do container
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Copiar apenas arquivos essenciais de dependências primeiro
# Isso nos permite usar o sistema de cache do Docker e não precisar baixar pacotes se o pyproject.toml não mudou
COPY pyproject.toml uv.lock ./

# Sincronizar as dependências, gerando a pasta .venv isolada (sem instalar os pacotes de dev)
RUN uv sync --frozen --no-install-project --no-dev

# Agora, copiar o código-fonte e arquivos de configuração estruturais do projeto
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY README.md ./

# Fazer a sincronização final para instalar o nosso próprio projeto no .venv gerado
RUN uv sync --frozen --no-dev

# ---------------------------------------------------
# STAGE 2: Final (Produção)
# Uma imagem enxuta apenas com o Python rodando
# ---------------------------------------------------
FROM python:3.14-slim

# Evita criação de arquivos .pyc na execução e garante logs em tempo real
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copiar o ambiente virtual (.venv) e o código do Stage 1
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/migrations /app/migrations
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Configurar o PATH para que o Python do ambiente virtual seja usado por padrão
# Isso garante que comandos como 'uvicorn' e 'alembic' funcionem diretamente
ENV PATH="/app/.venv/bin:$PATH"

# Expor a porta que a aplicação vai rodar
EXPOSE 8000

# Executar a aplicação
CMD ["uvicorn", "maestro.main:app", "--host", "0.0.0.0", "--port", "8000"]
