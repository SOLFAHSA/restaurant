"""Acceptance checks for mixed taxes, invoice discounts, payments, and native closing."""

import json
import re
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from restaurant import cash_count, pos
from restaurant.tests import test_fiscal_numbering


class TestCheckoutAcceptance(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.fiscal = test_fiscal_numbering.TestRestaurantFiscalNumbering()
        self.addCleanup(self.fiscal.doCleanups)
        self.fiscal.setUp()
        self.fiscal.make_cai(41, 100)
        self.sale = self.fiscal.sale
        self.cash = self.sale.mode_of_payment
        self.assertEqual(frappe.db.get_value("Mode of Payment", self.cash, "type"), "Cash")
        self.bank = next(
            row.parent
            for row in frappe.get_all(
                "Mode of Payment Account",
                filters={"company": self.sale.company, "default_account": ["is", "set"]},
                fields=["parent"],
            )
            if frappe.db.get_value("Mode of Payment", row.parent, "type") == "Bank"
        )
        profile = frappe.get_doc("POS Profile", self.sale.profile)
        profile.posa_cash_mode_of_payment = self.cash
        if self.bank not in {row.mode_of_payment for row in profile.payments}:
            profile.append("payments", {"mode_of_payment": self.bank})
        profile.save(ignore_permissions=True)
        frappe.db.set_default(
            f"rpos_cfg_{self.sale.profile}",
            json.dumps({
                "auto_validate_orders": 1,
                "enabled_payments": [self.cash, self.bank],
                "allow_line_discount": 1,
                "allow_global_discount": 1,
                "enable_gift_cards": 1,
            }),
        )
        self.shift = frappe.db.get_value(
            "POS Opening Shift", {"pos_profile": self.sale.profile, "docstatus": 1}, "name"
        )

    def make_item(self, rate):
        account = pos._resolve_tax_account(self.sale.company, rate or 15)
        letters = uuid4().hex.translate(str.maketrans("0123456789", "ghijklmnop"))
        label = "EXENTO" if rate == 0 else f"ISV {rate}%"
        template = frappe.get_doc({
            "doctype": "Item Tax Template",
            "title": f"QA Checkout {label} {letters}",
            "company": self.sale.company,
            "taxes": [{"tax_type": account, "tax_rate": rate}],
        }).insert(ignore_permissions=True)
        return self.sale.make_item(
            f"TAX-{rate}-{letters[:8]}", is_stock_item=0, standard_rate=100,
            taxes=[{"item_tax_template": template.name}],
        )

    def invoice(self, order, payments, **kwargs):
        response = pos.pay_and_invoice_order(order["name"], payments=payments, **kwargs)
        invoice = frappe.get_doc("Sales Invoice", response["invoice"]["name"])
        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(invoice.outstanding_amount, 0)
        self.assertEqual(invoice.posa_pos_opening_shift, self.shift)
        self.assertEqual(
            frappe.db.get_value("Restaurant Order", order["name"], "sales_invoice"), invoice.name
        )
        ledger = frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Sales Invoice", "voucher_no": invoice.name, "is_cancelled": 0},
            fields=["debit", "credit"],
        )
        self.assertEqual(
            flt(sum(row.debit for row in ledger), 2),
            flt(sum(row.credit for row in ledger), 2),
        )
        return invoice

    def ticket_amount(self, invoice, label):
        html = frappe.get_print("Sales Invoice", invoice.name, "Ticket", no_letterhead=1)
        match = re.search(
            re.escape(label) + r"\s*</td>\s*<td[^>]*>\s*([0-9.,]+)", html
        )
        self.assertIsNotNone(match, label)
        return flt(match.group(1).replace(",", ""), 2)

    def make_order(self):
        return self.sale.make_order({"item_code": self.make_item(15)})

    def test_mixed_tax_bases_and_ticket_match_independent_expected_amounts(self):
        order = self.sale.make_order(
            *({"item_code": self.make_item(rate)} for rate in (15, 18, 0))
        )
        self.assertEqual(order["grand_total"], 333)
        invoice = self.invoice(order, [{"mode_of_payment": self.cash, "amount": 333}])
        for field, expected in (
            ("taxed_amount_15", 100), ("isv_15", 15),
            ("taxed_amount_18", 100), ("isv_18", 18),
            ("exempt_amount", 100), ("grand_total", 333),
        ):
            self.assertEqual(flt(invoice.get(field), 2), expected, field)
        for label, expected in (
            ("GRAVADO 15% L.", 100), ("GRAVADO 18% L.", 100),
            ("IMPTO. 15% L.", 15), ("IMPTO. 18% L.", 18),
            ("EXENTO L.", 100), ("TOTAL FACTURA L.", 333),
        ):
            self.assertEqual(self.ticket_amount(invoice, label), expected, label)

    def test_global_percentage_discount_recalculates_tax_and_ticket(self):
        invoice = self.invoice(
            self.make_order(), [{"mode_of_payment": self.cash, "amount": 103.50}],
            global_discount_percentage=10,
        )
        self.assertEqual(flt(invoice.net_total, 2), 90)
        self.assertEqual(flt(invoice.isv_15, 2), 13.50)
        self.assertEqual(flt(invoice.grand_total, 2), 103.50)
        self.assertEqual(self.ticket_amount(invoice, "DESCUENTOS Y REBAJAS L."), 11.50)
        self.assertEqual(self.ticket_amount(invoice, "GRAVADO 15% L."), 90)

    def test_global_fixed_discount_recalculates_tax_and_ticket(self):
        invoice = self.invoice(
            self.make_order(), [{"mode_of_payment": self.cash, "amount": 105}],
            global_discount_amount=10,
        )
        self.assertEqual(flt(invoice.net_total, 2), 91.30)
        self.assertEqual(flt(invoice.isv_15, 2), 13.70)
        self.assertEqual(flt(invoice.grand_total, 2), 105)
        self.assertEqual(self.ticket_amount(invoice, "DESCUENTOS Y REBAJAS L."), 10)

    def test_full_global_discount_has_zero_tax_base_and_no_cash_tendered(self):
        invoice = self.invoice(
            self.make_order(), [{"mode_of_payment": self.cash, "amount": 0}],
            global_discount_percentage=100,
        )
        self.assertEqual(flt(invoice.grand_total, 2), 0)
        self.assertEqual(flt(invoice.taxed_amount_15, 2), 0)
        self.assertEqual(flt(invoice.isv_15, 2), 0)
        self.assertEqual(flt(invoice.paid_amount, 2), 0)
        self.assertEqual(flt(invoice.change_amount, 2), 0)
        self.assertEqual(self.ticket_amount(invoice, "GRAVADO 15% L."), 0)

    def test_full_line_discount_has_zero_total_and_no_cash_tendered(self):
        order = self.sale.make_order({
            "item_code": self.make_item(15), "discount_percentage": 100,
        })
        self.assertEqual(order["grand_total"], 0)
        invoice = self.invoice(order, [{"mode_of_payment": self.cash, "amount": 0}])
        self.assertEqual(flt(invoice.grand_total, 2), 0)
        self.assertEqual(flt(invoice.taxed_amount_15, 2), 0)
        self.assertEqual(flt(invoice.paid_amount, 2), 0)
        self.assertEqual(flt(invoice.change_amount, 2), 0)

    def test_mixed_payment_reconciles_and_cash_count_closes_only_temporary_shift(self):
        invoice = self.invoice(self.make_order(), [
            {"mode_of_payment": self.cash, "amount": 50},
            {"mode_of_payment": self.bank, "amount": 65},
        ])
        self.assertEqual(flt(invoice.paid_amount, 2), 115)
        self.assertEqual(flt(invoice.change_amount, 2), 0)
        snapshot = cash_count.get_cash_count_preview(self.shift)
        expected = {row["mode_of_payment"]: row["expected_amount"] for row in snapshot["payment_methods"]}
        self.assertEqual(expected[self.cash], 50)
        self.assertEqual(expected[self.bank], 65)
        response = cash_count.save_and_submit_cash_count({
            "pos_opening_shift": self.shift,
            "count_type": "Arqueo de Cierre",
            "denominations": [{"unit_value": 50, "quantity": 1, "denomination_label": "L 50"}],
            "payment_methods": [
                {"mode_of_payment": name, "counted_amount": amount}
                for name, amount in expected.items()
            ],
        })
        count = response["cash_count"]
        self.assertEqual(count["total_expected"], 115)
        self.assertEqual(count["total_counted"], 115)
        self.assertEqual(count["total_difference"], 0)
        self.assertTrue(count["pos_closing_shift"])
        self.assertEqual(frappe.db.get_value("POS Closing Shift", count["pos_closing_shift"], "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("POS Opening Shift", self.shift, "status"), "Closed")

    def test_cash_change_is_deducted_from_expected_closing_cash(self):
        invoice = self.invoice(
            self.make_order(), [{"mode_of_payment": self.cash, "amount": 200}],
        )
        self.assertEqual(flt(invoice.grand_total, 2), 115)
        self.assertEqual(flt(invoice.change_amount, 2), 85)
        self.assertEqual(self.ticket_amount(invoice, "CAMBIO L."), 85)
        snapshot = cash_count.get_cash_count_preview(self.shift)
        cash = next(row for row in snapshot["payment_methods"] if row["mode_of_payment"] == self.cash)
        self.assertEqual(cash["expected_amount"], 115)

    def test_sar_summary_preserves_zero_and_legacy_missing_net_amount(self):
        for raw_item, expected in (({"amount": 100, "net_amount": 0}, 0), ({"amount": 100}, 100)):
            with self.subTest(item=raw_item):
                invoice = {"items": [raw_item]}
                pos._sync_sar_tax_summary(
                    invoice, saved_rates=[json.dumps({"ISV": 15})],
                    si_meta=frappe.get_meta("Sales Invoice"),
                )
                self.assertEqual(invoice["taxed_amount_15"], expected)
                self.assertEqual(invoice["isv_15"], flt(expected * 0.15, 2))

    def test_default_payment_uses_discounted_total_for_omitted_empty_and_zero_rows(self):
        for payments in (None, [], [{"mode_of_payment": self.cash, "amount": 0}]):
            with self.subTest(payments=payments):
                invoice = self.invoice(self.make_order(), payments, global_discount_percentage=10)
                self.assertEqual(flt(invoice.grand_total, 2), 103.50)
                self.assertEqual(flt(invoice.paid_amount, 2), 103.50)
                self.assertEqual(flt(invoice.change_amount, 2), 0)

    def test_full_global_discount_zeroes_mixed_tax_bases(self):
        order = self.sale.make_order(
            *({"item_code": self.make_item(rate)} for rate in (15, 18, 0))
        )
        invoice = self.invoice(order, [], global_discount_percentage=100)
        for field in (
            "grand_total", "paid_amount", "change_amount", "taxed_amount_15",
            "taxed_amount_18", "isv_15", "isv_18", "exempt_amount",
        ):
            self.assertEqual(flt(invoice.get(field), 2), 0, field)
        self.assertEqual(self.ticket_amount(invoice, "TOTAL PAGADO L."), 0)
        self.assertEqual(self.ticket_amount(invoice, "IMPTO. 18% L."), 0)

    def test_full_global_fixed_discount_has_zero_total_and_payment(self):
        invoice = self.invoice(self.make_order(), None, global_discount_amount=115)
        for field in ("grand_total", "paid_amount", "change_amount", "taxed_amount_15", "isv_15"):
            self.assertEqual(flt(invoice.get(field), 2), 0, field)
        self.assertEqual(self.ticket_amount(invoice, "TOTAL PAGADO L."), 0)
        self.assertEqual(self.ticket_amount(invoice, "CAMBIO L."), 0)

    def test_explicit_cash_tender_is_preserved_with_global_discount(self):
        invoice = self.invoice(
            self.make_order(), [{"mode_of_payment": self.cash, "amount": 200}],
            global_discount_percentage=10,
        )
        self.assertEqual(flt(invoice.grand_total, 2), 103.50)
        self.assertEqual(flt(invoice.paid_amount, 2), 200)
        self.assertEqual(flt(invoice.change_amount, 2), 96.50)
        self.assertEqual(self.ticket_amount(invoice, "TOTAL PAGADO L."), 200)
        self.assertEqual(self.ticket_amount(invoice, "CAMBIO L."), 96.50)

    def make_gift_card(self):
        return frappe.get_doc({
            "doctype": "Restaurant Gift Card",
            "card_code": f"QA-CHECKOUT-{uuid4().hex}".upper(),
            "company": self.sale.company,
            "customer": self.sale.customer,
            "initial_amount": 50,
            "balance": 50,
            "enabled": 1,
        }).insert(ignore_permissions=True)

    def test_gift_card_reduces_default_payment_after_discount(self):
        card = self.make_gift_card()
        invoice = self.invoice(
            self.make_order(), [{"mode_of_payment": self.cash, "amount": 0}],
            global_discount_percentage=10, gift_card_code=card.name, gift_card_amount=50,
        )
        self.assertEqual(flt(invoice.grand_total, 2), 103.50)
        cash = sum(row.amount for row in invoice.payments if row.mode_of_payment == self.cash)
        self.assertEqual(flt(cash, 2), 53.50)
        self.assertEqual(flt(invoice.change_amount, 2), 0)
        self.assertEqual(frappe.db.get_value("Restaurant Gift Card", card.name, "balance"), 0)

    def test_zero_total_does_not_redeem_gift_card(self):
        card = self.make_gift_card()
        invoice = self.invoice(
            self.make_order(), [{"mode_of_payment": self.cash, "amount": 0}],
            global_discount_percentage=100, gift_card_code=card.name, gift_card_amount=50,
        )
        self.assertEqual(flt(invoice.grand_total, 2), 0)
        self.assertEqual(flt(invoice.paid_amount, 2), 0)
        self.assertEqual(flt(invoice.change_amount, 2), 0)
        self.assertEqual(frappe.db.get_value("Restaurant Gift Card", card.name, "balance"), 50)

    def test_default_payment_includes_native_discounted_tip_total(self):
        invoice = self.invoice(
            self.make_order(), None, global_discount_percentage=10, tip_amount=10,
        )
        self.assertEqual(flt(invoice.grand_total, 2), 112.50)
        self.assertEqual(flt(invoice.paid_amount, 2), 112.50)
        self.assertEqual(flt(invoice.change_amount, 2), 0)
        self.assertEqual(self.ticket_amount(invoice, "TOTAL FACTURA L."), 112.50)

    def test_zero_price_invoice_posts_and_reverses_native_stock(self):
        item = frappe.get_doc("Item", self.make_item(15))
        item.is_stock_item = 1
        item.save(ignore_permissions=True)
        self.sale.receive_stock(item.name, 1)
        order = self.sale.make_order({"item_code": item.name})
        invoice = self.invoice(
            order, [{"mode_of_payment": self.cash, "amount": 0}],
            global_discount_percentage=100,
        )
        self.assertEqual(invoice.update_stock, 1)
        self.assertEqual(flt(invoice.grand_total, 2), 0)
        self.assertEqual(self.sale.stock_qty(item.name), 0)
        ledger = self.sale.invoice_ledger(invoice)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0].actual_qty, -1)
        invoice.cancel()
        self.assertEqual(self.sale.stock_qty(item.name), 1)

    def test_gift_card_with_payment_account_uses_discounted_cash_remainder(self):
        account = frappe.get_doc({
            "doctype": "Account",
            "account_name": f"QA Checkout Gift {uuid4().hex[:8]}",
            "company": self.sale.company,
            "parent_account": frappe.db.get_value(
                "Account", {"company": self.sale.company, "root_type": "Liability", "is_group": 1}, "name"
            ),
            "is_group": 0,
        }).insert(ignore_permissions=True)
        mode_name = "Tarjeta de Regalo"
        if frappe.db.exists("Mode of Payment", mode_name):
            mode = frappe.get_doc("Mode of Payment", mode_name)
        else:
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = mode_name
            mode.type = "General"
        company_account = next(
            (row for row in mode.accounts if row.company == self.sale.company), None
        )
        if company_account:
            company_account.default_account = account.name
        else:
            mode.append("accounts", {"company": self.sale.company, "default_account": account.name})
        mode.save(ignore_permissions=True)
        card = self.make_gift_card()
        invoice = self.invoice(
            self.make_order(), [{"mode_of_payment": self.cash, "amount": 0}],
            global_discount_percentage=10, gift_card_code=card.name, gift_card_amount=50,
        )
        amounts = {row.mode_of_payment: flt(row.amount, 2) for row in invoice.payments}
        self.assertEqual(amounts[self.cash], 53.50)
        self.assertEqual(amounts[mode_name], 50)
        self.assertEqual(flt(invoice.paid_amount, 2), 103.50)
        self.assertEqual(flt(invoice.write_off_amount, 2), 0)
        self.assertEqual(flt(invoice.change_amount, 2), 0)
        self.assertEqual(frappe.db.get_value("Restaurant Gift Card", card.name, "balance"), 0)



