from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from maestro.services.job_path_registry import JobPathRegistryService

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "ui" / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui/job-registry", tags=["Job Path Registry"])


@router.get("/", response_class=HTMLResponse)
async def job_registry_page(request: Request):
    """Página principal do Job Path Registry."""
    return templates.TemplateResponse(request, "job_registry.html")


@router.get("/partials/list", response_class=HTMLResponse)
async def job_registry_list(
    request: Request,
    page: int = 1,
    search: str | None = None,
    service: JobPathRegistryService = Depends(),
):
    """Retorna a lista paginada de registros (partial para HTMX)."""
    per_page = 15
    entries, total_pages = await service.get_all_paginated(page=page, per_page=per_page, search=search)

    return templates.TemplateResponse(
        request,
        "partials/job_registry_table.html",
        {
            "entries": entries,
            "current_page": page,
            "total_pages": total_pages,
            "search_term": search or "",
        },
    )


@router.post("/discover", response_class=HTMLResponse)
async def job_registry_discover(
    request: Request,
    service: JobPathRegistryService = Depends(),
):
    """Executa o discovery de jobs no Jenkins e retorna o resultado."""
    try:
        result = await service.discover_from_jenkins()
        # Após o discovery, retorna a tabela atualizada com mensagem de sucesso
        entries, total_pages = await service.get_all_paginated(page=1, per_page=15)
        return templates.TemplateResponse(
            request,
            "partials/job_registry_table.html",
            {
                "entries": entries,
                "current_page": 1,
                "total_pages": total_pages,
                "search_term": "",
                "discovery_success": result.message,
            },
        )
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "partials/job_registry_table.html",
            {
                "entries": [],
                "current_page": 1,
                "total_pages": 1,
                "search_term": "",
                "discovery_error": str(e),
            },
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "partials/job_registry_table.html",
            {
                "entries": [],
                "current_page": 1,
                "total_pages": 1,
                "search_term": "",
                "discovery_error": f"Erro ao consultar Jenkins: {str(e)}",
            },
        )
