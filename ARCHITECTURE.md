# Arquitetura do Maestro

Maestro e um orquestrador de releases desenvolvido em Python com FastAPI. Ele gerencia pipelines complexas compostas por **stages** e **steps**, orquestrando a execucao de jobs em ferramentas de CI/CD (primariamente Jenkins) baseado em um descritor YAML (`Release`).

---

## 1. Visao Geral

O Maestro atua como um ponto central de controle para releases multi-repositorio. Ele:

- Recebe um **descritor YAML** declarativo que define stages e steps de uma release
- Valida pre-requisitos (branches, PRs, jobs existentes) antes de executar
- Dispara jobs no Jenkins passando parametros de branch
- Recebe **callbacks** do Jenkins informando sucesso/falha de cada step
- Avanca automaticamente entre stages conforme steps sao completados
- Suporta **aprovacao manual** (human-in-the-loop) para steps criticos
- Detecta **timeouts** via background task periodica
- Oferece uma **UI web** (HTMX + SSE) para acompanhamento em tempo real

---

## 2. Stack Tecnologica

| Camada | Tecnologia |
|--------|-----------|
| Linguagem | Python 3.11+ (3.14-slim no Docker) |
| Framework Web | FastAPI + Uvicorn |
| ORM | SQLAlchemy (async) |
| Driver DB | asyncpg (PostgreSQL) / aiosqlite (SQLite) |
| Banco de Dados | PostgreSQL 15 ou SQLite 3 |
| Migrations | Alembic (com `render_as_batch` para SQLite) |
| Validacao | Pydantic v2 + pydantic-settings |
| HTTP Client | httpx (async) |
| UI Server-side | Jinja2 + HTMX |
| Real-time | sse-starlette (Server-Sent Events) |
| Logging | python-json-logger (JSON estruturado) |
| Package Manager | uv |
| Build | Docker multi-stage + hatchling |
| Testes | pytest + pytest-asyncio + pytest-httpx + testcontainers |

---

## 3. Estrutura de Diretorios

```
src/maestro/
├── __init__.py
├── main.py                              # FastAPI app, lifespan (Alembic + timeout checker)
├── api/routes/
│   ├── orchestrator.py                  # REST: /orchestrator/* (CRUD, execute, dry-run, retry, approve)
│   ├── callback.py                      # REST: /callback/* (release callback, event callback)
│   └── ui.py                            # HTML: /ui/* (dashboard HTMX + SSE)
├── config/
│   ├── settings.py                      # Pydantic BaseSettings (DB, Jenkins, GitHub)
│   └── logger.py                        # JSON structured logger
├── database/
│   ├── models.py                        # SQLAlchemy ORM (5 modelos)
│   └── session.py                       # AsyncSession factory (asyncpg ou aiosqlite, detectado via DB_URL)
├── repositories/
│   ├── orchestrator.py                  # CRUD para OrchestratorDescriptor
│   ├── execution.py                     # CRUD para ReleaseExecution, ReleaseStepExecution, StepEvent
│   └── settings.py                      # CRUD para UISettings (upsert dialect-aware: PostgreSQL/SQLite)
├── schemas/
│   ├── enums.py                         # ExecutionStatus enum
│   ├── orchestrator.py                  # ReleaseConfigSchema (YAML), DTOs, DryRun responses
│   ├── callback.py                      # ReleaseCallbackSchema, StepEventSchema
│   ├── github.py                        # PullRequestSchema, PullRequestDetailSchema
│   └── jenkins.py                       # JenkinsQueueItemSchema, JenkinsPendingInputSchema
├── services/
│   ├── orchestrator.py                  # Maquina de estados (process_workflow, execute, approve, retry)
│   ├── jenkins.py                       # JenkinsService (trigger, poll correlation, approve)
│   ├── validation.py                    # ReleaseValidationService (pre-save branch/job checks)
│   ├── timeout_checker.py              # Background loop - marca steps com TIMEOUT
│   ├── settings.py                      # UISettingsService (CRUD + constantes de settings)
│   └── ui.py                            # UIService (views de execucao, SSE stream, stages)
├── integration/
│   ├── __init__.py
│   ├── jenkins.py                       # HTTP client - trigger, queue poll, approve, job_exists
│   └── github.py                        # HTTP client - branch_exists, PR lookup, PR details
└── ui/templates/
    ├── base.html                        # Layout base
    ├── index.html                       # Dashboard principal
    ├── execution_detail.html            # Detalhes de uma execucao
    ├── releases.html                    # Lista de releases
    ├── settings.html                    # Pagina de configuracoes
    └── partials/                         # Fragmentos HTMX
        ├── approve_result.html
        ├── dry_run_result.html
        ├── execute_result.html
        ├── executions_table.html
        ├── release_yaml_modal.html
        ├── resolve_timeout_result.html
        ├── retry_result.html
        ├── stages.html
        ├── status_badge.html
        └── step_events_modal.html
```

