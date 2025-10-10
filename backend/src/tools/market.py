import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from langchain.tools import tool
from .database import (
    get_company_facts,
    get_income_statements
)


@tool
async def get_company_facts_tool(ticker: str) -> Dict[str, Any]:
    """Get company facts and basic information by ticker symbol"""
    try:
        result = await get_company_facts(ticker.upper())
        if result:
            return {
                "success": True,
                "data": result,
                "message": f"Successfully retrieved company facts for {ticker.upper()}"
            }
        else:
            return {
                "success": False,
                "data": None,
                "message": f"No company facts found for ticker {ticker.upper()}"
            }
    except Exception as e:
        return {
            "success": False,
            "data": None,
            "message": f"Error retrieving company facts: {str(e)}"
        }


@tool
async def get_income_statements_tool(ticker: str, limit: int = 10) -> Dict[str, Any]:
    """Get income statements for a company by ticker symbol"""
    try:
        results = await get_income_statements(ticker.upper(), limit)
        return {
            "success": True,
            "data": results,
            "count": len(results),
            "message": f"Successfully retrieved {len(results)} income statements for {ticker.upper()}"
        }
    except Exception as e:
        return {
            "success": False,
            "data": None,
            "message": f"Error retrieving income statements: {str(e)}"
        }

