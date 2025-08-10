from typing import Dict, List, Optional, Union, Any
from pydantic import BaseModel, Field, constr, conint, conlist


class Condition(BaseModel):
    subquery_op: Optional[str] = Field(
        None,
        description="Operator for subquery comparison, e.g., '=', '>', '<', '>=', '<=', 'IN', 'NOT IN', 'EXISTS', 'NOT EXISTS'"
    )
    gte: Optional[Union[str, float]] = None
    lte: Optional[Union[str, float]] = None
    gt: Optional[Union[str, float]] = None
    lt: Optional[Union[str, float]] = None
    eq: Optional[Union[str, float]] = None
    like: Optional[str] = None
    regexp: Optional[str] = None
    subquery: Optional[Dict[str, Any]] = None


class OrderByItem(BaseModel):
    field: str
    direction: str = Field("ASC", description="ASC or DESC")


class SimpleQuery(BaseModel):
    table: constr(pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    fields: conlist(constr(min_length=1), min_length=1)
    conditions: Dict[str, Union[Condition, str, Dict[str, Any]]] = Field(default_factory=dict)
    limit: conint(ge=1, le=1000) = 100
    offset: conint(ge=0) = 0
    order_by: Optional[List[Union[str, OrderByItem, Dict[str, Any]]]] = None


class AggregatedQuery(BaseModel):
    table: constr(pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    fields: conlist(constr(min_length=1), min_length=1)
    aggregation: str = Field(..., pattern=r'^(count|sum|avg|min|max)$')
    group_by: conlist(constr(min_length=1), min_length=1)
    conditions: Dict[str, Union[Condition, str, Dict[str, Any]]] = Field(default_factory=dict)
    limit: conint(ge=1, le=1000) = 100
    offset: conint(ge=0) = 0
    order_by: Optional[List[Union[str, OrderByItem, Dict[str, Any]]]] = None


class JoinQuery(BaseModel):
    tables: conlist(constr(pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$'), min_length=2, max_length=2)
    fields: conlist(constr(min_length=1), min_length=1)
    join_conditions: Dict[str, str]
    join_type: str = Field(default="INNER", pattern=r'^(INNER|LEFT|RIGHT)$')
    conditions: Dict[str, Union[Condition, str, Dict[str, Any]]] = Field(default_factory=dict)
    limit: conint(ge=1, le=1000) = 100
    offset: conint(ge=0) = 0
    order_by: Optional[List[Union[str, OrderByItem, Dict[str, Any]]]] = None


class CustomQuery(BaseModel):
    query_draft: Dict[str, Any] 