from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
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
    """Fetch dashboard data with the same response shape, but minimize DB wait time.

    Performance changes are deliberately limited to fetching:
    - push active filters into the latest-row CTE so Fabric scans/ranks fewer rows;
    - replace the correlated CROSS APPLY used for previous forecasts with one
      grouped/ranked set-based query;
    - run independent SELECTs concurrently instead of waiting for them one-by-one.
    """
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

    logger.info(
        f"Generated SQL Conditions: {state_cond} | {chain_cond} | "
        f"{prem_cond} | {brand_cond} | {top_chain_cond}"
    )

    if not filters.date_version or filters.date_version in ["All", "Latest"]:
        selected_date_version_sql = (
            f"(SELECT MAX([DateVersion]) FROM "
            f"[{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}])"
        )
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

    # Filters use columns that are part of the logical-row partition, so applying
    # them before ROW_NUMBER is equivalent but avoids ranking unrelated records.
    fcst_query = f"""
        WITH LatestLogicalRows AS (
            SELECT
                [PlanningID], [State], [Chain Status], [Premise Type], [Brand],
                [Top Chain], [Date], [DateVersion], [ForecastQty_9L], [LoadTimestamp],
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
              AND {state_cond} AND {chain_cond} AND {prem_cond}
              AND {brand_cond} AND {top_chain_cond}
        )
        SELECT
            RTRIM(LTRIM([PlanningID])) AS [PlanningID],
            CAST([Date] AS DATE) AS [FcstDate],
            SUM([ForecastQty_9L]) AS [ForecastQty_9L]
        FROM LatestLogicalRows
        WHERE rn = 1
        GROUP BY RTRIM(LTRIM([PlanningID])), CAST([Date] AS DATE)
    """

    # Set-based equivalent of the old DISTINCT + CROSS APPLY + JOIN query.
    # First aggregate each available version, then rank the preferred version
    # once per PlanningID/date and keep rank 1.
    prev_fcst_query = f"""
        WITH AggregatedVersions AS (
            SELECT
                RTRIM(LTRIM([PlanningID])) AS [PlanningID],
                CAST([Date] AS DATE) AS [FcstDate],
                [DateVersion] AS [DateVersion],
                SUM([ForecastQty_9L]) AS [Prev_ForecastQty_9L]
            FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO}]
            WHERE YEAR(CAST([Date] AS DATE)) = {selected_year}
              AND {state_cond} AND {chain_cond} AND {prem_cond}
              AND {brand_cond} AND {top_chain_cond}
            GROUP BY
                RTRIM(LTRIM([PlanningID])),
                CAST([Date] AS DATE),
                [DateVersion]
        ), RankedVersions AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY [PlanningID], [FcstDate]
                    ORDER BY
                        CASE WHEN CAST([DateVersion] AS DATE) = [FcstDate] THEN 0 ELSE 1 END,
                        [DateVersion] DESC
                ) AS rn
            FROM AggregatedVersions
        )
        SELECT [PlanningID], [FcstDate], [Prev_ForecastQty_9L]
        FROM RankedVersions
        WHERE rn = 1
    """

    load_ts_query = f"""
        SELECT MAX([LoadTimestamp]) AS [LatestLoadTimestamp]
        FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}]
        WHERE [DateVersion] = {selected_date_version_sql}
    """

    # These queries do not depend on each other, so avoid serial network/DB waits.
    with ThreadPoolExecutor(max_workers=3) as pool:
        fcst_future = pool.submit(execute_query, fcst_query)
        prev_future = pool.submit(execute_query, prev_fcst_query)
        load_future = pool.submit(execute_query, load_ts_query)
        df_fcst = fcst_future.result()
        df_prev_fcst = prev_future.result()
        df_load_ts = load_future.result()

    planning_ids = (
        df_fcst['PlanningID'].astype(str).str.strip().unique().tolist()
        if not df_fcst.empty else []
    )

    if planning_ids:
        escaped_ids = "', '".join([p.replace("'", "''") for p in planning_ids])
        id_filter_clause = f"RTRIM(LTRIM([Demand Plan ID])) IN ('{escaped_ids}')"
        budget_id_filter_clause = f"RTRIM(LTRIM([Planning ID])) IN ('{escaped_ids}')"
    else:
        id_filter_clause = "1=0"
        budget_id_filter_clause = "1=0"

    # Dynamically split the selected year into completed Actual months and
    # remaining Forecast months. For the current year, the current month itself
    # is still forecast (e.g. September => Jan-Aug Actuals, Sep-Dec Forecast).
    today = datetime.now()
    if selected_year < today.year:
        actual_month_count = 12
    elif selected_year > today.year:
        actual_month_count = 0
    else:
        actual_month_count = max(0, today.month - 1)

    forecast_start_month = actual_month_count + 1

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
            ([Year] = {selected_year} AND CAST([Month Number] AS INT) <= {actual_month_count})
          )
        GROUP BY RTRIM(LTRIM([Demand Plan ID])), CAST([Year] AS INT), CAST([Month Number] AS INT)
    """

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

    # Both depend only on the already-resolved Planning IDs, and can run together.
    with ThreadPoolExecutor(max_workers=2) as pool:
        depletion_future = pool.submit(execute_query, depletion_query)
        budget_future = pool.submit(execute_query, budget_query)
        df_depletion = depletion_future.result()
        df_budget = budget_future.result()

    # Build lookup maps without DataFrame.iterrows() overhead.
    fcst_map = {}
    if not df_fcst.empty:
        for r in df_fcst.itertuples(index=False):
            pid = str(r.PlanningID).strip()
            dt = pd.to_datetime(r.FcstDate)
            fcst_map[(pid, dt.year, dt.month)] = sanitize_float(r.ForecastQty_9L)

    prev_fcst_map = {}
    if not df_prev_fcst.empty:
        for r in df_prev_fcst.itertuples(index=False):
            pid = str(r.PlanningID).strip()
            dt = pd.to_datetime(r.FcstDate)
            prev_fcst_map[(pid, dt.year, dt.month)] = sanitize_float(r.Prev_ForecastQty_9L)

    depletion_map = {}
    if not df_depletion.empty:
        for pid_raw, yr_raw, mn_raw, qty_raw in df_depletion.itertuples(index=False, name=None):
            pid = str(pid_raw).strip()
            depletion_map[(pid, int(yr_raw), int(mn_raw))] = sanitize_float(qty_raw)

    budget_map = {}
    if not df_budget.empty:
        for r in df_budget.itertuples(index=False):
            pid = str(r.PlanningID).strip()
            dt = pd.to_datetime(r.BudgetDate)
            budget_map[(pid, dt.year, dt.month)] = sanitize_float(r.BudgetQty_9L)

    latest_load_timestamp = None
    if not df_load_ts.empty and 'LatestLoadTimestamp' in df_load_ts.columns:
        ts_val = df_load_ts.iloc[0]['LatestLoadTimestamp']
        if pd.notna(ts_val):
            latest_load_timestamp = pd.to_datetime(ts_val).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    grid_data = []
    for p_id in planning_ids:
        actuals_2024 = [depletion_map.get((p_id, prev_year_1, m), 0.0) for m in range(1, 13)]
        actuals_2025 = [depletion_map.get((p_id, prev_year_2, m), 0.0) for m in range(1, 13)]
        actuals_2026 = [
            depletion_map.get((p_id, selected_year, m), 0.0)
            for m in range(1, actual_month_count + 1)
        ]

        forecasts_2026 = [
            fcst_map.get((p_id, selected_year, m), 0.0)
            for m in range(forecast_start_month, 13)
        ]
        prev_forecasts_2026 = [prev_fcst_map.get((p_id, selected_year, m), 0.0) for m in range(1, 13)]
        forecasts_2027 = [fcst_map.get((p_id, next_year, m), 0.0) for m in range(1, 13)]

        budget_2026 = [budget_map.get((p_id, selected_year, m), 0.0) for m in range(1, 13)]
        budget_2027 = [budget_map.get((p_id, next_year, m), 0.0) for m in range(1, 13)]

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

    try:
        _raw_dump = payload.model_dump() if hasattr(payload, "model_dump") else (
            payload.dict() if hasattr(payload, "dict") else payload
        )
        logger.info(f"RAW SUBMIT PAYLOAD (top-level keys/values): {_raw_dump}")
    except Exception as dump_err:
        logger.warning(f"Could not dump raw payload for diagnostics: {dump_err}")

    def resolve_filter_value(payload_obj, *candidate_names) -> Optional[str]:
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

    is_plan_by_month = getattr(payload, 'plan_by', '').lower() == 'month' or getattr(payload, 'plan_by_month', False)

    def clean_filter_value(val: Any) -> Optional[str]:
        if val is None:
            return None
        s_val = str(val).strip()
        if not s_val or s_val.lower().startswith("all") or s_val.lower() == "latest":
            return None
        return s_val.replace("'", "''")

    def normalized_dim(val: Any) -> str:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return ""
        return str(val).strip().upper()

    def normalized_date(val: Any) -> str:
        try:
            return pd.to_datetime(val).strftime("%Y-%m-%d")
        except Exception:
            return str(val).strip()

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

    # ------------------------------------------------------------------
    # FAST UPDATE FETCH
    # Fetch the latest baseline rows ONCE for every edited PlanningID/date.
    # Plan by Month fetches all dates for the edited PlanningIDs so the same
    # result can also be reused for carry-forward. This replaces the old
    # 2 SELECTs per edited row + an extra carry-forward SELECT.
    # ------------------------------------------------------------------
    edited_items = []
    updated_pids = set()
    updated_dates = set()
    for item in payload.items_to_update:
        pid = str(getattr(item, 'planning_id', '')).strip()
        fcst_date = normalized_date(getattr(item, 'date', ''))
        edited_items.append((item, pid, fcst_date))
        if pid:
            updated_pids.add(pid)
        if fcst_date:
            updated_dates.add(fcst_date)

    escaped_pids = "', '".join(p.replace("'", "''") for p in sorted(updated_pids))
    pid_where = f"RTRIM(LTRIM([PlanningID])) IN ('{escaped_pids}')" if escaped_pids else "1=0"

    if is_plan_by_month:
        date_where = "1=1"
    else:
        escaped_dates = "', '".join(d.replace("'", "''") for d in sorted(updated_dates))
        date_where = f"CAST([Date] AS DATE) IN ('{escaped_dates}')" if escaped_dates else "1=0"

    baseline_query = f"""
        WITH LatestLogicalRows AS (
            SELECT
                [PlanningID], [State], [Chain Status], [Premise Type], [Brand], [Top Chain],
                [Date], [DateVersion], [ForecastQty_9L], [LoadTimestamp],
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
              AND {pid_where}
              AND {date_where}
        )
        SELECT
            RTRIM(LTRIM([PlanningID])) AS [PlanningID],
            ISNULL([State], '') AS [State],
            ISNULL([Chain Status], '') AS [ChainStatus],
            ISNULL([Premise Type], '') AS [PremiseType],
            ISNULL([Brand], '') AS [Brand],
            ISNULL([Top Chain], '') AS [TopChain],
            CAST([Date] AS DATE) AS [Date],
            [ForecastQty_9L]
        FROM LatestLogicalRows
        WHERE rn = 1
    """
    df_baseline = execute_query(baseline_query)

    rows_by_key = {}
    all_baseline_rows = []
    if not df_baseline.empty:
        for r in df_baseline.itertuples(index=False):
            row = {
                "PlanningID": str(r.PlanningID).strip(),
                "State": "" if pd.isna(r.State) else str(r.State),
                "ChainStatus": "" if pd.isna(r.ChainStatus) else str(r.ChainStatus),
                "PremiseType": "" if pd.isna(r.PremiseType) else str(r.PremiseType),
                "Brand": "" if pd.isna(r.Brand) else str(r.Brand),
                "TopChain": "" if pd.isna(r.TopChain) else str(r.TopChain),
                "Date": normalized_date(r.Date),
                "ForecastQty_9L": sanitize_float(r.ForecastQty_9L),
            }
            all_baseline_rows.append(row)
            rows_by_key.setdefault((row["PlanningID"], row["Date"]), []).append(row)

    brand_match = normalized_dim(ui_brand_clean.replace("''", "'")) if ui_brand_clean is not None else None
    premise_match = normalized_dim(ui_premise_clean.replace("''", "'")) if ui_premise_clean is not None else None
    chain_match = normalized_dim(ui_chain_clean.replace("''", "'")) if ui_chain_clean is not None else None
    top_chain_match = normalized_dim(ui_top_chain_clean.replace("''", "'")) if ui_top_chain_clean is not None else None

    for item, pid, fcst_date in edited_items:
        st = str(getattr(item, 'state', '')).strip()
        raw_qty = float(getattr(item, 'forecast_qty_9l', 0.0))
        adj_factor = float(getattr(item, 'adjustment_factor', 1.0))
        new_consolidated_val = round(raw_qty * adj_factor, 6)

        st_active = clean_filter_value(st) is not None
        st_match = normalized_dim(st) if st_active else None
        source_rows = rows_by_key.get((pid, fcst_date), [])

        def row_matches_filters(row: Dict[str, Any]) -> bool:
            if st_match is not None and normalized_dim(row["State"]) != st_match:
                return False
            if brand_match is not None and normalized_dim(row["Brand"]) != brand_match:
                return False
            if premise_match is not None and normalized_dim(row["PremiseType"]) != premise_match:
                return False
            if chain_match is not None and normalized_dim(row["ChainStatus"]) != chain_match:
                return False
            if top_chain_match is not None and normalized_dim(row["TopChain"]) != top_chain_match:
                return False
            return True

        matching_rows = [r for r in source_rows if row_matches_filters(r)]
        has_dimension_filter = any(v is not None for v in (
            st_match, brand_match, premise_match, chain_match, top_chain_match
        ))
        unmatched_rows = [r for r in source_rows if not row_matches_filters(r)] if has_dimension_filter else []

        if matching_rows:
            consolidated_baseline = sum(r["ForecastQty_9L"] for r in matching_rows)
            num_rows = len(matching_rows)
            for row in matching_rows:
                base_qty = row["ForecastQty_9L"]
                mix_percentage = (base_qty / consolidated_baseline) if consolidated_baseline > 0 else (1.0 / num_rows)
                calculated_new_qty = round(new_consolidated_val * mix_percentage, 6)
                detailed_fcst_updates.append({
                    "PlanningID": pid,
                    "State": row["State"],
                    "ChainStatus": row["ChainStatus"],
                    "PremiseType": row["PremiseType"],
                    "Brand": row["Brand"],
                    "TopChain": row["TopChain"],
                    "Date": fcst_date,
                    "ForecastQty_9L": calculated_new_qty,
                    "OldValue": base_qty
                })
        else:
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

        for row in unmatched_rows:
            base_qty = row["ForecastQty_9L"]
            unmodified_subdimension_updates.append({
                "PlanningID": pid,
                "State": row["State"],
                "ChainStatus": row["ChainStatus"],
                "PremiseType": row["PremiseType"],
                "Brand": row["Brand"],
                "TopChain": row["TopChain"],
                "Date": fcst_date,
                "ForecastQty_9L": base_qty,
                "OldValue": base_qty
            })

    final_locked_records = list(detailed_fcst_updates) + list(unmodified_subdimension_updates)

    # Plan by Month: reuse the already-fetched baseline rows for carry-forward.
    # Preserve the existing behavior: any date edited in this submission is
    # excluded from carry-forward for all edited PlanningIDs.
    if is_plan_by_month and detailed_fcst_updates:
        for row in all_baseline_rows:
            if row["PlanningID"] in updated_pids and row["Date"] not in updated_dates:
                final_locked_records.append({
                    "PlanningID": row["PlanningID"],
                    "State": row["State"],
                    "ChainStatus": row["ChainStatus"],
                    "PremiseType": row["PremiseType"],
                    "Brand": row["Brand"],
                    "TopChain": row["TopChain"],
                    "Date": row["Date"],
                    "ForecastQty_9L": row["ForecastQty_9L"],
                    "OldValue": row["ForecastQty_9L"]
                })

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