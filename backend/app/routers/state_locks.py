from fastapi import APIRouter, Request
from pydantic import BaseModel
from app.services import state_locks

router = APIRouter(prefix='/api/v1/state-locks', tags=['State editing'])

class StateSelection(BaseModel):
    state: str

@router.get('/')
def state_status(request: Request, state: str):
    return state_locks.status(request, state)

@router.post('/acquire')
def acquire_state(payload: StateSelection, request: Request):
    return state_locks.acquire(request, payload.state)

@router.post('/release')
def release_state(payload: StateSelection, request: Request):
    state_locks.release(request, payload.state)
    return {'released': True}
