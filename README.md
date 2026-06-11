# Maestro - Orquestrador de Releases

Orquestrador de releases desenvolvido em Python com FastAPI. Gerencia pipelines complexas (stages e steps) orquestrando a execução de jobs no Jenkins, com suporte a aprovações manuais, callbacks assíncronos e interface web em tempo real.

## Funcionalidades

- Upload e versionamento de descritores de release (YAML)
- Execução orquestrada de pipelines com múltiplos stages e steps
- Integração nativa com Jenkins (disparo de jobs, aprovações, polling de fila)
- Validação de Pull Requests via GitHub antes da execução
- Callbacks assíncronos para atualização de status (event-driven)
- Suporte a aprovações manuais (waiting_approval)
- Retry de steps com falha
- **Job Path Registry** — cadastro centralizado de job paths com discovery automático do Jenkins
- Agendamento de releases
- Interface web com atualizações em tempo real (SSE + HTMX)
- Registro de eventos por step (logs do Jenkins)

## Estrutura do Projeto

```
src/maestro/
├── api/routes/       # Endpoints FastAPI (orchestrator, callback, ui)
├── config/           # Configurações de ambiente e logger
├── database/         # Modelos ORM e session async (SQLAlchemy + asyncpg/aiosqlite)
├── integration/      # Clientes HTTP para Jenkins e GitHub
├── repositories/     # Padrão repository para queries ao banco
├── schemas/          # Pydantic models (validação, DTOs, enums)
├── services/         # Lógica de negócio e máquina de estado
└── ui/templates/     # Templates HTML (Jinja2 + HTMX)
migrations/           # Migrations do Alembic
postman/              # Collection do Postman para testes de API
tests/                # Testes automatizados
```

## Pré-requisitos

