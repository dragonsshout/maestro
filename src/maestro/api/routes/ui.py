from pathlib import Path

import yaml as yaml_lib
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from maestro.auth.dependencies import get_current_user
from maestro.database.models import ExecutionActionLog, User
from maestro.repositories.execution import ExecutionRepository
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.schemas.enums import ExecutionStatus
from maestro.schemas.orchestrator import ReleaseConfigSchema
from maestro.services.orchestrator import OrchestratorService
from maestro.services.scheduler import SchedulerService
from maestro.services.settings import (
    KNOWN_SETTINGS,
    SETTING_GITHUB_BASE_URL,
    SETTING_GITHUB_ORGANIZATION,
    SETTING_JENKINS_BASE_URL,
    UISettingsService,
)
from maestro.services.ui import UIService

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "ui" / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui", tags=["UI"], dependencies=[Depends(get_current_user)])


def _extract_environments(descriptors) -> dict:
    """Extract environment from each descriptor's YAML spec. Returns dict keyed by descriptor name."""
    environments: dict[str, str] = {}
    for desc in descriptors:
        try:
            config = ReleaseConfigSchema(**yaml_lib.safe_load(desc.yaml))
            environments[desc.name] = config.spec.environment or "PRD"
        except Exception:
            environments[desc.name] = "PRD"
    return environments


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/partials/executions", response_class=HTMLResponse)
async def partials_executions(request: Request, page: int = 1, service: UIService = Depends()):
    executions, total_pages = await service.get_executions_paginated(page=page, per_page=15)
    return templates.TemplateResponse(
        request,
        "partials/executions_table.html",
        {
            "executions": executions,
            "current_page": page,
            "total_pages": total_pages,
        },
    )


