from datetime import datetime
import json
import math
from typing import Any, Dict, List, Optional
import pandas as pd
import logging
from app.config import settings
from app.database import execute_non_query, execute_query, execute_non_query_utf8_safe
from app.schemas import FilterParams, SubmitPayload,AddNewItemPayload
from pydantic import BaseModel, Field
from typing import Optional, List
import warnings,sys
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")


logger = logging.getLogger("forecast_logger")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class SubmitPayload(BaseModel):
    selected_state: Optional[str] = Field(None, alias="state")
    plan_type: Optional[str] = Field(None, alias="planType")
    
    # Handle both snake_case and camelCase field names from UI
    chain_status: Optional[str] = Field(None, validation_alias="chain_status") 
    premise_type: Optional[str] = Field(None, validation_alias="premise_type")
    brand: Optional[str] = Field(None, validation_alias="brand")
    top_chain: Optional[str] = Field(None, validation_alias="top_chain")

    items_to_update: Optional[List[Any]] = Field([], alias="itemsToUpdate")
    adjustments: Optional[List[Any]] = []

    class Config:
        populate_by_name = True

def fetch_item_master_data():
    query = f"""
        SELECT 
            [demand_plan_id]
        FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_ITEM_MASTER}]
    """
    df = execute_query(query)
    df = df.fillna("")  # Ensures safe JSON serialization
    return df.to_dict(orient="records")

def sanitize_float(val: Any) -> float:
    if val is None or pd.isna(val):
        return 0.0
    try:
        f_val = float(val)
        return 0.0 if math.isnan(f_val) or math.isinf(f_val) else f_val
    except (ValueError, TypeError):
        return 0.0

def build_where_clause(column_name: str, value: Optional[str]) -> str:
    if not value or value == "All":
        return "1=1"
    escaped_val = str(value).replace("'", "''")
    return f"{column_name} = '{escaped_val}'"


