from fastapi import APIRouter, Depends
from app.digital_twin.models import DigitalTwinState
from app.digital_twin.service import digital_twin_service
from app.auth.jwt import get_current_user

router = APIRouter(prefix="/digital-twin", tags=["Digital Twin"])

@router.get("/state", response_model=DigitalTwinState)
async def get_digital_twin_state(current_user: dict = Depends(get_current_user)):
    """Returns the latest Digital Twin state."""
    return digital_twin_service.get_state()

@router.post("/update", response_model=DigitalTwinState)
async def update_digital_twin_state(current_user: dict = Depends(get_current_user)):
    """Forces an immediate collection update of the Digital Twin state."""
    return digital_twin_service.update_state()


