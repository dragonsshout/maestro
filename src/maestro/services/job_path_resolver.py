"""
Utilitário para resolver o job path do Jenkins.

Regra:
- Se o step define `job.path` explicitamente, usa o valor informado.
- Caso contrário, gera o path padrão: job/<ENVIRONMENT>/job/<repository>/job/<repository>
- ENVIRONMENT vem de `spec.environment` (default: "PRD").
"""

from maestro.schemas.orchestrator import ReleaseSpecSchema, StepSchema


def resolve_job_path(step: StepSchema, spec: ReleaseSpecSchema) -> str:
    """
    Resolve o job path efetivo para um step.

    :param step: Definição do step no YAML.
    :param spec: Spec da release (contém environment).
    :return: O path do job no Jenkins.
    """
    # Se o job foi informado com path explícito, usa o valor
    if step.job and step.job.path:
        return step.job.path

    # Caso contrário, gera o path padrão a partir do repository e environment
    environment = spec.environment or "PRD"
    repository = step.repository

    return f"job/{environment}/job/{repository}/job/{repository}"
