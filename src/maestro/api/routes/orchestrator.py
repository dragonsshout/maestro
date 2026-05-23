from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from maestro.services.orchestrator import OrchestratorService

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
