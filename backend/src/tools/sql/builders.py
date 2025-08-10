from typing import Dict, List, Optional, Union, Any
import re
from ...core.config import settings
from .types import Condition


DANGEROUS_KEYWORDS = [
    'DROP', 'DELETE', 'UPDATE', 'INSERT', 'CREATE', 'ALTER',
    'TRUNCATE', 'REPLACE', '--', '/*', '*/', 'EXEC', 'EXECUTE',
    'DECLARE', 'SCRIPT'
]


def validate_field_name(field_name: str) -> bool:
    """Validate field name safety. Allow optional table prefix like table.field"""
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?$', field_name))


def resolve_table_name(table_name: str) -> str:
    """Apply optional `_view` suffix policy to table names."""
    try:
        append_suffix = getattr(settings, 'mysql_append_view_suffix', False)
    except Exception:
        append_suffix = False
    if append_suffix:
        return f"{table_name}_view"
    return table_name


def _render_order_by(order_by: Optional[List[Any]]) -> str:
    if not order_by:
        return ""
    parts: List[str] = []
    for item in order_by:
        if isinstance(item, dict):
            field = item.get("field")
            direction = str(item.get("direction") or "ASC").upper()
            if not field or not validate_field_name(field):
                continue
            if direction not in ("ASC", "DESC"):
                direction = "ASC"
            parts.append(f"{field} {direction}")
        else:
            # string
            if isinstance(item, str) and validate_field_name(item):
                parts.append(item)
    return (" ORDER BY " + ", ".join(parts)) if parts else ""


def _append_pagination(sql: str, params: List[Any], limit: int, offset: int) -> str:
    sql += " LIMIT %s"
    params.append(limit)
    if offset:
        sql += " OFFSET %s"
        params.append(offset)
    return sql


_SUBQUERY_OP_MAP = {
    None: "IN",
    "IN": "IN",
    "NOT IN": "NOT IN",
    "=": "=",
    ">": ">",
    "<": "<",
    ">=": ">=",
    "<=": "<=",
    "EXISTS": "EXISTS",
    "NOT EXISTS": "NOT EXISTS",
}


def build_query_from_draft(draft: Dict[str, Any], params: List[Any]) -> str:
    """Build SQL from a draft dict. Only supports safe single-table FROM and optional GROUP/ORDER/LIMIT/OFFSET."""
    # Basic safety
    draft_str_upper = str(draft).upper()
    for kw in DANGEROUS_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', draft_str_upper):
            raise ValueError(f"Dangerous keyword detected: {kw}")

    table = draft.get('from', '')
    if not isinstance(table, str) or not validate_field_name(table):
        raise ValueError(f"Invalid table name: {table}")

    select_fields = draft.get('select', ['*'])
    if not isinstance(select_fields, list) or not select_fields:
        select_fields = ['*']

    # WHERE
    where_params: List[Any] = []
    where_clause = build_conditions(draft.get('conditions', {}), where_params)

    # GROUP BY / Aggregation
    group_by = draft.get('group_by', [])
    aggregation = draft.get('aggregation')
    order_by = draft.get('order_by', [])

    if aggregation and 'fields' in draft and draft['fields']:
        agg_field = draft['fields'][0]
        if group_by:
            select_sql = f"{', '.join(group_by)}, {aggregation}({agg_field}) AS agg_value"
        else:
            select_sql = f"{aggregation}({agg_field}) AS agg_value"
    else:
        select_sql = ', '.join(select_fields)

    sql = f"SELECT {select_sql} FROM {resolve_table_name(table)}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    if group_by:
        sql += f" GROUP BY {', '.join(group_by)}"
    if order_by:
        order_clause = _render_order_by(order_by)
        sql += order_clause

    # LIMIT/OFFSET if provided
    limit = draft.get('limit')
    offset = draft.get('offset') or 0
    if isinstance(limit, int) and limit > 0:
        sql = _append_pagination(sql, where_params, limit, int(offset))

    # Append collected params
    params.extend(where_params)
    return sql


def build_conditions(conditions: Dict[str, Union[Condition, str, Dict[str, Any]]], params: List[Any]) -> str:
    """Build WHERE clause with support for Condition and nested subqueries."""
    if not conditions:
        return ""
    where_clauses: List[str] = []

    for field, cond in conditions.items():
        if not validate_field_name(field):
            raise ValueError(f"Invalid field name: {field}")

        # Normalize to Condition
        condition_obj: Optional[Condition] = None
        if isinstance(cond, Condition):
            condition_obj = cond
        elif isinstance(cond, dict):
            condition_obj = Condition(**cond)
        elif isinstance(cond, str):
            # equality shortcut
            where_clauses.append(f"{field} = %s")
            params.append(cond)
            continue
        else:
            continue

        if condition_obj.eq is not None:
            where_clauses.append(f"{field} = %s")
            params.append(condition_obj.eq)
        if condition_obj.gte is not None:
            where_clauses.append(f"{field} >= %s")
            params.append(condition_obj.gte)
        if condition_obj.lte is not None:
            where_clauses.append(f"{field} <= %s")
            params.append(condition_obj.lte)
        if condition_obj.gt is not None:
            where_clauses.append(f"{field} > %s")
            params.append(condition_obj.gt)
        if condition_obj.lt is not None:
            where_clauses.append(f"{field} < %s")
            params.append(condition_obj.lt)
        if condition_obj.like is not None:
            where_clauses.append(f"{field} LIKE %s")
            params.append(condition_obj.like)
        if condition_obj.regexp is not None:
            where_clauses.append(f"{field} REGEXP %s")
            params.append(condition_obj.regexp)
        if condition_obj.subquery is not None:
            sub_params: List[Any] = []
            sub_sql = build_query_from_draft(condition_obj.subquery, sub_params)
            op = _SUBQUERY_OP_MAP.get((condition_obj.subquery_op or '').upper(), None)
            if op is None:
                op = "IN"
            if op in ("EXISTS", "NOT EXISTS"):
                where_clauses.append(f"{op} ({sub_sql})")
            elif op in ("=", ">", "<", ">=", "<=", "IN", "NOT IN"):
                where_clauses.append(f"{field} {op} ({sub_sql})")
            else:
                where_clauses.append(f"{field} IN ({sub_sql})")
            params.extend(sub_params)

    return " AND ".join(where_clauses) 