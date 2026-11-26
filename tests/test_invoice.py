from decimal import Decimal

import pytest

from invoice_calc import invoice_total, line_total, round_money, tax_amount


def test_round_money_half_up():
    assert round_money("1.005") == Decimal("1.01")
    assert round_money("2.675") == Decimal("2.68")


def test_line_total_with_discount():
    assert line_total("10.00", 3, 10) == Decimal("27.00")


def test_line_total_rejects_bad_input():
    with pytest.raises(ValueError):
        line_total(5, -1)
    with pytest.raises(ValueError):
        line_total(5, 1, 150)


def test_tax_amount():
    assert tax_amount("200.00", 18) == Decimal("36.00")


def test_invoice_total():
    lines = [("10.00", 2), ("5.50", 4, 50)]
    assert invoice_total(lines, tax_rate_pct=10) == Decimal("34.10")
