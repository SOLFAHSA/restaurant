"""Tests for Restaurant Cash Denomination master catalog."""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant.cash_count import _get_default_denominations
from restaurant.setup import ensure_cash_denominations


class TestRestaurantCashDenomination(FrappeTestCase):
    def test_seeded_denominations_loaded_from_db(self):
        ensure_cash_denominations()
        rows = _get_default_denominations("HNL")
        self.assertGreaterEqual(len(rows), 9)
        self.assertEqual(rows[0]["unit_value"], 500.0)
        self.assertEqual(rows[0]["denomination_label"], "Billetes L 500")

    def test_unit_value_must_be_positive(self):
        doc = frappe.get_doc({
            "doctype": "Restaurant Cash Denomination",
            "denomination_label": "Billete Inválido Test",
            "currency": "HNL",
            "denomination_type": "Billete",
            "unit_value": 0,
            "enabled": 1,
        })
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