@router.get("/execution/{execution_id}", response_class=HTMLResponse)
async def execution_detail(
    request: Request,
    execution_id: int,
    service: UIService = Depends(),
    settings_service: UISettingsService = Depends(),
):
    result = await service.get_execution_with_stages(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")

    execution, stages, action_logs = result
    jenkins_base_url = await settings_service.get(SETTING_JENKINS_BASE_URL)
    github_base_url = await settings_service.get(SETTING_GITHUB_BASE_URL)
    github_organization = await settings_service.get(SETTING_GITHUB_ORGANIZATION)

    return templates.TemplateResponse(
        request,
        "execution_detail.html",
        {
            "execution": execution,
            "stages": stages,
            "action_logs": action_logs,
            "waiting_approval": execution.status == ExecutionStatus.WAITING_APPROVAL,
            "jenkins_base_url": (jenkins_base_url or "").rstrip("/"),
            "github_base_url": (github_base_url or "").rstrip("/"),
            "github_organization": github_organization or "",
        },
    )


class ApproveRequest(BaseModel):
    status: str


@router.post("/execution/{execution_id}/approve", response_class=HTMLResponse)
async def approve_execution(
    request: Request,
    execution_id: int,
    background_tasks: BackgroundTasks,
    payload: ApproveRequest,
    ui_service: UIService = Depends(),
    orchestrator_service: OrchestratorService = Depends(),
    execution_repo: ExecutionRepository = Depends(),
):
    result = await ui_service.get_execution_with_stages(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")

    execution, _, _logs = result

    try:
        await orchestrator_service.approve_release(execution.name, background_tasks, status=payload.status)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "partials/approve_result.html",
            {"error": str(e)},
            status_code=400,
        )

    # Grava no histórico de ações
    action = "approve" if payload.status == "Sucesso" else "deny"
    await execution_repo.add_action_log(
        ExecutionActionLog(
            release_execution_id=execution_id,
            action=action,
            detail=f"Status enviado: {payload.status}",
        )
    )

    return templates.TemplateResponse(
        request,
        "partials/approve_result.html",
        {"error": None},
    )


@router.get("/execution/{execution_id}/release-yaml", response_class=HTMLResponse)
async def execution_release_yaml(
    request: Request,
    execution_id: int,
    ui_service: UIService = Depends(),
):
    result = await ui_service.get_execution_with_stages(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")

    execution, _, _logs = result
    descriptor = await ui_service.orchestrator_repo.get_by_id(execution.orchestrator_descriptor_id)
    return templates.TemplateResponse(
        request,
        "partials/release_yaml_modal.html",
        {"yaml_content": descriptor.yaml, "execution": execution},
    )


@router.get("/sse/execution/{execution_id}")
async def sse_execution(execution_id: int, service: UIService = Depends()):
    return EventSourceResponse(service.execution_sse_stream(execution_id))


@router.get("/step-events/{correlation_id}", response_class=HTMLResponse)
async def step_events(
    request: Request,
    correlation_id: int,
    execution_repo: ExecutionRepository = Depends(),
    settings_service: UISettingsService = Depends(),
):
    """Retorna modal com histórico de eventos de um step."""
    events = await execution_repo.get_events_by_correlation_id(correlation_id)

    # Monta a URL do console output do Jenkins para esta build
    console_url = ""
    step = await execution_repo.get_step_by_correlation_id(correlation_id)
    if step:
        jenkins_base_url = (await settings_service.get(SETTING_JENKINS_BASE_URL) or "").rstrip("/")
        if jenkins_base_url:
            from maestro.repositories.job_path_registry import JobPathRegistryRepository
            from maestro.services.job_path_resolver import resolve_job_path_async

            execution = await execution_repo.get_execution_by_id(step.release_execution_id)
            if execution:
                orchestrator_repo = OrchestratorDescriptorRepository(db=execution_repo.db)
                descriptor = await orchestrator_repo.get_by_id(execution.orchestrator_descriptor_id)
                if descriptor:
                    config = ReleaseConfigSchema(**yaml_lib.safe_load(descriptor.yaml))
                    # Encontra o step_def correspondente
                    registry_repo = JobPathRegistryRepository(db=execution_repo.db)
                    for stage in config.spec.stages:
                        for step_def in stage.steps:
                            if stage.id == step.stage_id and step_def.id == step.step_id:
                                job_path = await resolve_job_path_async(step_def, config.spec, registry_repo)
                                console_url = f"{jenkins_base_url}/{job_path}/{correlation_id}/console"
                                break
                        if console_url:
                            break

    return templates.TemplateResponse(
        request,
        "partials/step_events_modal.html",
        {"events": events, "correlation_id": correlation_id, "console_url": console_url},
    )


@router.post("/retry-step/{step_execution_id}", response_class=HTMLResponse)
async def retry_step_ui(
    request: Request,
    step_execution_id: int,
    background_tasks: BackgroundTasks,
    orchestrator_service: OrchestratorService = Depends(),
    execution_repo: ExecutionRepository = Depends(),
):
    """Reexecuta um step que falhou via UI."""
    try:
        step = await orchestrator_service.retry_step(step_execution_id, background_tasks)
        # Grava no histórico de ações
        await execution_repo.add_action_log(
            ExecutionActionLog(
                release_execution_id=step.release_execution_id,
                action="retry_step",
                step_execution_id=step.id,
                stage_id=step.stage_id,
                step_id=step.step_id,
            )
        )
        return templates.TemplateResponse(
            request,
            "partials/retry_result.html",
            {"error": None, "step": step},
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "partials/retry_result.html",
            {"error": str(e), "step": None},
        )


@router.post("/resolve-timeout/{step_execution_id}", response_class=HTMLResponse)
async def resolve_timeout_ui(
    request: Request,
    step_execution_id: int,
    action: str,
    background_tasks: BackgroundTasks,
    execution_repo: ExecutionRepository = Depends(),
    orchestrator_service: OrchestratorService = Depends(),
):
    """Resolve um step em timeout marcando como sucesso ou falha."""
    step = await execution_repo.get_step_by_id(step_execution_id)
    if not step:
        return templates.TemplateResponse(
            request,
            "partials/resolve_timeout_result.html",
            {"error": "Step não encontrado.", "step": None, "action": action},
        )

    if step.status != ExecutionStatus.TIMEOUT:
        return templates.TemplateResponse(
            request,
            "partials/resolve_timeout_result.html",
            {"error": f"Step não está em timeout (status: {step.status}).", "step": None, "action": action},
        )

    if action == "success":
        step.status = ExecutionStatus.SUCCESS
        step.message = "Resolvido manualmente como sucesso."
        log_action = "resolve_timeout_success"
    elif action == "failure":
        step.status = ExecutionStatus.FAILURE
        step.message = "Resolvido manualmente como falha."
        log_action = "resolve_timeout_failure"
    else:
        return templates.TemplateResponse(
            request,
            "partials/resolve_timeout_result.html",
            {"error": f"Ação inválida: '{action}'.", "step": None, "action": action},
        )

    await execution_repo.update_step_execution(step)

    # Grava no histórico de ações
    await execution_repo.add_action_log(
        ExecutionActionLog(
            release_execution_id=step.release_execution_id,
            action=log_action,
            step_execution_id=step.id,
            stage_id=step.stage_id,
            step_id=step.step_id,
            detail=step.message,
        )
    )

    # Re-dispara o workflow para que ele continue processando
    background_tasks.add_task(orchestrator_service.process_workflow, step.release_execution_id)

    return templates.TemplateResponse(
        request,
        "partials/resolve_timeout_result.html",
        {"error": None, "step": step, "action": action},
    )


@router.post("/execution/{execution_id}/cancel", response_class=HTMLResponse)
async def cancel_execution_ui(
    request: Request,
    execution_id: int,
    abort_jobs: bool = False,
    orchestrator_service: OrchestratorService = Depends(),
    execution_repo: ExecutionRepository = Depends(),
):
    """
    Cancela uma execução em andamento.
    Se abort_jobs=true, também envia abort ao Jenkins para os steps ativos.
    """
    try:
        execution = await orchestrator_service.cancel_execution(execution_id, abort_jobs=abort_jobs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    detail = "Execução cancelada manualmente."
    if abort_jobs:
        detail += " Abort enviado aos jobs ativos no Jenkins."
    else:
        detail += " Jobs externos não foram interrompidos."

    await execution_repo.add_action_log(
        ExecutionActionLog(
            release_execution_id=execution_id,
            action="cancel_execution" if not abort_jobs else "cancel_execution_with_abort",
            detail=detail,
        )
    )

    # Retorna o OOB do header atualizado (status badge + área de aprovação)
    return templates.TemplateResponse(
        request,
        "partials/execution_oob.html",
        {
            "execution": execution,
            "waiting_approval": False,
        },
    )


# Steps terminais que o operador NÃO pode mais alterar via override.
# FAILURE é intencional aqui fora — um step com falha PODE ser forçado para sucesso.
TERMINAL_STEP_STATUSES = {ExecutionStatus.SUCCESS, ExecutionStatus.ABORTED}


@router.post("/step/{step_execution_id}/override/{action}", response_class=HTMLResponse)
async def override_step_ui(
    request: Request,
    step_execution_id: int,
    action: str,  # "success" | "failure" | "waiting_approval"
    background_tasks: BackgroundTasks,
    execution_repo: ExecutionRepository = Depends(),
    orchestrator_service: OrchestratorService = Depends(),
):
    """
    Permite ao operador forçar um step para sucesso, falha ou aguardando aprovação,
    independente do status atual (exceto steps já terminais).
    Se marcado como sucesso, re-dispara o workflow para continuar o fluxo.
    """
    if action not in ("success", "failure", "waiting_approval"):
        raise HTTPException(
            status_code=400,
            detail=f"Ação inválida: '{action}'. Use 'success', 'failure' ou 'waiting_approval'.",
        )

    step = await execution_repo.get_step_by_id(step_execution_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step não encontrado.")

    if step.status in TERMINAL_STEP_STATUSES:
        raise HTTPException(status_code=400, detail=f"Step já está em status terminal: {step.status}")

    previous_status = step.status
    if action == "success":
        step.status = ExecutionStatus.SUCCESS
        step.message = f"Marcado manualmente como sucesso (era: {previous_status})."
        log_action = "override_success"
    elif action == "waiting_approval":
        step.status = ExecutionStatus.WAITING_APPROVAL
        step.message = f"Marcado manualmente como aguardando aprovação (era: {previous_status})."
        log_action = "override_waiting_approval"
    else:
        step.status = ExecutionStatus.FAILURE
        step.message = f"Marcado manualmente como falha (era: {previous_status})."
        log_action = "override_failure"

    await execution_repo.update_step_execution(step)

    await execution_repo.add_action_log(
        ExecutionActionLog(
            release_execution_id=step.release_execution_id,
            action=log_action,
            step_execution_id=step.id,
            stage_id=step.stage_id,
            step_id=step.step_id,
            detail=step.message,
        )
    )

    # Re-dispara o workflow para recalcular o status da execução
    if action in ("success", "waiting_approval"):
        background_tasks.add_task(orchestrator_service.process_workflow, step.release_execution_id)

    return templates.TemplateResponse(
        request,
        "partials/override_result.html",
        {"error": None, "step": step, "action": action},
    )


@router.post("/step/{step_execution_id}/abort", response_class=HTMLResponse)
async def abort_step_ui(
    request: Request,
    step_execution_id: int,
    orchestrator_service: OrchestratorService = Depends(),
    execution_repo: ExecutionRepository = Depends(),
):
    """Envia cancelamento forçado ao Jenkins e marca o step como ABORTED."""
    try:
        step = await orchestrator_service.abort_step(step_execution_id)
        await execution_repo.add_action_log(
            ExecutionActionLog(
                release_execution_id=step.release_execution_id,
                action="abort_step",
                step_execution_id=step.id,
                stage_id=step.stage_id,
                step_id=step.step_id,
                detail=step.message,
            )
        )
        return templates.TemplateResponse(
            request,
            "partials/abort_step_result.html",
            {"error": None, "step": step},
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "partials/abort_step_result.html",
            {"error": str(e), "step": None},
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "partials/abort_step_result.html",
            {"error": f"Erro ao enviar abort ao Jenkins: {str(e)}", "step": None},
        )


@router.post("/step/{step_execution_id}/approve", response_class=HTMLResponse)
async def approve_step_ui(
    request: Request,
    step_execution_id: int,
    background_tasks: BackgroundTasks,
    orchestrator_service: OrchestratorService = Depends(),
    execution_repo: ExecutionRepository = Depends(),
):
    """Aprova individualmente um step que está aguardando aprovação no Jenkins."""
    try:
        step = await orchestrator_service.approve_step(step_execution_id, background_tasks)
        await execution_repo.add_action_log(
            ExecutionActionLog(
                release_execution_id=step.release_execution_id,
                action="approve_step",
                step_execution_id=step.id,
                stage_id=step.stage_id,
                step_id=step.step_id,
                detail=step.message,
            )
        )
        return templates.TemplateResponse(
            request,
            "partials/approve_step_result.html",
            {"error": None, "step": step},
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "partials/approve_step_result.html",
            {"error": str(e), "step": None},
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "partials/approve_step_result.html",
            {"error": f"Erro ao enviar aprovação ao Jenkins: {str(e)}", "step": None},
        )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    service: UISettingsService = Depends(),
    current_user: User = Depends(get_current_user),
):
    if current_user.group != "Administrators":
        raise HTTPException(status_code=403, detail="Acesso negado.")

    current = await service.get_all_masked()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"settings": current, "known_settings": KNOWN_SETTINGS, "current_user": current_user},
    )


@router.post("/execute/{name}", response_class=HTMLResponse)
async def execute_release_ui(
    request: Request,
    name: str,
    background_tasks: BackgroundTasks,
    orchestrator_service: OrchestratorService = Depends(),
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
):
    """Dispara execução de uma release pela UI."""
    descriptor = await orchestrator_repo.get_by_name(name)
    if descriptor and descriptor.archived == 1:
        return templates.TemplateResponse(
            request,
            "partials/execute_result.html",
            {"error": "Não é possível executar uma release arquivada.", "execution_id": None, "name": name},
        )
    try:
        execution_id = await orchestrator_service.execute_release(name, background_tasks)
        return templates.TemplateResponse(
            request,
            "partials/execute_result.html",
            {"error": None, "execution_id": execution_id, "name": name},
            headers={"HX-Trigger": "refreshReleases"},
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "partials/execute_result.html",
            {"error": str(e), "execution_id": None, "name": name},
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "partials/execute_result.html",
            {"error": f"Erro inesperado: {str(e)}", "execution_id": None, "name": name},
        )


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(
    request: Request,
    service: UISettingsService = Depends(),
    current_user: User = Depends(get_current_user),
):
    if current_user.group != "Administrators":
        raise HTTPException(status_code=403, detail="Acesso negado.")

    form = await request.form()
    data = {key: (form.get(key) or "").strip() or None for key in KNOWN_SETTINGS}
    await service.save(data)
    current = await service.get_all()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"settings": current, "known_settings": KNOWN_SETTINGS, "saved": True, "current_user": current_user},
    )


