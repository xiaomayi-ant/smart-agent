from typing import Dict, Any, List
from datetime import datetime, timedelta
from langchain.tools import tool


class DateCalculator:
    """Date calculation utilities"""

    @staticmethod
    def weekday_to_index(weekday: str) -> int:
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
        try:
            if base_date.lower() == "today":
                current_date = datetime.now()
            elif base_date.lower() == "yesterday":
                current_date = datetime.now() - timedelta(days=1)
            else:
                current_date = datetime.strptime(base_date, "%Y-%m-%d")

            for op in operations:
                op_type = str(op.get("type", "")).lower()
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
                    current_date += timedelta(days=value * 30)
                elif op_type == "subtract_months":
                    current_date -= timedelta(days=value * 30)
                elif op_type == "add_years":
                    current_date += timedelta(days=value * 365)
                elif op_type == "subtract_years":
                    current_date -= timedelta(days=value * 365)
                elif op_type == "end_of_month":
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
        except Exception:
            return base_date


@tool
async def date_calculator_tool(base_date: str, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate a target date from base_date using a list of operations (add/subtract days/weeks/months/years, start/end of month, next/previous weekday)."""
    try:
        result = DateCalculator.calculate_date_operations(base_date, operations)
        return {
            "success": True,
            "data": {"calculated_date": result},
            "message": f"Successfully calculated date: {result}"
        }
    except Exception as e:
        return {"success": False, "data": None, "message": str(e)} 