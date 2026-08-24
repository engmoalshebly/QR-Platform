from pydantic import BaseModel, Field, model_validator
from typing import Optional
from uuid import UUID
from datetime import datetime
from enum import Enum

__all__ = [
    "UsagePeriod",
    "PlanRead",
    "PlanLimitRead",
    "PlanWithLimits",
    "PlanAddonRead",
    "CustomPlanItem",
    "CustomPlanRequest",
    "CustomPlanCalculation",
    "CustomPlanRead",
    "AddonLineItem",
]


class UsagePeriod(str, Enum):
    month = "month"
    day = "day"
    none = "none"


class PlanRead(BaseModel):
    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    subtitle: Optional[str] = None
    price_monthly: float
    price_yearly: Optional[float] = None
    currency: str
    is_active: bool
    sort_order: int
    badge_color: Optional[str] = "#6b7280"
    is_popular: Optional[bool] = False
    is_customizable: Optional[bool] = True
    features: Optional[list[str]] = []


class PlanLimitRead(BaseModel):
    id: UUID
    plan_id: UUID
    key: str
    value: int
    period: UsagePeriod


class PlanWithLimits(PlanRead):
    limits: list[PlanLimitRead] = []


# ══════════════════════════════════════════════
# Custom Plan Builder Models
# ══════════════════════════════════════════════

class PlanAddonRead(BaseModel):
    """A purchasable add-on item with its unit price."""
    id: UUID
    key: str
    label_ar: str
    label_en: str
    unit_ar: str
    unit_en: str
    icon: str
    min_value: int
    max_value: int
    step: int
    price_per_unit: float
    category: str
    sort_order: int
    is_active: bool


class CustomPlanItem(BaseModel):
    """A single item in a custom plan request (key + desired quantity)."""
    key: str
    quantity: int = Field(..., ge=0)


class CustomPlanRequest(BaseModel):
    """Request to calculate or create a custom plan."""
    base_plan_code: str = "starter"
    name: Optional[str] = "باقتي المخصصة"
    items: list[CustomPlanItem] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def unique_item_keys(self):
        keys = [item.key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("لا يمكن تكرار نفس الإضافة أكثر من مرة")
        return self


class AddonLineItem(BaseModel):
    """One line in the price breakdown."""
    key: str
    label_ar: str
    label_en: str
    icon: str
    base_value: int
    extra_quantity: int
    unit_price: float
    line_total: float


class CustomPlanCalculation(BaseModel):
    """Result of a custom plan price calculation."""
    base_plan_code: str
    base_plan_name: str
    base_price: float
    addon_lines: list[AddonLineItem]
    addons_total: float
    total_monthly: float
    total_yearly: float
    currency: str = "YER"
    final_limits: dict[str, int]


class CustomPlanRead(BaseModel):
    """A saved custom plan."""
    id: UUID
    tenant_id: UUID
    base_plan_id: Optional[UUID] = None
    name: str
    addons: dict
    base_price: float
    addons_price: float
    total_price_monthly: float
    total_price_yearly: float
    final_limits: dict
    status: str
    created_at: datetime
    updated_at: datetime