@router.get("/partials/releases", response_class=HTMLResponse)
async def partials_releases(
    request: Request,
    page: int = 1,
    search: str | None = None,
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
    execution_repo: ExecutionRepository = Depends(),
):
    per_page = 15
    skip = (page - 1) * per_page
    descriptors = await orchestrator_repo.get_all(skip=skip, limit=per_page, search=search, archived=False)
    total_count = await orchestrator_repo.get_count(search=search, archived=False)
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    active_executions: dict = {}
    for desc in descriptors:
        active = await execution_repo.get_active_execution_by_name(desc.name)
        if active:
            active_executions[desc.name] = active

    environments = _extract_environments(descriptors)

    return templates.TemplateResponse(
        request,
        "partials/releases_table.html",
        {
            "descriptors": descriptors,
            "active_executions": active_executions,
            "environments": environments,
            "current_page": page,
            "total_pages": total_pages,
            "search_term": search or "",
        },
    )


@router.get("/releases", response_class=HTMLResponse)
async def releases_page(
    request: Request,
):
    return templates.TemplateResponse(
        request,
        "releases.html",
    )


@router.get("/releases/archived", response_class=HTMLResponse)
async def releases_archived_page(
    request: Request,
):
    return templates.TemplateResponse(
        request,
        "releases_archived.html",
    )


