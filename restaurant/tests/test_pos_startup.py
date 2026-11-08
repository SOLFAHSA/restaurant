"""Read-only POS startup and role-guard regression tests without test users."""

import json
from unittest.mock import patch

import frappe
from frappe.desk.desk_page import get as get_page
from frappe.tests.utils import FrappeTestCase

from restaurant.pos import (
    _require_pos_user,
    clear_completed_kds_orders,
    get_kds_orders,
    get_pos_bootstrap,
    save_pos_order,
    send_order_to_kitchen,
    update_kds_status,
)


class TestPosStartup(FrappeTestCase):
    observed_doctypes = (
        "Sales Invoice", "POS Invoice", "Payment Entry", "Stock Entry",
        "GL Entry", "Stock Ledger Entry", "Restaurant Order", "POS Opening Shift", "User",
    )

    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.savepoint = "restaurant_pos_startup_test"
        frappe.db.savepoint(self.savepoint)
        self.document_counts = {
            doctype: frappe.db.count(doctype) for doctype in self.observed_doctypes
        }

    def tearDown(self):
        frappe.set_user("Administrator")
        try:
            self.assertEqual(
                {doctype: frappe.db.count(doctype) for doctype in self.observed_doctypes},
                self.document_counts,
                "Loading the POS must not create or remove transactions, orders, shifts or users",
            )
        finally:
            frappe.db.rollback(save_point=self.savepoint)
            frappe.set_user(self.original_user)

    def test_native_page_loader_returns_pos_script_styles_and_roles(self):
        page = get_page("restaurant-pos")
        self.assertEqual(page["name"], "restaurant-pos")
        self.assertEqual(page["module"], "Restaurant")
        self.assertIsInstance(page.get("script"), str)
        self.assertIn('frappe.pages["restaurant-pos"].on_page_load', page["script"])
        self.assertIn('"restaurant.pos.get_pos_bootstrap"', page["script"])
        for expected_token in (
            'data-menu-tile="customer-display"',
            'data-menu-tile="toggle-theme"',
            'data-menu-tile="cash-movement"',
            'data-menu-tile="create-product"',
            'data-menu-tile="reprint-commands"',
            'data-menu-tile="close-register"',
            '"restaurant.pos.create_cash_movement"',
            '"restaurant.pos.get_closing_shift_preview"',
            '"restaurant.pos.create_pos_product"',
            '"restaurant.pos.get_emitted_commands"',
        ):
            with self.subTest(expected_token=expected_token):
                self.assertIn(expected_token, page["script"])
        self.assertIsInstance(page.get("style"), str)
        self.assertIn(".rpos-shell", page["style"])
        self.assertIn(".rpos-pos-menu-grid", page["style"])
        self.assertIn(".rpos-preset-row", page["style"])
        roles = {row["role"] for row in page.get("roles", [])}
        self.assertTrue({"System Manager", "Restaurant Manager"}.issubset(roles))
        self.assertNotIn("Guest", roles)

    def test_bootstrap_uses_installed_native_schema_and_serializes_for_desk(self):
        context = get_pos_bootstrap()
        self.assertIsInstance(context, dict)
        for key in (
            "pos_profiles", "areas", "categories", "items", "waiters", "customers",
            "price_lists", "modes_of_payment", "orders", "command_stations",
        ):
            with self.subTest(key=key):
                self.assertIsInstance(context.get(key), list)
        self.assertIsInstance(context.get("cashier"), dict)
        self.assertEqual(context["cashier"].get("user"), "Administrator")
        self.assertIsInstance(context.get("company"), dict)
        self.assertIsInstance(context.get("fiscal_defaults"), dict)
        for sar_key in ("cai", "due_date_cai", "authorized_range", "prefix"):
            with self.subTest(sar_key=sar_key):
                self.assertTrue(bool(context["fiscal_defaults"].get(sar_key)))
        self.assertTrue(context.get("opening_shift") is None or isinstance(context["opening_shift"], dict))
        decoded = json.loads(frappe.as_json(context))
        self.assertEqual(decoded["cashier"]["user"], "Administrator")
        self.assertEqual(len(decoded["items"]), len(context["items"]))
        self.assertEqual(len(decoded["areas"]), len(context["areas"]))

    def test_guest_guard_rejects_access_even_with_a_mocked_operational_role(self):
        with patch.dict(frappe.local.session, {"user": "Guest"}):
            with patch("frappe.get_roles", return_value=["Restaurant Manager"]):
                with self.assertRaises(frappe.PermissionError):
                    _require_pos_user()

    def test_authenticated_user_without_page_roles_is_rejected(self):
        with patch.dict(frappe.local.session, {"user": "pos-reader@example.invalid"}):
            with patch("frappe.get_roles", return_value=["All", "Sales User"]):
                with self.assertRaises(frappe.PermissionError):
                    _require_pos_user()

    def test_operational_page_roles_are_accepted_without_creating_users(self):
        for role in ("Restaurant Manager", "System Manager", "Restaurant User"):
            with self.subTest(role=role):
                with patch.dict(frappe.local.session, {"user": "pos-operator@example.invalid"}):
                    with patch("frappe.get_roles", return_value=["All", role]):
                        _require_pos_user()

    def test_role_matrix_enforces_least_privilege_on_restaurant_order(self):
        meta = frappe.get_meta("Restaurant Order")
        perms_by_role = {p.role: p for p in meta.permissions}
        self.assertIn("System Manager", perms_by_role)
        self.assertIn("Restaurant Manager", perms_by_role)
        self.assertIn("Restaurant User", perms_by_role)
        self.assertNotIn("Guest", perms_by_role)
        self.assertEqual(perms_by_role["System Manager"].delete, 1)
        self.assertEqual(getattr(perms_by_role["System Manager"], "import"), 1)
        self.assertEqual(perms_by_role["Restaurant Manager"].delete, 1)
        self.assertEqual(perms_by_role["Restaurant User"].read, 1)
        self.assertEqual(perms_by_role["Restaurant User"].create, 1)
        self.assertEqual(perms_by_role["Restaurant User"].write, 1)
        self.assertEqual(perms_by_role["Restaurant User"].delete, 0)

    def test_kds_page_loader_and_orders_api_return_stage_metadata(self):
        kds_page = get_page("restaurant-kds")
        self.assertEqual(kds_page["name"], "restaurant-kds")
        self.assertEqual(kds_page["module"], "Restaurant")
        self.assertIsInstance(kds_page.get("script"), str)
        self.assertIn('frappe.pages["restaurant-kds"].on_page_load', kds_page["script"])
        for token in (
            "Kitchen Display",
            "Pantalla de preparación",
            "Etapas de preparación",
            "Casi lista",
            "Lista",
            "Pantalla de",
            "Pantalla del estado de",
            "En progreso",
            "Tiempo promedio",
            "Por Preparar",
            "Para Entregar",
            "Completadas",
            "Restablecer",
            "Regresar a etapa anterior",
            'data-kds-action="toggle-item"',
            '"restaurant.kds.get_kds_state"',
            '"toggle_item"',
            '"dismiss_ticket"',
            '"save_display"',
            '"save_stage"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, kds_page["script"])
        self.assertIsInstance(kds_page.get("style"), str)
        self.assertIn(".rkds-shell", kds_page["style"])
        self.assertIn(".rkds-hub-card", kds_page["style"])
        self.assertIn(".rkds-item-row.is-struck", kds_page["style"])
        self.assertIn(".rkds-card", kds_page["style"])
        self.assertIn(".rkds-card-footer", kds_page["style"])
        payload = get_kds_orders()
        self.assertIsInstance(payload, dict)
        self.assertIsInstance(payload.get("orders"), list)
        self.assertIsInstance(payload.get("counts"), dict)
        self.assertTrue(bool(payload.get("server_now")))
        for stage_key in ("Todas", "Por Preparar", "Para Entregar", "Completadas"):
            with self.subTest(stage_key=stage_key):
                self.assertIn(stage_key, payload["counts"])

    def test_kds_stage_lifecycle_por_preparar_para_entregar_completadas_restablecer_and_listo(self):
        sp = "kds_lifecycle_sp"
        frappe.db.savepoint(sp)
        try:
            ctx = get_pos_bootstrap()
            first_item = ctx["items"][0]["item_code"]
            saved = save_pos_order({
                "order_name": "KDS Test Order",
                "service_type": "Comer en el local",
                "guests": 2,
                "items": [
                    {"item_code": first_item, "qty": 1, "note": "Sides : Sweet potato fries"},
                    {"item_code": first_item, "qty": 1, "note": "Sin cebolla"},
                ],
            })
            order_name = saved["order"]["name"]
            send_order_to_kitchen(order_name)

            kds_after_send = get_kds_orders()
            matched = next((o for o in kds_after_send["orders"] if o["name"] == order_name), None)
            self.assertIsNotNone(matched)
            self.assertEqual(matched["kds_stage"], "Por Preparar")
            self.assertIsInstance(matched["kds_wait_minutes"], int)

            after_first_strike = update_kds_status(order_name, "Listo", item_idx=1)
            self.assertEqual(after_first_strike["kds_stage"], "Por Preparar")
            self.assertEqual(after_first_strike["order"]["items"][0]["kds_status"], "Listo")

            to_ready = update_kds_status(order_name, "Listo", item_idx=2)
            self.assertEqual(to_ready["kds_stage"], "Para Entregar")
            self.assertEqual(to_ready["kds_status"], "Listo")

            to_completed = update_kds_status(order_name, "Completadas")
            self.assertEqual(to_completed["kds_stage"], "Completadas")
            self.assertEqual(to_completed["kds_status"], "Entregado")

            reset_to_cook = update_kds_status(order_name, "Por Preparar")
            self.assertEqual(reset_to_cook["kds_stage"], "Por Preparar")
            self.assertEqual(reset_to_cook["kds_status"], "En preparación")

            update_kds_status(order_name, "Completadas")
            closed = update_kds_status(order_name, "Cerrado")
            self.assertEqual(closed["kds_stage"], "Cerrado")
            self.assertEqual(closed["kds_status"], "Cerrado")

            kds_after_close = get_kds_orders()
            self.assertFalse(any(o["name"] == order_name for o in kds_after_close["orders"]))

            update_kds_status(order_name, "Completadas")
            cleared = clear_completed_kds_orders([order_name])
            self.assertIn(order_name, cleared["closed_orders"])
        finally:
            frappe.db.rollback(save_point=sp)
