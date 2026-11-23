"""Combo components leave the warehouse through the native Sales Invoice and come back on cancel."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from restaurant.tests import test_invoice_stock


class TestComboStock(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.sale = test_invoice_stock.TestRestaurantInvoiceStock()
        self.addCleanup(self.sale.doCleanups)
        self.sale.setUp()

        self.combo = self.sale.make_item("COMBO", is_stock_item=0, restaurant_options_enabled=1)
        self.drink = self.sale.make_item("DRINK")
        self.water = self.sale.make_item("WATER")
        self.burger = self.sale.make_item("BURGER", is_stock_item=0)
        self.make_group("Bebidas", [("Refresco", self.drink, 1), ("Agua", self.water, 2)])
        self.make_group("Platos", [("Hamburguesa", self.burger, 1)])

    def make_group(self, name, options, effect="Incluir en combo"):
        frappe.get_doc({
            "doctype": "Restaurant Option Group",
            "main_item": self.combo,
            "group_name": name,
            "min_selections": 0,
            "max_selections": 1,
            "currency": frappe.get_cached_value("Company", self.sale.company, "default_currency"),
            "options": [
                {"option_label": label, "effect": effect,
                 **({"item_code": item, "qty": qty, "uom": self.sale.uom} if item else {})}
                for label, item, qty in options
            ],
        }).insert(ignore_permissions=True)

    def order_combo(self, qty=1, chosen=(("Bebidas", "Refresco"), ("Platos", "Hamburguesa")), tampered=None):
        options = [{"group_name": group, "option_label": label, "effect": "Incluir en combo", **(tampered or {})}
                   for group, label in chosen]
        return self.sale.make_order({
            "item_code": self.combo, "qty": qty, "selected_options": options,
        })

    def test_chosen_drink_leaves_the_warehouse_and_returns_on_cancel(self):
        self.sale.receive_stock(self.drink, 5)
        order = self.order_combo(qty=2)

        invoice = self.sale.pay(order)
        self.assertEqual(invoice.update_stock, 1)
        self.assertEqual(self.sale.invoice_ledger(invoice), [
            {"item_code": self.drink, "warehouse": self.sale.warehouse, "actual_qty": -2},
        ])
        self.assertEqual(self.sale.stock_qty(self.drink), 3)

        component = next(row for row in invoice.items if row.item_code == self.drink)
        self.assertEqual((flt(component.qty), flt(component.rate), flt(component.amount)), (2, 0, 0))
        self.assertIn("combo", component.description)
        self.assertNotIn(self.burger, [row.item_code for row in invoice.items])  # dishes are not stock
        self.assertEqual(flt(invoice.grand_total, 2), flt(order["grand_total"], 2))

        invoice.cancel()
        self.assertEqual(self.sale.stock_qty(self.drink), 5)

    def test_configured_quantity_is_multiplied_by_the_combos_sold(self):
        self.sale.receive_stock(self.water, 6)
        invoice = self.sale.pay(self.order_combo(qty=3, chosen=(("Bebidas", "Agua"),)))
        self.assertEqual(self.sale.invoice_ledger(invoice), [
            {"item_code": self.water, "warehouse": self.sale.warehouse, "actual_qty": -6},
        ])

    def test_browser_cannot_change_what_leaves_the_warehouse(self):
        self.sale.receive_stock(self.drink, 1)
        self.sale.receive_stock(self.water, 10)
        order = self.order_combo(tampered={"item_code": self.water, "qty": 10})

        invoice = self.sale.pay(order)
        self.assertEqual(self.sale.invoice_ledger(invoice), [
            {"item_code": self.drink, "warehouse": self.sale.warehouse, "actual_qty": -1},
        ])
        self.assertEqual(self.sale.stock_qty(self.water), 10)

    def test_combo_without_stock_of_its_component_is_rejected(self):
        self.sale.assert_stock_rejection(self.order_combo())
        self.assertEqual(self.sale.stock_qty(self.drink), 0)

    def test_note_only_options_do_not_move_stock(self):
        self.make_group("Término", [("Bien cocido", None, None)], effect="Solo indicación")
        invoice = self.sale.pay(self.order_combo(chosen=(("Término", "Bien cocido"),)))
        self.assertEqual(invoice.update_stock, 0)
        self.assertEqual(self.sale.invoice_ledger(invoice), [])
        self.assertEqual([row.item_code for row in invoice.items], [self.combo])