def run_sql_query_fast(filters: FilterParams) -> Dict[str, Any]:
    logger.info("================ FRONTEND FILTERS RECEIVED ================")
    logger.info(f"State:        '{filters.state}'")
    logger.info(f"Chain Status: '{filters.chain_status}'")
    logger.info(f"Premise Type: '{filters.premise_type}'")
    logger.info(f"Brand:        '{filters.brand}'")
    logger.info(f"Top Chain:    '{filters.top_chain}'")
    logger.info(f"DateVersion:  '{filters.date_version}'")
    logger.info("========================================================")

    state_cond = build_where_clause("[State]", filters.state)
    chain_cond = build_where_clause("[Chain Status]", filters.chain_status)
    prem_cond = build_where_clause("[Premise Type]", filters.premise_type)
    brand_cond = build_where_clause("[Brand]", filters.brand)
    top_chain_cond = build_where_clause("[Top Chain]", filters.top_chain)

    # 🔍 LOG GENERATED SQL WHERE CLAUSES
    logger.info(f"Generated SQL Conditions: {state_cond} | {chain_cond} | {prem_cond} | {brand_cond} | {top_chain_cond}")
    state_cond = build_where_clause("[State]", filters.state)
    chain_cond = build_where_clause("[Chain Status]", filters.chain_status)
    prem_cond = build_where_clause("[Premise Type]", filters.premise_type)
    brand_cond = build_where_clause("[Brand]", filters.brand)
    top_chain_cond = build_where_clause("[Top Chain]", filters.top_chain)

    if not filters.date_version or filters.date_version in ["All", "Latest"]:
        selected_date_version_sql = f"(SELECT MAX([DateVersion]) FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}])"
        selected_year = datetime.now().year
    else:
        escaped_version = filters.date_version.replace("'", "''")
        selected_date_version_sql = f"'{escaped_version}'"
        try:
            selected_year = int(filters.date_version.split("-")[0])
        except (ValueError, IndexError):
            selected_year = datetime.now().year

    prev_year_1 = selected_year - 2
    prev_year_2 = selected_year - 1
    next_year = selected_year + 1

    # Aggregate quantities strictly by PlanningID and Date based on active filters
    fcst_query = f"""
        WITH LatestLogicalRows AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY RTRIM(LTRIM([PlanningID])),
                                    ISNULL([State], ''),
                                    ISNULL([Chain Status], ''),
                                    ISNULL([Premise Type], ''),
                                    ISNULL([Brand], ''),
                                    ISNULL([Top Chain], ''),
                                    CAST([Date] AS DATE),
                                    CAST([DateVersion] AS DATE)
                       ORDER BY [LoadTimestamp] DESC
                   ) AS rn
            FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}]
            WHERE [DateVersion] = {selected_date_version_sql}
        )
        SELECT 
            RTRIM(LTRIM([PlanningID])) AS [PlanningID],
            CAST([Date] AS DATE) AS [FcstDate],
            SUM([ForecastQty_9L]) AS [ForecastQty_9L]
        FROM LatestLogicalRows
        WHERE rn = 1
          AND {state_cond} AND {chain_cond} AND {prem_cond} AND {brand_cond} AND {top_chain_cond}
        GROUP BY RTRIM(LTRIM([PlanningID])), CAST([Date] AS DATE)
    """
    df_fcst = execute_query(fcst_query)

    prev_fcst_query = f"""
        WITH DistinctDates AS (
            SELECT DISTINCT 
                RTRIM(LTRIM([PlanningID])) AS [PlanningID],
                CAST([Date] AS DATE) AS [FcstDate]
            FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO}]
            WHERE YEAR(CAST([Date] AS DATE)) = {selected_year}
              AND {state_cond} AND {chain_cond} AND {prem_cond} AND {brand_cond} AND {top_chain_cond}
        )
        SELECT 
            d.[PlanningID],
            d.[FcstDate],
            SUM(f.[ForecastQty_9L]) AS [Prev_ForecastQty_9L]
        FROM DistinctDates d
        CROSS APPLY (
            -- Find the matching DateVersion (= Date) or fallback to the latest available DateVersion
            SELECT TOP 1 [DateVersion]
            FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO}]
            WHERE RTRIM(LTRIM([PlanningID])) = d.[PlanningID]
              AND CAST([Date] AS DATE) = d.[FcstDate]
              AND {state_cond} AND {chain_cond} AND {prem_cond} AND {brand_cond} AND {top_chain_cond}
            ORDER BY 
                CASE WHEN CAST([DateVersion] AS DATE) = d.[FcstDate] THEN 0 ELSE 1 END,
                [DateVersion] DESC
        ) best_version
        INNER JOIN [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO}] f
            ON RTRIM(LTRIM(f.[PlanningID])) = d.[PlanningID]
           AND CAST(f.[Date] AS DATE) = d.[FcstDate]
           AND f.[DateVersion] = best_version.[DateVersion]
        WHERE {state_cond} AND {chain_cond} AND {prem_cond} AND {brand_cond} AND {top_chain_cond}
        GROUP BY d.[PlanningID], d.[FcstDate]
    """
    df_prev_fcst = execute_query(prev_fcst_query)

    planning_ids = df_fcst['PlanningID'].astype(str).str.strip().unique().tolist() if not df_fcst.empty else []

    if planning_ids:
        escaped_ids = "', '".join([p.replace("'", "''") for p in planning_ids])
        id_filter_clause = f"RTRIM(LTRIM([Demand Plan ID])) IN ('{escaped_ids}')"
        budget_id_filter_clause = f"RTRIM(LTRIM([Planning ID])) IN ('{escaped_ids}')"
    else:
        id_filter_clause = "1=0"
        budget_id_filter_clause = "1=0"

    depletion_query = f"""
        SELECT 
            RTRIM(LTRIM([Demand Plan ID])) AS [PlanningID],
            CAST([Year] AS INT) AS [Year],
            CAST([Month Number] AS INT) AS [Month Number],
            SUM([Qty in 9L]) AS [ActualQty_9L]
        FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_DEPLETION}]
        WHERE {id_filter_clause}
          AND {state_cond} AND {chain_cond} AND {prem_cond} AND {brand_cond}
          AND (
            ([Year] = {prev_year_1}) OR 
            ([Year] = {prev_year_2}) OR 
            ([Year] = {selected_year} AND CAST([Month Number] AS INT) <= 7)
          )
        GROUP BY RTRIM(LTRIM([Demand Plan ID])), CAST([Year] AS INT), CAST([Month Number] AS INT)
    """
    df_depletion = execute_query(depletion_query)

    budget_state_cond = build_where_clause("[StateCode]", filters.state)
    
    budget_query = f"""
        SELECT 
            RTRIM(LTRIM([Planning ID])) AS [PlanningID],
            CAST([Date] AS DATE) AS [BudgetDate],
            SUM([9L Cases]) AS [BudgetQty_9L]
        FROM [{settings.FABRIC_SCHEMA}].[budget]
        WHERE {budget_id_filter_clause}
          AND {budget_state_cond}
          AND {chain_cond}
          AND {prem_cond}
          AND {brand_cond}
          AND {top_chain_cond}
          AND (YEAR(CAST([Date] AS DATE)) IN ({selected_year}, {next_year}))
        GROUP BY RTRIM(LTRIM([Planning ID])), CAST([Date] AS DATE)
    """
    df_budget = execute_query(budget_query)

    fcst_map = {}
    if not df_fcst.empty:
        for _, r in df_fcst.iterrows():
            pid = str(r['PlanningID']).strip()
            dt = pd.to_datetime(r["FcstDate"])
            fcst_map[(pid, dt.year, dt.month)] = sanitize_float(r["ForecastQty_9L"])

    prev_fcst_map = {}
    if not df_prev_fcst.empty:
        for _, r in df_prev_fcst.iterrows():
            pid = str(r['PlanningID']).strip()
            dt = pd.to_datetime(r["FcstDate"])
            prev_fcst_map[(pid, dt.year, dt.month)] = sanitize_float(r["Prev_ForecastQty_9L"])

    depletion_map = {}
    if not df_depletion.empty:
        for _, r in df_depletion.iterrows():
            pid = str(r['PlanningID']).strip()
            yr = int(r['Year'])
            mn = int(r['Month Number'])
            depletion_map[(pid, yr, mn)] = sanitize_float(r["ActualQty_9L"])

    budget_map = {}
    if not df_budget.empty:
        for _, r in df_budget.iterrows():
            pid = str(r['PlanningID']).strip()
            dt = pd.to_datetime(r["BudgetDate"])
            budget_map[(pid, dt.year, dt.month)] = sanitize_float(r["BudgetQty_9L"])

    load_ts_query = f"""
        SELECT MAX([LoadTimestamp]) AS [LatestLoadTimestamp]
        FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}]
        WHERE [DateVersion] = {selected_date_version_sql}
    """
    df_load_ts = execute_query(load_ts_query)
    latest_load_timestamp = None
    if not df_load_ts.empty and 'LatestLoadTimestamp' in df_load_ts.columns:
        ts_val = df_load_ts.iloc[0]['LatestLoadTimestamp']
        if pd.notna(ts_val):
            latest_load_timestamp = pd.to_datetime(ts_val).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    grid_data = []
    for p_id in planning_ids:
        actuals_2024 = [depletion_map.get((p_id, prev_year_1, m), 0.0) for m in range(1, 13)]
        actuals_2025 = [depletion_map.get((p_id, prev_year_2, m), 0.0) for m in range(1, 13)]
        actuals_2026 = [depletion_map.get((p_id, selected_year, m), 0.0) for m in range(1, 8)]

        forecasts_2026 = [fcst_map.get((p_id, selected_year, m), 0.0) for m in range(8, 13)]
        prev_forecasts_2026 = [prev_fcst_map.get((p_id, selected_year, m), 0.0) for m in range(1, 13)]
        forecasts_2027 = [fcst_map.get((p_id, next_year, m), 0.0) for m in range(1, 13)]

        budget_2026 = [budget_map.get((p_id, selected_year, m), 0.0) for m in range(1, 13)]
        budget_2027 = [budget_map.get((p_id, next_year, m), 0.0) for m in range(1, 13)]

        # Bind active UI filter labels directly to avoid misleading hardcoded sub-attributes
        grid_data.append({
            "planning_id": p_id,
            "state": filters.state if filters.state != "All" else "All States",
            "brand": filters.brand if filters.brand != "All" else "All Brands",
            "chain_status": filters.chain_status if filters.chain_status != "All" else "All Chain Statuses",
            "premise_type": filters.premise_type if filters.premise_type != "All" else "All Premise Types",
            "top_chain": filters.top_chain if filters.top_chain != "All" else "All Top Chains",
            "annualTarget": sanitize_float(sum(actuals_2026) + sum(forecasts_2026)),
            "actuals2024": actuals_2024,
            "actuals2025": actuals_2025,
            "actuals2026": actuals_2026,
            "forecasts2026": forecasts_2026,
            "prevForecasts2026": prev_forecasts_2026,
            "forecasts2027": forecasts_2027,
            f"budget{selected_year}": budget_2026,
            f"budget{next_year}": budget_2027
        })

    return {
        "grid_data": grid_data,
        "statistics": {
            "total_planning_ids": len(grid_data),
            "grand_total_actuals_2026_7mo": sanitize_float(sum(sum(item["actuals2026"]) for item in grid_data)),
            "grand_total_forecast_2026_5mo": sanitize_float(sum(sum(item["forecasts2026"]) for item in grid_data)),
            "latest_date_version": filters.date_version if filters.date_version else "Latest",
            "latest_load_timestamp": latest_load_timestamp
        }
    }

