"""One reading of a provider amount: minor units plus the currency they are in."""

from decimal import Decimal

from app.constants.payments import ISO_4217_DEFAULT_EXPONENT, ISO_4217_EXPONENTS


def currency_exponent(currency: str) -> int:
    """Digits after the decimal point in the currency's major unit (ISO 4217)."""
    return ISO_4217_EXPONENTS.get(currency.upper(), ISO_4217_DEFAULT_EXPONENT)


def to_major_units(amount_minor: int, currency: str) -> Decimal:
    """Convert a minor-unit amount to the currency's major unit, exactly."""
    return Decimal(amount_minor).scaleb(-currency_exponent(currency))


def format_money(amount_minor: int, currency: str) -> str:
    """Render a minor-unit amount as its major units and code, e.g. 30.00 USD."""
    return f"{to_major_units(amount_minor, currency):.{currency_exponent(currency)}f} {currency.upper()}"