Diretorio de testes:

```
tests/
├── conftest.py                          # Fixtures globais (mocks de banco, app de teste)
├── test_dry_run.py
├── test_integrations.py
├── test_main.py
├── test_repositories.py
├── test_routes.py
├── test_schemas.py
├── test_services.py
└── integration/                         # Testes com Testcontainers (PostgreSQL real)
    ├── conftest.py
    ├── test_callback_flow.py
    ├── test_orchestrator_flow.py
    └── test_settings_flow.py
```

---

## 4. Camadas do Projeto

O Maestro segue uma arquitetura em camadas com separacao clara de responsabilidades:

### 4.1 API (`api/routes/`)

Camada de entrada HTTP. Responsavel por:
- Receber requisicoes e validar payloads via Pydantic
- Injetar dependencias (repositories, services) via `Depends()`
- Delegar processamento para a camada de servicos
- Disparar background tasks quando necessario
- Retornar respostas HTTP (JSON para REST, HTML para UI)

### 4.2 Schemas (`schemas/`)

Contratos de dados do sistema:
- **DTOs de entrada/saida**: validacao de requests e formatacao de responses
- **Enums**: estados validos do sistema (`ExecutionStatus`)
- **Schemas de integracao**: mapeamento de respostas externas (Jenkins, GitHub)
- **Release Schema**: estrutura do YAML declarativo

### 4.3 Services (`services/`)

Logica de negocio e orquestracao:
- **OrchestratorService**: maquina de estados principal, controla o fluxo de execucao
- **JenkinsService**: abstrai interacao com Jenkins (trigger + polling de correlacao)
- **ReleaseValidationService**: validacoes pre-execucao (branch existe? PR clean? job existe?)
- **UIService**: monta dados para a interface web (views, SSE)
- **UISettingsService**: gerencia configuracoes persistentes
- **TimeoutChecker**: task de background que detecta steps travados

### 4.4 Repositories (`repositories/`)

Padrao Repository isolando queries SQL da logica de negocio:
- Toda interacao com o banco passa por esta camada
- Recebe `AsyncSession` via dependency injection
- Retorna modelos ORM ou None

### 4.5 Database (`database/`)

Infraestrutura de persistencia:
- **models.py**: definicao das 5 tabelas ORM (SQLAlchemy declarative)
- **session.py**: factory de `AsyncSession` com deteccao automatica de backend via prefixo da `DB_URL`
  - Se `DB_URL` inicia com `sqlite`: usa `aiosqlite`, habilita WAL mode e `check_same_thread=False`
  - Caso contrario: usa `asyncpg` para PostgreSQL

### 4.6 Integration (`integration/`)

Clientes HTTP para servicos externos:
- **JenkinsIntegration**: disparo de jobs, polling de fila, aprovacao de pipelines
- **GithubIntegration**: verificacao de branches, busca de PRs, detalhes de mergeability

### 4.7 Config (`config/`)

Configuracao centralizada:
- **Settings**: variaveis de ambiente via Pydantic BaseSettings (`.env` file)
- **Logger**: configuracao de logging estruturado em JSON

### 4.8 UI (`ui/templates/`)

Templates Jinja2 renderizados server-side:
- Layout base com TailwindCSS (via CDN)
- Componentes dinamicos via HTMX (swaps parciais sem JS custom)
- Atualizacoes em tempo real via SSE

---

## 5. Banco de Dados

O Maestro suporta dois backends de persistencia, selecionados automaticamente pelo prefixo da variavel `DB_URL`:

