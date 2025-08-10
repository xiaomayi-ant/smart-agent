import re
from typing import Any, Dict, List

# Import only the pure builder and type modules to avoid optional dependencies
from src.tools.sql.builders import (
    build_conditions,
    build_query_from_draft,
    validate_field_name,
    _render_order_by,
    _append_pagination,
    resolve_table_name,
)
from src.tools.sql.types import Condition


def test_validate_field_name():
    assert validate_field_name("table")
    assert validate_field_name("table.column")
    assert not validate_field_name("table;DROP")
    assert not validate_field_name("table.column;")


def test_build_conditions_basic_ops():
    params: List[Any] = []
    conds: Dict[str, Any] = {
        "age": Condition(gte=18, lt=65).model_dump(),
        "name": Condition(like="%apple%").model_dump(),
        "status": "active",
    }
    where_sql = build_conditions(conds, params)
    # Order depends on insertion order of the dict
    assert where_sql == "age >= %s AND age < %s AND name LIKE %s AND status = %s"
    assert params == [18, 65, "%apple%", "active"]


def test_build_conditions_with_regexp_and_eq():
    params: List[Any] = []
    conds: Dict[str, Any] = {
        "email": Condition(regexp=r".*@example\.com$").model_dump(),
        "role": Condition(eq="admin").model_dump(),
    }
    where_sql = build_conditions(conds, params)
    assert where_sql == "email REGEXP %s AND role = %s"
    assert params == [r".*@example\.com$", "admin"]


def test_build_query_from_draft_with_subquery_and_op():
    params: List[Any] = []
    draft = {
        "select": ["id", "name", "price"],
        "from": "products",
        "conditions": {
            "price": {
                "subquery_op": "=",
                "subquery": {
                    "select": ["AVG(price)"],
                    "from": "products",
                    "conditions": {"name": {"like": "%apple%"}},
                    "limit": 10,
                },
            }
        },
        "order_by": [{"field": "price", "direction": "DESC"}],
        "limit": 50,
        "offset": 5,
    }
    sql = build_query_from_draft(draft, params)
    # Basic structure checks
    assert sql.startswith("SELECT id, name, price FROM products")
    assert "WHERE price = (SELECT" in sql
    assert "FROM products" in sql
    assert "ORDER BY price DESC" in sql
    assert sql.endswith("LIMIT %s OFFSET %s")
    # Params include subquery's params first (like) then main limit and offset appended by builder
    assert params[0] == "%apple%"
    assert params[-2:] == [50, 5]


def test_render_order_by_and_pagination_helpers():
    order_clause = _render_order_by([{"field": "created_at", "direction": "desc"}, {"field": "score", "direction": "DESC"}])
    assert order_clause.strip().lower() == "order by created_at desc, score desc"

    sql = "SELECT * FROM t"
    p: List[Any] = []
    sql2 = _append_pagination(sql, p, 20, 10)
    assert sql2.endswith("LIMIT %s OFFSET %s")
    assert p == [20, 10] 