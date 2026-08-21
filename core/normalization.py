import re
from datetime import datetime
from typing import Optional
from dateutil import parser

class Normalizer:
    @staticmethod
    def normalize_name(name: str) -> Optional[str]:
        if not name:
            return None
        # Remove punctuation
        name = re.sub(r'[^\w\s]', '', name)
        # Handle 'Last, First' if passed as a single string
        return name.strip().lower()

    @staticmethod
    def normalize_tier(tier: str, mapping: dict) -> str:
        if not tier:
            return "UNKNOWN"
        normalized = tier.strip().upper()
        return mapping.get(normalized, "UNKNOWN / REVIEW")

    @staticmethod
    def normalize_plan(plan_name: str, rules: list) -> str:
        if not plan_name:
            return "UNKNOWN"
        plan_lower = plan_name.lower()
        for category, keywords in rules:
            if any(keyword in plan_lower for keyword in keywords):
                return category
        return "UNKNOWN"

    @staticmethod
    def normalize_date(date_str: str) -> Optional[str]:
        if not date_str:
            return None
        try:
            parsed_date = parser.parse(date_str)
            return parsed_date.strftime("%Y-%m-%d")
        except:
            return None

    @staticmethod
    def compare_periods(start1: str, end1: str, start2: str, end2: str) -> str:
        if not (start1 and start2):
            return "UNKNOWN"
        if start1 == start2 and end1 == end2:
            return "EXACT"
        try:
            s1 = datetime.strptime(start1, "%Y-%m-%d")
            s2 = datetime.strptime(start2, "%Y-%m-%d")
            e1 = datetime.strptime(end1, "%Y-%m-%d") if end1 else datetime.max
            e2 = datetime.strptime(end2, "%Y-%m-%d") if end2 else datetime.max
            if max(s1, s2) <= min(e1, e2):
                return "OVERLAPPING"
            else:
                return "NON_OVERLAPPING"
        except:
            return "UNKNOWN"
