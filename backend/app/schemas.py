from pydantic import BaseModel, Field
from typing import List, Optional  # <--- Ensure Optional is imported here!
from datetime import datetime

class FilterParams(BaseModel):
    state: str = "All"
    chain_status: Optional[str] = Field(default="All", alias="Chain Status")
    premise_type: Optional[str] = Field(default="All", alias="Premise Type")
    brand: Optional[str] = Field(default="All", alias="Brand")
    top_chain: Optional[str] = Field(default="All", alias="Top Chain")
    date_version: Optional[str] = Field(default=None, alias="DateVersion")

    class Config:
        populate_by_name = True

class ForecastItem(BaseModel):
    id: int = Field(..., alias="Id")
    planning_id: str = Field(..., alias="PlanningID")
    state: str = Field(..., alias="State")
    chain_status: str = Field(..., alias="Chain Status")
    date: str = Field(..., alias="Date")
    forecast_qty_9l: float = Field(..., alias="ForecastQty_9L")
    date_version: str = Field(..., alias="DateVersion")
    premise_type: str = Field(..., alias="Premise Type")
    brand: str = Field(..., alias="Brand")
    top_chain: Optional[str] = Field(None, alias="Top Chain")
    adjustment_factor: float = 1.0

    class Config:
        populate_by_name = True

class DepletionItem(BaseModel):
    id: int = Field(..., alias="Id")
    demand_plan_id: Optional[str] = Field(None, alias="Demand Plan ID")
    class_of_trade: Optional[str] = Field(None, alias="Class of Trade")
    state: str = Field(..., alias="State")
    premise_type: Optional[str] = Field(None, alias="Premise Type")
    chain_status: Optional[str] = Field(None, alias="Chain Status")
    concept_owner_name: Optional[str] = Field(None, alias="Concept Owner Name")
    immediate_owner: Optional[str] = Field(None, alias="Immediate Owner")
    chain_sub_division: Optional[str] = Field(None, alias="Chain Sub Division")
    ultimate_owner: Optional[str] = Field(None, alias="Ultimate Owner")
    chain_division: Optional[str] = Field(None, alias="Chain Division")
    brand: Optional[str] = Field(None, alias="Brand")
    business_channel: Optional[str] = Field(None, alias="Business Channel")
    year: Optional[int] = Field(None, alias="Year")
    month_number: Optional[int] = Field(None, alias="Month Number")
    year_month: Optional[str] = Field(None, alias="YearMonth")
    qty_in_9l: Optional[float] = Field(None, alias="Qty in 9L")
    qty_in_cases: Optional[float] = Field(None, alias="Qty in Cases")
    avg_bottle_price: Optional[float] = Field(None, alias="Avg Bottle Price")
    depl_mix: Optional[float] = Field(None, alias="DeplMix")
    fcst_key: Optional[str] = Field(None, alias="FcstKey")
    top_chain: Optional[str] = Field(None, alias="TopChain")

    class Config:
        populate_by_name = True

class ChangeLogItem(BaseModel):
    when: datetime = Field(default_factory=datetime.now, alias="When")
    user: str = Field(..., alias="User")
    item: str = Field(..., alias="Item")
    old_value: float = Field(..., alias="OldValue")
    new_value: float = Field(..., alias="NewValue")
    fcst_date: str = Field(..., alias="FcstDate")
    state: str = Field(..., alias="State")
    chain_status: str = Field(..., alias="ChainStatus")
    date_version: str = Field(..., alias="DateVersion")
    premise_type: str = Field(..., alias="PremiseType")
    top_chain: Optional[str] = Field(None, alias="TopChain")

    class Config:
        populate_by_name = True

class SubmitPayload(BaseModel):
    selected_state: str
    plan_type: str

    # These were previously missing from this model entirely, so pydantic
    # silently dropped them from the incoming request (extra fields are
    # ignored by default) -- getattr(payload, 'chain_status', None) in
    # forecast_engine.py was always falling back to None regardless of what
    # the UI sent. Adding them here is what actually fixes the filter.
    plan_by: Optional[str] = None
    plan_by_month: Optional[bool] = False
    chain_status: Optional[str] = "All"
    premise_type: Optional[str] = "All"
    brand: Optional[str] = "All"
    top_chain: Optional[str] = "All"

    adjustments: List[ChangeLogItem]
    items_to_update: List[ForecastItem]

    class Config:
        populate_by_name = True
# for adding the item master table schema
# app/schemas.py
class ItemMasterSchema(BaseModel):
    item_id: Optional[str] = Field(None, alias="item_id")
    bc_desc: Optional[str] = Field(None, alias="bc_desc")
    bc_itemGroup: Optional[str] = Field(None, alias="bc_itemGroup")
    demand_plan_id: Optional[str] = Field(None, alias="demand_plan_id")
    vist_itemGroup: Optional[str] = Field(None, alias="vist_itemGroup")
    bc_casePack: Optional[int] = Field(None, alias="bc_casePack")
    bc_bottleSize: Optional[str] = Field(None, alias="bc_bottleSize")
    Converter9L: Optional[float] = Field(None, alias="Converter9L")
    bc_brandCode: Optional[str] = Field(None, alias="bc_brandCode")
    bc_brandName: Optional[str] = Field(None, alias="bc_brandName")
    bc_containerType: Optional[str] = Field(None, alias="bc_containerType")
    bc_containerMaterial: Optional[str] = Field(None, alias="bc_containerMaterial")
    bc_brandGroup: Optional[str] = Field(None, alias="bc_brandGroup")
    bc_proof: Optional[float] = Field(None, alias="bc_proof")
    bc_flavor: Optional[str] = Field(None, alias="bc_flavor")
    barcode_BTL: Optional[str] = Field(None, alias="barcode_BTL")
    barcode_CS: Optional[str] = Field(None, alias="barcode_CS")
    bc_itemStatus: Optional[str] = Field(None, alias="bc_itemStatus")
    
class AddNewItemPayload(BaseModel):
    demand_plan_id: str
    state: str
    brand: str
    template_choice: str  # 'new' or 'existing'
    existing_demand_plan_id: Optional[str] = None
    class Config:
        populate_by_name = True