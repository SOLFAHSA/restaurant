"""Regression and RBAC security tests for Restaurant POS and Cash Count."""

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant import order_operations, pos
from restaurant.setup import ensure_link_permissions, ensure_restaurant_roles


class TestRBACSecurityRegression(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        ensure_restaurant_roles()
        ensure_link_permissions()
        self.suffix = uuid4().hex[:6]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _make_user(self, prefix, roles):
        email = f"{prefix}-{self.suffix}@leaf.test"
        doc = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": prefix,
            "enabled": 1,
            "user_type": "System User",
            "send_welcome_email": 0,
            "roles": [{"role": r} for r in roles],
        }).insert(ignore_permissions=True)
        return doc.name

    def _make_item(self, rate=100.0):
        item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
        uom = frappe.db.get_value("UOM", {"must_be_whole_number": 1}, "name") or "Nos"
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": f"QA-ITEM-{self.suffix}",
            "item_name": f"Platillo QA {self.suffix}",
            "item_group": item_group,
            "stock_uom": uom,
            "is_stock_item": 0,
            "standard_rate": rate,
        }).insert(ignore_permissions=True)
        return item.name

    def _make_area_and_table(self, status="Disponible"):
        branch = frappe.db.get_value("Branch", {}, "name")
        if not branch:
            branch = frappe.get_doc({"doctype": "Branch", "branch": f"Sucursal QA {self.suffix}"}).insert(ignore_permissions=True).name
        area = frappe.get_doc({
            "doctype": "Restaurant Area",
            "area_name": f"Salon QA {self.suffix}",
            "branch": branch,
            "capacity": 20,
            "display_order": 1,
            "enabled": 1,
            "floor_background": "Madera cálida",
        }).insert(ignore_permissions=True)
        table = frappe.get_doc({
            "doctype": "Restaurant Table",
            "table_number": f"T-{self.suffix}",
            "restaurant_area": area.name,
            "branch": branch,
            "seats": 4,
            "status": status,
        }).insert(ignore_permissions=True)
        return area.name, table.name

    def test_waiter_cannot_open_or_close_pos_shift(self):
        waiter = self._make_user("qa-waiter-shift", ["Restaurant User"])
        frappe.set_user(waiter)
        with self.assertRaises(frappe.PermissionError):
            pos.open_pos_shift()
        with self.assertRaises(frappe.PermissionError):
            pos.close_pos_shift("NO-SHIFT")

    def test_waiter_cannot_create_cash_movement(self):
        waiter = self._make_user("qa-waiter-mv", ["Restaurant User"])
        frappe.set_user(waiter)
        with self.assertRaises(frappe.PermissionError):
            pos.create_cash_movement("Retiro", 50.0, note="Prueba no autorizada")

    def test_direct_cashier_blocked_on_table_transfer(self):
        direct_cashier = self._make_user("qa-direct", ["Restaurant Cashier", "Restaurant Direct Cashier"])
        _area, table_name = self._make_area_and_table("Disponible")
        frappe.set_user(direct_cashier)
        with self.assertRaises(frappe.PermissionError):
            order_operations.transfer_account("ORD-DUMMY", target_table=table_name)

    def test_waiter_has_read_only_table_area_customer_permissions(self):
        waiter = self._make_user("qa-waiter-perms", ["Restaurant User"])
        frappe.set_user(waiter)
        for doctype in ("Restaurant Table", "Restaurant Area", "Customer"):
            self.assertTrue(frappe.has_permission(doctype, "read"), f"{doctype} should be readable by Restaurant User")
            self.assertTrue(frappe.has_permission(doctype, "select"), f"{doctype} should be selectable by Restaurant User")
        for doctype in ("Restaurant Table", "Restaurant Area"):
            self.assertFalse(frappe.has_permission(doctype, "write"), f"{doctype} must not be writable by Restaurant User")
            self.assertFalse(frappe.has_permission(doctype, "create"), f"{doctype} must not be creatable by Restaurant User")
            self.assertFalse(frappe.has_permission(doctype, "delete"), f"{doctype} must not be deletable by Restaurant User")

    def test_inactive_table_rejected_on_order(self):
        _area, inactive_table = self._make_area_and_table("Inactiva")
        item_code = self._make_item(100.0)
        customer = frappe.db.get_value("Customer", {}, "name")
        if not customer:
            customer = frappe.get_doc({"doctype": "Customer", "customer_name": f"Cliente QA {self.suffix}"}).insert(ignore_permissions=True).name

        order = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": f"QA-INACT-{self.suffix}",
            "customer": customer,
            "restaurant_table": inactive_table,
            "items": [{"item_code": item_code, "qty": 1, "base_rate": 100.0}],
        })
        with self.assertRaises(frappe.ValidationError):
            order.insert(ignore_permissions=True)

    def test_underpayment_rejected_on_invoice(self):
        item_code = self._make_item(100.0)
        customer = frappe.db.get_value("Customer", {}, "name")
        if not customer:
            customer = frappe.get_doc({"doctype": "Customer", "customer_name": f"Cliente QA {self.suffix}"}).insert(ignore_permissions=True).name
        company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
        pos_profile = frappe.db.get_value("POS Profile", {"company": company}, "name")
        mode_of_payment = frappe.db.get_value("Mode of Payment", {}, "name") or "Cash"

        order = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": f"QA-PAY-{self.suffix}",
            "customer": customer,
            "company": company,
            "pos_profile": pos_profile,
            "items": [{"item_code": item_code, "qty": 1, "base_rate": 100.0}],
        }).insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            pos.pay_and_invoice_order(
                order.name,
                payments=[{"mode_of_payment": mode_of_payment, "amount": 10.0}],
            )

