"""Integration tests for Restaurant Sales Invoice stock movements."""

import json
from uuid import uuid4

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, now_datetime

from restaurant import pos
from restaurant.tests.fixtures import ensure_restaurant_test_baseline, item_tax_rows


class TestRestaurantInvoiceStock(FrappeTestCase):
    def setUp(self):
        super().setUp()
        ensure_restaurant_test_baseline()
        original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.addCleanup(frappe.set_user, original_user)
        self.addCleanup(frappe.clear_cache)
        self.savepoint = f"restaurant_invoice_stock_{uuid4().hex}"
        frappe.db.savepoint(self.savepoint)
        self.addCleanup(frappe.db.rollback, save_point=self.savepoint)

        self.company = pos._get_default_company()
        source_profile = pos._get_default_pos_profile(self.company)
        self.assertTrue(source_profile, "Development requires a POS Profile with a test SAR series")
        self.customer = source_profile.customer or pos._get_default_customer()
        self.uom = frappe.db.get_value("UOM", {"must_be_whole_number": 1}, "name")
        self.item_group = frappe.db.get_value(
            "Item Group", {"is_group": 0, "name": ["not in", ["Servicios", "Sub-ensambles", "Materia prima"]]},
            "name",
        )
        self.suffix = uuid4().hex[:8]
        self.warehouse = self.make_warehouse("POS")
        profile = frappe.copy_doc(frappe.get_doc("POS Profile", source_profile.name))
        profile.name = f"QA Stock POS {self.suffix}"
        profile.warehouse = self.warehouse
        profile.update_stock = 1
        profile.applicable_for_users = []
        profile.insert(ignore_permissions=True, set_name=profile.name)
        self.profile = profile.name
        self.mode_of_payment = profile.payments[0].mode_of_payment
        self.set_auto_submit(1)
        frappe.get_doc({
            "doctype": "POS Opening Shift",
            "period_start_date": now_datetime(),
            "company": self.company,
            "user": "Administrator",
            "pos_profile": self.profile,
            "balance_details": [{"mode_of_payment": self.mode_of_payment, "opening_amount": 0}],
        }).insert(ignore_permissions=True).submit()

    def make_warehouse(self, label):
        return frappe.get_doc({
            "doctype": "Warehouse",
            "warehouse_name": f"QA Restaurant Stock {label} {self.suffix}",
            "company": self.company,
            "parent_warehouse": frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 1}, "name"),
        }).insert(ignore_permissions=True).name

    def make_item(self, label, is_stock_item=1, **fields):
        code = f"QA-RESTAURANT-STOCK-{label}-{self.suffix}"
        return frappe.get_doc({
            "doctype": "Item",
            "item_code": code,
            "item_name": code,
            "item_group": self.item_group,
            "stock_uom": self.uom,
            "is_sales_item": 1,
            "is_stock_item": is_stock_item,
            "taxes": item_tax_rows(),
            **fields,
        }).insert(ignore_permissions=True).name

    def set_auto_submit(self, enabled):
        frappe.db.set_default(
            f"rpos_cfg_{self.profile}",
            json.dumps({"auto_validate_orders": enabled, "enabled_payments": [self.mode_of_payment]}),
        )

    def receive_stock(self, item, qty, warehouse=None):
        make_stock_entry(
            item_code=item, qty=qty, company=self.company, to_warehouse=warehouse or self.warehouse, rate=10,
        )

    def stock_qty(self, item, warehouse=None):
        return flt(frappe.db.get_value(
            "Bin", {"item_code": item, "warehouse": warehouse or self.warehouse}, "actual_qty",
        ))

    def make_order(self, *rows):
        return pos.save_pos_order({
            "order_name": f"QA-{self.suffix}",
            "company": self.company,
            "pos_profile": self.profile,
            "customer": self.customer,
            "service_type": "Para llevar",
            "items": [
                {"item_code": row["item_code"], "qty": 1, "base_rate": 100, **row}
                for row in rows
            ],
        })["order"]

    def pay(self, order):
        result = pos.pay_and_invoice_order(
            order["name"],
            payments=[{"mode_of_payment": self.mode_of_payment, "amount": order["grand_total"]}],
        )
        return frappe.get_doc("Sales Invoice", result["invoice"]["name"])

    def invoice_ledger(self, invoice):
        return frappe.get_all(
            "Stock Ledger Entry",
            filters={"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
            fields=["item_code", "warehouse", "actual_qty"],
        )

    def assert_stock_rejection(self, order):
        # A failed Frappe POST rolls back the request. Mirror it for a direct Python call.
        frappe.db.savepoint("restaurant_stock_rejection")
        try:
            with self.assertRaisesRegex(frappe.ValidationError, "Existencia insuficiente"):
                self.pay(order)
        finally:
            frappe.db.rollback(save_point="restaurant_stock_rejection")
        self.assertFalse(frappe.db.exists("Sales Invoice", {"restaurant_order": order["name"]}))
        current = frappe.get_doc("Restaurant Order", order["name"])
        self.assertEqual(current.status, "En curso")
        self.assertFalse(current.sales_invoice)

    def test_zero_stock_in_pos_warehouse_blocks_even_when_another_warehouse_has_stock(self):
        item = self.make_item("EMPTY")
        other_warehouse = self.make_warehouse("Other")
        self.receive_stock(item, 2, other_warehouse)
        order = self.make_order({"item_code": item})

        self.assert_stock_rejection(order)
        self.assertEqual(self.stock_qty(item), 0)
        self.assertEqual(self.stock_qty(item, other_warehouse), 2)

    def test_stock_item_requires_a_warehouse_on_the_pos_profile(self):
        item = self.make_item("NO-WAREHOUSE")
        order = self.make_order({"item_code": item})
        frappe.db.set_value("POS Profile", self.profile, "warehouse", None)

        with self.assertRaisesRegex(frappe.ValidationError, "Configura un almacén"):
            self.pay(order)
        self.assertFalse(frappe.db.exists("Sales Invoice", {"restaurant_order": order["name"]}))

    def test_exact_stock_in_mixed_invoice_posts_once_and_cancel_restores_stock(self):
        item = self.make_item("EXACT")
        service = self.make_item("NONSTOCK", is_stock_item=0)
        self.receive_stock(item, 1)
        frappe.db.set_value("POS Profile", self.profile, "update_stock", 0)
        order = self.make_order({"item_code": item}, {"item_code": service})

        invoice = self.pay(order)
        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(invoice.update_stock, 1)
        self.assertEqual(invoice.restaurant_order, order["name"])
        self.assertEqual(frappe.db.get_value("Restaurant Order", order["name"], "sales_invoice"), invoice.name)
        self.assertEqual(self.invoice_ledger(invoice), [
            {"item_code": item, "warehouse": self.warehouse, "actual_qty": -1},
        ])
        self.assertEqual(self.stock_qty(item), 0)
        with self.assertRaisesRegex(frappe.ValidationError, "ya fue facturada"):
            self.pay(order)
        self.assertEqual(len(self.invoice_ledger(invoice)), 1)
        self.assert_stock_rejection(self.make_order({"item_code": item}))

        invoice.cancel()
        self.assertEqual(invoice.docstatus, 2)
        self.assertEqual(self.stock_qty(item), 1)
        self.assertCountEqual([row.actual_qty for row in self.invoice_ledger(invoice)], [-1, 1])

    def test_nonstock_item_can_be_invoiced_without_stock_movement(self):
        item = self.make_item("DISH", is_stock_item=0)
        invoice = self.pay(self.make_order({"item_code": item}))

        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(invoice.update_stock, 0)
        self.assertEqual(self.invoice_ledger(invoice), [])

    def test_repeated_lines_use_converted_quantity_even_if_item_allows_negative_stock(self):
        package = frappe.get_doc({
            "doctype": "UOM", "uom_name": f"QA Restaurant Pack {self.suffix}", "must_be_whole_number": 1,
        }).insert(ignore_permissions=True).name
        item = self.make_item(
            "UOM", allow_negative_stock=1,
            uoms=[{"uom": package, "conversion_factor": 2}],
        )
        self.receive_stock(item, 2)
        order = self.make_order({"item_code": item, "uom": package}, {"item_code": item, "uom": self.uom})

        self.assert_stock_rejection(order)
        self.assertEqual(self.stock_qty(item), 2)

    def test_draft_invoice_rechecks_stock_on_later_submission(self):
        item = self.make_item("DRAFT")
        self.receive_stock(item, 1)
        self.set_auto_submit(0)
        invoice = self.pay(self.make_order({"item_code": item}))
        self.assertEqual(invoice.docstatus, 0)
        self.assertEqual(invoice.update_stock, 1)
        self.assertEqual(self.invoice_ledger(invoice), [])

        invoice.update_stock = 0
        with self.assertRaisesRegex(frappe.ValidationError, "No se puede desactivar"):
            invoice.save()
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "update_stock"), 1)

        other_warehouse = self.make_warehouse("Draft Other")
        self.receive_stock(item, 1, other_warehouse)
        invoice.reload()
        invoice.set_warehouse = other_warehouse
        invoice.items[0].warehouse = other_warehouse
        with self.assertRaisesRegex(frappe.ValidationError, "No se puede cambiar el almacén"):
            invoice.save()
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "set_warehouse"), self.warehouse)

        invoice.reload()
        invoice.items[0].warehouse = other_warehouse
        with self.assertRaisesRegex(frappe.ValidationError, "debe usar el almacén"):
            invoice.save()
        self.assertEqual(self.stock_qty(item, other_warehouse), 1)

        make_stock_entry(
            item_code=item, qty=1, company=self.company, from_warehouse=self.warehouse,
        )
        invoice.reload()

        frappe.db.savepoint("restaurant_stock_draft_submit")
        try:
            with self.assertRaisesRegex(frappe.ValidationError, "Existencia insuficiente"):
                invoice.submit()
        finally:
            frappe.db.rollback(save_point="restaurant_stock_draft_submit")
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 0)
        self.assertEqual(self.invoice_ledger(invoice), [])

    def test_legacy_stock_draft_cannot_submit_without_tracking(self):
        item = self.make_item("LEGACY")
        self.receive_stock(item, 1)
        self.set_auto_submit(0)
        invoice = self.pay(self.make_order({"item_code": item}))
        # Re-create the fields persisted by Restaurant before stock tracking was enabled.
        frappe.db.set_value("Sales Invoice", invoice.name, {"update_stock": 0, "set_warehouse": None})
        invoice.reload()

        with self.assertRaisesRegex(frappe.ValidationError, "Activa la actualización de inventario"):
            invoice.submit()
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 0)
        self.assertEqual(self.stock_qty(item), 1)
        self.assertEqual(self.invoice_ledger(invoice), [])

        other_warehouse = self.make_warehouse("Legacy Other")
        self.receive_stock(item, 1, other_warehouse)
        invoice.reload()
        invoice.update_stock = 1
        invoice.set_warehouse = other_warehouse
        invoice.items[0].warehouse = other_warehouse
        with self.assertRaisesRegex(frappe.ValidationError, "No se puede cambiar el almacén"):
            invoice.save()

        invoice.reload()
        invoice.update_stock = 1
        invoice.set_warehouse = self.warehouse
        invoice.submit()
        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(self.stock_qty(item), 0)
        self.assertEqual(self.stock_qty(item, other_warehouse), 1)
        self.assertEqual(self.invoice_ledger(invoice), [
            {"item_code": item, "warehouse": self.warehouse, "actual_qty": -1},
        ])

