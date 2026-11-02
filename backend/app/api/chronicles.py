from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from app.engine.repository import EngineRepository

router = APIRouter(prefix="/api/chronicles", tags=["chronicles"])


class ChronicleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    world_id: UUID
    session_id: UUID
    title: str
    recap: dict[str, object]
    created_at: datetime


@router.get("", response_model=list[ChronicleResponse])
async def list_chronicles(
    request: Request, world_id: UUID, limit: int = Query(default=50, ge=1, le=100)
) -> list[ChronicleResponse]:
    repository: EngineRepository = request.app.state.engine.repository
    rows = await repository.chronicles(world_id, limit)
    return [ChronicleResponse.model_validate(row, from_attributes=True) for row in rows]


@router.get("/{chronicle_id}", response_model=ChronicleResponse)
async def get_chronicle(chronicle_id: UUID, request: Request) -> ChronicleResponse:
    repository: EngineRepository = request.app.state.engine.repository
    row = await repository.get_chronicle(chronicle_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Chronicle not found.")
    return ChronicleResponse.model_validate(row, from_attributes=True)
