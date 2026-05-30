# Arquitetura do Maestro

Maestro é um orquestrador de releases desenvolvido em Python (FastAPI). Ele gerencia pipelines complexas (stages e steps) orquestrando a execução de jobs em ferramentas de CI/CD, primariamente o Jenkins, baseado em um descritor YAML (`Release`).

## Decisões Arquiteturais

1. **Assincronicidade e Background Tasks**:
   - A API usa chamadas assíncronas (`async/await`) em conjunto com `FastAPI` para garantir alta concorrência.
   - O processamento principal do workflow (verificação de steps, chamadas ao Jenkins, avanço de stages) é feito em background via `BackgroundTasks` para não bloquear as rotas de API.

2. **Gerenciamento de Estado**:
   - O estado do pipeline é versionado e gravado no banco relacional (PostgreSQL) usando SQLAlchemy assíncrono.
   - Tabelas principais:
     - `OrchestratorDescriptor`: Guarda o conteúdo YAML original da release.
     - `ReleaseExecution`: O rastreio principal daquela execução como um todo.
     - `ReleaseStepExecution`: Rastreia individualmente cada passo de cada estágio.

3. **Integração com Ferramentas Externas**:
   - A camada de `integration/` lida com as abstrações externas (HTTP client com `httpx`).
   - **Jenkins**: As chamadas ao Jenkins utilizam a API REST e a `wfapi` para manipular as aprovações pendentes (inputs), disparar jobs via `/buildWithParameters` e buscar estados de fila.
   - **GitHub**: Validação do status de Pull Requests e verificação de *mergeability* antes de começar os fluxos.

4. **Event-Driven e Callbacks**:
   - O Maestro não faz *polling* agressivo para descobrir se um job terminou.
   - A responsabilidade de avisar o sucesso/falha do workflow fica do lado de quem o executou. O Jenkins (via pipeline steps) é responsável por enviar um *callback* de volta para a rota `/callback/release` do Maestro.
   - Esse callback atualiza o status na base de dados e injeta novamente a rotina `process_workflow` na fila, reativando a checagem de estado do orquestrador para avançar de stage.

## Camadas do Projeto (`src/maestro`)

- `api/routes`: Endpoints do FastAPI, separados por domínio (`orchestrator`, `callback`).
- `config`: Configurações de ambiente (via Pydantic BaseSettings) e setup de logger.
- `database`: Conexões com SQLAlchemy, session makers assíncronos e modelos ORM.
- `repositories`: Padrão repository isolando as queries do banco de dados da regra de negócio.
- `schemas`: Pydantic models para validação de entrada, saída (DTOs) e os Enums de estados.
- `services`: Lógica de negócio (onde fica a máquina de estado do orquestrador e a abstração das integrações).
- `integration`: Clientes HTTP crus para falar com as APIs de terceiros.
