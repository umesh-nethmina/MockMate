from fastapi import APIRouter, Depends

from app.config import get_settings
from app.tools.sandbox import Sandbox, get_sandbox

router = APIRouter(tags=["health"])


@router.get("/health")
def health(sandbox: Sandbox = Depends(get_sandbox)) -> dict[str, str | bool]:
    settings = get_settings()
    return {"status": "ok", "environment": settings.environment, "coding_available": sandbox.available()}