@router.get("/partials/releases-archived", response_class=HTMLResponse)
async def partials_releases_archived(
    request: Request,
    page: int = 1,
    search: str | None = None,
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
):
    per_page = 15
    skip = (page - 1) * per_page
    descriptors = await orchestrator_repo.get_all(skip=skip, limit=per_page, search=search, archived=True)
    total_count = await orchestrator_repo.get_count(search=search, archived=True)
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    environments = _extract_environments(descriptors)

    return templates.TemplateResponse(
        request,
        "partials/releases_archived_table.html",
        {
            "descriptors": descriptors,
            "environments": environments,
            "current_page": page,
            "total_pages": total_pages,
            "search_term": search or "",
        },
    )


@router.post("/releases/{descriptor_id}/archive", response_class=HTMLResponse)
async def archive_release_ui(
    request: Request,
    descriptor_id: int,
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
):
    descriptor = await orchestrator_repo.set_archived(descriptor_id, True)
    if not descriptor:
        raise HTTPException(status_code=404, detail="Descriptor não encontrado.")
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshReleases"},
    )


@router.post("/releases/{descriptor_id}/unarchive", response_class=HTMLResponse)
async def unarchive_release_ui(
    request: Request,
    descriptor_id: int,
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
):
    descriptor = await orchestrator_repo.set_archived(descriptor_id, False)
    if not descriptor:
        raise HTTPException(status_code=404, detail="Descriptor não encontrado.")
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshReleasesArchived"},
    )


