from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from maestro.repositories.execution import ExecutionRepository
from maestro.schemas.orchestrator import (
    ApproveReleaseRequest,
    DryRunResponse,
    ExecuteReleaseRequest,
    ReleaseDetailsResponse,
    ReleaseStatusResponse,
)
from maestro.schemas.schedule import ScheduleReleaseRequest, ScheduleReleaseResponse
from maestro.services.orchestrator import OrchestratorService
from maestro.services.scheduler import SchedulerService

router = APIRouter(prefix="/orchestrator", tags=["Orchestrator"])


@router.post("/config")
async def upload_config(file: UploadFile = File(...), service: OrchestratorService = Depends()):
    if not file.filename.endswith((".yaml", ".yml")):
        raise HTTPException(status_code=400, detail="O arquivo deve ter a extensão .yaml ou .yml")

    content = await file.read()
    try:
        yaml_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="O arquivo não pôde ser lido como UTF-8")

    try:
        descriptor = await service.save_descriptor(yaml_content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "Configuração do orquestrador salva com sucesso", "id": descriptor.id}


@router.post("/execute")
async def execute_release(
    payload: ExecuteReleaseRequest, background_tasks: BackgroundTasks, service: OrchestratorService = Depends()
):
    try:
        execution_id = await service.execute_release(payload.name, background_tasks)
        return {"message": "Processo de release iniciado com sucesso", "release_execution_id": execution_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/dry-run", response_model=DryRunResponse)
async def dry_run_release(payload: ExecuteReleaseRequest, service: OrchestratorService = Depends()):
    try:
        result = await service.dry_run_release(payload.name)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/retry-step/{step_execution_id}")
async def retry_step(
    step_execution_id: int, background_tasks: BackgroundTasks, service: OrchestratorService = Depends()
):
    try:
        step = await service.retry_step(step_execution_id, background_tasks)
        return {
            "message": "Step reenviado para execução com sucesso",
            "step_execution_id": step.id,
            "stage_id": step.stage_id,
            "step_id": step.step_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/approve/{name}")
async def approve_release(
    name: str,
    payload: ApproveReleaseRequest,
    background_tasks: BackgroundTasks,
    service: OrchestratorService = Depends(),
):
    try:
        result = await service.approve_release(name, background_tasks, status=payload.status)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status/{name}", response_model=ReleaseStatusResponse)
async def get_release_status(name: str, execution_repo: ExecutionRepository = Depends()):
    execution = await execution_repo.get_latest_execution_by_name(name)
    if not execution:
        raise HTTPException(status_code=404, detail=f"Nenhuma execução encontrada para a release '{name}'.")

    return execution


@router.get("/details/{name}", response_model=ReleaseDetailsResponse)
async def get_release_details(name: str, execution_repo: ExecutionRepository = Depends()):
    execution = await execution_repo.get_latest_execution_by_name(name)
    if not execution:
        raise HTTPException(status_code=404, detail=f"Nenhuma execução encontrada para a release '{name}'.")

    steps = await execution_repo.get_steps_by_execution_id(execution.id)

    return ReleaseDetailsResponse(
        id=execution.id,
        name=execution.name,
        status=execution.status,
        message=execution.message,
        created_at=execution.created_at,
        steps=steps,
    )


@router.post("/schedule", response_model=ScheduleReleaseResponse)
async def schedule_release(payload: ScheduleReleaseRequest, service: SchedulerService = Depends()):
    """Agenda a execucao de uma release para uma data/hora futura."""
    try:
        schedule = await service.schedule_release(payload.name, payload.scheduled_at)
        return schedule
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schedules", response_model=List[ScheduleReleaseResponse])
async def list_schedules(name: Optional[str] = None, service: SchedulerService = Depends()):
    """Lista agendamentos. Filtra por nome da release se informado."""
    if name:
        return await service.get_schedules_for_release(name)
    return await service.get_all_schedules()


@router.delete("/schedule/{schedule_id}")
async def cancel_schedule(schedule_id: int, service: SchedulerService = Depends()):
    """Cancela um agendamento pendente."""
    try:
        await service.cancel_schedule(schedule_id)
        return {"message": "Agendamento cancelado com sucesso."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
