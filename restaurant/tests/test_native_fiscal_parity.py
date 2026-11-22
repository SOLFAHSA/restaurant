"""Native fiscal parity checks with isolated QA authorizations and rollback."""

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from restaurant import pos
from restaurant.tests import test_checkout_acceptance
from restaurant.tax_configuration import get_native_tax_configuration


class TestNativeFiscalParity(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.checkout = test_checkout_acceptance.TestCheckoutAcceptance()
        self.addCleanup(self.checkout.doCleanups)
        self.checkout.setUp()
        self.sale = self.checkout.sale
        self.config = get_native_tax_configuration(self.sale.company, create=True)
        frappe.db.set_value("POS Profile", self.sale.profile, {
            "taxes_and_charges": self.config["taxes_and_charges"],
            "tax_category": "Contribuyente",
            "posa_max_discount_allowed": 0,
        })

    def make_item(self, rate):
        return self.sale.make_item(
            "NATIVE-" + uuid4().hex[:8], is_stock_item=0, standard_rate=100,
            taxes=[{"item_tax_template": self.config["item_tax_templates"][rate]}],
        )

    def invoice(self, order, paid, **kwargs):
        return self.checkout.invoice(
            order, [{"mode_of_payment": self.checkout.cash, "amount": paid}], **kwargs,
        )

    def assert_summary(self, invoice, **values):
        for field, expected in values.items():
            self.assertEqual(flt(invoice.get(field), 2), expected, field)
        persisted = frappe.get_doc("Sales Invoice", invoice.name)
        before = {field: persisted.get(field) for field in values}
        persisted.get_itemised_tax_info()
        self.assertEqual({field: persisted.get(field) for field in values}, before)
        self.assertFalse(persisted.flags.get("restaurant_tax_override"))

    def test_native_mixed_tax_invoice_posts_to_separate_accounts_and_reverses(self):
        order = self.sale.make_order(*({"item_code": self.make_item(rate)} for rate in (15, 18, 0)))
        invoice = self.invoice(order, 299.70, global_discount_percentage=10)
        self.assert_summary(
            invoice, grand_total=299.70, taxed_amount_15=90, taxed_amount_18=90,
            exempt_amount=90, isv_15=13.50, isv_18=16.20,
        )
        taxes = [row for row in invoice.taxes if flt(row.tax_amount_after_discount_amount)]
        self.assertEqual(len({row.account_head for row in taxes}), 2)
        gl = frappe.get_all("GL Entry", filters={
            "voucher_type": "Sales Invoice", "voucher_no": invoice.name, "is_cancelled": 0,
        }, fields=["account", "credit", "debit"])
        for tax in taxes:
            balance = sum(flt(row.credit) - flt(row.debit) for row in gl if row.account == tax.account_head)
            self.assertEqual(flt(balance, 2), flt(tax.tax_amount_after_discount_amount, 2))
        ticket = frappe.get_print("Sales Invoice", invoice.name, "Ticket", no_letterhead=1)
        self.assertIn(invoice.name, ticket)
        self.assertIn("299.70", ticket)
        invoice.cancel()
        reversal = frappe.get_all("GL Entry", filters={
            "voucher_type": "Sales Invoice", "voucher_no": invoice.name,
        }, fields=["account", "credit", "debit", "is_cancelled"])
        self.assertTrue(reversal)
        self.assertTrue(all(row.is_cancelled for row in reversal))
        for account in {row.account for row in reversal}:
            balance = sum(flt(row.debit) - flt(row.credit) for row in reversal if row.account == account)
            self.assertEqual(flt(balance, 2), 0, account)
        reopened = frappe.get_doc("Restaurant Order", order["name"])
        self.assertEqual(reopened.status, "En curso")
        self.assertFalse(reopened.sales_invoice)

    def test_native_exoneration_keeps_net_line_discount_and_global_discount(self):
        frappe.db.set_value("Customer", self.sale.customer, {
            "custom_constancia_exonerado": "QA-EXO-001",
            "custom_subtipo_exonerado": "Constancia SAR / SAG / SEFIN",
        })
        order = self.sale.make_order({
            "item_code": self.make_item(18), "discount_percentage": 10,
        })
        invoice = self.invoice(
            order, 81, tax_category="Exonerado", global_discount_percentage=10,
            custom_orden_compra_exenta="QA-OC-001", custom_constancia_exonerado="QA-EXO-001",
        )
        self.assert_summary(invoice, grand_total=81, exonerated_amount=81, isv_15=0, isv_18=0)
        self.assertEqual(flt(invoice.items[0].rate), 90)
        self.assertEqual(flt(invoice.items[0].discount_percentage), 10)
        invoice.cancel()
        self.assertEqual(frappe.db.get_value("Restaurant Order", order["name"], "status"), "En curso")

    def test_native_full_discount_has_no_tax_base_or_amount_received(self):
        order = self.sale.make_order(*({"item_code": self.make_item(rate)} for rate in (15, 18, 0)))
        invoice = self.invoice(order, 0, global_discount_percentage=100)
        self.assert_summary(
            invoice, grand_total=0, taxed_amount_15=0, taxed_amount_18=0,
            exempt_amount=0, isv_15=0, isv_18=0, paid_amount=0, change_amount=0,
        )

    def test_native_exoneration_without_line_discount_keeps_net_price(self):
        order = self.sale.make_order({"item_code": self.make_item(18)})
        frappe.db.set_value("Customer", self.sale.customer, {
            "custom_subtipo_exonerado": "Constancia SAR / SAG / SEFIN",
            "custom_constancia_exonerado": "QA-EXO-002",
        })
        invoice = self.invoice(
            order, 100, tax_category="Exonerado",
            custom_orden_compra_exenta="QA-OC-002",
            custom_constancia_exonerado="QA-EXO-002",
        )
        self.assert_summary(invoice, grand_total=100, exonerated_amount=100, isv_15=0, isv_18=0)
