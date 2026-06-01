from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from maestro.services.ui import UIService
from maestro.services.orchestrator import OrchestratorService
from maestro.services.settings import UISettingsService, KNOWN_SETTINGS, SETTING_JENKINS_BASE_URL, SETTING_GITHUB_BASE_URL, SETTING_GITHUB_ORGANIZATION
from maestro.repositories.execution import ExecutionRepository
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.schemas.enums import ExecutionStatus

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "ui" / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui", tags=["UI"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/partials/executions", response_class=HTMLResponse)
async def partials_executions(request: Request, service: UIService = Depends()):
    executions = await service.get_all_executions()
    return templates.TemplateResponse(
        request,
        "partials/executions_table.html",
        {"executions": executions}
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

    execution, stages = result
    jenkins_base_url = await settings_service.get(SETTING_JENKINS_BASE_URL)
    github_base_url = await settings_service.get(SETTING_GITHUB_BASE_URL)
    github_organization = await settings_service.get(SETTING_GITHUB_ORGANIZATION)
    return templates.TemplateResponse(
        request,
        "execution_detail.html",
        {
            "execution": execution,
            "stages": stages,
            "waiting_approval": execution.status == ExecutionStatus.WAITING_APPROVAL,
            "jenkins_base_url": (jenkins_base_url or "").rstrip("/"),
            "github_base_url": (github_base_url or "").rstrip("/"),
            "github_organization": github_organization or "",
        }
    )


@router.post("/execution/{execution_id}/approve", response_class=HTMLResponse)
async def approve_execution(
    request: Request,
    execution_id: int,
    background_tasks: BackgroundTasks,
    ui_service: UIService = Depends(),
    orchestrator_service: OrchestratorService = Depends(),
):
    result = await ui_service.get_execution_with_stages(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")

    execution, _ = result

    try:
        await orchestrator_service.approve_release(execution.name, background_tasks)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "partials/approve_result.html",
            {"error": str(e)},
            status_code=400,
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

    execution, _ = result
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
):
    """Reexecuta um step que falhou via UI."""
    try:
        step = await orchestrator_service.retry_step(step_execution_id, background_tasks)
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


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, service: UISettingsService = Depends()):
    current = await service.get_all()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"settings": current, "known_settings": KNOWN_SETTINGS},
    )


@router.post("/execute/{name}", response_class=HTMLResponse)
async def execute_release_ui(
    request: Request,
    name: str,
    background_tasks: BackgroundTasks,
    orchestrator_service: OrchestratorService = Depends(),
):
    """Dispara execução de uma release pela UI."""
    try:
        execution_id = await orchestrator_service.execute_release(name, background_tasks)
        return templates.TemplateResponse(
            request,
            "partials/execute_result.html",
            {"error": None, "execution_id": execution_id, "name": name},
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
async def settings_save(request: Request, service: UISettingsService = Depends()):
    form = await request.form()
    data = {key: (form.get(key) or "").strip() or None for key in KNOWN_SETTINGS}
    await service.save(data)
    current = await service.get_all()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"settings": current, "known_settings": KNOWN_SETTINGS, "saved": True},
    )


@router.get("/releases", response_class=HTMLResponse)
async def releases_page(
    request: Request,
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
):
    descriptors = await orchestrator_repo.get_all()
    return templates.TemplateResponse(
        request,
        "releases.html",
        {"descriptors": descriptors},
    )


@router.post("/releases/upload", response_class=HTMLResponse)
async def releases_upload(
    request: Request,
    file: UploadFile = File(...),
    orchestrator_service: OrchestratorService = Depends(),
    orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
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
    return templates.TemplateResponse(
        request,
        "releases.html",
        {"descriptors": descriptors, "upload_error": error, "upload_success": error is None},
    )


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
