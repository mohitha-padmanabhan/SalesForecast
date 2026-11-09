from fastapi import APIRouter, HTTPException, status, Query, Request
from fastapi.encoders import jsonable_encoder
from typing import List
from app.schemas import ItemMasterSchema,AddNewItemPayload
from app.services.forecast_engine import fetch_item_master_data, create_new_planning_item, fetch_existing_planning_ids
from app.schemas import FilterParams, SubmitPayload
from app.services.forecast_engine import run_sql_query_fast, process_and_submit_adjustments

from app.services.state_locks import edit_guard

router = APIRouter(prefix="/api/v1/forecast", tags=["Forecast Engine"])

@router.post("/query-base")
def query_base_forecast(filters: FilterParams):
    """Fetches forecasted data, depletion actuals, and calculated statistics."""
    try:
        raw_result = run_sql_query_fast(filters)
        return jsonable_encoder(raw_result)  # <--- Fixes Starlette serialization error
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Failed to query forecast data: {str(e)}"
        )

@router.post("/plan-mode/{mode}")
def set_plan_mode(mode: str):
    """Controls editable month/year grid views."""
    mode_clean = mode.lower().strip()
    if mode_clean in ["year", "yr"]:
        return {
            "plan_mode": "Yr",
            "editable_columns": ["Annual_Target"],
            "lock_columns": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        }
    elif mode_clean in ["month", "mo"]:
        return {
            "plan_mode": "Mo",
            "editable_columns": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            "lock_columns": ["Annual_Target"]
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid planning mode. Allowed values: 'year' or 'month'."
        )

@router.post("/submit")
def submit_forecast_changes(payload: SubmitPayload, request: Request):
    """Submits updates to 24mo forecast, locks approved values, and logs change history."""
    try:
        with edit_guard(request, payload.selected_state):
            result = process_and_submit_adjustments(payload)
        return {
            "status": "success",
            "message": f"Updated {result['updated_fcst_rows']} forecast records, locked output, and logged {result['uploaded_chglog_rows']} audit changes.",
            "details": result
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Fabric database operation failed: {str(e)}"
        )

@router.get("/items")
def get_item_master_data(brand: str = Query("All")):
    """Fetch item-master Demand Plan IDs, optionally filtered by bc_brandGroup."""
    try:
        return fetch_item_master_data(brand)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch item master details: {str(e)}"
        )

@router.get("/existing-ids")
def get_existing_ids(brand: str = Query("All"), state: str = Query("All")):
    """Return only IDs; avoid full forecast calculations when opening Add Item."""
    try:
        return fetch_existing_planning_ids(brand, state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to check existing planning items.") from exc

@router.post("/add-item")
def add_new_planning_item(payload: AddNewItemPayload, request: Request):
    """Creates a new planning item template in sf.fcstState24mo_locked."""
    try:
        scope = payload.edit_scope if payload.edit_scope is not None else payload.state
        if scope != 'All' and scope.strip().upper() != payload.state.strip().upper():
            raise HTTPException(400, 'Select the target state on the Dashboard before creating an item.')
        with edit_guard(request, scope):
            result = create_new_planning_item(payload)
        return {
            "status": "success",
            "message": f"Successfully created item '{payload.demand_plan_id}' with {result['inserted_rows']} records.",
            "details": result
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create new item: {str(e)}"
        )