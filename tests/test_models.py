"""Prüfe Datentypen, unveränderte Ursprungswerte und optionale Herkunft."""

from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from research_update_assistant.models import FinancialPeriod, SourceMetadata


def test_optional_values_default_to_none() -> None:
    period = FinancialPeriod(
        company_name="Synthetic Industrial AG", period_label="FY2025",
        period_end=date(2025, 12, 31), period_months=12, currency="CHF", scale="million",
    )
    for name in (
        "revenue", "ebitda", "adjusted_ebitda", "ebit", "adjusted_ebit", "net_income",
        "operating_cash_flow", "capex", "reported_free_cash_flow", "cash",
        "current_financial_debt", "noncurrent_financial_debt", "gross_debt",
        "reported_net_debt", "inventory", "receivables", "payables", "total_assets", "equity",
        "basic_eps", "diluted_eps",
        "source",
    ):
        assert getattr(period, name) is None


def test_period_values_are_immutable(periods) -> None:
    with pytest.raises(FrozenInstanceError):
        periods["FY2024"].ebit = 485


def test_source_metadata_can_describe_comparatives_and_unicode(periods) -> None:
    source = SourceMetadata(
        source_document="Geschäftsbericht_2025.pdf", source_document_period="FY2025",
        reported_as_comparative=True, source_page=12,
        source_label="Geschäftstätigkeit – CHF ’000", restated=True, user_confirmed=False,
    )
    period = replace(periods["FY2024"], source=source)
    assert period.period_label == "FY2024"
    assert period.source.source_document_period == "FY2025"
    assert "’" in period.source.source_label
    assert period.source.reported_as_comparative is True
    assert SourceMetadata().restated is None


@pytest.mark.parametrize("months", [0, -6, 6.5, True])
def test_period_months_must_be_a_positive_integer(periods, months) -> None:
    with pytest.raises(ValueError, match="period_months"):
        replace(periods["FY2024"], period_months=months)


@pytest.mark.parametrize("field_name", ["company_name", "period_label", "currency", "scale"])
def test_metadata_cannot_be_blank(periods, field_name) -> None:
    with pytest.raises(ValueError, match=field_name):
        replace(periods["FY2024"], **{field_name: " "})


def test_period_end_uses_a_real_date(periods) -> None:
    with pytest.raises(TypeError, match="datetime.date"):
        replace(periods["FY2024"], period_end="2024-12-31")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "1000", True])
def test_invalid_financial_values_rejected(periods, value) -> None:
    with pytest.raises(ValueError, match="revenue"):
        replace(periods["FY2024"], revenue=value)


def test_negative_financial_values_are_not_clamped(periods) -> None:
    period = replace(periods["FY2024"], net_income=-25, capex=-60, reported_net_debt=-10)
    assert period.net_income == -25
    assert period.capex == -60
    assert period.reported_net_debt == -10
