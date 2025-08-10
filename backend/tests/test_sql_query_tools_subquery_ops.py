from typing import Any, Dict, List
from src.tools.sql.builders import build_query_from_draft


def _make_subquery(op: str) -> Dict[str, Any]:
    return {
        "select": ["id"],
        "from": "orders",
        "conditions": {"status": {"eq": "done"}},
        "limit": 10,
    }


def test_subquery_op_in():
    params: List[Any] = []
    draft = {
        "select": ["id", "name"],
        "from": "users",
        "conditions": {
            "id": {
                "subquery_op": "IN",
                "subquery": _make_subquery("IN"),
            }
        },
        "limit": 5,
    }
    sql = build_query_from_draft(draft, params)
    assert "id IN (SELECT" in sql


def test_subquery_op_not_in():
    params: List[Any] = []
    draft = {
        "select": ["id"],
        "from": "users",
        "conditions": {
            "id": {
                "subquery_op": "NOT IN",
                "subquery": _make_subquery("NOT IN"),
            }
        },
        "limit": 5,
    }
    sql = build_query_from_draft(draft, params)
    assert "id NOT IN (SELECT" in sql


def test_subquery_op_exists():
    params: List[Any] = []
    draft = {
        "select": ["id"],
        "from": "users",
        "conditions": {
            "any": {
                "subquery_op": "EXISTS",
                "subquery": _make_subquery("EXISTS"),
            }
        },
        "limit": 5,
    }
    sql = build_query_from_draft(draft, params)
    assert "EXISTS (SELECT" in sql


def test_subquery_op_not_exists():
    params: List[Any] = []
    draft = {
        "select": ["id"],
        "from": "users",
        "conditions": {
            "any": {
                "subquery_op": "NOT EXISTS",
                "subquery": _make_subquery("NOT EXISTS"),
            }
        },
        "limit": 5,
    }
    sql = build_query_from_draft(draft, params)
    assert "NOT EXISTS (SELECT" in sql


def test_subquery_op_comparison():
    params: List[Any] = []
    draft = {
        "select": ["id"],
        "from": "products",
        "conditions": {
            "price": {
                "subquery_op": ">",
                "subquery": {
                    "select": ["AVG(price)"],
                    "from": "products",
                    "limit": 1,
                },
            }
        },
        "limit": 5,
    }
    sql = build_query_from_draft(draft, params)
    assert "price > (SELECT" in sql 