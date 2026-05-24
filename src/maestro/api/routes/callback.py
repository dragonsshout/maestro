from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from maestro.schemas.callback import ReleaseCallbackSchema
from maestro.repositories.execution import ExecutionRepository
from maestro.services.orchestrator import OrchestratorService

router = APIRouter(prefix="/callback", tags=["Callback"])

@router.post("/release")
async def release_callback(
    payload: ReleaseCallbackSchema,
    background_tasks: BackgroundTasks,
    execution_repo: ExecutionRepository = Depends(),
    orchestrator_service: OrchestratorService = Depends()
):
    correlation_id = payload.job_execution_correlation_id

    step = await execution_repo.get_step_by_correlation_id(correlation_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step não encontrado para este correlation_id.")

    step.status = payload.status
    if payload.message:
        step.message = payload.message

    await execution_repo.update_step_execution(step)

    background_tasks.add_task(orchestrator_service.process_workflow, step.release_execution_id)

    return {
        "message": "Callback recebido e processado com sucesso",
        "job_execution_correlation_id": correlation_id,
        "release_process_id": step.release_execution_id,
        "stage": step.stage_id,
        "step": step.step_id,
        "status": payload.status
    }