@router.delete("/releases/{descriptor_id}", response_class=HTMLResponse)
async def delete_release_ui(
    request: Request,
    descriptor_id: int,
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
    execution_repo: ExecutionRepository = Depends(),
):
    """Exclui permanentemente uma release arquivada. Só permitido se não houver execuções."""
    current_user = request.state.current_user
    if current_user.group != "Administrators":
        return HTMLResponse(
            content="""<div class="alert alert-error text-sm shadow p-3">
                <svg class="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                          d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/>
                </svg>
                Apenas Administrators podem excluir releases.
            </div>""",
            status_code=403,
        )

    descriptor = await orchestrator_repo.get_by_id(descriptor_id)
    if not descriptor:
        raise HTTPException(status_code=404, detail="Descriptor não encontrado.")

    # Valida no momento do clique — impede exclusão se houver execuções vinculadas
    exec_count = await execution_repo.count_by_descriptor_id(descriptor_id)
    if exec_count > 0:
        return HTMLResponse(
            content=f"""<div class="alert alert-error text-sm shadow p-3" id="delete-error-{descriptor_id}">
                <svg class="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                          d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/>
                </svg>
                <span>A release <strong>{descriptor.name}</strong> possui {exec_count} execução(ões) registrada(s) e não pode ser excluída.</span>
            </div>""",
            status_code=409,
        )

    await orchestrator_repo.delete(descriptor_id)
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshReleasesArchived"},
    )


