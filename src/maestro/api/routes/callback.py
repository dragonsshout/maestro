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
    execution_id = payload.release_process_id

    step = await execution_repo.get_specific_step(execution_id, payload.stage_id, payload.step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step não encontrado.")

    step.status = payload.status
    if payload.message:
        step.message = payload.message

    await execution_repo.update_step_execution(step)

    background_tasks.add_task(orchestrator_service.process_workflow, execution_id)

    return {
        "message": "Callback recebido e processado com sucesso",
        "release_process_id": payload.release_process_id,
        "stage": payload.stage_id,
        "step": payload.step_id,
        "status": payload.status
    }
