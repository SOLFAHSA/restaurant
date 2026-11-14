"""Tests for Restaurant POS waiter PIN locking, linked employee isolation, invoicing RBAC, and supervisor audit."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import set_encrypted_password

from restaurant import pos, pos_auth
from restaurant.setup import ensure_employee_pos_fields, ensure_restaurant_roles


class TestRestaurantPOSAuth(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        ensure_restaurant_roles()
        ensure_employee_pos_fields()

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _make_user(self, email, first_name, roles):
        if frappe.db.exists("User", email):
            doc = frappe.get_doc("User", email)
        else:
            doc = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
            })
            doc.insert(ignore_permissions=True)
        doc.set("roles", [{"role": r} for r in roles])
        doc.save(ignore_permissions=True)
        return doc.name

    def _make_waiter(self, first_name, pin=None, user_id=None):
        company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
        doc = frappe.get_doc({
            "doctype": "Employee",
            "first_name": first_name,
            "gender": "Prefer not to say",
            "date_of_birth": "1995-01-01",
            "date_of_joining": "2024-01-01",
            "status": "Active",
            "designation": "Mesero",
            "company": company,
            "user_id": user_id or "",
        })
        doc.insert(ignore_permissions=True)
        if pin:
            set_encrypted_password("Employee", doc.name, pin, fieldname="restaurant_pos_pin")
        return doc.name

    def test_waiter_cannot_invoice(self):
        waiter_user = self._make_user("test_mesero_rbac@example.com", "MeseroRBAC", ["Restaurant User"])
        frappe.set_user(waiter_user)
        self.assertFalse(pos_auth.user_can_invoice())
        with self.assertRaises(frappe.PermissionError):
            pos.pay_and_invoice_order("NON-EXISTENT-ORDER", payments=[])

    def test_shared_terminal_waiter_pin_unlock(self):
        shared_user = self._make_user("test_meseros_shared@example.com", "MeserosShared", ["Restaurant User"])
        adrian = self._make_waiter("AdrianPIN", pin="1234")
        pedro = self._make_waiter("PedroPIN", pin="5678")
        self.assertTrue(pedro)

        company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
        order = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": "Cuenta Test PIN",
            "service_type": "Comer en el local",
            "company": company,
            "waiter": adrian,
        })
        order.insert(ignore_permissions=True)

        frappe.set_user(shared_user)
        frappe.cache().delete_value(f"rpos_unlocked:{shared_user}:{order.name}")

        with self.assertRaises(frappe.PermissionError):
            pos.unlock_waiter_order(order.name, "5678")

        res = pos.unlock_waiter_order(order.name, "1234")
        self.assertTrue(res["unlocked"])
        self.assertTrue(pos_auth.is_order_unlocked_for_session(order.name))

    def test_supervisor_pin_authorization_and_audit(self):
        waiter_user = self._make_user("test_mesero_sup@example.com", "MeseroSup", ["Restaurant User"])
        sup_user = self._make_user("test_sup_pos@example.com", "SupervisorPOS", ["Restaurant Manager"])
        self._make_waiter("SupervisorEmp", pin="9999", user_id=sup_user)

        frappe.set_user(waiter_user)
        with self.assertRaises(frappe.PermissionError):
            pos.authorize_clear_order(supervisor_user=sup_user, supervisor_pin="0000", reason="Prueba")

        res = pos.authorize_clear_order(
            supervisor_user=sup_user,
            supervisor_pin="9999",
            reason="Corrección autorizada",
        )
        self.assertTrue(res["authorized"])
        self.assertEqual(res["supervisor"], sup_user)

        audit_exists = frappe.db.exists(
            "Activity Log",
            {"user": waiter_user, "subject": ["like", "%Vaciar orden%"]},
        )
        self.assertTrue(audit_exists)

    def test_linked_employee_waiter_isolation(self):
        u1 = self._make_user("test_mesero1@example.com", "MeseroUno", ["Restaurant User"])
        u2 = self._make_user("test_mesero2@example.com", "MeseroDos", ["Restaurant User"])
        emp1 = self._make_waiter("JuanLinked", user_id=u1)
        emp2 = self._make_waiter("CarlosLinked", user_id=u2)

        company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
        order_emp1 = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": "Cuenta Juan",
            "service_type": "Comer en el local",
            "company": company,
            "waiter": emp1,
        })
        order_emp1.insert(ignore_permissions=True)

        frappe.set_user(u2)
        linked = pos_auth.get_linked_employee_for_user()
        self.assertEqual(linked["name"], emp2)
        with self.assertRaises(frappe.PermissionError):
            pos.save_pos_order({"name": order_emp1.name, "order_name": "Intento cambio"})

    def test_cashier_bypasses_waiter_pin_and_needs_supervisor_for_cancel(self):
        cashier_user = self._make_user(
            "test_cajero@example.com",
            "CajeroTest",
            ["Restaurant User", "Restaurant Cashier"],
        )
        adrian = self._make_waiter("AdrianCashierTest", pin="4321")
        company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
        order = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": "Cuenta Mesero para Cajero",
            "service_type": "Comer en el local",
            "company": company,
            "waiter": adrian,
        })
        order.insert(ignore_permissions=True)

        frappe.set_user(cashier_user)
        self.assertTrue(pos_auth.user_can_invoice())
        self.assertTrue(pos_auth.is_cashier_only())
        self.assertFalse(pos_auth.is_waiter_only())
        self.assertFalse(pos_auth.is_supervisor())

        saved = pos.save_pos_order({"name": order.name, "order_name": "Actualizada por Cajero"})
        self.assertEqual(saved["order"]["order_name"], "Actualizada por Cajero")

        with self.assertRaises(frappe.PermissionError):
            pos.cancel_pos_order(order.name)

    def test_direct_cashier_cannot_assign_table(self):
        direct_user = self._make_user(
            "test_cajero_directo@example.com",
            "CajeroDirecto",
            ["Restaurant Cashier", "Restaurant Direct Cashier"],
        )
        frappe.set_user(direct_user)
        self.assertTrue(pos_auth.user_can_invoice())
        self.assertTrue(pos_auth.is_direct_cashier())
        with self.assertRaises(frappe.PermissionError):
            pos.save_pos_order({"order_name": "Intento Mesa", "restaurant_table": "MESA-FAKE"})