def process_and_submit_adjustments(payload: SubmitPayload) -> Dict[str, int]:
    if not payload.items_to_update:
        raise ValueError("No forecast data rows supplied for submission.")

    now = datetime.now()
    current_date_version = now.replace(day=1).strftime("%Y-%m-%d")
    current_load_timestamp = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    detailed_fcst_updates = []
    unmodified_subdimension_updates = []

    # ---------------------------------------------------------------------
    # DIAGNOSTIC: dump the raw payload once so we can see the real attribute
    # names FastAPI/pydantic populated on the actual request model (this
    # file's local `SubmitPayload` class above is shadowed by the one
    # imported from app.schemas and is NOT what's actually received here).
    # ---------------------------------------------------------------------
    try:
        _raw_dump = payload.model_dump() if hasattr(payload, "model_dump") else (
            payload.dict() if hasattr(payload, "dict") else payload
        )
        logger.info(f"RAW SUBMIT PAYLOAD (top-level keys/values): {_raw_dump}")
    except Exception as dump_err:
        logger.warning(f"Could not dump raw payload for diagnostics: {dump_err}")

    def resolve_filter_value(payload_obj, *candidate_names) -> Optional[str]:
        """
        Look up a filter value trying every plausible attribute/key name,
        since the real request schema (app.schemas.SubmitPayload) may name
        fields differently than assumed here (snake_case vs camelCase vs
        a display-style key). Returns the first non-None match found.
        """
        payload_dict = None
        if isinstance(payload_obj, dict):
            payload_dict = payload_obj
        else:
            for method_name in ("model_dump", "dict"):
                fn = getattr(payload_obj, method_name, None)
                if callable(fn):
                    try:
                        payload_dict = fn()
                    except TypeError:
                        payload_dict = fn(by_alias=False) if method_name == "model_dump" else None
                    break

        for name in candidate_names:
            if hasattr(payload_obj, name):
                val = getattr(payload_obj, name)
                if val is not None:
                    return val
            if payload_dict and name in payload_dict and payload_dict[name] is not None:
                return payload_dict[name]
        return None

    # Check if 'Plan by Month' is active
    is_plan_by_month = getattr(payload, 'plan_by', '').lower() == 'month' or getattr(payload, 'plan_by_month', False)
    
    # Helper function to check if a filter value is an active filter (i.e. not "All" or generic "All X")
    def clean_filter_value(val: Any) -> Optional[str]:
        if val is None:
            return None
        s_val = str(val).strip()
        if not s_val or s_val.lower().startswith("all") or s_val.lower() == "latest":
            return None
        return s_val.replace("'", "''")

    # Extract UI-level filters STRICTLY from top-level payload attributes
    ui_brand_clean = clean_filter_value(resolve_filter_value(payload, 'brand', 'Brand'))
    ui_premise_clean = clean_filter_value(resolve_filter_value(payload, 'premise_type', 'premiseType', 'Premise Type'))
    ui_chain_clean = clean_filter_value(resolve_filter_value(payload, 'chain_status', 'chainStatus', 'Chain Status'))
    ui_top_chain_clean = clean_filter_value(resolve_filter_value(payload, 'top_chain', 'topChain', 'Top Chain'))

    logger.info("================ RESOLVED SUBMIT FILTERS ================")
    logger.info(f"Chain Status Filter: '{ui_chain_clean}'")
    logger.info(f"Brand Filter:        '{ui_brand_clean}'")
    logger.info(f"Premise Type Filter: '{ui_premise_clean}'")
    logger.info(f"Top Chain Filter:    '{ui_top_chain_clean}'")
    logger.info("=========================================================")

    first_item = payload.items_to_update[0]
    source_date_version = clean_filter_value(getattr(first_item, 'date_version', None))
    if source_date_version:
        source_date_version_sql = f"'{source_date_version}'"
    else:
        source_date_version_sql = f"(SELECT MAX([DateVersion]) FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}])"

    latest_rows_cte = f"""
        WITH LatestLogicalRows AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY RTRIM(LTRIM([PlanningID])),
                                    ISNULL([State], ''),
                                    ISNULL([Chain Status], ''),
                                    ISNULL([Premise Type], ''),
                                    ISNULL([Brand], ''),
                                    ISNULL([Top Chain], ''),
                                    CAST([Date] AS DATE),
                                    CAST([DateVersion] AS DATE)
                       ORDER BY [LoadTimestamp] DESC
                   ) AS rn
            FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}]
            WHERE [DateVersion] = {source_date_version_sql}
        )
    """

    for item in payload.items_to_update:
        pid = str(getattr(item, 'planning_id', '')).strip()
        st = str(getattr(item, 'state', '')).strip()
        fcst_date = str(getattr(item, 'date', '')).strip()
        
        raw_qty = float(getattr(item, 'forecast_qty_9l', 0.0))
        adj_factor = float(getattr(item, 'adjustment_factor', 1.0))
        new_consolidated_val = round(raw_qty * adj_factor, 6)

        pid_clean = pid.replace("'", "''")
        st_clean = st.replace("'", "''")

        # ---------------------------------------------------------------------
        # STEP 1A: Query baseline rows strictly matching active UI filters
        # ---------------------------------------------------------------------
        base_key_where = [
            f"RTRIM(LTRIM([PlanningID])) = '{pid_clean}'",
            f"CAST([Date] AS DATE) = '{fcst_date}'"
        ]
        dimension_match_where = []

        if clean_filter_value(st) is not None:
            dimension_match_where.append(f"UPPER(TRIM([State])) = UPPER('{st_clean}')")

        if ui_brand_clean is not None:
            dimension_match_where.append(f"UPPER(TRIM(ISNULL([Brand], ''))) = UPPER('{ui_brand_clean}')")

        if ui_premise_clean is not None:
            dimension_match_where.append(f"UPPER(TRIM(ISNULL([Premise Type], ''))) = UPPER('{ui_premise_clean}')")

        if ui_chain_clean is not None:
            dimension_match_where.append(f"UPPER(TRIM(ISNULL([Chain Status], ''))) = UPPER('{ui_chain_clean}')")

        if ui_top_chain_clean is not None:
            dimension_match_where.append(f"UPPER(TRIM(ISNULL([Top Chain], ''))) = UPPER('{ui_top_chain_clean}')")

        matching_where = base_key_where + dimension_match_where
        matching_where_sql = " AND ".join(matching_where)

        detail_query = f"""
            {latest_rows_cte}
            SELECT 
                RTRIM(LTRIM([PlanningID])) AS [PlanningID],
                [State],
                ISNULL([Chain Status], '') AS [ChainStatus],
                ISNULL([Premise Type], '') AS [PremiseType],
                ISNULL([Brand], '') AS [Brand],
                ISNULL([Top Chain], '') AS [TopChain],
                CAST([Date] AS DATE) AS [Date],
                [ForecastQty_9L]
            FROM LatestLogicalRows
            WHERE rn = 1 AND {matching_where_sql}
        """
        df_details = execute_query(detail_query)

        # Disaggregate across matching baseline rows
        if not df_details.empty:
            consolidated_baseline = df_details['ForecastQty_9L'].apply(sanitize_float).sum()
            num_rows = len(df_details)

            for _, row in df_details.iterrows():
                base_qty = sanitize_float(row['ForecastQty_9L'])
                mix_percentage = (base_qty / consolidated_baseline) if consolidated_baseline > 0 else (1.0 / num_rows)
                calculated_new_qty = round(new_consolidated_val * mix_percentage, 6)

                detailed_fcst_updates.append({
                    "PlanningID": pid,
                    "State": str(row['State']),
                    "ChainStatus": str(row['ChainStatus']),
                    "PremiseType": str(row['PremiseType']),
                    "Brand": str(row['Brand']),
                    "TopChain": str(row['TopChain']),
                    "Date": fcst_date,
                    "ForecastQty_9L": calculated_new_qty,
                    "OldValue": base_qty
                })
        else:
            # Fallback if no matching records exist in DB
            detailed_fcst_updates.append({
                "PlanningID": pid,
                "State": st,
                "ChainStatus": ui_chain_clean or "",
                "PremiseType": ui_premise_clean or "",
                "Brand": ui_brand_clean or "",
                "TopChain": ui_top_chain_clean or "",
                "Date": fcst_date,
                "ForecastQty_9L": new_consolidated_val,
                "OldValue": float(getattr(item, 'old_value', 0.0))
            })

        # ---------------------------------------------------------------------
        # STEP 1B: Fetch NON-MATCHING sub-dimension rows for the SAME PlanningID & Date
        # ---------------------------------------------------------------------
        unmatched_where = list(base_key_where)
        if dimension_match_where:
            unmatched_where.append(f"NOT ({' AND '.join(dimension_match_where)})")
        else:
            # No narrower sub-dimension filter exists, so there are no
            # non-matching rows for this PlanningID/date pair to preserve here.
            unmatched_where.append("1=0")

        unmatched_query = f"""
            {latest_rows_cte}
            SELECT 
                RTRIM(LTRIM([PlanningID])) AS [PlanningID],
                [State],
                ISNULL([Chain Status], '') AS [ChainStatus],
                ISNULL([Premise Type], '') AS [PremiseType],
                ISNULL([Brand], '') AS [Brand],
                ISNULL([Top Chain], '') AS [TopChain],
                CAST([Date] AS DATE) AS [Date],
                [ForecastQty_9L]
            FROM LatestLogicalRows
            WHERE rn = 1 AND {" AND ".join(unmatched_where)}
        """
        df_unmatched = execute_query(unmatched_query)

        if not df_unmatched.empty:
            for _, row in df_unmatched.iterrows():
                base_qty = sanitize_float(row['ForecastQty_9L'])
                unmodified_subdimension_updates.append({
                    "PlanningID": pid,
                    "State": str(row['State']),
                    "ChainStatus": str(row['ChainStatus']),
                    "PremiseType": str(row['PremiseType']),
                    "Brand": str(row['Brand']),
                    "TopChain": str(row['TopChain']),
                    "Date": fcst_date,
                    "ForecastQty_9L": base_qty,
                    "OldValue": base_qty
                })

    final_locked_records = list(detailed_fcst_updates) + list(unmodified_subdimension_updates)

    # ---------------------------------------------------------------------
    # STEP 2: Carry forward un-edited dates for 'Plan by Month'
    # ---------------------------------------------------------------------
    if is_plan_by_month and detailed_fcst_updates:
        updated_pids = list({r["PlanningID"] for r in detailed_fcst_updates})
        updated_dates = list({r["Date"] for r in detailed_fcst_updates})
        
        pids_str = "', '".join([p.replace("'", "''") for p in updated_pids])
        dates_str = "', '".join([d.replace("'", "''") for d in updated_dates])

        carry_over_query = f"""
            {latest_rows_cte}
            SELECT 
                RTRIM(LTRIM([PlanningID])) AS [PlanningID],
                [State],
                ISNULL([Chain Status], '') AS [ChainStatus],
                ISNULL([Premise Type], '') AS [PremiseType],
                ISNULL([Brand], '') AS [Brand],
                ISNULL([Top Chain], '') AS [TopChain],
                CAST([Date] AS DATE) AS [Date],
                [ForecastQty_9L] AS [ForecastQty_9L],
                [ForecastQty_9L] AS [OldValue]
            FROM LatestLogicalRows
            WHERE rn = 1
              AND RTRIM(LTRIM([PlanningID])) IN ('{pids_str}')
              AND CAST([Date] AS DATE) NOT IN ('{dates_str}')
        """
        df_carry = execute_query(carry_over_query)

        if not df_carry.empty:
            for _, r in df_carry.iterrows():
                final_locked_records.append({
                    "PlanningID": str(r["PlanningID"]),
                    "State": str(r["State"]),
                    "ChainStatus": str(r["ChainStatus"]),
                    "PremiseType": str(r["PremiseType"]),
                    "Brand": str(r["Brand"]),
                    "TopChain": str(r["TopChain"]),
                    "Date": str(r["Date"]),
                    "ForecastQty_9L": sanitize_float(r["ForecastQty_9L"]),
                    "OldValue": sanitize_float(r["OldValue"])
                })

    # ---------------------------------------------------------------------
    # STEP 3: Append the new monthly snapshot version.
    # DateVersion stays fixed at the first day of the current month;
    # LoadTimestamp distinguishes every load made within that month.
    # ---------------------------------------------------------------------
    locked_insert_payload = [
        {
            "PlanningID": r["PlanningID"],
            "State": r["State"],
            "ChainStatus": r["ChainStatus"],
            "Date": r["Date"],
            "ForecastQty_9L": r["ForecastQty_9L"],
            "DateVersion": current_date_version,
            "PremiseType": r["PremiseType"],
            "Brand": r["Brand"],
            "TopChain": r["TopChain"],
            "LoadTimestamp": current_load_timestamp
        }
        for r in final_locked_records
    ]
    json_locked = json.dumps(locked_insert_payload)

    insert_locked_sql = f"""
        INSERT INTO [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}] (
            [PlanningID], [State], [Chain Status], [Date],
            [ForecastQty_9L], [DateVersion], [Premise Type], [Brand], [Top Chain], [LoadTimestamp]
        )
        SELECT 
            [PlanningID], [State], [ChainStatus], CAST([Date] AS DATE),
            [ForecastQty_9L], [DateVersion], [PremiseType], [Brand], [TopChain], CAST([LoadTimestamp] AS DATETIME2(3))
        FROM OPENJSON(?)
        WITH (
            [PlanningID] NVARCHAR(255) '$.PlanningID',
            [State] NVARCHAR(100) '$.State',
            [ChainStatus] NVARCHAR(100) '$.ChainStatus',
            [Date] VARCHAR(50) '$.Date',
            [ForecastQty_9L] FLOAT '$.ForecastQty_9L',
            [DateVersion] VARCHAR(50) '$.DateVersion',
            [PremiseType] NVARCHAR(100) '$.PremiseType',
            [Brand] NVARCHAR(255) '$.Brand',
            [TopChain] NVARCHAR(255) '$.TopChain',
            [LoadTimestamp] VARCHAR(30) '$.LoadTimestamp'
        )
    """
    execute_non_query_utf8_safe(insert_locked_sql, json_locked)

    # ---------------------------------------------------------------------
    # STEP 4: Insert ONLY modified records into fcstChangelog
    # ---------------------------------------------------------------------
    uploaded_chglog_count = 0
    if payload.adjustments:
        chglog_payload = []
        user_identity = payload.adjustments[0].user if payload.adjustments and "@" in str(payload.adjustments[0].user) else "user@company.com"

        for r in detailed_fcst_updates:
            chglog_payload.append({
                "When": current_load_timestamp,
                "User": user_identity,
                "Item": r["PlanningID"],
                "OldValue": float(r["OldValue"]),
                "NewValue": float(r["ForecastQty_9L"]),
                "FcstDate": r["Date"],
                "State": r["State"],
                "ChainStatus": r["ChainStatus"],
                "DateVersion": current_date_version,
                "PremiseType": r["PremiseType"],
                "TopChain": r["TopChain"]
            })

        json_chglog = json.dumps(chglog_payload)

        insert_chglog_sql = f"""
            INSERT INTO [{settings.FABRIC_SCHEMA}].[{settings.TABLE_CHANGELOG}] (
                [When], [User], [Item], [OldValue], [NewValue], 
                [FcstDate], [State], [ChainStatus], [DateVersion], 
                [PremiseType], [TopChain]
            )
            SELECT 
                [When], [User], [Item], [OldValue], [NewValue], 
                CAST([FcstDate] AS DATE), [State], [ChainStatus], [DateVersion], 
                [PremiseType], [TopChain]
            FROM OPENJSON(?)
            WITH (
                [When] DATETIME2 '$.When',
                [User] NVARCHAR(255) '$.User',
                [Item] NVARCHAR(255) '$.Item',
                [OldValue] FLOAT '$.OldValue',
                [NewValue] FLOAT '$.NewValue',
                [FcstDate] VARCHAR(50) '$.FcstDate',
                [State] NVARCHAR(100) '$.State',
                [ChainStatus] NVARCHAR(100) '$.ChainStatus',
                [DateVersion] VARCHAR(50) '$.DateVersion',
                [PremiseType] NVARCHAR(100) '$.PremiseType',
                [TopChain] NVARCHAR(100) '$.TopChain'
            )
        """
        execute_non_query_utf8_safe(insert_chglog_sql, json_chglog)
        uploaded_chglog_count = len(chglog_payload)

    return {
        "updated_fcst_rows": 0,
        "appended_locked_rows": len(locked_insert_payload),
        "uploaded_chglog_rows": uploaded_chglog_count,
        "date_version": current_date_version,
        "load_timestamp": current_load_timestamp
    }   

