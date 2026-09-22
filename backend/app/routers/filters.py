from fastapi import APIRouter, Query
from typing import Optional
from app.config import settings
from app.database import execute_query

router = APIRouter(prefix="/filters", tags=["Filters"])

@router.get("/")
def get_filter_options(
    state: Optional[str] = Query(None),
    chain_status: Optional[str] = Query(None),
    premise_type: Optional[str] = Query(None)
):
    # 1. Fetch DateVersion and Brand strictly from 24mo_locked table
    locked_query = f"""
        SELECT DISTINCT [Brand], CAST([DateVersion] AS DATE) AS [DateVersion]
        FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_FCST_24MO_LOCKED}]
    """
    df_locked = execute_query(locked_query)
    
    date_versions = []
    if 'DateVersion' in df_locked and not df_locked.empty:
        date_versions = sorted({str(v)[:10] for v in df_locked['DateVersion'].dropna().tolist()}, reverse=True)
    latest_date_version = date_versions[0] if date_versions else None
    brands = sorted(df_locked['Brand'].dropna().unique().tolist()) if 'Brand' in df_locked and not df_locked.empty else []

    # 2. Fetch ALL States (unfiltered by selected state so all dropdown choices remain visible)
    state_query = f"""
        SELECT DISTINCT [State] 
        FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_CHAIN_MASTER}]
        WHERE [State] IS NOT NULL
    """
    df_states = execute_query(state_query)
    states = sorted(df_states['State'].dropna().unique().tolist()) if 'State' in df_states and not df_states.empty else []

    # 3. Build WHERE clauses for cascading options (Premise Type & Top Chain)
    where_clauses = []
    params = []

    if state and state.upper() != "ALL":
        where_clauses.append("[State] = ?")
        params.append(state)

    if premise_type and premise_type.upper() != "ALL":
        where_clauses.append("[Premise Type] = ?")
        params.append(premise_type)

    where_stmt = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # 4. Query chain_master for cascaded Premise Types and Top Chains
    chain_query = f"""
        SELECT DISTINCT 
            [Premise Type], 
            [Concept Owner Name]
        FROM [{settings.FABRIC_SCHEMA}].[{settings.TABLE_CHAIN_MASTER}]
        {where_stmt}
    """
    
    if params:
        df_chain = execute_query(chain_query, tuple(params))
    else:
        df_chain = execute_query(chain_query)

    premise_types = sorted(df_chain['Premise Type'].dropna().unique().tolist()) if 'Premise Type' in df_chain and not df_chain.empty else []

    # Hardcoded Chain Status options since it's not a column in DB
    chain_statuses = ["CHAIN", "INDEPENDENT"]

    # 5. Handle Top Chain (Concept Owner Name) conditional rule
    if chain_status and chain_status.upper() == "INDEPENDENT":
        top_chains = ["Other"]
    else:
        top_chains = sorted(df_chain['Concept Owner Name'].dropna().unique().tolist()) if 'Concept Owner Name' in df_chain and not df_chain.empty else []

    return {
        "states": states,
        "chain_statuses": chain_statuses,
        "premise_types": premise_types,
        "top_chains": top_chains,
        "brands": brands,
        "date_versions": date_versions,
        "default_date_version": latest_date_version
    }