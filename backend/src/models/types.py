"""
Type definitions for the  backend
"""
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class Period(str, Enum):
    QUARTERLY = "quarterly"
    TTM = "ttm"
    ANNUAL = "annual"


class CompanyFacts(BaseModel):
    ticker: str
    name: str
    cik: str
    market_cap: float
    number_of_employees: int
    sic_code: str
    sic_description: str
    website_url: str
    listing_date: str
    is_active: bool


class CompanyFactsResponse(BaseModel):
    company_facts: CompanyFacts


class IncomeStatement(BaseModel):
    ticker: str
    calendar_date: str
    report_period: str
    period: Period
    revenue: float
    cost_of_revenue: float
    gross_profit: float
    operating_expense: float
    selling_general_and_administrative_expenses: float
    research_and_development: float
    operating_income: float
    interest_expense: float
    ebit: float
    income_tax_expense: float
    net_income_discontinued_operations: float
    net_income_non_controlling_interests: float
    net_income: float
    net_income_common_stock: float
    preferred_dividends_impact: float
    consolidated_income: float
    earnings_per_share: float
    earnings_per_share_diluted: float
    dividends_per_common_share: float
    weighted_average_shares: float
    weighted_average_shares_diluted: float


class IncomeStatementsResponse(BaseModel):
    income_statements: List[IncomeStatement]

class CashFlowStatement(BaseModel):
    ticker: str
    calendar_date: str
    report_period: str
    period: Period
    net_cash_flow_from_operations: float
    depreciation_and_amortization: float
    share_based_compensation: float
    net_cash_flow_from_investing: float
    capital_expenditure: float
    business_acquisitions_and_disposals: float
    investment_acquisitions_and_disposals: float
    net_cash_flow_from_financing: float
    issuance_or_repayment_of_debt_securities: float
    issuance_or_purchase_of_equity_shares: float
    dividends_and_other_cash_distributions: float
    change_in_cash_and_equivalents: float
    effect_of_exchange_rate_changes: float


class CashFlowStatementsResponse(BaseModel):
    cash_flow_statements: List[CashFlowStatement]


# API Request/Response Models
class ThreadCreateRequest(BaseModel):
    pass


class ThreadCreateResponse(BaseModel):
    thread_id: str


class Message(BaseModel):
    role: str
    content: str


class StreamRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Input data for the stream")


class StreamEvent(BaseModel):
    event: str
    data: Dict[str, Any]


# Graph State Models
class GraphState(BaseModel):
    messages: List[Message] = Field(default_factory=list)
    intent: Optional[str] = None
    stream_callback: Optional[Any] = None 