@router.post("/releases/upload", response_class=HTMLResponse)
async def releases_upload(
    request: Request,
    file: UploadFile = File(...),
    orchestrator_service: OrchestratorService = Depends(),
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
    execution_repo: ExecutionRepository = Depends(),
):
    error = None
    if not file.filename.endswith((".yaml", ".yml")):
        error = "O arquivo deve ter a extensão .yaml ou .yml"
    else:
        content = await file.read()
        try:
            yaml_content = content.decode("utf-8")
        except UnicodeDecodeError:
            error = "O arquivo não pôde ser lido como UTF-8"
        else:
            try:
                await orchestrator_service.save_descriptor(yaml_content)
            except ValueError as e:
                error = str(e)

    descriptors = await orchestrator_repo.get_all()
    active_executions: dict = {}
    for desc in descriptors:
        active = await execution_repo.get_active_execution_by_name(desc.name)
        if active:
            active_executions[desc.name] = active

    environments = _extract_environments(descriptors)

    return templates.TemplateResponse(
        request,
        "releases.html",
        {
            "descriptors": descriptors,
            "active_executions": active_executions,
            "environments": environments,
            "upload_error": error,
            "upload_success": error is None,
        },
    )


# ─── Release Builder ─────────────────────────────────────────────────────────


@router.get("/releases/new", response_class=HTMLResponse)
async def release_builder_page(request: Request):
    """Página do Release Builder — cadastro visual de releases."""
    return templates.TemplateResponse(request, "release_builder.html")


@router.get("/api/validate-repository", response_class=HTMLResponse)
async def validate_repository(
    request: Request,
    repository: str = "",
    environment: str = "PRD",
    stage_idx: int = 0,
    step_idx: int = 0,
    settings_service: UISettingsService = Depends(),
):
    """
    Valida o repositório no GitHub e o job correspondente no Jenkins.
    Retorna um partial HTML com:
      - Estado da validação (ok / erro)
      - Dropdown de branches 'release/*' quando ok
    """
    from maestro.services.app_settings import get_integration_settings
    from maestro.integration.github import GithubIntegration
    from maestro.integration.jenkins import JenkinsIntegration
    from maestro.database.session import AsyncSessionLocal
    from maestro.repositories.job_path_registry import JobPathRegistryRepository
    from maestro.services.job_path_resolver import resolve_job_path_by_repository

    repository = repository.strip()
    if not repository:
        return HTMLResponse(content="")

    # ── Busca cfg + resolve path em uma única sessão ──────────────────────────
    async with AsyncSessionLocal() as session:
        cfg = await get_integration_settings(session)
        registry_repo = JobPathRegistryRepository(db=session)
        resolved = await resolve_job_path_by_repository(repository, environment, registry_repo)

    jenkins_path = resolved.path
    jenkins_path_source = resolved.source

    github = GithubIntegration(
        organization=cfg.github_organization,
        token=cfg.github_token,
        base_url=cfg.github_base_url,
        trust_env=cfg.http_trust_env,
    )
    jenkins = JenkinsIntegration(
        base_url=cfg.jenkins_url,
        username=cfg.jenkins_username,
        token=cfg.jenkins_token,
        trust_env=cfg.http_trust_env,
    )

    repo_exists = False
    jenkins_ok = False
    branches: list[str] = []
    error_msg = None

    try:
        repo_exists = await github.repository_exists(repository)
    except Exception:
        repo_exists = False

    if repo_exists:
        try:
            jenkins_ok = await jenkins.job_exists(jenkins_path)
        except Exception:
            jenkins_ok = False

        try:
            branches = await github.list_release_branches(repository)
        except Exception:
            branches = []
    else:
        error_msg = f"Repositório '{repository}' não encontrado no GitHub."

    if repo_exists and not jenkins_ok:
        error_msg = f"Job Jenkins '{jenkins_path}' não encontrado."

    return templates.TemplateResponse(
        request,
        "partials/release_branches_dropdown.html",
        {
            "repo_exists": repo_exists,
            "jenkins_ok": jenkins_ok,
            "branches": branches,
            "jenkins_path": jenkins_path,
            "jenkins_path_source": jenkins_path_source,
            "repository": repository,
            "error_msg": error_msg,
            "stage_idx": stage_idx,
            "step_idx": step_idx,
        },
    )


