import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import set_encrypted_password

from restaurant.kds import get_kds_state
from restaurant.pos import (
    cancel_pos_order,
    cancel_sent_order_item,
    clear_pos_order,
    save_pos_order,
    send_order_to_kitchen,
)
from restaurant.setup import ensure_employee_pos_fields, ensure_restaurant_roles


class TestWaiterPermissionsAndCancellations(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ensure_restaurant_roles()
        ensure_employee_pos_fields()

        cls.company = frappe.defaults.get_defaults().get("company") or frappe.db.get_value("Company", {}, "name")
        cls.customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
        if not cls.customer:
            cust = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": "Cliente QA Mesero",
                "customer_type": "Individual",
                "customer_group": frappe.db.get_value("Customer Group", {}, "name") or "Individual",
                "territory": frappe.db.get_value("Territory", {}, "name") or "All Territories",
            }).insert(ignore_permissions=True)
            cls.customer = cust.name

        cls.item_code = frappe.db.get_value("Item", {"disabled": 0, "is_sales_item": 1}, "name")
        if not cls.item_code:
            item = frappe.get_doc({
                "doctype": "Item",
                "item_code": "QA-PLATO-MESERO",
                "item_name": "Plato QA Mesero",
                "item_group": frappe.db.get_value("Item Group", {}, "name") or "Products",
                "stock_uom": frappe.db.get_value("UOM", {}, "name") or "Nos",
                "is_sales_item": 1,
                "is_stock_item": 0,
            }).insert(ignore_permissions=True)
            cls.item_code = item.name

        cls.waiter_user = "qa.mesero.rbac@leaf.local"
        cls.supervisor_user = "qa.supervisor.rbac@leaf.local"
        cls.waiter_emp = cls._ensure_user_and_employee(cls.waiter_user, "QA Mesero", "Restaurant User", "1111")
        cls.supervisor_emp = cls._ensure_user_and_employee(cls.supervisor_user, "QA Supervisor", "Restaurant Manager", "9999")

    @classmethod
    def _ensure_user_and_employee(cls, email, full_name, role, pin):
        if not frappe.db.exists("User", email):
            frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": full_name,
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
                "roles": [{"role": role}],
            }).insert(ignore_permissions=True)
        emp_name = frappe.db.get_value("Employee", {"user_id": email}, "name")
        if not emp_name:
            emp = frappe.get_doc({
                "doctype": "Employee",
                "first_name": full_name,
                "company": cls.company,
                "gender": frappe.db.get_value("Gender", {}, "name") or "Male",
                "date_of_birth": "1995-01-01",
                "date_of_joining": "2026-01-01",
                "status": "Active",
                "user_id": email,
            }).insert(ignore_permissions=True)
            emp_name = emp.name
        set_encrypted_password("Employee", emp_name, pin, fieldname="restaurant_pos_pin")
        return emp_name

    def setUp(self):
        frappe.set_user(self.waiter_user)
        frappe.cache().delete_value(f"rpos_sup_fail:{self.waiter_user}:{self.supervisor_user}")

    def tearDown(self):
        frappe.set_user("Administrator")

    def _create_draft_order_with_items(self, qty=2):
        res = save_pos_order({
            "order_name": "Mesa QA Mesero",
            "service_type": "Comer en el local",
            "customer": self.customer,
            "waiter": self.waiter_emp,
            "items": [
                {
                    "item_code": self.item_code,
                    "qty": qty,
                    "base_rate": 100,
                    "tax_rate": 15,
                }
            ],
        })
        return res["order"]

    def test_01_to_04_waiter_draft_edit_and_send_to_kitchen(self):
        # Prueba 1 & 2: Crear cuenta y agregar platillos
        order = self._create_draft_order_with_items(qty=2)
        self.assertEqual(len(order["items"]), 1)
        self.assertEqual(order["items"][0]["kds_status"], "Pendiente")

        # Prueba 3: Retirar platillo en borrador antes de enviar a cocina
        cleared_draft = save_pos_order({
            "name": order["name"],
            "expected_modified": order["modified"],
            "items": [],
        })["order"]
        self.assertEqual(len(cleared_draft["items"]), 0)

        # Agregar nuevamente y enviar a cocina (Prueba 4)
        updated = save_pos_order({
            "name": cleared_draft["name"],
            "expected_modified": cleared_draft["modified"],
            "items": [{"item_code": self.item_code, "qty": 2, "base_rate": 100, "tax_rate": 15}],
        })["order"]
        sent = send_order_to_kitchen(updated["name"], station="ALL")["order"]
        self.assertEqual(sent["items"][0]["kds_status"], "En preparación")

    def test_05_and_15_waiter_cannot_remove_or_tamper_sent_item_via_api(self):
        order = self._create_draft_order_with_items(qty=2)
        sent = send_order_to_kitchen(order["name"], station="ALL")["order"]
        row_name = sent["items"][0]["name"]

        # Prueba 5 & 11: Omitir línea enviada en save_pos_order debe rechazarse
        with self.assertRaises(frappe.PermissionError):
            save_pos_order({
                "name": sent["name"],
                "expected_modified": sent["modified"],
                "items": [],
            })

        # Prueba 15: Reducir cantidad o revertir kds_status a Pendiente debe rechazarse
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            save_pos_order({
                "name": sent["name"],
                "expected_modified": sent["modified"],
                "items": [{
                    "name": row_name,
                    "item_code": self.item_code,
                    "qty": 1,
                    "base_rate": 100,
                    "kds_status": "Pendiente",
                }],
            })

    def test_06_and_07_supervisor_pin_validation_audit_and_kds_sync(self):
        order = self._create_draft_order_with_items(qty=2)
        sent = send_order_to_kitchen(order["name"], station="ALL")["order"]
        row_name = sent["items"][0]["name"]

        # Prueba 6: PIN incorrecto rechaza sin modificar la orden
        with self.assertRaises(frappe.PermissionError):
            cancel_sent_order_item(
                order_name=sent["name"],
                item_row_name=row_name,
                cancel_qty=1,
                supervisor_user=self.supervisor_user,
                supervisor_pin="0000",
                reason="Error de digitación",
            )

        # Autoautorización del mesero debe rechazarse
        with self.assertRaises(frappe.PermissionError):
            cancel_sent_order_item(
                order_name=sent["name"],
                item_row_name=row_name,
                cancel_qty=1,
                supervisor_user=self.waiter_user,
                supervisor_pin="1111",
                reason="Intento propio",
            )

        # Prueba 7: PIN válido de supervisor (sin enviar supervisor_user) procesa cancelación y registra al supervisor en auditoría
        res = cancel_sent_order_item(
            order_name=sent["name"],
            item_row_name=row_name,
            cancel_qty=1,
            supervisor_user=None,
            supervisor_pin="9999",
            reason="Cliente cambió de opinión",
        )
        updated_order = res["order"]
        cancelled_rows = [r for r in updated_order["items"] if r["is_cancelled"]]
        active_rows = [r for r in updated_order["items"] if not r["is_cancelled"]]
        self.assertEqual(len(cancelled_rows), 1)
        self.assertEqual(cancelled_rows[0]["kds_status"], "Cancelado")
        self.assertEqual(cancelled_rows[0]["cancelled_by_supervisor"], self.supervisor_user)
        self.assertEqual(active_rows[0]["qty"], 1)
        self.assertEqual(updated_order["subtotal"], active_rows[0]["rate"])

        # Bitácora registrada
        audit_exists = frappe.db.exists(
            "Restaurant Audit Log",
            {"restaurant_order": sent["name"], "supervisor_user": self.supervisor_user, "result": "Autorizado"},
        )
        self.assertTrue(audit_exists)

        # Prueba 12: KDS mantiene el estado Cancelado en la fila cancelada (consultado por pantalla/supervisor)
        frappe.set_user(self.supervisor_user)
        kds_state = get_kds_state()
        self.assertIsNotNone(kds_state)
        doc_after = frappe.get_doc("Restaurant Order", sent["name"])
        self.assertTrue(any(r.kds_status == "Cancelado" for r in doc_after.items))

    def test_08_to_10_cancel_and_clear_order_require_supervisor(self):
        order = self._create_draft_order_with_items(qty=1)
        sent = send_order_to_kitchen(order["name"], station="ALL")["order"]

        # Prueba 10: Vaciar orden confirmada sin PIN debe fallar
        with self.assertRaises(frappe.PermissionError):
            clear_pos_order(order_name=sent["name"], reason="Intento sin PIN")

        # Vaciar con PIN válido conserva trazabilidad de cancelación
        cleared = clear_pos_order(
            order_name=sent["name"],
            supervisor_user=self.supervisor_user,
            supervisor_pin="9999",
            reason="Mesa se retiró antes de servir",
        )["order"]
        self.assertEqual(cleared["subtotal"], 0)
        self.assertTrue(all(r["is_cancelled"] for r in cleared["items"]))

        # Prueba 8: Cancelar orden completa sin PIN debe fallar
        with self.assertRaises(frappe.PermissionError):
            cancel_pos_order(order_name=sent["name"], reason="Intento sin PIN")

        cancelled = cancel_pos_order(
            order_name=sent["name"],
            supervisor_user=self.supervisor_user,
            supervisor_pin="9999",
            reason="Cuenta anulada",
        )["order"]
        self.assertEqual(cancelled["status"], "Cancelada")

        # Prueba 9 & 11: Eliminar físicamente vía delete_doc debe rechazarse
        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc("Restaurant Order", sent["name"])

    def test_13_and_14_effective_rbac_permissions_for_waiter(self):
        # Prueba 13: Leer, crear, escribir e imprimir permitidos
        self.assertTrue(frappe.has_permission("Restaurant Order", "read", user=self.waiter_user))
        self.assertTrue(frappe.has_permission("Restaurant Order", "create", user=self.waiter_user))
        self.assertTrue(frappe.has_permission("Restaurant Order", "write", user=self.waiter_user))
        self.assertTrue(frappe.has_permission("Restaurant Order", "print", user=self.waiter_user))

        # Prueba 14: Delete denegado y sin acceso a Restaurant Audit Log
        self.assertFalse(frappe.has_permission("Restaurant Order", "delete", user=self.waiter_user))
        self.assertFalse(frappe.has_permission("Restaurant Table", "delete", user=self.waiter_user))
        self.assertFalse(frappe.has_permission("Restaurant Area", "delete", user=self.waiter_user))
        self.assertFalse(frappe.has_permission("Restaurant Audit Log", "read", user=self.waiter_user))
        self.assertFalse(frappe.has_permission("Restaurant Audit Log", "write", user=self.waiter_user))
        self.assertFalse(frappe.has_permission("Restaurant Audit Log", "delete", user=self.waiter_user))