| Backend | Driver | Formato da URL | Uso recomendado |
|---------|--------|----------------|-----------------|
| PostgreSQL | asyncpg | `postgresql+asyncpg://user:pass@host:port/dbname` | Producao, alta concorrencia |
| SQLite | aiosqlite | `sqlite+aiosqlite:///./maestro.db` | Desenvolvimento, testes, single-user |

### 5.0 Deteccao de Dialeto

A deteccao ocorre em tres pontos:
1. **`database/session.py`**: cria o engine com parametros especificos para cada backend (ex: `check_same_thread=False` e WAL mode para SQLite)
2. **`migrations/env.py`**: aplica `render_as_batch=True` quando o backend e SQLite (necessario para operacoes ALTER TABLE)
3. **`repositories/settings.py`**: usa a funcao `insert` do dialeto correto para operacoes de upsert (PostgreSQL `ON CONFLICT` vs SQLite `ON CONFLICT`)

### 5.0.1 Consideracoes sobre SQLite

- **WAL mode**: habilitado automaticamente via `PRAGMA journal_mode=WAL` no evento de conexao, permitindo leituras concorrentes com uma escrita
- **Timezone**: colunas `DateTime(timezone=True)` armazenam timestamps como texto ISO sem offset; a aplicacao deve operar em UTC
- **Concorrencia**: para multiplos workers uvicorn ou alta carga de escrita, PostgreSQL e fortemente recomendado

### 5.1 Modelos (5 tabelas)

#### `orchestrator_descriptor`
Armazena os descritores YAML de release.

| Coluna | Tipo | Restricoes |
|--------|------|-----------|
| id | Integer | PK, autoincrement |
| name | String | NOT NULL, UNIQUE |
| yaml | Text | NOT NULL |
| created_at | DateTime(tz) | server_default=now() |

#### `release_execution`
Rastreia uma execucao de release como um todo.

| Coluna | Tipo | Restricoes |
|--------|------|-----------|
| id | Integer | PK, autoincrement |
| name | String | NOT NULL |
| status | String | NOT NULL |
| message | Text | nullable |
| orchestrator_descriptor_id | Integer | FK -> orchestrator_descriptor.id |
| created_at | DateTime(tz) | server_default=now() |
| updated_at | DateTime(tz) | server_default=now(), onupdate=now() |

#### `release_step_execution`
Rastreia individualmente cada step de cada stage.

| Coluna | Tipo | Restricoes |
|--------|------|-----------|
| id | Integer | PK, autoincrement |
| release_execution_id | Integer | FK -> release_execution.id |
| stage_id | String | NOT NULL |
| step_id | String | NOT NULL |
| status | String | NOT NULL |
| message | Text | nullable |
| job_execution_correlation_id | Integer | nullable |
| job_input_id | String | nullable |
| updated_at | DateTime(tz) | server_default=now(), onupdate=now() |

**Index**: `ix_release_step_execution_execution_stage_step` (release_execution_id, stage_id, step_id) UNIQUE

#### `ui_settings`
Armazenamento chave/valor para configuracoes da UI.

| Coluna | Tipo | Restricoes |
|--------|------|-----------|
| id | Integer | PK, autoincrement |
| key | String | NOT NULL, UNIQUE |
| value | Text | nullable |
| updated_at | DateTime(tz) | server_default=now(), onupdate=now() |

#### `step_event`
Log de eventos (mensagens) recebidos para cada step.

| Coluna | Tipo | Restricoes |
|--------|------|-----------|
| id | Integer | PK, autoincrement |
| job_execution_correlation_id | Integer | NOT NULL, INDEXED |
| message | Text | NOT NULL |
| created_at | DateTime(tz) | server_default=now() |

### 5.2 Relacionamentos

```
OrchestratorDescriptor 1 ──── N ReleaseExecution
ReleaseExecution       1 ──── N ReleaseStepExecution
ReleaseStepExecution   1 ──── N StepEvent (via job_execution_correlation_id)
```

### 5.3 Migrations

Gerenciadas pelo Alembic. Executadas automaticamente no startup da aplicacao via subprocess:

