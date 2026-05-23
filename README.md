# Maestro - Orquestrador de Releases

Orquestrador de releases desenvolvido em Python.

## Estrutura do Projeto

Este projeto segue as melhores práticas de estrutura de projetos em Python:

- `src/maestro/`: Código-fonte principal da aplicação.
- `tests/`: Testes automatizados.
- `pyproject.toml`: Configuração do projeto e dependências (otimizado para o `uv`).
- `docker-compose.yaml`: Configuração da infraestrutura local (ex: Banco de Dados PostgreSQL).

## Como executar

É recomendado usar o gerenciador de pacotes [uv](https://github.com/astral-sh/uv).

Para rodar o banco de dados:
```bash
docker-compose up -d
```