- Python >= 3.11
- PostgreSQL 15+ **ou** SQLite 3 (incluso no Python)
- Docker e Docker Compose (para infra local com PostgreSQL)
- [uv](https://github.com/astral-sh/uv) (gerenciador de pacotes recomendado)

## Como executar

### 1. Subir a infraestrutura

```bash
docker-compose up -d
```

Isso inicia:
- **PostgreSQL** na porta `5432`
- **Jenkins** na porta `8080`

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env` com suas credenciais:

```env
JENKINS_URL=http://localhost:8080
JENKINS_USERNAME=seu_usuario
JENKINS_TOKEN=seu_token

GITHUB_ORGANIZATION=sua-org
GITHUB_TOKEN=seu_token_do_github
```

#### Configuracao do Banco de Dados (`DB_URL`)

O Maestro suporta dois backends de banco de dados, configurados pela variavel `DB_URL` no arquivo `.env`:

**PostgreSQL** (recomendado para producao e ambientes com alta concorrencia):

```env
DB_URL=postgresql+asyncpg://maestro_user:maestro_password@localhost:5432/maestro_db
```

**SQLite** (ideal para desenvolvimento, testes ou deploys single-user):

```env
DB_URL=sqlite+aiosqlite:///./maestro.db
```

> **Notas sobre SQLite:**
> - O arquivo do banco (`maestro.db`) e criado automaticamente no diretorio informado.
> - O WAL mode (Write-Ahead Logging) e habilitado automaticamente para melhor concorrencia.
> - A opcao `check_same_thread=False` e aplicada internamente para compatibilidade com async.
> - Colunas `DateTime(timezone=True)` armazenam timestamps como texto ISO sem offset -- a aplicacao deve operar em UTC.
> - Para ambientes com multiplos workers ou alta concorrencia de escrita, prefira PostgreSQL.

### 3. Instalar dependências

```bash
uv sync
```

### 4. Rodar a aplicação

```bash
uv run maestro
```

A API estará disponível em `http://localhost:8000`.

> As migrations do Alembic são executadas automaticamente ao iniciar a aplicação.

## Endpoints da API

### System

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Health check |

### Orchestrator

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/orchestrator/config` | Upload de YAML de configuração de release |
| POST | `/orchestrator/execute` | Inicia a execução de uma release |
| POST | `/orchestrator/retry-step/{step_execution_id}` | Reexecuta um step com falha |
| POST | `/orchestrator/approve/{name}` | Aprova uma release aguardando aprovação |
| GET | `/orchestrator/status/{name}` | Status da última execução de uma release |
| GET | `/orchestrator/details/{name}` | Detalhes completos (com steps) de uma release |

### Callback

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/callback/release` | Callback do Jenkins ao finalizar um step |
| POST | `/callback/event` | Eventos informativos de um step (logs) |

### UI (Interface Web)

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/ui/` | Página inicial |
| GET | `/ui/execution/{id}` | Detalhes de uma execução |
| POST | `/ui/execution/{id}/approve` | Aprovar execução via UI |
| GET | `/ui/sse/execution/{id}` | Stream SSE para atualizações em tempo real |
| GET | `/ui/step-events/{correlation_id}` | Histórico de eventos de um step |
| POST | `/ui/retry-step/{id}` | Retry de step via UI |
| GET | `/ui/settings` | Página de configurações |
| POST | `/ui/settings` | Salvar configurações |
| POST | `/ui/execute/{name}` | Executar release via UI |
| GET | `/ui/releases` | Listagem de releases cadastradas |
| POST | `/ui/releases/upload` | Upload de YAML de release |

### Job Path Registry

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/ui/job-registry/` | Página do Job Path Registry |
| GET | `/ui/job-registry/partials/list` | Lista paginada com filtro por repositório |
| POST | `/ui/job-registry/discover` | Discovery automático de jobs via Jenkins API |

## Descritor de Release (YAML)

Exemplo de arquivo de configuração:

```yaml
apiVersion: v1
kind: Release
metadata:
  name: minha-release
  author: time-platform
  description: Deploy dos microsserviços
spec:
  strategy:
    type: all-or-nothing
  stages:
    - id: stage-build
      steps:
        - id: build-api
          repository: meu-repo
          release: main
          critical: true
          job:
            type: jenkins
            path: /job/build-api
    - id: stage-deploy
      steps:
        - id: deploy-api
          repository: meu-repo
          release: main
          critical: true
          requires_approval: true
          job:
            type: jenkins
            path: /job/deploy-api
```

## Job Path Registry

O Maestro mantém um cadastro centralizado de job paths, eliminando a necessidade de definir `job.path` explicitamente no YAML de cada release.

### Como funciona

1. **Discovery automático**: Clique no botão "Discovery" na UI (`/ui/job-registry/`). O Maestro consulta a API do Jenkins e importa todos os jobs encontrados.
2. **Resolução de path**: Ao executar uma release, o Maestro resolve o path do job com a seguinte prioridade:
   - `job.path` explícito no YAML (sempre prevalece)
   - Busca na tabela `job_path_registry` por (repository + environment)
   - Fallback: padrão `job/<ENV>/job/<repo>/job/<repo>`

### Tabela `job_path_registry`

| Coluna | Descrição |
|--------|-----------|
| repository | Nome do repositório (ex: `api-gateway`) |
| environment | Ambiente (ex: `PRD`, `UAT`) |
| domain | Agrupamento lógico (ex: `risk-energy`) |
| type | Tipo de job (default: `jenkins`) |
| path | Caminho completo do job |

**Chave única**: `(repository, environment)` — o discovery sempre opera como upsert.

### Estrutura esperada no Jenkins

O discovery extrai dados da árvore de folders do Jenkins:

```
<JENKINS_BASE_URL>/job/<ENVIRONMENT>/job/<DOMAIN>/job/<REPOSITORY>/
```

## Tecnologias

- **FastAPI** -- Framework web assincrono
- **SQLAlchemy** (async) + **asyncpg** / **aiosqlite** -- ORM com suporte a PostgreSQL e SQLite
- **Alembic** -- Migrations de banco de dados (compativel com ambos os backends)
- **Pydantic** -- Validacao de dados e configuracoes
- **Jinja2** + **HTMX** -- Interface web com SSE
- **httpx** -- Cliente HTTP para integracoes
- **uv** -- Gerenciador de pacotes e ambiente virtual

## Desenvolvimento

```bash
# Instalar dependências de desenvolvimento
uv sync --group dev

# Linter
uv run ruff check src/
```

## Testes

O projeto conta com uma suíte de **288 testes** organizada em duas camadas:

### Testes Unitários (254 testes)

Testam cada camada isoladamente com mocks, sem dependências externas.

```bash
# Rodar todos os testes unitários
uv run pytest tests/ -m "not integration"
```

| Arquivo | Testes | Cobertura |
|---------|--------|-----------|
| `tests/test_schemas.py` | 39 | Todos os modelos Pydantic, enums, validação |
| `tests/test_repositories.py` | 29 | Repositórios com AsyncSession mockada |
| `tests/test_services.py` | 35 | Lógica de negócio, orquestração, validação |
| `tests/test_routes.py` | 21 | Rotas da API (status codes, payloads, erros) |
| `tests/test_integrations.py` | 29 | Clientes HTTP do GitHub e Jenkins |
| `tests/test_dry_run.py` | 6 | Cenários de dry-run end-to-end |
| `tests/test_main.py` | 1 | Health check |
| `tests/test_job_path_registry.py` | 36 | Repository, service, resolver, e rotas do Job Registry |

### Testes de Integração (34 testes)

Testam o fluxo completo com um **PostgreSQL real** via container (Docker/Podman). As APIs externas (Jenkins, GitHub) são mockadas no nível HTTP com `pytest-httpx`.

```bash
# Rodar apenas testes de integração (requer Docker ou Podman)
uv run pytest tests/integration/ -m integration

# Rodar um módulo específico
uv run pytest tests/integration/test_orchestrator_flow.py -v
```

| Arquivo | Testes | Cobertura |
|---------|--------|-----------|
| `tests/integration/test_orchestrator_flow.py` | 16 | Upload → dry-run → execute → retry (fluxo completo) |
| `tests/integration/test_callback_flow.py` | 11 | Callbacks do Jenkins atualizando estado real no banco |
| `tests/integration/test_settings_flow.py` | 7 | CRUD de settings com upsert no PostgreSQL |

**Pré-requisitos para testes de integração:**
- Docker ou Podman instalado e com imagem `postgres:16-alpine` disponível
- Porta TCP livre (alocada automaticamente)

**Arquitetura dos testes de integração:**

```
Request HTTP → FastAPI → Service → Integration (mock httpx) ✓
                                 → Repository → PostgreSQL (container real) ✓
```

### Rodar toda a suíte

```bash
# Todos os testes (unitários + integração)
uv run pytest tests/ -v

# Com relatório de cobertura (se pytest-cov instalado)
uv run pytest tests/ --cov=src/maestro --cov-report=term-missing
```

## Docker (Produção)

```bash
docker build -t maestro .
docker run -p 8000:8000 --env-file .env maestro
```

## Arquitetura

Para detalhes sobre decisões arquiteturais, consulte o [ARCHITECTURE.md](ARCHITECTURE.md).