- Todas as migrations usam `CURRENT_TIMESTAMP` (compativel com ambos os dialetos) em vez de `now()` (PostgreSQL-only)
- Para SQLite, o Alembic utiliza `render_as_batch=True` para contornar limitacoes do `ALTER TABLE`
- O `alembic.ini` obtem a URL de conexao da variavel de ambiente `DB_URL`

```
migrations/versions/
├── 528447aa8a58_create_orchestrator_descriptor.py
├── 5995f0803bff_create_release_execution.py
├── 77fa95ecd37b_create_release_step_execution.py
├── a1b2c3d4e5f6_create_ui_settings.py
├── b2c3d4e5f6a7_create_step_event.py
├── c3d4e5f6a7b8_create_execution_action_log.py
└── d4e5f6a7b8c9_create_scheduled_release.py
```

---

## 6. Maquina de Estados

### 6.1 Status Possiveis

```python
class ExecutionStatus(str, Enum):
    PENDING          = "pending"
    IN_PROGRESS      = "in_progress"
    SUCCESS          = "success"
    FAILURE          = "failure"
    ERROR            = "error"
    ABORTED          = "aborted"
    WAITING_APPROVAL = "waiting_approval"
    TIMEOUT          = "timeout"
```

### 6.2 Transicoes de Estado (Step)

```
                    ┌─────────────────────────────────┐
                    │                                 │
                    v                                 │ (retry)
              ┌─────────┐     trigger      ┌─────────────────┐
              │ PENDING │ ───────────────> │  IN_PROGRESS    │
              └─────────┘                  └─────────────────┘
                                                   │
                              ┌─────────────────────┼──────────────────┐
                              │                     │                  │
                              v                     v                  v
                    ┌──────────────┐    ┌───────────────────┐   ┌──────────┐
                    │   SUCCESS    │    │ WAITING_APPROVAL  │   │ FAILURE  │
                    └──────────────┘    └───────────────────┘   └──────────┘
                                                │                     ^
                                                │ approve             │
                                                v                     │ (retry)
                                        ┌─────────────────┐           │
                                        │  IN_PROGRESS    │ ──────────┘
                                        └─────────────────┘
                                                │
                                                v
                                        ┌──────────────┐
                                        │   TIMEOUT    │ ─── (retry) ──> PENDING
                                        └──────────────┘
```

### 6.3 Transicoes de Estado (Execucao/Release)

- **PENDING -> IN_PROGRESS**: quando `process_workflow` inicia
- **IN_PROGRESS -> SUCCESS**: todos os steps de todos os stages finalizaram com sucesso
- **IN_PROGRESS -> FAILURE**: um step critico falhou (all-or-nothing)
- **IN_PROGRESS -> WAITING_APPROVAL**: todos os steps disponiveis foram processados, mas um ou mais aguardam aprovacao
- **WAITING_APPROVAL -> IN_PROGRESS**: apos aprovacao manual
- **FAILURE/TIMEOUT -> IN_PROGRESS**: apos retry de um step

---

## 7. Endpoints da API

### 7.1 Orchestrator (`/orchestrator`)

| Metodo | Rota | Descricao |
|--------|------|-----------|
| POST | `/orchestrator/config` | Upload de descritor YAML |
| POST | `/orchestrator/execute` | Inicia execucao de uma release |
| POST | `/orchestrator/dry-run` | Validacao pre-flight (branch, PR, job) |
| POST | `/orchestrator/retry-step/{id}` | Reexecuta step com falha/timeout |
| POST | `/orchestrator/approve/{name}` | Aprova steps aguardando aprovacao |
| GET | `/orchestrator/status/{name}` | Status resumido da execucao |
| GET | `/orchestrator/details/{name}` | Detalhes completos da execucao |

### 7.2 Callback (`/callback`)

| Metodo | Rota | Descricao |
|--------|------|-----------|
| POST | `/callback/release` | Jenkins notifica conclusao/status de um step |
| POST | `/callback/event` | Jenkins envia eventos informativos/logs |

### 7.3 UI (`/ui`)

