"""Regression checks for switching the restaurant register between two companies."""

from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, today

from restaurant import kds, pos


class TestOrderCompanyIsolation(FrappeTestCase):
    def setUp(self):
        super().setUp()
        original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.addCleanup(frappe.set_user, original_user)
        frappe.db.savepoint("order_company_isolation")
        self.addCleanup(frappe.db.rollback, save_point="order_company_isolation")

        self.profiles = {}
        for profile in frappe.get_all("POS Profile", filters={"disabled": 0},
                                      fields=["name", "company"], order_by="creation asc"):
            self.profiles.setdefault(profile.company, profile.name)
            if len(self.profiles) == 2:
                break
        if len(self.profiles) < 2:
            self.skipTest("This integration scenario needs active POS profiles in two companies")

        self.orders = {}
        self.shifts = {}
        self.item = frappe.db.get_value("Item", {"disabled": 0, "is_sales_item": 1}, "name")
        self.assertTrue(self.item)
        for company, profile in self.profiles.items():
            previous = self.make_shift(company, profile, "Closed")
            self.shifts[company] = self.make_shift(company, profile, "Open")
            self.orders[company] = frappe.get_doc({
                "doctype": "Restaurant Order", "order_name": "QA " + uuid4().hex[:10],
                "company": company, "pos_profile": profile, "pos_opening_shift": previous.name,
                "service_type": "Comer en el local", "status": "En curso", "guests": 1,
                "items": [{"item_code": self.item, "qty": 1, "base_rate": 10}],
            }).insert()

    def make_shift(self, company, profile, status):
        shift = frappe.get_doc({
            "doctype": "POS Opening Shift", "name": "QA-SHIFT-" + uuid4().hex[:12],
            "company": company, "pos_profile": profile, "user": frappe.session.user,
            "docstatus": 1, "status": status, "posting_date": today(),
            "period_start_date": now_datetime(),
        })
        # Seed historical and current shifts without invoking the user's cash-opening workflow.
        shift.db_insert()
        return shift

    @contextmanager
    def cashier_context(self, company, other_company):
        shift = self.shifts[company]
        with (
            patch.object(pos, "_get_active_opening_shift", return_value=shift.as_dict()),
            patch.object(pos, "_get_default_company", return_value=other_company),
        ):
            yield

    def company_pairs(self):
        first, second = self.profiles
        return [(first, second), (second, first)]

    def test_register_lists_only_its_company_and_keeps_previous_shift_orders(self):
        for company, other in self.company_pairs():
            with self.subTest(company=company), self.cashier_context(company, other):
                context = pos.get_pos_bootstrap()
                self.assertEqual(context["company"]["name"], company)
                visible = {order["name"] for order in context["orders"]}
                self.assertIn(self.orders[company].name, visible)
                self.assertNotIn(self.orders[other].name, visible)
                self.assertTrue(all(row["company"] == company for row in context["orders"]))

    def test_new_order_belongs_to_register_even_when_user_default_differs(self):
        for company, other in self.company_pairs():
            with self.subTest(company=company), self.cashier_context(company, other):
                shift = self.shifts[company]
                result = pos.save_pos_order({
                    "order_name": "QA " + uuid4().hex[:10], "service_type": "Comer en el local",
                    "pos_profile": shift.pos_profile, "pos_opening_shift": shift.name,
                    "items": [{"item_code": self.item, "qty": 1, "base_rate": 10}],
                })["order"]
                stored = frappe.get_doc("Restaurant Order", result["name"])
                self.assertEqual((stored.company, stored.pos_profile, stored.pos_opening_shift),
                                 (company, shift.pos_profile, shift.name))

    def test_other_company_order_rejected_before_edit_or_invoice(self):
        for company, other in self.company_pairs():
            with self.subTest(company=company), self.cashier_context(company, other):
                order = self.orders[other]
                before = order.reload().as_dict()
                with self.assertRaises(frappe.PermissionError):
                    pos.save_pos_order({"name": order.name, "reference_note": "QA"})
                with self.assertRaises(frappe.PermissionError):
                    pos.get_precuenta_data(order.name, tip_percentage=10)
                with self.assertRaises(frappe.PermissionError):
                    pos.cancel_pos_order(order.name, reason="QA")
                with self.assertRaises(frappe.PermissionError):
                    pos.send_order_to_kitchen(order.name)
                with self.assertRaises(frappe.PermissionError):
                    pos.get_order_operation_context(order.name)
                # Prevent invoice insertion and fiscal allocation even if this regression returns.
                with patch.object(SalesInvoice, "insert", side_effect=AssertionError("Unexpected invoice")):
                    with self.assertRaises(frappe.PermissionError):
                        pos.pay_and_invoice_order(order.name)
                order.reload()
                for field in ("company", "reference_note", "modified", "pos_opening_shift",
                              "pos_profile", "status", "sales_invoice", "tip_percentage",
                              "tip_amount", "precuenta_printed", "kds_status"):
                    self.assertEqual(order.get(field), before.get(field), field)

    def test_register_rejects_foreign_profile_or_shift_on_new_order(self):
        for company, other in self.company_pairs():
            foreign = self.shifts[other]
            for field, value in (("pos_profile", foreign.pos_profile), ("pos_opening_shift", foreign.name)):
                with self.subTest(company=company, field=field), self.cashier_context(company, other):
                    label = "QA " + uuid4().hex[:10]
                    with self.assertRaises(frappe.PermissionError):
                        pos.save_pos_order({"order_name": label, field: value})
                    self.assertFalse(frappe.db.exists("Restaurant Order", {"order_name": label}))

    def test_cashier_can_edit_own_previous_shift_order(self):
        for company, other in self.company_pairs():
            with self.subTest(company=company), self.cashier_context(company, other):
                order = self.orders[company]
                previous_shift = order.pos_opening_shift
                self.assertNotEqual(previous_shift, self.shifts[company].name)
                pos.save_pos_order({"name": order.name, "reference_note": "QA previous shift"})
                order.reload()
                self.assertEqual(order.reference_note, "QA previous shift")
                self.assertEqual((order.company, order.pos_opening_shift), (company, previous_shift))

    def test_reprint_list_only_shows_own_company_commands(self):
        for order in self.orders.values():
            frappe.db.set_value("Restaurant Order", order.name, "sent_to_kitchen_at", now_datetime())
        for company, other in self.company_pairs():
            with self.subTest(company=company), self.cashier_context(company, other):
                visible = {row["name"] for row in pos.get_emitted_commands()["commands"]}
                self.assertIn(self.orders[company].name, visible)
                self.assertNotIn(self.orders[other].name, visible)

    def test_other_company_order_rejected_across_pos_and_split_operations(self):
        for company, other in self.company_pairs():
            with self.subTest(company=company), self.cashier_context(company, other):
                order = self.orders[other].reload()
                item_row = order.items[0].name
                split_payload = [{"item_row": item_row, "qty": 1}]
                with self.assertRaises(frappe.PermissionError):
                    pos.clear_pos_order(order.name, reason="QA")
                with self.assertRaises(frappe.PermissionError):
                    pos.preview_split_order(order.name, split_payload)
                with self.assertRaises(frappe.PermissionError):
                    pos.split_order(order.name, split_payload, new_order_name="QA Split")
                with self.assertRaises(frappe.PermissionError):
                    pos.transfer_order_table(order.name, new_order_name="QA Transfer")
                with self.assertRaises(frappe.PermissionError):
                    pos.unlock_waiter_order(order.name, "0000")
                with self.assertRaises(frappe.PermissionError):
                    pos.authorize_reprint_command(order_name=order.name, reason="QA")

    def test_table_occupancy_is_isolated_by_company(self):
        table = frappe.db.get_value(
            "Restaurant Table",
            {"status": ["in", ["Disponible", "Ocupada"]]},
            ["name", "restaurant_area"],
            as_dict=True,
        )
        if not table:
            self.skipTest("Site missing an active Restaurant Table")
        first, second = self.profiles
        frappe.db.set_value(
            "Restaurant Order",
            self.orders[first].name,
            {"restaurant_table": table.name, "restaurant_area": table.restaurant_area},
        )
        with self.cashier_context(first, second):
            areas = pos.get_pos_bootstrap()["areas"]
            row = next(
                (t for area in areas for t in (area.get("tables") or []) if t["name"] == table.name),
                None,
            )
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "Ocupada")
            self.assertEqual(row["active_order"]["order_id"], self.orders[first].name)
        with self.cashier_context(second, first):
            areas = pos.get_pos_bootstrap()["areas"]
            row = next(
                (t for area in areas for t in (area.get("tables") or []) if t["name"] == table.name),
                None,
            )
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "Disponible")
            self.assertIsNone(row.get("active_order"))

    def test_kds_hides_and_protects_other_company_orders(self):
        suffix = uuid4().hex[:6]
        stages = [
            kds.save_stage({"stage_name": f"{label} {suffix}", "color": color, "alert_minutes": mins})["name"]
            for label, color, mins in (
                ("QA Prep", "#9CA3AF", 10),
                ("QA Listo", "#3B82F6", 5),
                ("QA Entregado", "#22C55E", 0),
            )
        ]
        display_name = kds.save_display({
            "display_name": f"QA Display {suffix}",
            "description": "QA isolation display",
            "enabled": 1,
            "auto_clear": 0,
            "auto_clear_minutes": 10,
            "stages": stages,
            "pos_profiles": [],
            "item_groups": [],
        })["name"]
        for order in self.orders.values():
            frappe.db.set_value(
                "Restaurant Order",
                order.name,
                {"kds_status": "En preparación", "sent_to_kitchen_at": now_datetime()},
            )
            for row in order.items:
                frappe.db.set_value("Restaurant Order Item", row.name, "kds_status", "En preparación")
        for company, other in self.company_pairs():
            with self.subTest(company=company), self.cashier_context(company, other):
                state = kds.get_kds_state(display_name)
                visible = {row["name"] for row in state["orders"]}
                self.assertIn(self.orders[company].name, visible)
                self.assertNotIn(self.orders[other].name, visible)
                foreign = self.orders[other].reload()
                with self.assertRaises(frappe.PermissionError):
                    kds.toggle_item(display_name, foreign.name, foreign.items[0].name, stages[0])
