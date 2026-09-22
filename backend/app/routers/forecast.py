from fastapi import APIRouter, HTTPException, status
from fastapi.encoders import jsonable_encoder
from typing import List
from app.schemas import ItemMasterSchema,AddNewItemPayload
from app.services.forecast_engine import fetch_item_master_data, create_new_planning_item
from app.schemas import FilterParams, SubmitPayload
from app.services.forecast_engine import run_sql_query_fast, process_and_submit_adjustments

router = APIRouter(prefix="/forecast", tags=["Forecast Engine"])

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
def submit_forecast_changes(payload: SubmitPayload):
    """Submits updates to 24mo forecast, locks approved values, and logs change history."""
    try:
        result = process_and_submit_adjustments(payload)
        return {
            "status": "success",
            "message": f"Updated {result['updated_fcst_rows']} forecast records, locked output, and logged {result['uploaded_chglog_rows']} audit changes.",
            "details": result
        }
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Fabric database operation failed: {str(e)}"
        )

@router.get("/items")
def get_item_master_data():
    """Fetches all items from the item_master table."""
    try:
        return fetch_item_master_data()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch item master details: {str(e)}"
        )

@router.post("/add-item")
def add_new_planning_item(payload: AddNewItemPayload):
    """Creates a new planning item template in sf.fcstState24mo_locked."""
    try:
        result = create_new_planning_item(payload)
        return {
            "status": "success",
            "message": f"Successfully created item '{payload.demand_plan_id}' with {result['inserted_rows']} records.",
            "details": result
        }
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create new item: {str(e)}"
        )