@router.post("/releases/create", response_class=HTMLResponse)
async def release_create(
    request: Request,
    orchestrator_service: OrchestratorService = Depends(),
):
    """Recebe o form do Release Builder, monta o YAML e salva via save_descriptor."""
    form = await request.form()

    # ── Metadados ──────────────────────────────────────────────────────────────
    name = (form.get("name") or "").strip()
    author = (form.get("author") or "").strip()
    description = (form.get("description") or "").strip()
    strategy = (form.get("strategy") or "all-or-nothing").strip()
    environment = (form.get("environment") or "PRD").strip()

    if not name or not author:
        return templates.TemplateResponse(
            request,
            "release_builder.html",
            {"error": "Nome e autor são obrigatórios.", "form": dict(form)},
        )

    # ── Monta stages e steps a partir dos campos nomeados ──────────────────────
    # Convenção de nomes: stages[0][id], stages[0][steps][0][repository], ...
    stages_raw: dict[int, dict] = {}
    for key, value in form.multi_items():
        # stages[0][id] ou stages[0][steps][0][repository]
        import re
        m = re.match(r"stages\[(\d+)\]\[steps\]\[(\d+)\]\[(.+?)\]", key)
        if m:
            si, ti, field = int(m.group(1)), int(m.group(2)), m.group(3)
            stages_raw.setdefault(si, {"id": "", "steps": {}})
            stages_raw[si]["steps"].setdefault(ti, {})
            stages_raw[si]["steps"][ti][field] = value
            continue
        m2 = re.match(r"stages\[(\d+)\]\[id\]", key)
        if m2:
            si = int(m2.group(1))
            stages_raw.setdefault(si, {"id": "", "steps": {}})
            stages_raw[si]["id"] = value

    # ── Validação mínima ──────────────────────────────────────────────────────
    if not stages_raw:
        return templates.TemplateResponse(
            request,
            "release_builder.html",
            {"error": "Adicione pelo menos um stage com um step.", "form": dict(form)},
        )

    # ── Serializa para YAML ────────────────────────────────────────────────────
    stages_list = []
    for si in sorted(stages_raw):
        stage = stages_raw[si]
        stage_id = stage["id"].strip()
        if not stage_id:
            continue
        steps_list = []
        for ti in sorted(stage.get("steps", {})):
            step = stage["steps"][ti]
            repo = step.get("repository", "").strip()
            release_branch = step.get("release", "").strip()
            step_id = step.get("id", "").strip()
            if not repo or not release_branch or not step_id:
                continue
            step_dict: dict = {
                "id": step_id,
                "repository": repo,
                "release": release_branch,
                "critical": step.get("critical") == "true",
                "requires_approval": step.get("requires_approval") == "true",
            }
            custom_path = step.get("job_path", "").strip()
            if custom_path:
                step_dict["job"] = {"type": "jenkins", "path": custom_path}
            steps_list.append(step_dict)
        if steps_list:
            stages_list.append({"id": stage_id, "steps": steps_list})

    if not stages_list:
        return templates.TemplateResponse(
            request,
            "release_builder.html",
            {"error": "Nenhum stage válido encontrado. Verifique os campos obrigatórios.", "form": dict(form)},
        )

    yaml_dict = {
        "apiVersion": "maestro.ecosoft.com/v1alpha1",
        "kind": "Release",
        "metadata": {
            "name": name,
            "author": author,
            **({"description": description} if description else {}),
        },
        "spec": {
            "strategy": {"type": strategy},
            "environment": environment,
            "stages": stages_list,
        },
    }

    yaml_content = yaml_lib.dump(yaml_dict, allow_unicode=True, sort_keys=False)

    try:
        await orchestrator_service.save_descriptor(yaml_content)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "release_builder.html",
            {"error": str(e), "form": dict(form)},
        )

    return RedirectResponse(url="/ui/releases?created=1", status_code=303)


