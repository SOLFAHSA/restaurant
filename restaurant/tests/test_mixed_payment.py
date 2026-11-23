"""Mixed payments: several methods on one native invoice, and only cash gives change."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from restaurant.tests import test_checkout_acceptance


class TestMixedPayment(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.checkout = test_checkout_acceptance.TestCheckoutAcceptance()
        self.addCleanup(self.checkout.doCleanups)
        self.checkout.setUp()
        self.cash = self.checkout.cash
        self.bank = self.checkout.bank

    def test_card_plus_cash_gives_change_from_the_cash_part(self):
        invoice = self.checkout.invoice(self.checkout.make_order(), [
            {"mode_of_payment": self.bank, "amount": 65},
            {"mode_of_payment": self.cash, "amount": 100},
        ])
        self.assertEqual(flt(invoice.grand_total, 2), 115)
        self.assertEqual(flt(invoice.change_amount, 2), 50)
        self.assertEqual(
            {row.mode_of_payment: flt(row.amount, 2) for row in invoice.payments},
            {self.bank: 65, self.cash: 100},
        )

    def test_card_cannot_pay_more_than_the_amount_due(self):
        order = self.checkout.make_order()
        with self.assertRaisesRegex(frappe.ValidationError, "Solo el efectivo puede dar cambio"):
            self.checkout.invoice(order, [
                {"mode_of_payment": self.cash, "amount": 10},
                {"mode_of_payment": self.bank, "amount": 150},
            ])
        self.assertFalse(frappe.db.get_value("Restaurant Order", order["name"], "sales_invoice"))
