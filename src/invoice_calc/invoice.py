"""Tiny invoice calculator.

It exists only to give the CI workflow a real (if trivial) test suite to run.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Tuple

_CENT = Decimal("0.01")


def round_money(value) -> Decimal:
    """Round to cents using the commercial (half-up) rule."""
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def line_total(unit_price, quantity, discount_pct=0) -> Decimal:
    """Total of one invoice line after a percentage discount."""
    if quantity < 0:
        raise ValueError("quantity must be >= 0")
    if not 0 <= Decimal(str(discount_pct)) <= 100:
        raise ValueError("discount_pct must be between 0 and 100")
    gross = Decimal(str(unit_price)) * Decimal(str(quantity))
    discount = gross * Decimal(str(discount_pct)) / Decimal(100)
    return round_money(gross - discount)


def tax_amount(base, rate_pct) -> Decimal:
    """Tax over a monetary base."""
    return round_money(Decimal(str(base)) * Decimal(str(rate_pct)) / Decimal(100))


def invoice_total(lines: Iterable[Tuple], tax_rate_pct=0) -> Decimal:
    """Sum of line totals plus tax. Each line is (unit_price, qty[, discount_pct])."""
    subtotal = sum((line_total(*line) for line in lines), Decimal("0"))
    return round_money(subtotal + tax_amount(subtotal, tax_rate_pct))