@router.post("/dry-run/{name}", response_class=HTMLResponse)
async def dry_run_release_ui(
    request: Request,
    name: str,
    orchestrator_service: OrchestratorService = Depends(),
):
    """Executa dry-run de uma release pela UI."""
    try:
        result = await orchestrator_service.dry_run_release(name)
        return templates.TemplateResponse(
            request,
            "partials/dry_run_result.html",
            {"error": None, "result": result, "name": name},
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "partials/dry_run_result.html",
            {"error": str(e), "result": None, "name": name},
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "partials/dry_run_result.html",
            {"error": f"Erro inesperado: {str(e)}", "result": None, "name": name},
        )


@router.get("/releases/{descriptor_id}/yaml", response_class=HTMLResponse)
async def release_descriptor_yaml(
    request: Request,
    descriptor_id: int,
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
):
    descriptor = await orchestrator_repo.get_by_id(descriptor_id)
    if not descriptor:
        raise HTTPException(status_code=404, detail="Descriptor não encontrado.")
    return templates.TemplateResponse(
        request,
        "partials/release_yaml_modal.html",
        {"yaml_content": descriptor.yaml, "execution": descriptor},
    )


@router.post("/schedule/{name}", response_class=HTMLResponse)
async def schedule_release_ui(
    request: Request,
    name: str,
    scheduled_at: str = Form(...),
    scheduler_service: SchedulerService = Depends(),
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
):
    """Agenda a execucao de uma release pela UI."""
    from datetime import datetime as dt
    from datetime import timezone as tz

    descriptor = await orchestrator_repo.get_by_name(name)
    if descriptor and descriptor.archived == 1:
        return templates.TemplateResponse(
            request,
            "partials/schedule_result.html",
            {"error": "Não é possível agendar uma release arquivada.", "schedule": None, "name": name},
        )

    try:
        # Substitui 'Z' por '+00:00' para compatibilidade com fromisoformat no Python < 3.11
        parsed_dt = dt.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        if not parsed_dt.tzinfo:
            parsed_dt = parsed_dt.replace(tzinfo=tz.utc)
        schedule = await scheduler_service.schedule_release(name, parsed_dt)
        return templates.TemplateResponse(
            request,
            "partials/schedule_result.html",
            {"error": None, "schedule": schedule, "name": name},
            headers={"HX-Trigger": "refreshSchedules"},
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "partials/schedule_result.html",
            {"error": str(e), "schedule": None, "name": name},
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "partials/schedule_result.html",
            {"error": f"Erro inesperado: {str(e)}", "schedule": None, "name": name},
        )


@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(request: Request):
    return templates.TemplateResponse(request, "schedules.html")


@router.delete("/schedule/{schedule_id}", response_class=HTMLResponse)
async def cancel_schedule_ui(
    request: Request,
    schedule_id: int,
    page: int = 1,
    search: str | None = None,
    scheduler_service: SchedulerService = Depends(),
):
    """Cancela um agendamento pela UI e retorna a lista atualizada."""
    cancel_error = None
    try:
        await scheduler_service.cancel_schedule(schedule_id)
    except ValueError as e:
        cancel_error = str(e)

    per_page = 15
    skip = (page - 1) * per_page
    schedules = await scheduler_service.get_all_schedules(skip=skip, limit=per_page, search=search)
    total_count = await scheduler_service.get_schedules_count(search=search)
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request,
        "partials/schedules_list.html",
        {
            "schedules": schedules,
            "cancel_error": cancel_error,
            "current_page": page,
            "total_pages": total_pages,
            "search_term": search or "",
        },
    )


@router.get("/partials/schedules", response_class=HTMLResponse)
async def partials_schedules(
    request: Request,
    page: int = 1,
    search: str | None = None,
    scheduler_service: SchedulerService = Depends(),
):
    """Retorna a lista de agendamentos (partial para HTMX)."""
    per_page = 15
    skip = (page - 1) * per_page
    schedules = await scheduler_service.get_all_schedules(skip=skip, limit=per_page, search=search)
    total_count = await scheduler_service.get_schedules_count(search=search)
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request,
        "partials/schedules_list.html",
        {
            "schedules": schedules,
            "current_page": page,
            "total_pages": total_pages,
            "search_term": search or "",
        },
    )
