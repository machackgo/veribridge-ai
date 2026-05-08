"""Market data provider abstraction for Opportunity & Salary Heatmap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MarketLocation:
    location_name: str
    country: str
    estimated_open_roles: int
    salary_min: int
    salary_max: int
    currency: str
    competition_level: str
    remote_availability: str
    field_strengths: tuple[str, ...]


class MarketDataProvider(Protocol):
    """Provider interface for future Adzuna, JSearch, and BLS adapters."""

    name: str

    def get_location_market_data(
        self,
        career_fields: list[str],
        target_roles: list[str],
        target_locations: list[str],
    ) -> list[MarketLocation]:
        """Return normalized market signals for the requested profile."""


class MockMarketDataProvider:
    """Static global market dataset for local MVP development."""

    name = "mock"

    _locations = (
        MarketLocation("California, USA", "USA", 18400, 95000, 154000, "USD", "High", "High", ("Technology & Software", "AI & Data", "Healthcare & Life Sciences", "Design & Architecture")),
        MarketLocation("Massachusetts, USA", "USA", 8300, 78000, 128000, "USD", "Medium", "Medium", ("Healthcare & Life Sciences", "Research / Academia", "Robotics & Manufacturing", "Education")),
        MarketLocation("New York, USA", "USA", 12100, 82000, 142000, "USD", "High", "High", ("Finance & Accounting", "Business & Management", "Marketing & Communications", "Media / Journalism", "Law & Policy")),
        MarketLocation("Toronto, Canada", "Canada", 7600, 72000, 118000, "CAD", "Medium", "High", ("Technology & Software", "Business & Management", "Finance & Accounting", "Design & Architecture")),
        MarketLocation("London, UK", "UK", 9400, 52000, 93000, "GBP", "High", "Medium", ("Finance & Accounting", "Law & Policy", "Marketing & Communications", "Research / Academia")),
        MarketLocation("Dubai, UAE", "UAE", 4100, 210000, 360000, "AED", "Medium", "Medium", ("Business & Management", "Supply Chain & Operations", "Entrepreneurship", "Design & Architecture")),
        MarketLocation("Hyderabad, India", "India", 11800, 900000, 2400000, "INR", "Medium", "Medium", ("Technology & Software", "AI & Data", "Robotics & Manufacturing", "Supply Chain & Operations")),
        MarketLocation("Sydney, Australia", "Australia", 5300, 76000, 126000, "AUD", "Medium", "High", ("Healthcare & Life Sciences", "Environmental Science", "Education", "Engineering")),
        MarketLocation("Remote worldwide", "Global", 15200, 65000, 132000, "USD", "Medium", "High", ("Technology & Software", "AI & Data", "Marketing & Communications", "Education", "Design & Architecture", "Business & Management")),
    )

    def get_location_market_data(
        self,
        career_fields: list[str],
        target_roles: list[str],
        target_locations: list[str],
    ) -> list[MarketLocation]:
        return list(self._locations)


"""
Future provider plan:
- Adzuna: job ads, regional vacancy data, and salary estimates.
- JSearch/RapidAPI: live job postings and salary fields where available.
- BLS: US wage data by occupation, metro, state, and national wage percentiles.
"""
