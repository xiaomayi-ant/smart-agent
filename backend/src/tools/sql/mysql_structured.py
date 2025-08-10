from typing import Dict, Any, List, Optional
from langchain.tools import tool
from ..database import db_manager
from .types import SimpleQuery, AggregatedQuery, JoinQuery, CustomQuery
from .builders import (
    validate_field_name,
    build_conditions,
    build_query_from_draft,
    _render_order_by,
    _append_pagination,
    resolve_table_name,
)


@tool(args_schema=SimpleQuery)
async def mysql_simple_query_tool(
    table: str,
    fields: List[str],
    conditions: Dict[str, Any] = {},
    limit: int = 100,
    offset: int = 0,
    order_by: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Query a single table with fields, optional conditions, order, limit and offset."""
    try:
        params: List[Any] = []
        # Validate fields
        for f in fields:
            if not validate_field_name(f):
                raise ValueError(f"Invalid field name: {f}")
        where_clause = build_conditions(conditions, params)
        sql = f"SELECT {', '.join(fields)} FROM {resolve_table_name(table)}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        sql += _render_order_by(order_by)
        sql = _append_pagination(sql, params, limit, offset)
        rows = await db_manager.execute_query(sql, tuple(params))
        return {"success": True, "data": rows, "row_count": len(rows), "message": "OK"}
    except Exception as e:
        return {"success": False, "data": [], "row_count": 0, "message": str(e)}


@tool(args_schema=AggregatedQuery)
async def mysql_aggregated_query_tool(
    table: str,
    fields: List[str],
    aggregation: str,
    group_by: List[str],
    conditions: Dict[str, Any] = {},
    limit: int = 100,
    offset: int = 0,
    order_by: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Aggregate over a table by group_by with count/sum/avg/min/max and optional conditions."""
    try:
        params: List[Any] = []
        for f in fields + group_by:
            if not validate_field_name(f):
                raise ValueError(f"Invalid field name: {f}")
        where_clause = build_conditions(conditions, params)
        agg_field = fields[0]
        select_sql = f"{', '.join(group_by)}, {aggregation}({agg_field}) AS agg_value"
        sql = f"SELECT {select_sql} FROM {resolve_table_name(table)}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        if group_by:
            sql += f" GROUP BY {', '.join(group_by)}"
        sql += _render_order_by(order_by)
        sql = _append_pagination(sql, params, limit, offset)
        rows = await db_manager.execute_query(sql, tuple(params))
        return {"success": True, "data": rows, "row_count": len(rows), "message": "OK"}
    except Exception as e:
        return {"success": False, "data": [], "row_count": 0, "message": str(e)}


def _rewrite_join_field(field: str, table_map: Dict[str, str]) -> str:
    # Convert table.field to resolved table names according to table_map
    if '.' not in field:
        return field
    t, c = field.split('.', 1)
    resolved_t = table_map.get(t, t)
    return f"{resolved_t}.{c}"


@tool(args_schema=JoinQuery)
async def mysql_join_query_tool(
    tables: List[str],
    fields: List[str],
    join_conditions: Dict[str, str],
    join_type: str = "INNER",
    conditions: Dict[str, Any] = {},
    limit: int = 100,
    offset: int = 0,
    order_by: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Join two tables with ON conditions and optional filters; supports limit, offset, order."""
    try:
        if len(tables) != 2:
            raise ValueError("Exactly two tables are required for join_query")
        for f in fields:
            if not validate_field_name(f):
                raise ValueError(f"Invalid field name: {f}")
        # Build table map for suffix resolution
        t1, t2 = tables[0], tables[1]
        rt1, rt2 = resolve_table_name(t1), resolve_table_name(t2)
        table_map = {t1: rt1, t2: rt2}

        # Build JOIN clause
        join_parts: List[str] = [rt1]
        on_conditions: List[str] = []
        for left, right in join_conditions.items():
            if not validate_field_name(left) or not validate_field_name(right):
                raise ValueError("Invalid join condition field names")
            # rewrite according to resolved table names if needed
            left_rw = _rewrite_join_field(left, table_map)
            right_rw = _rewrite_join_field(right, table_map)
            on_conditions.append(f"{left_rw} = {right_rw}")
        join_parts.append(f"{join_type} JOIN {rt2} ON {' AND '.join(on_conditions)}")

        params: List[Any] = []
        where_clause = build_conditions(conditions, params)
        sql = f"SELECT {', '.join(fields)} FROM {' '.join(join_parts)}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        sql += _render_order_by(order_by)
        sql = _append_pagination(sql, params, limit, offset)
        rows = await db_manager.execute_query(sql, tuple(params))
        return {"success": True, "data": rows, "row_count": len(rows), "message": "OK"}
    except Exception as e:
        return {"success": False, "data": [], "row_count": 0, "message": str(e)}


@tool(args_schema=CustomQuery)
async def mysql_custom_query_tool(query_draft: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a custom structured query draft with nested conditions and subqueries."""
    try:
        params: List[Any] = []
        sql = build_query_from_draft(query_draft, params)
        rows = await db_manager.execute_query(sql, tuple(params))
        return {"success": True, "data": rows, "row_count": len(rows), "message": "OK"}
    except Exception as e:
        return {"success": False, "data": [], "row_count": 0, "message": str(e)} 