#new item creation logic
def create_new_planning_item(payload: AddNewItemPayload) -> Dict[str, Any]:
    new_pid = payload.demand_plan_id.replace("'", "''").strip()
    st = payload.state.replace("'", "''").strip()
    br = payload.brand.replace("'", "''").strip()
    now = datetime.now()
    today_version = now.replace(day=1).strftime("%Y-%m-%d")
    load_timestamp = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    if payload.template_choice == "new":
        # Pull distinct combinations for state and brand under latest DateVersion
        query = f"""
            WITH LatestLogicalRows AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY RTRIM(LTRIM([PlanningID])), ISNULL([State], ''),
                                 ISNULL([Chain Status], ''), ISNULL([Premise Type], ''),
                                 ISNULL([Brand], ''), ISNULL([Top Chain], ''),
                                 CAST([Date] AS DATE), CAST([DateVersion] AS DATE)
                    ORDER BY [LoadTimestamp] DESC
                ) AS rn
                FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}]
                WHERE [DateVersion] = (SELECT MAX([DateVersion]) FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}])
            )
            SELECT DISTINCT
                [State], [Brand], [Chain Status], [Premise Type], [Top Chain],
                CAST([Date] AS DATE) AS [Date]
            FROM LatestLogicalRows
            WHERE rn = 1 AND [State] = '{st}' AND [Brand] = '{br}'
        """
        df_template = execute_query(query)

        if df_template.empty:
            raise ValueError(f"No existing template rows found for State: '{payload.state}' and Brand: '{payload.brand}'.")

        insert_payload = []
        for _, r in df_template.iterrows():
            insert_payload.append({
                "PlanningID": new_pid,
                "State": str(r["State"]),
                "ChainStatus": str(r["Chain Status"] or ""),
                "PremiseType": str(r["Premise Type"] or ""),
                "Brand": str(r["Brand"] or ""),
                "TopChain": str(r["Top Chain"] or ""),
                "Date": str(r["Date"]),
                "ForecastQty_9L": 0.0,
                "DateVersion": today_version,
                "LoadTimestamp": load_timestamp
            })

    elif payload.template_choice == "existing":
        if not payload.existing_demand_plan_id:
            raise ValueError("Existing Demand Plan ID is required for 'existing' template choice.")

        ex_pid = payload.existing_demand_plan_id.replace("'", "''").strip()

        # Extract combinations matching state, brand, and existing planning ID
        query = f"""
            WITH LatestLogicalRows AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY RTRIM(LTRIM([PlanningID])), ISNULL([State], ''),
                                 ISNULL([Chain Status], ''), ISNULL([Premise Type], ''),
                                 ISNULL([Brand], ''), ISNULL([Top Chain], ''),
                                 CAST([Date] AS DATE), CAST([DateVersion] AS DATE)
                    ORDER BY [LoadTimestamp] DESC
                ) AS rn
                FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}]
                WHERE [DateVersion] = (SELECT MAX([DateVersion]) FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}])
            )
            SELECT DISTINCT
                [State], [Brand], [Chain Status], [Premise Type], [Top Chain],
                CAST([Date] AS DATE) AS [Date], [ForecastQty_9L]
            FROM LatestLogicalRows
            WHERE rn = 1
              AND [State] = '{st}'
              AND [Brand] = '{br}'
              AND RTRIM(LTRIM([PlanningID])) = '{ex_pid}'
        """
        df_template = execute_query(query)

        if df_template.empty:
            raise ValueError(f"No template found for PlanningID '{payload.existing_demand_plan_id}', State '{payload.state}', and Brand '{payload.brand}'.")

        insert_payload = []
        for _, r in df_template.iterrows():
            insert_payload.append({
                "PlanningID": new_pid,
                "State": str(r["State"]),
                "ChainStatus": str(r["Chain Status"] or ""),
                "PremiseType": str(r["Premise Type"] or ""),
                "Brand": str(r["Brand"] or ""),
                "TopChain": str(r["Top Chain"] or ""),
                "Date": str(r["Date"]),
                "ForecastQty_9L": sanitize_float(r["ForecastQty_9L"]),
                "DateVersion": today_version,
                "LoadTimestamp": load_timestamp
            })

    else:
        raise ValueError("Invalid template choice specified.")

    # Execute UTF-8 bulk insertion using OPENJSON
    json_insert = json.dumps(insert_payload)
    insert_sql = f"""
        INSERT INTO [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}] (
            [PlanningID], [State], [Chain Status], [Premise Type], 
            [Brand], [Top Chain], [Date], [ForecastQty_9L], [DateVersion], [LoadTimestamp]
        )
        SELECT 
            [PlanningID], [State], [ChainStatus], [PremiseType],
            [Brand], [TopChain], CAST([Date] AS DATE), [ForecastQty_9L], [DateVersion], CAST([LoadTimestamp] AS DATETIME2(3))
        FROM OPENJSON(?)
        WITH (
            [PlanningID] NVARCHAR(255) '$.PlanningID',
            [State] NVARCHAR(100) '$.State',
            [ChainStatus] NVARCHAR(100) '$.ChainStatus',
            [PremiseType] NVARCHAR(100) '$.PremiseType',
            [Brand] NVARCHAR(255) '$.Brand',
            [TopChain] NVARCHAR(255) '$.TopChain',
            [Date] VARCHAR(50) '$.Date',
            [ForecastQty_9L] FLOAT '$.ForecastQty_9L',
            [DateVersion] VARCHAR(50) '$.DateVersion',
            [LoadTimestamp] VARCHAR(30) '$.LoadTimestamp'
        )
    """
    execute_non_query_utf8_safe(insert_sql, json_insert)

    return {
        "inserted_rows": len(insert_payload),
        "planning_id": payload.demand_plan_id,
        "date_version": today_version,
        "load_timestamp": load_timestamp
    }