| Metodo | Rota | Descricao |
|--------|------|-----------|
| GET | `/ui/` | Dashboard principal |
| GET | `/ui/partials/executions` | Tabela de execucoes (partial HTMX) |
| GET | `/ui/execution/{id}` | Pagina de detalhes de execucao |
| POST | `/ui/execution/{id}/approve` | Aprovacao via UI |
| GET | `/ui/execution/{id}/release-yaml` | Modal com YAML da release |
| GET | `/ui/sse/execution/{id}` | Stream SSE para atualizacoes real-time |
| GET | `/ui/step-events/{correlation_id}` | Modal de eventos do step |
| POST | `/ui/retry-step/{id}` | Retry de step via UI |
| POST | `/ui/resolve-timeout/{id}` | Resolucao manual de timeout |
| GET | `/ui/settings` | Pagina de configuracoes |
| POST | `/ui/settings` | Salvar configuracoes |
| GET | `/ui/releases` | Lista de releases cadastradas |
| POST | `/ui/releases/upload` | Upload de YAML via UI |
| POST | `/ui/execute/{name}` | Executar release via UI |
| POST | `/ui/dry-run/{name}` | Dry-run via UI |
| GET | `/ui/releases/{id}/yaml` | Visualizar YAML de release |

### 7.4 System

| Metodo | Rota | Descricao |
|--------|------|-----------|
| GET | `/health` | Health check |

---

## 8. Schema do YAML de Release

```yaml
apiVersion: maestro.ecosoft.com/v1alpha1
kind: Release
metadata:
  name: "build-and-deploy-app"       # Identificador unico da release
  author: "Nome do Autor"
  description: "Descricao da release"
spec:
  strategy:
    type: "all-or-nothing"            # ou "fire-and-forget"
  stages:
    - id: "deploy"                    # Identificador unico do stage
      steps:
        - id: deploy-web              # Identificador unico do step
          repository: web-app         # Repositorio no GitHub
          release: "release/v1.0"     # Branch de release
          critical: true              # Se falhar, aborta a release (all-or-nothing)
          requires_approval: true     # Aguarda aprovacao manual no Jenkins
          timeout_minutes: 60         # Timeout em minutos (opcional)
          job:
            type: jenkins             # Tipo de job (apenas Jenkins por ora)
            path: jobs/build-web      # Caminho do job no Jenkins
```

### Estrategias

| Estrategia | Comportamento |
|------------|--------------|
| `all-or-nothing` | Se um step critico falhar, os demais steps dependentes nao serao executados |
| `fire-and-forget` | Mesmo que um step critico falhe, os demais continuam sendo executados |

### Campos do Step

| Campo | Tipo | Obrigatorio | Descricao |
|-------|------|-------------|-----------|
| id | string | sim | Identificador unico dentro do stage |
| repository | string | sim | Nome do repositorio no GitHub |
| release | string | sim | Branch de release (ex: release/v1.0) |
| critical | boolean | nao | Define se falha aborta a release (default: false) |
| requires_approval | boolean | nao | Step aguarda aprovacao manual (default: false) |
| timeout_minutes | integer | nao | Timeout em minutos para o step |
| job.type | string | sim | Tipo de CI/CD (atualmente apenas "jenkins") |
| job.path | string | sim | Caminho do job na ferramenta de CI/CD |

---

## 9. Fluxo de Execucao

### 9.1 Fluxo Completo (do upload ao final)

