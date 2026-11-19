"""Development integration tests for Restaurant fiscal authorization and native invoice numbering."""

from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from restaurant import pos
from restaurant.tests import test_invoice_stock


class TestRestaurantFiscalNumbering(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.sale = test_invoice_stock.TestRestaurantInvoiceStock()
        self.addCleanup(self.sale.doCleanups)
        self.sale.setUp()
        serial = uuid4().int % 10000
        self.series_key = f"{900 + serial // 100:03d}-{900 + serial % 100:03d}-01-"
        self.series = f"{self.series_key}.########"
        self.assertFalse(frappe.db.exists("CAI", {"prefix": self.series}))
        self.assertIsNone(self.current_number())
        frappe.db.set_value("POS Profile", self.sale.profile, "prefix", self.series)
        self.item = self.sale.make_item("FISCAL", is_stock_item=0)

    def make_cai(self, lower, upper, *, days_left=10, status=None):
        label = f"QA-FISCAL-{uuid4().hex[:12]}"
        authorization = frappe.get_doc({
            "doctype": "CAI",
            "name_cai": label,
            "no_declaration": label,
            "cai": label,
            "initial_number": f"{lower:08d}",
            "final_number": f"{upper:08d}",
            "reception_date": add_days(nowdate(), -5),
            "issue_deadline": add_days(nowdate(), days_left),
            "select_doc_for_series": "Sales Invoice",
            "prefix": self.series,
            "expired_days": "1",
            "expired_amount": 1,
        }).insert(ignore_permissions=True)
        if status and authorization.status != status:
            authorization.db_set("status", status)
        return authorization

    def current_number(self):
        return frappe.db.get_value("Series", self.series_key, "current", order_by="name")

    def make_order(self, item=None):
        return self.sale.make_order({"item_code": item or self.item})

    def assert_rejected(self, order, message="no tiene un CAI vigente"):
        before = self.current_number()
        self.addCleanup(frappe.clear_messages)
        frappe.db.savepoint("restaurant_fiscal_rejection")
        try:
            with self.assertRaisesRegex(frappe.ValidationError, message):
                self.sale.pay(order)
        finally:
            frappe.db.rollback(save_point="restaurant_fiscal_rejection")
        self.assertEqual(self.current_number(), before)
        self.assertFalse(frappe.db.exists("Sales Invoice", {"restaurant_order": order["name"]}))
        order_doc = frappe.get_doc("Restaurant Order", order["name"])
        self.assertFalse(order_doc.sales_invoice)
        self.assertEqual(order_doc.status, "En curso")

    def test_precheck_repeated_then_first_folio_starts_at_authorized_number(self):
        authorization = self.make_cai(41, 43)
        order = self.make_order()
        for _ in range(2):
            pos.get_precuenta_data(order["name"])
        self.assertIsNone(self.current_number())
        self.assertFalse(frappe.db.exists("Sales Invoice", {"restaurant_order": order["name"]}))

        response = pos.pay_and_invoice_order(
            order["name"],
            payments=[{"mode_of_payment": self.sale.mode_of_payment, "amount": order["grand_total"]}],
            cai="QA-UNASSIGNED",
            due_date_cai="2099-12-31",
            authorized_range="QA-UNASSIGNED",
        )["invoice"]
        invoice = frappe.get_doc("Sales Invoice", response["name"])
        self.assertEqual(invoice.name, f"{self.series_key}00000041")
        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(self.current_number(), 41)
        self.assertEqual(invoice.cai, authorization.cai)
        self.assertEqual(response["cai"], invoice.cai)
        self.assertEqual(response["due_date_cai"], str(invoice.due_date_cai))
        self.assertEqual(response["authorized_range"], f"{self.series_key}00000041 al {self.series_key}00000043")
        ticket = frappe.get_print("Sales Invoice", invoice.name, "Ticket", no_letterhead=1)
        self.assertIn(invoice.name, ticket)
        self.assertIn(authorization.cai, ticket)
        footer = ticket.split("Rango Autorizado", 1)[1].split("Original: Cliente", 1)[0]
        range_start, range_end = response["authorized_range"].split(" al ")
        self.assertIn(range_start, footer)
        self.assertIn(range_end, footer)
        self.assertIn(invoice.due_date_cai.strftime("%d/%m/%Y"), footer)
        self.assertNotIn("QA-UNASSIGNED", ticket)

    def test_missing_authorization_does_not_use_another_series(self):
        fiscal_info = pos._resolve_sar_fiscal_info(self.sale.profile, self.sale.company)
        self.assertEqual(fiscal_info["prefix"], self.series)
        self.assertFalse(fiscal_info["cai"])
        self.assertFalse(fiscal_info["authorized_range"])
        self.assert_rejected(self.make_order())

    def test_expired_authorization_is_rejected(self):
        self.make_cai(1, 10, days_left=-1)
        self.assert_rejected(self.make_order())

    def test_fractional_authorized_number_is_rejected(self):
        authorization = self.make_cai(1, 10)
        authorization.db_set("initial_number", "1.5")
        self.assert_rejected(self.make_order())

    def test_duplicate_active_authorizations_are_rejected(self):
        self.make_cai(1, 10)
        self.make_cai(11, 20, status="Active")
        self.assert_rejected(self.make_order(), "Hay más de un CAI activo")

    def test_last_folio_is_valid_then_series_is_exhausted(self):
        self.make_cai(9, 9)
        invoice = self.sale.pay(self.make_order())
        self.assertEqual(invoice.name, f"{self.series_key}00000009")
        self.assert_rejected(self.make_order())
        self.assertEqual(self.current_number(), 9)

    def test_pending_authorization_can_start_without_an_active_cai(self):
        pending = self.make_cai(104, 106, status="Pending")
        invoice = self.sale.pay(self.make_order())
        self.assertEqual(invoice.name, f"{self.series_key}00000104")
        self.assertEqual(invoice.cai, pending.cai)
        self.assertEqual(frappe.db.get_value("CAI", pending.name, "status"), "Active")

    def test_renewal_does_not_reuse_an_overlapping_folio(self):
        active = self.make_cai(20, 20)
        pending = self.make_cai(20, 22)
        first_invoice = self.sale.pay(self.make_order())
        second_invoice = self.sale.pay(self.make_order())

        self.assertEqual(first_invoice.name, f"{self.series_key}00000020")
        self.assertEqual(second_invoice.name, f"{self.series_key}00000021")
        self.assertEqual(first_invoice.reload().cai, active.cai)
        self.assertEqual(second_invoice.cai, pending.cai)
        self.assertEqual(frappe.db.get_value("CAI", active.name, "status"), "Inactive")
        self.assertEqual(frappe.db.get_value("CAI", pending.name, "status"), "Active")

    def test_expired_pending_authorization_does_not_replace_the_active_cai(self):
        active = self.make_cai(3, 3)
        pending = self.make_cai(4, 7, days_left=-1)
        self.sale.pay(self.make_order())
        self.assert_rejected(self.make_order())

        self.assertEqual(frappe.db.get_value("CAI", pending.name, "status"), "Pending")
        self.assertEqual(frappe.db.get_value("CAI", active.name, "status"), "Active")

    def test_draft_with_expired_cai_cannot_be_submitted(self):
        self.make_cai(50, 53, days_left=2)
        self.sale.set_auto_submit(0)
        invoice = self.sale.pay(self.make_order())
        self.assertEqual(invoice.docstatus, 0)
        tomorrow_after_deadline = add_days(invoice.due_date_cai, 1)

        with patch(
            "erpnext.accounts.doctype.sales_invoice.sales_invoice.nowdate", return_value=tomorrow_after_deadline,
        ):
            with self.assertRaisesRegex(frappe.ValidationError, "CAI de esta factura está vencido"):
                invoice.reload().submit()

        invoice.reload()
        self.assertEqual(invoice.docstatus, 0)
        self.assertEqual(self.current_number(), 50)
        self.assertFalse(frappe.db.exists("GL Entry", {"voucher_type": "Sales Invoice", "voucher_no": invoice.name}))

    def test_stock_rejection_rolls_back_cai_activation_and_folio(self):
        pending = self.make_cai(72, 73, status="Pending")
        stock_item = self.sale.make_item("FISCAL-STOCK")
        order = self.make_order(stock_item)
        self.assert_rejected(order, "Existencia insuficiente")
        self.assertIsNone(self.current_number())
        self.assertEqual(frappe.db.get_value("CAI", pending.name, "status"), "Pending")
        self.sale.receive_stock(stock_item, 1)
        invoice = self.sale.pay(order)
        self.assertEqual(invoice.name, f"{self.series_key}00000072")
