"""The billed order shows the issued invoice totals, and recovers its own totals on cancellation."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from restaurant.tests import test_checkout_acceptance


class TestOrderInvoiceTotals(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.checkout = test_checkout_acceptance.TestCheckoutAcceptance()
        self.addCleanup(self.checkout.doCleanups)
        self.checkout.setUp()

    def order_totals(self, name):
        return frappe.db.get_value(
            "Restaurant Order", name, ["subtotal", "isv_15", "tax_amount", "grand_total", "status"], as_dict=True
        )

    def test_global_discount_is_reflected_on_the_order(self):
        order = self.checkout.make_order()
        before = self.order_totals(order["name"])
        invoice = self.checkout.invoice(
            order, [{"mode_of_payment": self.checkout.cash, "amount": 103.50}], global_discount_percentage=10,
        )
        after = self.order_totals(order["name"])

        self.assertLess(flt(invoice.grand_total), flt(before.grand_total))
        self.assertEqual(flt(after.grand_total, 2), flt(invoice.grand_total, 2))
        self.assertEqual(flt(after.subtotal, 2), flt(invoice.net_total, 2))
        self.assertEqual(flt(after.isv_15, 2), flt(invoice.isv_15, 2))
        self.assertEqual(flt(after.subtotal + after.tax_amount, 2), flt(after.grand_total, 2))

    def test_cancelled_invoice_restores_the_order_totals(self):
        order = self.checkout.make_order()
        before = self.order_totals(order["name"])
        invoice = self.checkout.invoice(
            order, [{"mode_of_payment": self.checkout.cash, "amount": 103.50}], global_discount_percentage=10,
        )
        invoice.reload()
        invoice.flags.ignore_permissions = True
        invoice.cancel()

        reopened = self.order_totals(order["name"])
        self.assertEqual(reopened.status, "En curso")
        self.assertEqual(flt(reopened.grand_total, 2), flt(before.grand_total, 2))
        self.assertEqual(flt(reopened.subtotal, 2), flt(before.subtotal, 2))
