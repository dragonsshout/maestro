from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from maestro.services.orchestrator import OrchestratorService
from maestro.schemas.orchestrator import ExecuteReleaseRequest, ReleaseStatusResponse, ReleaseDetailsResponse
from maestro.repositories.execution import ExecutionRepository

router = APIRouter(prefix="/orchestrator", tags=["Orchestrator"])

@router.post("/config")
async def upload_config(
    file: UploadFile = File(...),
    service: OrchestratorService = Depends()
):
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
        
    return {
        "message": "Configuração do orquestrador salva com sucesso",
        "id": descriptor.id
    }

@router.post("/execute")
async def execute_release(
    payload: ExecuteReleaseRequest,
    service: OrchestratorService = Depends()
):
    try:
        execution_id = await service.execute_release(payload.name)
        return {
            "message": "Processo de release iniciado com sucesso",
            "release_execution_id": execution_id
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/status/{name}", response_model=ReleaseStatusResponse)
async def get_release_status(
    name: str,
    execution_repo: ExecutionRepository = Depends()
):
    execution = await execution_repo.get_latest_execution_by_name(name)
    if not execution:
        raise HTTPException(status_code=404, detail=f"Nenhuma execução encontrada para a release '{name}'.")
    
    return execution

@router.get("/details/{name}", response_model=ReleaseDetailsResponse)
async def get_release_details(
    name: str,
    execution_repo: ExecutionRepository = Depends()
):
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
        steps=steps
    )
