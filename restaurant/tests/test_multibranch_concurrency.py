"""Multi-branch and multi-terminal concurrency tests for Restaurant POS and KDS."""

import unittest
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant import kds, order_operations, pos
from restaurant.setup import ensure_link_permissions, ensure_restaurant_roles


class TestQAMultiBranchConcurrency(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        ensure_restaurant_roles()
        ensure_link_permissions()
        self.suffix = uuid4().hex[:6]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _make_branch(self, label):
        name = f"{label}-{self.suffix}"
        return frappe.get_doc({"doctype": "Branch", "branch": name}).insert(ignore_permissions=True).name

    def _make_area_and_table(self, branch, area_label, table_label):
        area = frappe.get_doc({
            "doctype": "Restaurant Area",
            "area_name": f"{area_label}-{self.suffix}",
            "branch": branch,
            "capacity": 20,
            "display_order": 1,
            "enabled": 1,
            "floor_background": "Madera cálida",
        }).insert(ignore_permissions=True)
        table = frappe.get_doc({
            "doctype": "Restaurant Table",
            "table_number": f"{table_label}-{self.suffix}",
            "restaurant_area": area.name,
            "branch": branch,
            "seats": 4,
            "status": "Disponible",
        }).insert(ignore_permissions=True)
        return area.name, table.name

    def _make_item(self):
        item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
        uom = frappe.db.get_value("UOM", {"must_be_whole_number": 1}, "name") or "Nos"
        return frappe.get_doc({
            "doctype": "Item",
            "item_code": f"MB-ITEM-{self.suffix}",
            "item_name": f"Platillo MB {self.suffix}",
            "item_group": item_group,
            "stock_uom": uom,
            "is_stock_item": 0,
            "standard_rate": 120.0,
        }).insert(ignore_permissions=True).name

    def _make_customer(self):
        existing = frappe.db.get_value("Customer", {}, "name")
        if existing:
            return existing
        return frappe.get_doc({
            "doctype": "Customer",
            "customer_name": f"Cliente MB {self.suffix}",
        }).insert(ignore_permissions=True).name

    def test_stale_expected_modified_rejected_on_transfer(self):
        """PASS: Two PCs racing on transfer_account are protected by expected_modified."""
        branch = self._make_branch("SucA")
        _a1, table1 = self._make_area_and_table(branch, "Salon1", "M1")
        _a2, table2 = self._make_area_and_table(branch, "Salon2", "M2")
        item = self._make_item()
        customer = self._make_customer()

        order = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": f"MB-ORD-{self.suffix}",
            "customer": customer,
            "restaurant_table": table1,
            "items": [{"item_code": item, "qty": 1, "base_rate": 120.0}],
        }).insert(ignore_permissions=True)
        stale_modified = "2000-01-01 00:00:00"

        with self.assertRaises(frappe.TimestampMismatchError):
            order_operations.transfer_account(
                order.name,
                target_table=table2,
                expected_modified=stale_modified,
            )

    def test_kds_stale_stage_rejected(self):
        """PASS: Concurrent KDS stage updates are guarded by _check_expected_stage."""
        with self.assertRaises(frappe.TimestampMismatchError):
            kds._check_expected_stage({"stages": [{"name": "Listo"}], "stage_index": 0}, "En preparación")

    @unittest.expectedFailure
    def test_save_pos_order_requires_fresh_modified_when_updating(self):
        """DEF-MB-003: save_pos_order ignores stale 'modified' if 'expected_modified' is omitted."""
        item = self._make_item()
        customer = self._make_customer()
        order = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": f"MB-RACE-{self.suffix}",
            "customer": customer,
            "items": [{"item_code": item, "qty": 1, "base_rate": 120.0}],
        }).insert(ignore_permissions=True)

        with self.assertRaises(frappe.TimestampMismatchError):
            pos.save_pos_order({
                "name": order.name,
                "order_name": order.order_name,
                "customer": customer,
                "modified": "2000-01-01 00:00:00",
                "items": [{"item_code": item, "qty": 2, "base_rate": 120.0}],
            })

    @unittest.expectedFailure
    def test_transfer_account_blocks_cross_branch_table(self):
        """DEF-MB-008: transfer_account currently allows moving an order to a table in another Branch."""
        branch_a = self._make_branch("SucursalA")
        branch_b = self._make_branch("SucursalB")
        _a1, table_a = self._make_area_and_table(branch_a, "SalonA", "A1")
        _a2, table_b = self._make_area_and_table(branch_b, "SalonB", "B1")
        item = self._make_item()
        customer = self._make_customer()

        order = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": f"MB-XBR-{self.suffix}",
            "customer": customer,
            "restaurant_table": table_a,
            "items": [{"item_code": item, "qty": 1, "base_rate": 120.0}],
        }).insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            order_operations.transfer_account(
                order.name,
                target_table=table_b,
                expected_modified=str(order.modified),
            )

