from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from maestro.database.models import StepEvent
from maestro.repositories.execution import ExecutionRepository
from maestro.schemas.callback import ReleaseCallbackSchema, StepEventSchema
from maestro.schemas.enums import ExecutionStatus
from maestro.services.orchestrator import OrchestratorService

router = APIRouter(prefix="/callback", tags=["Callback"])


@router.post("/release")
async def release_callback(
    payload: ReleaseCallbackSchema,
    background_tasks: BackgroundTasks,
    execution_repo: ExecutionRepository = Depends(),
    orchestrator_service: OrchestratorService = Depends(),
):
    correlation_id = payload.job_execution_correlation_id

    step = await execution_repo.get_step_by_correlation_id(correlation_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step não encontrado para este correlation_id.")

    status = ExecutionStatus.from_string(payload.status)
    step.status = status.value

    if payload.message:
        step.message = payload.message

    if status == ExecutionStatus.WAITING_APPROVAL:
        if not payload.input_id:
            raise HTTPException(status_code=400, detail="Input_id é obrigatório para status WAITING_APPROVAL.")

        step.job_input_id = payload.input_id

    await execution_repo.update_step_execution(step)

    background_tasks.add_task(orchestrator_service.process_workflow, step.release_execution_id)

    return {
        "message": "Callback recebido e processado com sucesso",
        "job_execution_correlation_id": correlation_id,
        "release_process_id": step.release_execution_id,
        "stage": step.stage_id,
        "step": step.step_id,
        "status": payload.status,
    }


@router.post("/event")
async def step_event_callback(
    payload: StepEventSchema,
    execution_repo: ExecutionRepository = Depends(),
):
    """Recebe eventos informativos de um step (ex: logs do Jenkins)."""
    step = await execution_repo.get_step_by_correlation_id(payload.job_execution_correlation_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step não encontrado para este correlation_id.")

    event = StepEvent(
        job_execution_correlation_id=payload.job_execution_correlation_id,
        message=payload.message,
    )
    await execution_repo.add_step_event(event)

    return {
        "message": "Evento registrado com sucesso",
        "job_execution_correlation_id": payload.job_execution_correlation_id,
    }
