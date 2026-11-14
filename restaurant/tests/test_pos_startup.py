"""Read-only POS startup and role-guard regression tests without test users."""

import json
from unittest.mock import patch

import frappe
from frappe.desk.desk_page import get as get_page
from frappe.tests.utils import FrappeTestCase

from restaurant.kds import get_kds_state
from restaurant.pos import (
    _require_pos_user,
    get_pos_bootstrap,
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
            'data-menu-tile="cash-count"',
            'data-menu-tile="reprint-commands"',
            'data-menu-tile="close-register"',
            '"restaurant.pos.create_cash_movement"',
            '"restaurant.pos.get_closing_shift_preview"',
            '"restaurant.pos.get_emitted_commands"',
        ):
            with self.subTest(expected_token=expected_token):
                self.assertIn(expected_token, page["script"])
        for removed_token in (
            'data-menu-tile="install-app"',
            'data-menu-tile="reload-data"',
            'data-menu-tile="create-product"',
            'data-menu-tile="idle-wallpaper"',
        ):
            with self.subTest(removed_token=removed_token):
                self.assertNotIn(removed_token, page["script"])
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
        for legacy_token in ("Por Preparar", "Para Entregar", "Completadas"):
            with self.subTest(legacy_token=legacy_token):
                self.assertNotIn(legacy_token, kds_page["script"])
        self.assertIsInstance(kds_page.get("style"), str)
        self.assertIn(".rkds-shell", kds_page["style"])
        self.assertIn(".rkds-hub-card", kds_page["style"])
        self.assertIn(".rkds-item-row.is-struck", kds_page["style"])
        self.assertIn(".rkds-card", kds_page["style"])
        self.assertIn(".rkds-card-footer", kds_page["style"])
        payload = get_kds_state()
        self.assertIsInstance(payload, dict)
        self.assertIsInstance(payload.get("orders"), list)
        self.assertIsInstance(payload.get("displays"), list)
        self.assertIsInstance(payload.get("stages_catalog"), list)
        self.assertTrue(bool(payload.get("server_now")))
        self.assertGreaterEqual(len(payload["stages_catalog"]), 3)
        stage_names = {row["stage_name"] for row in frappe.get_all("Restaurant Preparation Stage", fields=["stage_name"])}
        self.assertEqual({row["stage_name"] for row in payload["stages_catalog"]}, stage_names)

    def test_closing_shift_preview_separates_cash_movements_and_odoo_ui_tokens(self):
        from types import SimpleNamespace
        from restaurant.pos import get_closing_shift_preview

        page = get_page("restaurant-pos")
        for token in (
            "Cierre de caja registradora",
            "Diferencia de pagos",
            "Continuar de todos modos",
            "Entrada/salida de efectivo",
            "Venta diaria",
            "rpos-odoo-methods",
        ):
            with self.subTest(token=token):
                self.assertIn(token, page["script"])
        self.assertIn(".rpos-odoo-warn-overlay", page["style"])

        fake_opening = SimpleNamespace(
            name="POSA-OS-TEST-99",
            pos_profile="POS 01 HNL",
            company="Empresa Demostrativa",
            user="Administrator",
            period_start_date="2026-11-12 08:00:00",
            as_dict=lambda: {
                "name": "POSA-OS-TEST-99",
                "pos_profile": "POS 01 HNL",
                "company": "Empresa Demostrativa",
                "user": "Administrator",
                "period_start_date": "2026-11-12 08:00:00",
            },
        )
        fake_closing = frappe._dict({
            "pos_transactions": [{"name": "SINV-1"}, {"name": "SINV-2"}],
            "grand_total": 38.80,
            "payment_reconciliation": [
                SimpleNamespace(mode_of_payment="Efectivo", opening_amount=1500.0, expected_amount=1581.0),
                SimpleNamespace(mode_of_payment="Tarjetas de credito", opening_amount=0.0, expected_amount=7.80),
            ],
        })
        fake_movements = {
            "total_ingreso": 100.0,
            "total_retiro": 50.0,
            "net_cash_movement": 50.0,
            "movements": [],
        }

        with (
            patch("frappe.db.exists", return_value=True),
            patch("frappe.get_doc", return_value=fake_opening),
            patch("frappe.get_cached_doc", return_value=frappe._dict({"currency": "HNL", "hide_expected_amount": 0})),
            patch("restaurant.pos.get_shift_cash_movements", return_value=fake_movements),
            patch("posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift.make_closing_shift_from_opening", return_value=fake_closing),
        ):
            preview = get_closing_shift_preview("POSA-OS-TEST-99")

        self.assertEqual(preview["invoice_count"], 2)
        self.assertEqual(preview["total_sales"], 38.80)
        cash_row, card_row = preview["payment_reconciliation"]
        self.assertEqual(cash_row["is_cash"], 1)
        self.assertEqual(cash_row["opening_amount"], 1500.0)
        self.assertEqual(cash_row["cash_movement_net"], 50.0)
        self.assertEqual(cash_row["sales_amount"], 31.0)
        self.assertEqual(card_row["is_cash"], 0)
        self.assertEqual(card_row["sales_amount"], 7.80)
