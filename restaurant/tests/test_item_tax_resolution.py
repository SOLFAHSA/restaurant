"""Item tax rates come from native templates: the item first, then its item groups."""

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant.pos import _get_item_tax_rates
from restaurant.tax_configuration import get_item_tax_template
from restaurant.tests import test_invoice_stock


class TestItemTaxResolution(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.sale = test_invoice_stock.TestRestaurantInvoiceStock()
        self.addCleanup(self.sale.doCleanups)
        self.sale.setUp()
        self.company = self.sale.company
        self.suffix = uuid4().hex[:8]
        self.root_group = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ["is", "not set"]}, "name")

    def make_group(self, label, parent=None, is_group=0, rate=None):
        group = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": f"QA Impuesto {label} {self.suffix}",
            "parent_item_group": parent or self.root_group,
            "is_group": is_group,
        })
        if rate is not None:
            group.append("taxes", {"item_tax_template": get_item_tax_template(self.company, rate, create=True)})
        return group.insert(ignore_permissions=True).name

    def make_item(self, group, rate=None):
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": f"QA-TAX-{uuid4().hex[:10]}",
            "item_name": "Producto de prueba fiscal",
            "item_group": group,
            "stock_uom": self.sale.uom,
            "is_stock_item": 0,
            "is_sales_item": 1,
            "standard_rate": 100,
        })
        if rate is not None:
            item.append("taxes", {"item_tax_template": get_item_tax_template(self.company, rate, create=True)})
        return item.insert(ignore_permissions=True).name

    def test_item_template_wins_over_its_group(self):
        item = self.make_item(self.make_group("Comidas", rate=15), rate=0)
        self.assertEqual(_get_item_tax_rates([item], self.company)[item], 0.0)

    def test_item_without_template_inherits_its_group(self):
        item = self.make_item(self.make_group("Licores", rate=18))
        self.assertEqual(_get_item_tax_rates([item], self.company)[item], 18.0)

    def test_template_is_inherited_from_a_parent_group(self):
        parent = self.make_group("Bebidas alcohólicas", is_group=1, rate=18)
        item = self.make_item(self.make_group("Cervezas", parent=parent))
        self.assertEqual(_get_item_tax_rates([item], self.company)[item], 18.0)

    def test_template_of_another_company_is_ignored(self):
        item = self.make_item(self.make_group("Otra empresa"), rate=15)
        self.assertIsNone(_get_item_tax_rates([item], f"Empresa inexistente {self.suffix}")[item])

    def test_order_rejects_item_without_any_template(self):
        item = self.make_item(self.make_group("Sin impuesto"))
        self.assertIsNone(_get_item_tax_rates([item], self.company)[item])
        with self.assertRaisesRegex(frappe.ValidationError, "plantilla de impuesto"):
            self.sale.make_order({"item_code": item})
