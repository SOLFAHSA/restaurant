"""POS catalog prices for users without Item Price permission."""

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant.pos import _get_catalog_for_pos


class TestPosCatalogPrices(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.addCleanup(frappe.set_user, "Administrator")
        self.savepoint = f"pos_catalog_prices_{uuid4().hex[:8]}"
        frappe.db.savepoint(self.savepoint)
        self.addCleanup(frappe.db.rollback, save_point=self.savepoint)

        suffix = uuid4().hex[:8]
        currency = frappe.db.get_value("Company", frappe.db.get_value("Company", {}, "name"), "default_currency")
        self.selling_list = self.make_price_list(f"QA Venta {suffix}", currency, selling=1)
        self.buying_list = self.make_price_list(f"QA Compra {suffix}", currency, buying=1)
        self.item = frappe.get_doc({
            "doctype": "Item",
            "item_code": f"QA-CATALOG-{suffix}",
            "item_name": f"Producto de catálogo {suffix}",
            "item_group": frappe.db.get_value(
                "Item Group", {"is_group": 0, "name": ["not in", ["Servicios", "Sub-ensambles", "Materia prima"]]},
                "name",
            ),
            "stock_uom": frappe.db.get_value("UOM", {}, "name"),
            "is_stock_item": 0,
            "is_sales_item": 1,
        }).insert(ignore_permissions=True).name
        self.make_price(self.selling_list, 45)
        self.make_price(self.buying_list, 22)
        self.waiter = self.make_waiter(suffix)

    def make_price_list(self, name, currency, selling=0, buying=0):
        return frappe.get_doc({
            "doctype": "Price List", "price_list_name": name, "currency": currency,
            "selling": selling, "buying": buying, "enabled": 1,
        }).insert(ignore_permissions=True).name

    def make_price(self, price_list, rate):
        frappe.get_doc({
            "doctype": "Item Price", "item_code": self.item, "price_list": price_list, "price_list_rate": rate,
        }).insert(ignore_permissions=True)

    def make_waiter(self, suffix):
        return frappe.get_doc({
            "doctype": "User",
            "email": f"qa-waiter-{suffix}@example.com",
            "first_name": "Mesero QA",
            "user_type": "System User",
            "send_welcome_email": 0,
            "roles": [{"role": "Restaurant User"}],
        }).insert(ignore_permissions=True).name

    def catalog_price(self):
        _categories, items = _get_catalog_for_pos(self.selling_list)
        return next(row["price"] for row in items if row["item_code"] == self.item)

    def test_waiter_without_item_price_permission_sees_selling_price(self):
        frappe.set_user(self.waiter)
        self.assertFalse(frappe.has_permission("Item Price", "read"))
        self.assertEqual(self.catalog_price(), 45)

    def test_catalog_never_exposes_buying_prices(self):
        frappe.set_user(self.waiter)
        frappe.db.delete("Item Price", {"item_code": self.item, "price_list": self.selling_list})
        self.assertEqual(self.catalog_price(), 0)
