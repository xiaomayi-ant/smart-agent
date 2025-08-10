"""
Main tools for the financial expert
"""
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from langchain.tools import tool
from .database import (
    get_company_facts,
    get_income_statements,
    get_balance_sheets,
    get_cash_flow_statements,
    get_stock_snapshot
)
from .vector_search import hybrid_milvus_search


@tool
async def get_company_facts_tool(ticker: str) -> Dict[str, Any]:
    """Get company facts and basic information by ticker symbol"""
    try:
        print(f"[Tool] Getting company facts for ticker: {ticker}")
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
        print(f"[Tool] Error getting company facts: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Error retrieving company facts: {str(e)}"
        }


@tool
async def get_income_statements_tool(ticker: str, limit: int = 10) -> Dict[str, Any]:
    """Get income statements for a company by ticker symbol"""
    try:
        print(f"[Tool] Getting income statements for ticker: {ticker}, limit: {limit}")
        results = await get_income_statements(ticker.upper(), limit)
        return {
            "success": True,
            "data": results,
            "count": len(results),
            "message": f"Successfully retrieved {len(results)} income statements for {ticker.upper()}"
        }
    except Exception as e:
        print(f"[Tool] Error getting income statements: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Error retrieving income statements: {str(e)}"
        }


@tool
async def get_balance_sheets_tool(ticker: str, limit: int = 10) -> Dict[str, Any]:
    """Get balance sheets for a company by ticker symbol"""
    try:
        print(f"[Tool] Getting balance sheets for ticker: {ticker}, limit: {limit}")
        results = await get_balance_sheets(ticker.upper(), limit)
        return {
            "success": True,
            "data": results,
            "count": len(results),
            "message": f"Successfully retrieved {len(results)} balance sheets for {ticker.upper()}"
        }
    except Exception as e:
        print(f"[Tool] Error getting balance sheets: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Error retrieving balance sheets: {str(e)}"
        }


@tool
async def get_cash_flow_statements_tool(ticker: str, limit: int = 10) -> Dict[str, Any]:
    """Get cash flow statements for a company by ticker symbol"""
    try:
        print(f"[Tool] Getting cash flow statements for ticker: {ticker}, limit: {limit}")
        results = await get_cash_flow_statements(ticker.upper(), limit)
        return {
            "success": True,
            "data": results,
            "count": len(results),
            "message": f"Successfully retrieved {len(results)} cash flow statements for {ticker.upper()}"
        }
    except Exception as e:
        print(f"[Tool] Error getting cash flow statements: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Error retrieving cash flow statements: {str(e)}"
        }


@tool
async def get_stock_snapshot_tool(ticker: str) -> Dict[str, Any]:
    """Get current stock price and market data by ticker symbol"""
    try:
        print(f"[Tool] Getting stock snapshot for ticker: {ticker}")
        result = await get_stock_snapshot(ticker.upper())
        if result:
            return {
                "success": True,
                "data": result,
                "message": f"Successfully retrieved stock snapshot for {ticker.upper()}"
            }
        else:
            return {
                "success": False,
                "data": None,
                "message": f"No stock snapshot found for ticker {ticker.upper()}"
            }
    except Exception as e:
        print(f"[Tool] Error getting stock snapshot: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Error retrieving stock snapshot: {str(e)}"
        }


@tool
async def hybrid_milvus_search_tool(query: str = None, publish_time: str = None, limit: int = 3) -> Dict[str, Any]:
    """Search for financial news and documents using hybrid vector and metadata search"""
    try:
        print(f"[Tool] Hybrid search - query: {query}, publish_time: {publish_time}, limit: {limit}")
        results = await hybrid_milvus_search(query, publish_time, limit)
        return {
            "success": True,
            "data": results,
            "count": len(results),
            "message": f"Successfully found {len(results)} relevant documents"
        }
    except Exception as e:
        print(f"[Tool] Error in hybrid search: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Error in search: {str(e)}"
        }


class DateCalculator:
    """Date calculation utilities"""
    
    @staticmethod
    def weekday_to_index(weekday: str) -> int:
        """Convert weekday name to index (0=Monday, 6=Sunday)"""
        weekdays = {
            "monday": 0, "mon": 0,
            "tuesday": 1, "tue": 1,
            "wednesday": 2, "wed": 2,
            "thursday": 3, "thu": 3,
            "friday": 4, "fri": 4,
            "saturday": 5, "sat": 5,
            "sunday": 6, "sun": 6
        }
        return weekdays.get(weekday.lower(), 0)
    
    @staticmethod
    def calculate_date_operations(base_date: str, operations: List[Dict[str, Any]]) -> str:
        """Calculate date based on operations"""
        try:
            # Parse base date
            if base_date.lower() == "today":
                current_date = datetime.now()
            elif base_date.lower() == "yesterday":
                current_date = datetime.now() - timedelta(days=1)
            else:
                current_date = datetime.strptime(base_date, "%Y-%m-%d")
            
            # Apply operations
            for op in operations:
                op_type = op.get("type", "").lower()
                value = op.get("value", 0)
                
                if op_type == "add_days":
                    current_date += timedelta(days=value)
                elif op_type == "subtract_days":
                    current_date -= timedelta(days=value)
                elif op_type == "add_weeks":
                    current_date += timedelta(weeks=value)
                elif op_type == "subtract_weeks":
                    current_date -= timedelta(weeks=value)
                elif op_type == "add_months":
                    # Simple month addition (approximate)
                    current_date += timedelta(days=value * 30)
                elif op_type == "subtract_months":
                    current_date -= timedelta(days=value * 30)
                elif op_type == "add_years":
                    current_date += timedelta(days=value * 365)
                elif op_type == "subtract_years":
                    current_date -= timedelta(days=value * 365)
                elif op_type == "end_of_month":
                    # Move to end of current month
                    if current_date.month == 12:
                        current_date = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(days=1)
                    else:
                        current_date = current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)
                elif op_type == "start_of_month":
                    current_date = current_date.replace(day=1)
                elif op_type == "next_weekday":
                    weekday_index = DateCalculator.weekday_to_index(str(value))
                    days_ahead = weekday_index - current_date.weekday()
                    if days_ahead <= 0:
                        days_ahead += 7
                    current_date += timedelta(days=days_ahead)
                elif op_type == "previous_weekday":
                    weekday_index = DateCalculator.weekday_to_index(str(value))
                    days_behind = current_date.weekday() - weekday_index
                    if days_behind <= 0:
                        days_behind += 7
                    current_date -= timedelta(days=days_behind)
            
            return current_date.strftime("%Y-%m-%d")
            
        except Exception as e:
            print(f"[DateCalculator] Error calculating date: {e}")
            return base_date


@tool
async def date_calculator_tool(base_date: str, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate dates based on various operations"""
    try:
        print(f"[Tool] Date calculation - base_date: {base_date}, operations: {operations}")
        result = DateCalculator.calculate_date_operations(base_date, operations)
        return {
            "success": True,
            "data": {"calculated_date": result},
            "message": f"Successfully calculated date: {result}"
        }
    except Exception as e:
        print(f"[Tool] Error in date calculation: {e}")
        return {
            "success": False,
            "data": None,
            "message": f"Error in date calculation: {str(e)}"
        }


# Export all tools
ALL_TOOLS_LIST = [
    get_company_facts_tool,
    get_income_statements_tool,
    get_balance_sheets_tool,
    get_cash_flow_statements_tool,
    get_stock_snapshot_tool,
    hybrid_milvus_search_tool,
    date_calculator_tool
] 