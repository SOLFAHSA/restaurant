"""Read-only POS startup and role-guard regression tests without test users."""

import json
from unittest.mock import patch

import frappe
from frappe.desk.desk_page import get as get_page
from frappe.tests.utils import FrappeTestCase

from restaurant.pos import _require_pos_user, get_pos_bootstrap


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
        for role in ("Restaurant Manager", "System Manager"):
            with self.subTest(role=role):
                with patch.dict(frappe.local.session, {"user": "pos-operator@example.invalid"}):
                    with patch("frappe.get_roles", return_value=["All", role]):
                        _require_pos_user()
