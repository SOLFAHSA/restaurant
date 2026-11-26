"""Required matrix before the Grintsys PR: price modes, tip liability, migrate isolation, dish tax gate.

Every test runs inside the savepoint of the reused checkout fixtures, so nothing persists.
"""

import re
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, money_in_words

from restaurant import cash_count, pos, setup
from restaurant.tax_configuration import _account, get_native_tax_configuration
from restaurant.tests import test_checkout_acceptance
from restaurant.tests.fixtures import ensure_tip_liability_account, set_restaurant_settings

TICKET = "Ticket Restaurant"


class TestFiscalTipIsolation(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.checkout = test_checkout_acceptance.TestCheckoutAcceptance()
        self.addCleanup(self.checkout.doCleanups)
        self.checkout.setUp()
        self.sale = self.checkout.sale
        self.company = self.sale.company
        self.config = get_native_tax_configuration(self.company, create=True)
        self.net_template = self.config["taxes_and_charges"]
        self.exonerated_template = self.config["exonerated_taxes_and_charges"]
        set_restaurant_settings(
            company=self.company,
            sales_taxes_template=self.net_template,
            exonerated_taxes_template=self.exonerated_template,
            tip_liability_account=None,
        )

    # ------------------------------------------------------------------ helpers

    def make_included_template(self):
        doc = frappe.get_doc({
            "doctype": "Sales Taxes and Charges Template",
            "title": f"QA ISV incluido {uuid4().hex[:8]}",
            "company": self.company,
            "taxes": [{
                "charge_type": "On Net Total", "account_head": _account(self.company, rate),
                "description": f"ISV {rate}%", "rate": rate, "included_in_print_rate": 1,
            } for rate in (15, 18)],
        }).insert(ignore_permissions=True)
        return doc.name

    def use_included_prices(self):
        set_restaurant_settings(sales_taxes_template=self.make_included_template())

    def make_item(self, rate, price):
        return self.sale.make_item(
            f"FTI-{rate}-{uuid4().hex[:8]}", is_stock_item=0, standard_rate=price,
            taxes=[{"item_tax_template": self.config["item_tax_templates"][rate]}],
        )

    def make_exonerated_customer(self):
        frappe.db.set_value("Customer", self.sale.customer, {
            "tax_category": "Exonerado",
            "custom_subtipo_exonerado": "Constancia SAR / SAG / SEFIN",
            "custom_constancia_exonerado": "QA-EXO-FTI",
        })

    def pay(self, order, amount, **kwargs):
        return self.checkout.invoice(order, [{"mode_of_payment": self.checkout.cash, "amount": amount}], **kwargs)

    def pay_exonerated(self, order, amount):
        return self.pay(
            order, amount, tax_category="Exonerado",
            custom_orden_compra_exenta="QA-OC-FTI", custom_constancia_exonerado="QA-EXO-FTI",
        )

    def assert_parity(self, order, invoice):
        """Pre-bill (Restaurant Order before billing) and native Sales Invoice must match to the cent."""
        exempt = flt(invoice.exempt_amount) + flt(invoice.exonerated_amount)
        expected = {
            "taxed_amount_15": flt(invoice.taxed_amount_15, 2),
            "isv_15": flt(invoice.isv_15, 2),
            "taxed_amount_18": flt(invoice.taxed_amount_18, 2),
            "isv_18": flt(invoice.isv_18, 2),
            "exempt_amount": flt(exempt, 2),
            "grand_total": flt(invoice.grand_total, 2),
        }
        actual = {field: flt(order[field], 2) for field in expected}
        self.assertEqual(actual, expected)
        self.assertFalse([row for row in invoice.taxes if row.charge_type == "Actual"])

    def set_tip(self, order, amount=0, percentage=0):
        doc = frappe.get_doc("Restaurant Order", order["name"])
        doc.tip_percentage = percentage
        doc.tip_amount = amount
        doc.save()
        return pos._serialize_order(doc)

    def ticket(self, invoice):
        return frappe.get_print("Sales Invoice", invoice.name, TICKET, no_letterhead=1)

    def ticket_amount(self, html, label):
        match = re.search(re.escape(label) + r"\s*</td>\s*<td[^>]*>\s*([0-9.,]+)", html)
        self.assertIsNotNone(match, label)
        return flt(match.group(1).replace(",", ""), 2)

    # ------------------------------------------- 1. net vs tax-inclusive price parity

    def test_net_prices_mixed_rates_with_discount_match_invoice(self):
        order = self.sale.make_order(
            {"item_code": self.make_item(15, 100), "discount_percentage": 10},
            {"item_code": self.make_item(18, 100)},
            {"item_code": self.make_item(0, 100)},
        )
        self.assertEqual(order["grand_total"], 321.50)
        invoice = self.pay(order, 321.50)
        self.assert_parity(order, invoice)
        self.assertEqual(flt(invoice.isv_15, 2), 13.50)
        self.assertEqual(flt(invoice.isv_18, 2), 18)

    def test_tax_inclusive_prices_mixed_rates_do_not_duplicate_isv(self):
        self.use_included_prices()
        order = self.sale.make_order(
            {"item_code": self.make_item(15, 115)},
            {"item_code": self.make_item(18, 118)},
            {"item_code": self.make_item(0, 100)},
        )
        # Prices already include ISV: the total is the sum of the prices, ISV is only broken down.
        self.assertEqual(order["grand_total"], 333)
        self.assertEqual(order["taxed_amount_15"], 100)
        self.assertEqual(order["isv_15"], 15)
        self.assertEqual(order["taxed_amount_18"], 100)
        self.assertEqual(order["isv_18"], 18)
        invoice = self.pay(order, 333)
        self.assert_parity(order, invoice)
        self.assertEqual(self.ticket_amount(self.ticket(invoice), "TOTAL FACTURA L."), 333)

    def test_tax_inclusive_prices_with_line_discount_and_odd_cents_match_invoice(self):
        self.use_included_prices()
        order = self.sale.make_order(
            {"item_code": self.make_item(15, 57.50), "qty": 3, "discount_percentage": 10},
            {"item_code": self.make_item(18, 99.99), "qty": 2},
            {"item_code": self.make_item(0, 45.25)},
        )
        invoice = self.pay(order, order["grand_total"])
        self.assert_parity(order, invoice)
        self.assertEqual(flt(invoice.grand_total, 2), flt(155.25 + 199.98 + 45.25, 2))

    def test_company_templates_with_custom_names_and_single_isv_account_are_accepted(self):
        """Grintsys-style setup: one ISV account, tax-inclusive prices, item templates with any title."""
        account = _account(self.company, 15)
        tag = uuid4().hex[:6]
        sales = frappe.get_doc({
            "doctype": "Sales Taxes and Charges Template", "title": f"QA Honduras {tag}", "company": self.company,
            "taxes": [{"charge_type": "On Net Total", "account_head": account, "description": "ISV",
                       "rate": 15, "included_in_print_rate": 1}],
        }).insert(ignore_permissions=True).name
        set_restaurant_settings(sales_taxes_template=sales)
        items = []
        for rate, price in ((15, 115), (18, 118), (0, 100)):
            template = frappe.get_doc({
                "doctype": "Item Tax Template", "title": f"QA Tasa {rate} {tag}", "company": self.company,
                "taxes": [{"tax_type": account, "tax_rate": rate}],
            }).insert(ignore_permissions=True).name
            items.append({"item_code": self.sale.make_item(
                f"FTI-G{rate}-{tag}", is_stock_item=0, standard_rate=price, taxes=[{"item_tax_template": template}],
            )})
        order = self.sale.make_order(*items)
        self.assertEqual(order["grand_total"], 333)
        invoice = self.pay(order, 333)
        self.assert_parity(order, invoice)
        self.assertEqual(flt(invoice.isv_18, 2), 18)
        self.assertEqual({row.item_tax_template for row in invoice.items}, {
            frappe.db.get_value("Item Tax Template", {"title": f"QA Tasa {rate} {tag}"}, "name") for rate in (15, 18, 0)
        })

    def test_net_prices_exonerated_customer_matches_invoice(self):
        self.make_exonerated_customer()
        order = self.sale.make_order(
            {"item_code": self.make_item(15, 100)}, {"item_code": self.make_item(18, 100)},
            {"item_code": self.make_item(0, 100)},
        )
        self.assertEqual(order["tax_amount"], 0)
        invoice = self.pay_exonerated(order, 300)
        self.assert_parity(order, invoice)
        self.assertEqual(flt(invoice.exonerated_amount, 2), 300)

    def test_tax_inclusive_prices_exonerated_customer_pays_net_price(self):
        self.use_included_prices()
        self.make_exonerated_customer()
        order = self.sale.make_order(
            {"item_code": self.make_item(15, 115)}, {"item_code": self.make_item(18, 118), "discount_percentage": 10},
            {"item_code": self.make_item(0, 100)},
        )
        self.assertEqual(order["grand_total"], 290)
        invoice = self.pay_exonerated(order, 290)
        self.assert_parity(order, invoice)
        self.assertEqual(flt(invoice.isv_15) + flt(invoice.isv_18), 0)

    # ------------------------------------------------- 2. tip as a liability

    def test_tip_is_a_liability_outside_the_invoice_and_reverses_on_cancel(self):
        liability = ensure_tip_liability_account(self.company)
        order = self.set_tip(self.sale.make_order({"item_code": self.make_item(15, 1000)}), amount=100)
        self.assertEqual(order["grand_total"], 1250)
        invoice = self.pay(order, 1250)

        self.assertEqual(flt(invoice.grand_total, 2), 1150)
        self.assertEqual(flt(invoice.isv_15, 2), 150)
        self.assertEqual(flt(invoice.paid_amount, 2), 1150)
        self.assertEqual(invoice.in_words, money_in_words(1150, invoice.currency))
        self.assertFalse([row for row in invoice.taxes if row.charge_type == "Actual"])
        self.assertFalse([row for row in invoice.taxes if "propina" in (row.description or "").lower()])

        stored = frappe.get_doc("Restaurant Order", order["name"])
        self.assertEqual(stored.tip_mode_of_payment, self.checkout.cash)
        journal = frappe.get_doc("Journal Entry", stored.tip_journal_entry)
        self.assertEqual(journal.docstatus, 1)
        self.assertEqual(flt(journal.total_debit, 2), 100)
        self.assertIn(order["name"], journal.user_remark)
        self.assertIn(invoice.name, journal.user_remark)
        cash_account = frappe.db.get_value(
            "Mode of Payment Account", {"parent": self.checkout.cash, "company": self.company}, "default_account",
        )
        rows = {row.account: row for row in journal.accounts}
        self.assertEqual(flt(rows[cash_account].debit_in_account_currency, 2), 100)
        self.assertEqual(flt(rows[liability].credit_in_account_currency, 2), 100)
        gl_accounts = frappe.get_all("GL Entry", filters={
            "voucher_type": "Journal Entry", "voucher_no": journal.name, "is_cancelled": 0,
        }, pluck="account")
        root_types = {frappe.db.get_value("Account", account, "root_type") for account in gl_accounts}
        self.assertNotIn("Income", root_types)
        self.assertEqual(frappe.db.get_value("Account", liability, "root_type"), "Liability")

        html = self.ticket(invoice)
        self.assertEqual(self.ticket_amount(html, "TOTAL FACTURA L."), 1150)
        self.assertEqual(self.ticket_amount(html, "PROPINA VOLUNTARIA (PERSONAL): L."), 100)
        self.assertEqual(self.ticket_amount(html, "TOTAL COBRADO EN TRANSACCIÓN: L."), 1250)
        self.assertIn("no forma parte del total facturado", html)
        self.assertLess(html.index("Son:"), html.index("PROPINA VOLUNTARIA"))
        self.assertLess(html.index("TOTAL FACTURA L."), html.index("PROPINA VOLUNTARIA"))

        invoice.cancel()
        self.assertEqual(frappe.db.get_value("Journal Entry", journal.name, "docstatus"), 2)
        reopened = frappe.get_doc("Restaurant Order", order["name"])
        self.assertEqual(reopened.status, "En curso")
        self.assertFalse(reopened.sales_invoice)
        self.assertFalse(reopened.tip_journal_entry)
        self.assertFalse(reopened.tip_mode_of_payment)

    def test_tip_defaults_to_the_electronic_payment_and_cash_count_reconciles(self):
        ensure_tip_liability_account(self.company)
        order = self.set_tip(self.sale.make_order({"item_code": self.make_item(15, 100)}), percentage=10)
        self.assertEqual(order["tip_amount"], 10)
        invoice = self.checkout.invoice(order, [
            {"mode_of_payment": self.checkout.cash, "amount": 50},
            {"mode_of_payment": self.checkout.bank, "amount": 75},
        ])
        payments = {row.mode_of_payment: flt(row.amount, 2) for row in invoice.payments}
        self.assertEqual(payments, {self.checkout.cash: 50, self.checkout.bank: 65})
        self.assertEqual(
            frappe.db.get_value("Restaurant Order", order["name"], "tip_mode_of_payment"), self.checkout.bank,
        )

        snapshot = cash_count.get_cash_count_preview(self.checkout.shift)
        rows = {row["mode_of_payment"]: row for row in snapshot["payment_methods"]}
        self.assertEqual(rows[self.checkout.bank]["sales_amount"], 65)
        self.assertEqual(rows[self.checkout.bank]["tip_amount"], 10)
        self.assertEqual(rows[self.checkout.bank]["expected_amount"], 75)
        self.assertEqual(rows[self.checkout.cash]["expected_amount"], 50)
        self.assertEqual(snapshot["total_tips"], 10)
        self.assertEqual(snapshot["total_sales"], 115)

        response = cash_count.save_and_submit_cash_count({
            "pos_opening_shift": self.checkout.shift,
            "count_type": "Arqueo de Cierre",
            "denominations": [{"unit_value": 50, "quantity": 1, "denomination_label": "L 50"}],
            "payment_methods": [
                {"mode_of_payment": name, "counted_amount": row["expected_amount"]} for name, row in rows.items()
            ],
            "payment_details": [{"mode_of_payment": self.checkout.bank, "amount": 75, "reference": "QA-LOTE"}],
        })["cash_count"]
        self.assertEqual(response["total_difference"], 0)
        count = frappe.get_doc("Restaurant Cash Count", response["name"])
        self.assertEqual(flt(count.total_tips, 2), 10)
        closing = response["pos_closing_shift"]
        self.assertTrue(closing)
        closing_rows = {
            row.mode_of_payment: row for row in frappe.get_doc("POS Closing Shift", closing).payment_reconciliation
        }
        # POS Closing Shift reconciles invoices only: the tip is outside its expected and closing amounts.
        self.assertEqual(flt(closing_rows[self.checkout.bank].closing_amount, 2), 65)
        self.assertEqual(flt(closing_rows[self.checkout.bank].expected_amount, 2), 65)

    def test_tip_requires_a_configured_liability_account(self):
        order = self.set_tip(self.sale.make_order({"item_code": self.make_item(15, 100)}), amount=5)
        with self.assertRaisesRegex(frappe.ValidationError, "cuenta de pasivo"):
            pos.pay_and_invoice_order(
                order["name"], payments=[{"mode_of_payment": self.checkout.cash, "amount": 120}],
            )
        self.assertFalse(frappe.db.get_value("Restaurant Order", order["name"], "sales_invoice"))

    def test_tip_account_must_be_a_liability_ledger(self):
        from restaurant.checkout.tips import validate_tip_liability_account

        income = frappe.db.get_value("Account", {"company": self.company, "root_type": "Income", "is_group": 0}, "name")
        with self.assertRaisesRegex(frappe.ValidationError, "pasivo"):
            validate_tip_liability_account(income, self.company)

    # ---------------------------------------------- 3. migrate isolation

    def test_migrate_never_modifies_foreign_pos_profiles(self):
        profile = frappe.copy_doc(frappe.get_doc("POS Profile", self.sale.profile))
        profile.name = f"QA Retail {uuid4().hex[:8]}"
        profile.disable_rounded_total = 0
        profile.print_format = ""
        profile.applicable_for_users = []
        profile.insert(ignore_permissions=True, set_name=profile.name)
        before = frappe.db.get_value("POS Profile", profile.name, ["disable_rounded_total", "print_format", "modified"])

        setup.ensure_link_permissions()

        after = frappe.db.get_value("POS Profile", profile.name, ["disable_rounded_total", "print_format", "modified"])
        self.assertEqual(after, before)
        self.assertEqual(after[0], 0)
        self.assertFalse(after[1])

        setup.set_restaurant_pos_profile_defaults(profile.name)
        self.assertEqual(
            frappe.db.get_value("POS Profile", profile.name, ["disable_rounded_total", "print_format"]),
            (1, TICKET),
        )

    def test_sar_series_workaround_permissions_are_no_longer_installed(self):
        import inspect

        self.assertNotIn("Prefix sales for days", inspect.getsource(setup.ensure_cashier_permissions))
        self.assertNotIn("Daily summary series", inspect.getsource(setup.ensure_cashier_permissions))

    # ------------------------------------- 4. dish without Item Tax Template

    def make_plain_group(self):
        return frappe.get_doc({
            "doctype": "Item Group", "item_group_name": f"QA Sin ISV {uuid4().hex[:8]}",
            "parent_item_group": "All Item Groups", "is_group": 0,
        }).insert(ignore_permissions=True).name

    def new_item(self, group, **fields):
        code = f"QA-DISH-{uuid4().hex[:8]}"
        return frappe.get_doc({
            "doctype": "Item", "item_code": code, "item_name": code, "item_group": group,
            "stock_uom": self.sale.uom, "is_stock_item": 0, "is_sales_item": 1, **fields,
        })

    def test_restaurant_dish_without_tax_template_is_rejected_in_spanish(self):
        group = self.make_plain_group()
        with self.assertRaisesRegex(frappe.ValidationError, "no tiene una plantilla de impuesto"):
            self.new_item(group, restaurant_options_enabled=1).insert(ignore_permissions=True)
        dish = self.new_item(
            group, restaurant_options_enabled=1,
            taxes=[{"item_tax_template": self.config["item_tax_templates"][15]}],
        ).insert(ignore_permissions=True)
        self.assertTrue(dish.name)

    def test_dish_inherits_template_from_item_group(self):
        group = frappe.get_doc("Item Group", self.make_plain_group())
        group.append("taxes", {"item_tax_template": self.config["item_tax_templates"][18]})
        group.save(ignore_permissions=True)
        self.assertTrue(self.new_item(group.name, restaurant_options_enabled=1).insert(ignore_permissions=True).name)

    def test_non_restaurant_item_keeps_native_behavior(self):
        item = self.new_item(self.make_plain_group()).insert(ignore_permissions=True)
        self.assertTrue(item.name)
