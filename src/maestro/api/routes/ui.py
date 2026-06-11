from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from maestro.auth.dependencies import can_admin, can_approve, can_operate, can_view
from maestro.database.models import ExecutionActionLog, User
from maestro.repositories.execution import ExecutionRepository
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.schemas.enums import ExecutionStatus
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

router = APIRouter(prefix="/ui", tags=["UI"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, current_user: User = Depends(can_view)):
    return templates.TemplateResponse(request, "index.html", {"current_user": current_user})


@router.get("/partials/executions", response_class=HTMLResponse)
async def partials_executions(
    request: Request,
    page: int = 1,
    service: UIService = Depends(),
    current_user: User = Depends(can_view),
):
    executions, total_pages = await service.get_executions_paginated(page=page, per_page=15)
    return templates.TemplateResponse(
        request,
        "partials/executions_table.html",
        {
            "executions": executions,
            "current_page": page,
            "total_pages": total_pages,
            "current_user": current_user,
        },
    )


@router.get("/execution/{execution_id}", response_class=HTMLResponse)
async def execution_detail(
    request: Request,
    execution_id: int,
    service: UIService = Depends(),
    settings_service: UISettingsService = Depends(),
    current_user: User = Depends(can_view),
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
            "current_user": current_user,
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
    current_user: User = Depends(can_approve),
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
    current_user: User = Depends(can_view),
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
async def sse_execution(
    execution_id: int,
    service: UIService = Depends(),
    current_user: User = Depends(can_view),
):
    return EventSourceResponse(service.execution_sse_stream(execution_id))


@router.get("/step-events/{correlation_id}", response_class=HTMLResponse)
async def step_events(
    request: Request,
    correlation_id: int,
    execution_repo: ExecutionRepository = Depends(),
    current_user: User = Depends(can_view),
):
    """Retorna modal com histórico de eventos de um step."""
    events = await execution_repo.get_events_by_correlation_id(correlation_id)
    return templates.TemplateResponse(
        request,
        "partials/step_events_modal.html",
        {"events": events, "correlation_id": correlation_id},
    )


@router.post("/retry-step/{step_execution_id}", response_class=HTMLResponse)
async def retry_step_ui(
    request: Request,
    step_execution_id: int,
    background_tasks: BackgroundTasks,
    orchestrator_service: OrchestratorService = Depends(),
    execution_repo: ExecutionRepository = Depends(),
    current_user: User = Depends(can_operate),
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
    current_user: User = Depends(can_operate),
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
    current_user: User = Depends(can_operate),
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
    current_user: User = Depends(can_operate),
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

    # Re-dispara o workflow apenas se for success, pois falha ou waiting approval pausam o fluxo
    if action == "success":
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
    current_user: User = Depends(can_operate),
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
    current_user: User = Depends(can_approve),
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
    current_user: User = Depends(can_admin),
):
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
    current_user: User = Depends(can_operate),
):
    """Dispara execução de uma release pela UI."""
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
    current_user: User = Depends(can_admin),
):
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
    current_user: User = Depends(can_view),
):
    per_page = 15
    skip = (page - 1) * per_page
    descriptors = await orchestrator_repo.get_all(skip=skip, limit=per_page, search=search)
    total_count = await orchestrator_repo.get_count(search=search)
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    active_executions: dict = {}
    for desc in descriptors:
        active = await execution_repo.get_active_execution_by_name(desc.name)
        if active:
            active_executions[desc.name] = active

    return templates.TemplateResponse(
        request,
        "partials/releases_table.html",
        {
            "descriptors": descriptors,
            "active_executions": active_executions,
            "current_page": page,
            "total_pages": total_pages,
            "search_term": search or "",
            "current_user": current_user,
        },
    )


@router.get("/releases", response_class=HTMLResponse)
async def releases_page(
    request: Request,
    current_user: User = Depends(can_view),
):
    return templates.TemplateResponse(
        request,
        "releases.html",
        {"current_user": current_user},
    )


@router.post("/releases/upload", response_class=HTMLResponse)
async def releases_upload(
    request: Request,
    file: UploadFile = File(...),
    orchestrator_service: OrchestratorService = Depends(),
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
    execution_repo: ExecutionRepository = Depends(),
    current_user: User = Depends(can_operate),
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
    return templates.TemplateResponse(
        request,
        "releases.html",
        {
            "descriptors": descriptors,
            "active_executions": active_executions,
            "upload_error": error,
            "upload_success": error is None,
            "current_user": current_user,
        },
    )


@router.post("/dry-run/{name}", response_class=HTMLResponse)
async def dry_run_release_ui(
    request: Request,
    name: str,
    orchestrator_service: OrchestratorService = Depends(),
    current_user: User = Depends(can_operate),
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
    current_user: User = Depends(can_view),
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
    current_user: User = Depends(can_operate),
):
    """Agenda a execucao de uma release pela UI."""
    from datetime import datetime as dt
    from datetime import timezone as tz

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
async def schedules_page(
    request: Request,
    current_user: User = Depends(can_view),
):
    return templates.TemplateResponse(request, "schedules.html", {"current_user": current_user})


@router.delete("/schedule/{schedule_id}", response_class=HTMLResponse)
async def cancel_schedule_ui(
    request: Request,
    schedule_id: int,
    page: int = 1,
    search: str | None = None,
    scheduler_service: SchedulerService = Depends(),
    current_user: User = Depends(can_operate),
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
    current_user: User = Depends(can_view),
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
