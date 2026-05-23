from fastapi import APIRouter
from maestro.schemas.callback import ReleaseCallbackSchema

router = APIRouter(prefix="/callback", tags=["Callback"])

@router.post("/release")
async def release_callback(payload: ReleaseCallbackSchema):
    # Futuramente este endpoint irá interagir com o serviço para retomar o job travado.
    return {
        "message": "Callback recebido e processado com sucesso",
        "release_process_id": payload.release_process_id,
        "stage": payload.stage_id,
        "step": payload.step_id,
        "status": payload.status
    }
