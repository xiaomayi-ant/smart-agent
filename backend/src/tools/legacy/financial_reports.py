"""
Legacy financial report tools (kept silent, not exported in registry)
"""
from typing import Dict, Any
from langchain.tools import tool
from ..database import (
    get_company_facts,
    get_income_statements,
    get_balance_sheets,
    get_cash_flow_statements,
    get_stock_snapshot,
)


@tool
async def get_company_facts_tool(ticker: str) -> Dict[str, Any]:
    try:
        result = await get_company_facts(ticker.upper())
        if result:
            return {"success": True, "data": result, "message": f"Successfully retrieved company facts for {ticker.upper()}"}
        return {"success": False, "data": None, "message": f"No company facts found for ticker {ticker.upper()}"}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e)}


@tool
async def get_income_statements_tool(ticker: str, limit: int = 10) -> Dict[str, Any]:
    try:
        results = await get_income_statements(ticker.upper(), limit)
        return {"success": True, "data": results, "count": len(results), "message": f"Retrieved {len(results)} income statements"}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e)}


@tool
async def get_balance_sheets_tool(ticker: str, limit: int = 10) -> Dict[str, Any]:
    try:
        results = await get_balance_sheets(ticker.upper(), limit)
        return {"success": True, "data": results, "count": len(results), "message": f"Retrieved {len(results)} balance sheets"}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e)}


@tool
async def get_cash_flow_statements_tool(ticker: str, limit: int = 10) -> Dict[str, Any]:
    try:
        results = await get_cash_flow_statements(ticker.upper(), limit)
        return {"success": True, "data": results, "count": len(results), "message": f"Retrieved {len(results)} cash flow statements"}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e)}


@tool
async def get_stock_snapshot_tool(ticker: str) -> Dict[str, Any]:
    try:
        result = await get_stock_snapshot(ticker.upper())
        if result:
            return {"success": True, "data": result, "message": f"Successfully retrieved stock snapshot for {ticker.upper()}"}
        return {"success": False, "data": None, "message": f"No stock snapshot found for ticker {ticker.upper()}"}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e)} 