```
1. Upload do YAML
   └─> POST /orchestrator/config
       └─> Valida YAML (schema Pydantic)
       └─> Valida branches e jobs existem (GitHub + Jenkins)
       └─> Persiste OrchestratorDescriptor

2. Execucao
   └─> POST /orchestrator/execute
       └─> Verifica se descritor existe
       └─> Verifica se nao ha execucao duplicada
       └─> Valida PRs (estado "clean")
       └─> Cria ReleaseExecution (PENDING)
       └─> Cria ReleaseStepExecution para cada step (PENDING)
       └─> Dispara process_workflow em BackgroundTask

3. Process Workflow (background)
   └─> Percorre stages sequencialmente
       └─> Para cada stage:
           └─> Verifica status de todos os steps
           └─> Se ha FAILURE em step critico: marca execucao FAILURE, para
           └─> Se ha TIMEOUT: para e aguarda resolucao
           └─> Dispara steps PENDING (trigger no Jenkins)
           └─> Se ha IN_PROGRESS: para e aguarda callback
           └─> Se ha WAITING_APPROVAL: marca execucao WAITING_APPROVAL

4. Trigger de Job (JenkinsService)
   └─> POST Jenkins /job/path/buildWithParameters (BRANCH=release_branch)
   └─> Recebe queue_url (header Location)
   └─> Inicia polling assincrono (ate 120s) para obter build_number
   └─> Salva build_number como job_execution_correlation_id

5. Callback do Jenkins
   └─> POST /callback/release (com correlation_id e status)
       └─> Atualiza status do step (SUCCESS/FAILURE/WAITING_APPROVAL)
       └─> Se WAITING_APPROVAL: salva job_input_id
       └─> Re-dispara process_workflow para avancar

6. Eventos do Jenkins
   └─> POST /callback/event (com correlation_id e mensagem)
       └─> Salva StepEvent para historico/logs

7. Aprovacao Manual
   └─> POST /orchestrator/approve/{name}
       └─> Chama Jenkins wfapi para aprovar input pendente
       └─> Atualiza step para IN_PROGRESS
       └─> Re-dispara process_workflow

8. Retry de Step
   └─> POST /orchestrator/retry-step/{id}
       └─> Reseta step para PENDING
       └─> Reseta execucao para IN_PROGRESS
       └─> Re-dispara process_workflow
```

### 9.2 Diagrama de Sequencia Simplificado

```
 Usuario         Maestro API        Background        Jenkins         GitHub
    │                │                   │                │               │
    │── POST config ─>│                   │                │               │
    │                │── validate ────────────────────────────────────────>│
    │                │── validate ────────────────────────>│               │
    │<── 200 OK ─────│                   │                │               │
    │                │                   │                │               │
    │── POST execute >│                   │                │               │
    │                │── check PRs ──────────────────────────────────────>│
    │                │── create records ──│                │               │
    │<── 200 OK ─────│── background ────>│                │               │
    │                │                   │── trigger job ─>│               │
    │                │                   │<── queue_url ───│               │
    │                │                   │── poll queue ──>│               │
    │                │                   │<── build_number │               │
    │                │                   │                │               │
    │                │                   │    (job runs)  │               │
    │                │                   │                │               │
    │                │<── POST callback ─────────────────── │              │
    │                │── background ────>│                │               │
    │                │                   │ (advance stage) │               │
```

---

## 10. Decisoes Arquiteturais

### 10.1 Assincronicidade e Background Tasks

- A API usa `async/await` com FastAPI para alta concorrencia sem threads
- O processamento do workflow (`process_workflow`) roda em `BackgroundTasks` para nao bloquear as rotas
- O polling de fila do Jenkins roda como `asyncio.create_task` independente
- O timeout checker roda como task asyncio na lifespan da aplicacao

### 10.2 Callback-Driven (nao Polling)

- O Maestro **nao** faz polling agressivo para saber se um job terminou
- A responsabilidade de notificar sucesso/falha e do Jenkins (via pipeline steps)
- O Jenkins envia um callback HTTP para `/callback/release` com o resultado
- O unico polling existente e o de **correlacao** (queue -> build_number), limitado a 120 segundos apos trigger

### 10.3 Gerenciamento de Estado no Banco

- Todo estado e persistido no banco de dados (PostgreSQL ou SQLite, conforme `DB_URL`) -- nao ha estado em memoria
- Background tasks criam suas proprias sessoes de banco (`AsyncSessionLocal()`) para evitar problemas de ciclo de vida
- Migrations Alembic sao executadas via subprocess no startup para evitar conflito de event loops
- A camada de repositorio detecta o dialeto em runtime para operacoes dialect-specific (ex: upsert)

### 10.4 Timeout com Hierarquia

A resolucao de timeout segue prioridade:
1. `timeout_minutes` definido no step (YAML)
2. `step_timeout_minutes` global (configuracao na UI/banco)
3. Sem timeout (step roda indefinidamente se nenhum dos anteriores estiver configurado)

### 10.5 Dependency Injection

- FastAPI `Depends()` e usado em todas as camadas
- Repositories recebem `AsyncSession` via DI
- Services recebem repositories via DI
- Routes recebem services via DI

