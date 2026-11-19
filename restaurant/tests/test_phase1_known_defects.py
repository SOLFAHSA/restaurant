"""Reproduction tests for the Phase 1 defects found on 2026-11-19.

Every test asserts a rule that must hold no matter which pending business decision is
taken (see docs/qa/linea-base-2026-11-19.md). They are marked ``expectedFailure`` because
the current code still breaks those rules. When Phase 1 fixes a defect, unittest reports
an "unexpected success": remove the decorator from that test at that moment.

Not covered on purpose: the empty-payment default (full cash) is pending a business
decision, so no expected behavior can be asserted yet.
"""

import unittest
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, now_datetime

from restaurant import pos
from restaurant.tests import test_checkout_acceptance

DISCOUNT_ERROR = (frappe.ValidationError, frappe.PermissionError)


class TestPhase1KnownDefects(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.checkout = test_checkout_acceptance.TestCheckoutAcceptance()
        self.addCleanup(self.checkout.doCleanups)
        self.checkout.setUp()
        self.sale = self.checkout.sale

    # -- helpers ---------------------------------------------------------------

    def cancel(self, invoice):
        invoice.reload()
        invoice.flags.ignore_permissions = True
        invoice.cancel()
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 2)

    def make_cashier(self):
        """Create a cashier without supervisor roles, with an open shift on the test POS."""
        email = f"qa-cashier-{uuid4().hex[:8]}@example.com"
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": "Cajero QA",
            "enabled": 1,
            "user_type": "System User",
            "send_welcome_email": 0,
            "roles": [{"role": "Restaurant User"}, {"role": "Restaurant Cashier"}],
        }).insert(ignore_permissions=True)
        frappe.get_doc({
            "doctype": "POS Opening Shift",
            "period_start_date": now_datetime(),
            "company": self.sale.company,
            "user": user.name,
            "pos_profile": self.sale.profile,
            "balance_details": [{"mode_of_payment": self.checkout.cash, "opening_amount": 0}],
        }).insert(ignore_permissions=True).submit()
        self.addCleanup(frappe.set_user, "Administrator")
        return user.name

    def save_order_as(self, user, item, discount_percentage):
        frappe.set_user(user)
        try:
            return pos.save_pos_order({
                "order_name": f"QA-DISC-{uuid4().hex[:8]}",
                "company": self.sale.company,
                "pos_profile": self.sale.profile,
                "customer": self.sale.customer,
                "service_type": "Para llevar",
                "items": [{
                    "item_code": item, "qty": 1, "base_rate": 100,
                    "discount_percentage": discount_percentage,
                }],
            })["order"]
        finally:
            frappe.set_user("Administrator")

    # -- 1a: invoice cancellation ---------------------------------------------

    @unittest.expectedFailure
    def test_cancelled_invoice_does_not_leave_the_order_billed(self):
        """DEF 1a: after cancelling, the order must not stay 'Facturada' linked to a cancelled invoice."""
        order = self.checkout.make_order()
        invoice = self.checkout.invoice(order, [{"mode_of_payment": self.checkout.cash, "amount": 0}])
        self.cancel(invoice)

        current = frappe.get_doc("Restaurant Order", order["name"])
        self.assertNotEqual(current.sales_invoice, invoice.name)
        self.assertNotEqual(current.status, "Facturada")

    @unittest.expectedFailure
    def test_cancelled_invoice_restores_the_gift_card_balance(self):
        """DEF 1a: the redeemed gift card amount must return to the card when the invoice is cancelled."""
        card = self.checkout.make_gift_card()
        invoice = self.checkout.invoice(
            self.checkout.make_order(), [{"mode_of_payment": self.checkout.cash, "amount": 0}],
            gift_card_code=card.name, gift_card_amount=50,
        )
        self.assertEqual(flt(frappe.db.get_value("Restaurant Gift Card", card.name, "balance"), 2), 0)

        self.cancel(invoice)
        self.assertEqual(flt(frappe.db.get_value("Restaurant Gift Card", card.name, "balance"), 2), 50)

    # -- 1c: discount limits ---------------------------------------------------

    @unittest.expectedFailure
    def test_cashier_cannot_exceed_the_pos_profile_discount_limit_alone(self):
        """DEF 1c: a cashier without supervisor approval must not exceed posa_max_discount_allowed."""
        frappe.db.set_value("POS Profile", self.sale.profile, "posa_max_discount_allowed", 10)
        cashier = self.make_cashier()
        item = self.checkout.make_item(15)

        # Sanity check: inside the limit the same cashier can save, so the setup is valid.
        self.assertTrue(self.save_order_as(cashier, item, 5)["name"])

        with self.assertRaisesRegex(DISCOUNT_ERROR, "(?i)descuento"):
            self.save_order_as(cashier, item, 50)

    @unittest.expectedFailure
    def test_item_max_discount_is_enforced_when_the_order_is_saved(self):
        """DEF 1c: the native Item.max_discount must be rejected on the order, not only at payment."""
        item = self.checkout.make_item(15)
        frappe.db.set_value("Item", item, "max_discount", 10)

        self.assertTrue(self.save_order_as("Administrator", item, 5)["name"])

        with self.assertRaisesRegex(DISCOUNT_ERROR, "(?i)descuento"):
            self.save_order_as("Administrator", item, 50)
