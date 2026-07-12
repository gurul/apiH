from fastapi import APIRouter

from app import schemas
from app.config import get_settings

router = APIRouter()


@router.get("/health", response_model=schemas.HealthOut)
def health() -> schemas.HealthOut:
    return schemas.HealthOut(ok=True, h_mode=get_settings().h_mode)
