# Copyright (c) 2026, Grintsys and Contributors
# See license.txt

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestRestaurantCashCount(FrappeTestCase):
    """Tests for server-side cash count calculation, movements, and shift closing."""

    def _build_mock_snapshot(self):
        return {
            "pos_opening_shift": "POSA-OS-TEST-0001",
            "shift_status": "Open",
            "pos_profile": "POS Test",
            "company": "_Test Company",
            "currency": "HNL",
            "hide_expected_amount": 0,
            "cash_mode_of_payment": "Efectivo",
            "cashier": "Administrator",
            "cashier_name": "Administrator",
            "period_start_date": "2026-11-11 08:00:00",
            "invoice_count": 3,
            "total_sales": 1200.0,
            "total_income": 300.0,
            "total_expense": 150.0,
            "net_cash_movement": 150.0,
            "total_expected": 1850.0,
            "denominations": [
                {
                    "denomination_type": "Billete",
                    "unit_value": 500.0,
                    "denomination_label": "Billetes L 500",
                    "quantity": 0,
                    "subtotal": 0.0,
                },
                {
                    "denomination_type": "Billete",
                    "unit_value": 100.0,
                    "denomination_label": "Billetes L 100",
                    "quantity": 0,
                    "subtotal": 0.0,
                },
                {
                    "denomination_type": "Moneda",
                    "unit_value": 0.50,
                    "denomination_label": "Monedas L 0.50",
                    "quantity": 0,
                    "subtotal": 0.0,
                },
            ],
            "payment_methods": [
                {
                    "mode_of_payment": "Efectivo",
                    "is_cash": 1,
                    "detail_kind": "cash",
                    "opening_amount": 500.0,
                    "sales_amount": 700.0,
                    "income_amount": 300.0,
                    "expense_amount": 150.0,
                    "expected_amount": 1350.0,
                    "counted_amount": 0.0,
                    "difference": -1350.0,
                    "reference_note": "",
                },
                {
                    "mode_of_payment": "Tarjeta",
                    "is_cash": 0,
                    "detail_kind": "card",
                    "opening_amount": 0.0,
                    "sales_amount": 350.0,
                    "income_amount": 0.0,
                    "expense_amount": 0.0,
                    "expected_amount": 350.0,
                    "counted_amount": 0.0,
                    "difference": -350.0,
                    "reference_note": "",
                },
                {
                    "mode_of_payment": "Transferencia Bancaria",
                    "is_cash": 0,
                    "detail_kind": "transfer",
                    "opening_amount": 0.0,
                    "sales_amount": 150.0,
                    "income_amount": 0.0,
                    "expense_amount": 0.0,
                    "expected_amount": 150.0,
                    "counted_amount": 0.0,
                    "difference": -150.0,
                    "reference_note": "",
                },
            ],
            "movements": [
                {
                    "name": "MOV-001",
                    "type_transaction": "Ingreso",
                    "amount": 300.0,
                    "note": "Cambio adicional de gerencia",
                    "posting_date": "2026-11-11",
                },
                {
                    "name": "MOV-002",
                    "type_transaction": "Retiro",
                    "amount": 150.0,
                    "note": "Compra de hielo",
                    "posting_date": "2026-11-11",
                },
            ],
            "recent_counts": [],
        }

    def test_recalculate_balanced_count_ignores_tampered_totals(self):
        from restaurant.cash_count import DEFAULT_HNL_DENOMINATIONS, recalculate_cash_count_doc

        self.assertTrue(all(d[0] == "Billete" for d in DEFAULT_HNL_DENOMINATIONS))

        doc = frappe.new_doc("Restaurant Cash Count")
        doc.count_type = "Arqueo Parcial"
        doc.pos_opening_shift = "POSA-OS-TEST-0001"
        doc.total_difference = 99999.0  # Tampered client value must be overwritten.

        doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 500.0,
            "denomination_label": "Billetes L 500",
            "quantity": 2,
            "subtotal": 1.0,  # Tampered subtotal must be recalculated.
        })
        doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 100.0,
            "denomination_label": "Billetes L 100",
            "quantity": 3,
        })
        doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 50.0,
            "denomination_label": "Billetes L 50",
            "quantity": 1,
        })
        doc.append("payment_methods", {
            "mode_of_payment": "Efectivo",
            "counted_amount": 10.0,  # Must be overwritten by cash_counted_total (1350).
        })
        doc.append("payment_methods", {
            "mode_of_payment": "Tarjeta",
            "counted_amount": 350.0,
            "reference_note": "Lote BAC #441",
        })
        doc.append("payment_methods", {
            "mode_of_payment": "Transferencia Bancaria",
            "counted_amount": 150.0,
            "reference_note": "1 transferencia",
        })

        with patch("restaurant.cash_count.build_cash_count_snapshot", return_value=self._build_mock_snapshot()):
            recalculate_cash_count_doc(doc, use_denomination_cash_total=True)

        self.assertEqual(doc.cash_bills_total, 1350.0)
        self.assertEqual(doc.cash_coins_total, 0.0)
        self.assertEqual(doc.cash_counted_total, 1350.0)
        self.assertEqual(doc.total_expected, 1850.0)
        self.assertEqual(doc.total_counted, 1850.0)
        self.assertEqual(doc.total_difference, 0.0)
        self.assertEqual(doc.status, "Cuadrado")
        self.assertEqual(len(doc.cash_movements), 2)
        self.assertEqual(doc.cash_movements[1].note, "Compra de hielo")

    def test_recalculate_shortage_and_surplus_statuses(self):
        from restaurant.cash_count import recalculate_cash_count_doc

        snapshot = self._build_mock_snapshot()

        # Shortage (-100 HNL on Efectivo)
        shortage_doc = frappe.new_doc("Restaurant Cash Count")
        shortage_doc.pos_opening_shift = "POSA-OS-TEST-0001"
        shortage_doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 500.0,
            "denomination_label": "Billetes L 500",
            "quantity": 2,
        })
        shortage_doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 100.0,
            "denomination_label": "Billetes L 100",
            "quantity": 2.5 if False else 2,
        })
        shortage_doc.append("payment_methods", {"mode_of_payment": "Tarjeta", "counted_amount": 350.0})
        shortage_doc.append("payment_methods", {"mode_of_payment": "Transferencia Bancaria", "counted_amount": 150.0})

        with patch("restaurant.cash_count.build_cash_count_snapshot", return_value=snapshot):
            recalculate_cash_count_doc(shortage_doc, use_denomination_cash_total=True)

        self.assertEqual(shortage_doc.cash_counted_total, 1200.0)
        self.assertEqual(shortage_doc.total_difference, -150.0)
        self.assertEqual(shortage_doc.status, "Faltante")

        # Surplus (+200 HNL on Efectivo)
        surplus_doc = frappe.new_doc("Restaurant Cash Count")
        surplus_doc.pos_opening_shift = "POSA-OS-TEST-0001"
        surplus_doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 500.0,
            "denomination_label": "Billetes L 500",
            "quantity": 3,
        })
        surplus_doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 100.0,
            "denomination_label": "Billetes L 100",
            "quantity": 1,
        })
        surplus_doc.append("payment_methods", {"mode_of_payment": "Tarjeta", "counted_amount": 350.0})
        surplus_doc.append("payment_methods", {"mode_of_payment": "Transferencia Bancaria", "counted_amount": 150.0})

        with patch("restaurant.cash_count.build_cash_count_snapshot", return_value=snapshot):
            recalculate_cash_count_doc(surplus_doc, use_denomination_cash_total=True)

        self.assertEqual(surplus_doc.cash_counted_total, 1600.0)
        self.assertEqual(surplus_doc.total_difference, 250.0)
        self.assertEqual(surplus_doc.status, "Sobrante")

    def test_close_linked_pos_shift_passes_counted_amounts(self):
        from restaurant.cash_count import close_linked_pos_shift_from_count

        doc = frappe.new_doc("Restaurant Cash Count")
        doc.pos_opening_shift = "POSA-OS-TEST-0001"
        doc.append("payment_methods", {"mode_of_payment": "Efectivo", "counted_amount": 1350.0})
        doc.append("payment_methods", {"mode_of_payment": "Tarjeta", "counted_amount": 350.0})

        with patch(
            "restaurant.cash_count.close_pos_shift",
            return_value={"closed": True, "pos_closing_shift": "POSA-CS-TEST-0001"},
        ) as mocked_close:
            res = close_linked_pos_shift_from_count(doc)

        self.assertEqual(res["pos_closing_shift"], "POSA-CS-TEST-0001")
        mocked_close.assert_called_once_with(
            "POSA-OS-TEST-0001",
            closing_amounts=[
                {"mode_of_payment": "Efectivo", "closing_amount": 1350.0},
                {"mode_of_payment": "Tarjeta", "closing_amount": 350.0},
            ],
        )

    def test_on_cancel_blocks_when_pos_closing_shift_still_submitted(self):
        doc = frappe.new_doc("Restaurant Cash Count")
        doc.pos_closing_shift = "POSA-CS-TEST-0001"

        with (
            patch("frappe.db.exists", return_value=True),
            patch("frappe.db.get_value", return_value=1),
        ):
            with self.assertRaises(frappe.ValidationError):
                doc.on_cancel()

    def test_doctypes_and_print_formats_exist_and_render(self):
        from restaurant.cash_count import PRINT_FORMAT_LETTER, PRINT_FORMAT_TICKET

        for doctype_name in (
            "Restaurant Cash Count",
            "Restaurant Cash Count Denomination",
            "Restaurant Cash Count Method",
            "Restaurant Cash Count Payment Detail",
            "Restaurant Cash Count Movement",
        ):
            self.assertTrue(
                frappe.db.exists("DocType", doctype_name),
                f"Missing DocType {doctype_name}",
            )

        doc = frappe.new_doc("Restaurant Cash Count")
        doc.name = "ARQ-TEST-PREVIEW"
        doc.count_type = "Arqueo de Cierre"
        doc.status = "Cuadrado"
        doc.posting_date = "2026-11-11 21:00:00"
        doc.currency = "HNL"
        doc.cashier = "Administrator"
        doc.cashier_name = "Administrator"
        doc.pos_profile = "POS Test"
        doc.pos_opening_shift = "POSA-OS-TEST-0001"
        doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 500.0,
            "denomination_label": "Billetes L 500",
            "quantity": 2,
            "subtotal": 1000.0,
        })
        doc.append("payment_methods", {
            "mode_of_payment": "Efectivo",
            "opening_amount": 500.0,
            "sales_amount": 500.0,
            "expected_amount": 1000.0,
            "counted_amount": 1000.0,
            "difference": 0.0,
        })
        doc.append("payment_details", {
            "mode_of_payment": "Tarjetas de credito",
            "detail_kind": "Tarjeta",
            "pos_terminal": "POS BAC 1",
            "reference": "LOTE-991",
            "amount": 250.0,
        })
        doc.append("payment_details", {
            "mode_of_payment": "Transferencia bancaria",
            "detail_kind": "Transferencia",
            "bank_name": "Banco Atlántida",
            "reference": "TRF-7788",
            "amount": 150.0,
        })
        doc.total_expected = 1000.0
        doc.total_counted = 1000.0
        doc.total_difference = 0.0
        doc.cash_bills_total = 1000.0
        doc.cash_coins_total = 0.0
        doc.cash_counted_total = 1000.0

        for pf_name in (PRINT_FORMAT_TICKET, PRINT_FORMAT_LETTER):
            self.assertTrue(
                frappe.db.exists("Print Format", pf_name),
                f"Missing Print Format {pf_name}",
            )
            html = frappe.get_print("Restaurant Cash Count", doc=doc, print_format=pf_name)
            self.assertIn("ARQ-TEST-PREVIEW", html)
            self.assertIn("Billetes L 500", html)
            self.assertIn("POS BAC 1", html)
            self.assertIn("TRF-7788", html)
            self.assertNotIn("Referencia / Lote", html)

    def test_payment_details_sum_into_methods_and_classify_system_modes(self):
        from restaurant.cash_count import _classify_payment_method, recalculate_cash_count_doc

        self.assertEqual(_classify_payment_method("Efectivo", "Cash", "Efectivo"), "cash")
        self.assertEqual(_classify_payment_method("Tarjetas de credito", "Bank", "Efectivo"), "card")
        self.assertEqual(_classify_payment_method("Transferencia bancaria", "Bank", "Efectivo"), "transfer")
        self.assertEqual(_classify_payment_method("Cheque", "Bank", "Efectivo"), "other")

        doc = frappe.new_doc("Restaurant Cash Count")
        doc.count_type = "Arqueo Parcial"
        doc.pos_opening_shift = "POSA-OS-TEST-0001"
        doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 500.0,
            "denomination_label": "Billetes L 500",
            "quantity": 2,
        })
        doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 100.0,
            "denomination_label": "Billetes L 100",
            "quantity": 3,
        })
        doc.append("denominations", {
            "denomination_type": "Billete",
            "unit_value": 50.0,
            "denomination_label": "Billetes L 50",
            "quantity": 1,
        })
        # Client tries sending tampered counted_amount on Tarjeta & Transferencia; server must sum payment_details.
        doc.append("payment_methods", {"mode_of_payment": "Tarjeta", "counted_amount": 9999.0})
        doc.append("payment_methods", {"mode_of_payment": "Transferencia Bancaria", "counted_amount": 1.0})
        doc.append("payment_details", {
            "mode_of_payment": "Tarjeta",
            "pos_terminal": "BAC POS 1",
            "bank_name": "Should Clear",
            "reference": "LOTE-10",
            "amount": 200.0,
        })
        doc.append("payment_details", {
            "mode_of_payment": "Tarjeta",
            "pos_terminal": "Ficohsa POS 2",
            "reference": "LOTE-20",
            "amount": 150.0,
        })
        doc.append("payment_details", {
            "mode_of_payment": "Transferencia Bancaria",
            "pos_terminal": "Should Clear",
            "bank_name": "Banco Atlántida",
            "reference": "TRF-009",
            "amount": 150.0,
        })

        with patch("restaurant.cash_count.build_cash_count_snapshot", return_value=self._build_mock_snapshot()):
            recalculate_cash_count_doc(doc, use_denomination_cash_total=True)

        by_mop = {m.mode_of_payment: m for m in doc.payment_methods}
        self.assertEqual(by_mop["Tarjeta"].counted_amount, 350.0)
        self.assertEqual(by_mop["Transferencia Bancaria"].counted_amount, 150.0)
        self.assertEqual(doc.total_counted, 1850.0)
        self.assertEqual(doc.total_difference, 0.0)
        self.assertEqual(doc.status, "Cuadrado")
        self.assertEqual(len(doc.payment_details), 3)
        self.assertEqual(doc.payment_details[0].detail_kind, "Tarjeta")
        self.assertEqual(doc.payment_details[0].bank_name, "")
        self.assertEqual(doc.payment_details[2].detail_kind, "Transferencia")
        self.assertEqual(doc.payment_details[2].pos_terminal, "")


