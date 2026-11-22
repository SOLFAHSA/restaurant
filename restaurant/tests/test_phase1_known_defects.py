"""Verify payments, discounts, and cancellation against the native invoice lifecycle."""

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, now_datetime

from restaurant import pos
from restaurant.tests import test_checkout_acceptance

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

    def test_cancelled_invoice_does_not_leave_the_order_billed(self):
        """DEF 1a: after cancelling, the order must not stay 'Facturada' linked to a cancelled invoice."""
        order = self.checkout.make_order()
        invoice = self.checkout.invoice(order, [{"mode_of_payment": self.checkout.cash, "amount": 115}])
        self.cancel(invoice)

        current = frappe.get_doc("Restaurant Order", order["name"])
        self.assertNotEqual(current.sales_invoice, invoice.name)
        self.assertNotEqual(current.status, "Facturada")

    def test_cancelled_invoice_restores_native_certificate_balance(self):
        certificate, code = self.checkout.make_gift_certificate()
        order = self.checkout.make_order()
        invoice = self.checkout.invoice(
            order, [{"mode_of_payment": self.checkout.cash, "amount": 65}],
            gift_card_code=code, gift_card_amount=50,
        )
        self.assertEqual(flt(certificate.reload().saldo_disponible, 2), 0)

        self.cancel(invoice)
        certificate.reload()
        self.assertEqual(flt(certificate.saldo_disponible, 2), 50)
        self.assertEqual(certificate.historial[-1].documento_referencia, invoice.name)
        self.assertEqual(certificate.historial[-1].tipo_movimiento, "Reversión por Anulación de Factura")


    # -- 1c: discount limits ---------------------------------------------------

    def test_cashier_cannot_invoice_above_the_pos_profile_discount_limit_alone(self):
        frappe.db.set_value("POS Profile", self.sale.profile, "posa_max_discount_allowed", 10)
        cashier = self.make_cashier()
        item = self.checkout.make_item(15)
        order = self.save_order_as(cashier, item, 50)

        frappe.set_user(cashier)
        try:
            with self.assertRaises(pos.DiscountApprovalRequired):
                pos.pay_and_invoice_order(
                    order["name"], payments=[{"mode_of_payment": self.checkout.cash, "amount": 57.50}],
                )
        finally:
            frappe.set_user("Administrator")
        self.assertFalse(frappe.db.get_value("Restaurant Order", order["name"], "sales_invoice"))

    def test_pos_discount_limit_requires_reason_and_records_supervisor(self):
        item = self.checkout.make_item(15)
        frappe.db.set_value("POS Profile", self.sale.profile, "posa_max_discount_allowed", 10)
        order = self.save_order_as("Administrator", item, 50)
        payments = [{"mode_of_payment": self.checkout.cash, "amount": 57.50}]

        with self.assertRaises(pos.DiscountApprovalRequired):
            pos.pay_and_invoice_order(order["name"], payments=payments)
        invoice = self.checkout.invoice(order, payments, reason="Descuento de cortesía autorizado")
        self.assertEqual(flt(invoice.grand_total, 2), 57.50)
        self.assertTrue(frappe.db.exists("Restaurant Audit Log", {
            "restaurant_order": order["name"], "action": "Descuento sobre el límite",
            "supervisor_user": "Administrator", "reason": "Descuento de cortesía autorizado",
        }))

    def test_supervisor_respects_native_item_discount_limit(self):
        item = self.checkout.make_item(15)
        frappe.db.set_value("Item", item, "max_discount", 10)
        order = self.save_order_as("Administrator", item, 5)
        with self.assertRaisesRegex(frappe.ValidationError, "supera el máximo configurado"):
            pos.pay_and_invoice_order(
                order["name"], global_discount_percentage=10,
                payments=[{"mode_of_payment": self.checkout.cash, "amount": 115}],
                reason="Descuento de cortesía",
            )