### 10.6 Separacao Integration vs Service

- `integration/` contem clientes HTTP puros (sem logica de negocio)
- `services/` contem a logica de orquestracao que utiliza as integracoes
- Isso permite testar a logica de negocio mockando apenas a camada HTTP

### 10.7 UI Server-Side com HTMX

- Sem frameworks JS (React, Vue, etc.)
- Templates Jinja2 renderizados no servidor
- HTMX faz swaps parciais de HTML via requisicoes AJAX
- SSE (Server-Sent Events) para atualizacoes em tempo real sem WebSocket
- Partials sao fragmentos HTML retornados por endpoints especificos

### 10.8 Estrategia All-or-Nothing

- No modo `all-or-nothing`, se qualquer step critico falhar, a execucao inteira e marcada como FAILURE
- No modo `fire-and-forget`, steps continuam independentemente
- Steps sao processados sequencialmente dentro de um stage
- Stages sao processados sequencialmente (proximo stage so inicia quando o anterior completa)

---

## 11. Infraestrutura e Deploy

### 11.1 Docker (Producao)

Build multi-stage com `uv` como package manager:

```dockerfile
# Stage 1: Builder (uv sync das dependencias)
FROM python:3.14-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
# ... sync dependencies + install project

# Stage 2: Runtime (imagem final enxuta)
FROM python:3.14-slim
COPY --from=builder /app/.venv /app/.venv
# ...
CMD ["uvicorn", "maestro.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

A aplicacao expoe a porta **8000**.

### 11.2 Docker Compose (Desenvolvimento)

```yaml
services:
  db:
    image: postgres:15-alpine
    ports: ["5432:5432"]
    environment:
      POSTGRES_USER: maestro_user
      POSTGRES_PASSWORD: maestro_password
      POSTGRES_DB: maestro_db

  jenkins:
    image: jenkins/jenkins:lts
    ports: ["8080:8080", "50000:50000"]
```

### 11.3 Variaveis de Ambiente

| Variavel | Default | Descricao |
|----------|---------|-----------|
| `ENVIRONMENT` | local | Ambiente de execucao |
| `DB_URL` | postgresql+asyncpg://...localhost:5432/maestro_db | Connection string do banco (PostgreSQL ou SQLite) |
| `JENKINS_URL` | http://localhost:8080 | URL base do Jenkins |
| `JENKINS_USERNAME` | None | Usuario de autenticacao Jenkins |
| `JENKINS_TOKEN` | None | Token/senha de autenticacao Jenkins |
| `GITHUB_ORGANIZATION` | my-org | Organizacao no GitHub |
| `GITHUB_TOKEN` | None | Personal Access Token do GitHub |

Exemplos de `DB_URL`:
- PostgreSQL: `postgresql+asyncpg://maestro_user:maestro_password@localhost:5432/maestro_db`
- SQLite: `sqlite+aiosqlite:///./maestro.db`

### 11.4 Startup da Aplicacao

Na lifespan do FastAPI, o Maestro executa:
1. **Alembic migrations** via subprocess (`alembic upgrade head`)
2. **Timeout checker** como asyncio task de background (loop a cada 30s)

---

## 12. Testes

### 12.1 Estrategia

| Tipo | Diretorio | Descricao |
|------|-----------|-----------|
| Unitarios | `tests/test_*.py` | Mocks de banco e HTTP, testa logica isolada |
| Integracao | `tests/integration/` | Testcontainers com PostgreSQL real |

### 12.2 Ferramentas

- **pytest**: runner principal
- **pytest-asyncio**: suporte a testes async (`asyncio_mode = "auto"`)
- **pytest-httpx**: mock de chamadas httpx
- **testcontainers**: container PostgreSQL efemero para testes de integracao

### 12.3 Configuracao

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
markers = [
    "integration: marks tests that require Docker (Testcontainers)",
]
```

### 12.4 Execucao

```bash
# Testes unitarios
pytest tests/ -m "not integration"

# Testes de integracao (requer Docker)
pytest tests/integration/ -m integration

# Todos
pytest
```

---

## Apendice: Colecao Postman

Uma colecao Postman esta disponivel em `postman/Maestro.postman_collection.json` para facilitar testes manuais da API.
