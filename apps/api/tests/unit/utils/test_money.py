"""A provider amount is minor units in its own currency, divided by that currency's exponent."""

from decimal import Decimal

import pytest

from app.utils.money import currency_exponent, format_money, to_major_units


@pytest.mark.parametrize(
    ("amount_minor", "currency", "rendered"),
    [
        (3000, "USD", "30.00 USD"),
        (59244, "zar", "592.44 ZAR"),
        (0, "INR", "0.00 INR"),
        (1000, "JPY", "1000 JPY"),
        (1500, "KWD", "1.500 KWD"),
        (12345, "CLF", "1.2345 CLF"),
    ],
)
def test_format_money_divides_by_the_currencys_own_exponent(
    amount_minor: int, currency: str, rendered: str
) -> None:
    assert format_money(amount_minor, currency) == rendered


def test_major_units_are_exact() -> None:
    assert to_major_units(57284, "ZAR") == Decimal("572.84")


def test_currency_code_case_does_not_change_the_exponent() -> None:
    assert currency_exponent("jpy") == currency_exponent("JPY") == 0
