"""Transactional preparation-display regression tests with rollback-only fixtures."""

from unittest.mock import Mock, patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from restaurant import kds
from restaurant.pos import (
    _serialize_order, pay_and_invoice_order, save_pos_order, send_order_to_kitchen,
    split_order, transfer_order_table,
)


class TestPreparationDisplay(FrappeTestCase):
    transaction_doctypes = (
        "Sales Invoice", "POS Invoice", "Payment Entry", "Stock Entry",
        "GL Entry", "Stock Ledger Entry", "User", "POS Opening Shift",
    )

    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.savepoint = "restaurant_kds_test"
        frappe.db.savepoint(self.savepoint)
        self.transaction_counts = {
            doctype: frappe.db.count(doctype) for doctype in self.transaction_doctypes
        }
        self.suffix = uuid4().hex[:10]
        root = frappe.db.get_value(
            "Item Group", {"is_group": 1, "parent_item_group": ["is", "not set"]}, "name"
        )
        self.groups = [frappe.get_doc({
            "doctype": "Item Group", "item_group_name": "_Test KDS " + label + self.suffix,
            "parent_item_group": root, "is_group": 0,
        }).insert().name for label in ("Cocina ", "Bebidas ")]
        stock_uom = frappe.db.get_value("UOM", {}, "name")
        self.items = [frappe.get_doc({
            "doctype": "Item", "item_code": "_Test-KDS-" + str(index) + self.suffix,
            "item_name": "Platillo de prueba " + str(index), "item_group": group,
            "stock_uom": stock_uom, "is_stock_item": 0, "is_sales_item": 1,
        }).insert().name for index, group in enumerate(self.groups)]
        self.stages = [kds.save_stage({
            "stage_name": label + " " + self.suffix, "color": color, "alert_minutes": minutes,
        })["name"] for label, color, minutes in (
            ("Preparación", "#9CA3AF", 10), ("Entrega", "#3B82F6", 5),
            ("Completado", "#22C55E", 0),
        )]
        self.display = self.make_display()

    def tearDown(self):
        frappe.set_user("Administrator")
        try:
            self.assertEqual(
                {doctype: frappe.db.count(doctype) for doctype in self.transaction_doctypes},
                self.transaction_counts,
                "Preparation must not create financial transactions, stock movements, users or shifts",
            )
        finally:
            frappe.db.rollback(save_point=self.savepoint)
            frappe.clear_cache()
            frappe.set_user(self.original_user)

    def make_display(self, **values):
        payload = {
            "display_name": "Pantalla " + uuid4().hex[:10], "description": "Prueba de cocina",
            "enabled": 1, "auto_clear": 0, "auto_clear_minutes": 10,
            "stages": self.stages, "pos_profiles": [], "item_groups": [],
        }
        payload.update(values)
        return kds.save_display(payload)["name"]

    def make_order(self, sent=True, groups=(0, 0), **values):
        payload = {
            "doctype": "Restaurant Order", "order_name": "Prueba KDS " + self.suffix,
            "service_type": "Comer en el local", "status": "En curso", "guests": 2,
            "kds_status": "En preparación" if sent else "Sin enviar",
            "sent_to_kitchen_at": now_datetime() if sent else None,
            "items": [{
                "item_code": self.items[index], "qty": 1, "base_rate": 100,
                "kds_status": "En preparación" if sent else "Pendiente",
                "note": "Sin cebolla", "command_station": "Cocina General",
            } for index in groups],
        }
        payload.update(values)
        return frappe.get_doc(payload).insert()

    def order_state(self, order, display=None):
        result = kds.get_kds_state(display_name=display or self.display)
        return next((row for row in result["orders"] if row["name"] == order.name), None)

    def mark(self, order, line, stage=0, completed=1, display=None):
        return kds.toggle_item(
            display_name=display or self.display, order_name=order.name,
            item_name=order.items[line].name, expected_stage=self.stages[stage],
            completed=completed,
        )

    def complete(self, order, display=None):
        for stage in (0, 1):
            for index in range(len(order.items)):
                self.mark(order, index, stage=stage, display=display)

    def ticket(self, order, display=None):
        return frappe.get_doc("Restaurant Preparation Ticket", {
            "preparation_display": display or self.display, "restaurant_order": order.name,
        })

    def make_table(self, label):
        if not getattr(self, "test_area", None):
            branch = frappe.get_doc({
                "doctype": "Branch", "branch": "_Test KDS " + self.suffix,
            }).insert().name
            self.test_area = frappe.get_doc({
                "doctype": "Restaurant Area", "area_name": "_Test KDS " + self.suffix,
                "branch": branch, "capacity": 20, "status": "Activa", "visible_in_pos": 1,
            }).insert().name
        return frappe.get_doc({
            "doctype": "Restaurant Table", "restaurant_area": self.test_area,
            "table_number": label, "seats": 4, "status": "Disponible",
        }).insert().name

    def isolate_display(self):
        for row in frappe.get_all("Restaurant Preparation Display", fields=["name"]):
            if row.name != self.display:
                frappe.db.set_value(
                    "Restaurant Preparation Display", row.name, "enabled", 0, update_modified=False
                )

    def test_get_is_read_only_and_excludes_unsent_or_cancelled_orders(self):
        unsent = self.make_order(sent=False)
        cancelled = self.make_order(status="Cancelada")
        sent = self.make_order()
        before = frappe.db.count("Restaurant Preparation Ticket")
        first = kds.get_kds_state(display_name=self.display)
        second = kds.get_kds_state(display_name=self.display)
        names = {row["name"] for row in first["orders"]}
        self.assertIn(sent.name, names)
        self.assertNotIn(unsent.name, names)
        self.assertNotIn(cancelled.name, names)
        self.assertEqual(before, frappe.db.count("Restaurant Preparation Ticket"))
        self.assertEqual(
            [row["name"] for row in first["orders"]], [row["name"] for row in second["orders"]]
        )
        self.assertFalse(any(row["kds_status"] == "Pendiente" for row in self.order_state(sent)["items"]))

    def test_each_stage_requires_all_lines_and_clears_strikes_for_next_stage(self):
        order = self.make_order()
        original = frappe.get_doc("Restaurant Order", order.name).as_dict()
        self.mark(order, 0)
        partial = self.order_state(order)
        self.assertEqual(partial["stage_index"], 0)
        self.assertEqual(partial["completed_item_names"], [order.items[0].name])
        self.mark(order, 1)
        ready = self.order_state(order)
        self.assertEqual(ready["stage_index"], 1)
        self.assertEqual(ready["completed_item_names"], [])
        self.mark(order, 0, stage=1)
        self.assertEqual(self.order_state(order)["stage_index"], 1)
        self.mark(order, 1, stage=1)
        self.assertEqual(self.order_state(order)["stage_index"], 2)
        self.assertTrue(self.ticket(order).completed_at)
        kds.dismiss_ticket(self.display, order.name, expected_stage=self.stages[2])
        self.assertIsNone(self.order_state(order))
        self.assertTrue(frappe.db.exists("Restaurant Order", order.name))
        after = frappe.get_doc("Restaurant Order", order.name).as_dict()
        for field in ("grand_total", "subtotal", "tax_amount", "sales_invoice", "status", "docstatus"):
            self.assertEqual(after[field], original[field], field)

    def test_marks_and_stage_timer_persist_across_reloads_and_repeat_is_idempotent(self):
        order = self.make_order()
        self.mark(order, 0)
        ticket_before = self.ticket(order).as_dict()
        self.mark(order, 0)
        ticket_after = self.ticket(order).as_dict()
        self.assertEqual(ticket_after["stage_index"], 0)
        self.assertEqual(ticket_after["completed_items_json"], ticket_before["completed_items_json"])
        self.assertEqual(ticket_after["stage_started_at"], ticket_before["stage_started_at"])
        frappe.clear_cache()
        self.assertEqual(self.order_state(order)["completed_item_names"], [order.items[0].name])
        self.mark(order, 0, completed=0)
        self.assertEqual(self.order_state(order)["completed_item_names"], [])

    def test_stale_stage_is_rejected_before_mutation(self):
        order = self.make_order()
        self.mark(order, 0)
        self.mark(order, 1)
        before = self.ticket(order).as_dict()
        with self.assertRaises(frappe.TimestampMismatchError):
            self.mark(order, 0, stage=0)
        after = self.ticket(order).as_dict()
        self.assertEqual(after["stage_index"], before["stage_index"])
        self.assertEqual(after["completed_items_json"], before["completed_items_json"])

    def test_same_order_on_two_displays_has_independent_progress(self):
        second_display = self.make_display()
        order = self.make_order()
        self.mark(order, 0)
        self.mark(order, 1)
        self.assertEqual(self.order_state(order)["stage_index"], 1)
        self.assertEqual(self.order_state(order, second_display)["stage_index"], 0)
        self.assertEqual(self.order_state(order, second_display)["completed_item_names"], [])
        self.complete(order, display=second_display)
        self.assertEqual(self.order_state(order)["stage_index"], 1)
        kds.dismiss_ticket(second_display, order.name, expected_stage=self.stages[2])
        self.assertIsNone(self.order_state(order, second_display))
        self.assertIsNotNone(self.order_state(order))

    def test_category_filter_hides_other_lines_and_prevents_toggling_them(self):
        display = self.make_display(item_groups=[self.groups[0]])
        order = self.make_order(groups=(0, 1))
        state = self.order_state(order, display)
        self.assertEqual([row["name"] for row in state["items"]], [order.items[0].name])
        with self.assertRaises(frappe.ValidationError):
            self.mark(order, 1, display=display)
        self.mark(order, 0, display=display)
        self.assertEqual(self.order_state(order, display)["stage_index"], 1)

    def test_pos_profile_filter_is_applied_on_server(self):
        profile = frappe.db.get_value("POS Profile", {"disabled": 0}, "name")
        self.assertTrue(profile, "Development must provide a native POS Profile")
        display = self.make_display(pos_profiles=[profile])
        included = self.make_order(pos_profile=profile)
        excluded = self.make_order(pos_profile=None)
        self.assertIsNotNone(self.order_state(included, display))
        self.assertIsNone(self.order_state(excluded, display))
        with self.assertRaises(frappe.ValidationError):
            self.mark(excluded, 0, display=display)

    def test_pending_lines_of_partially_sent_order_are_not_visible_or_mutable(self):
        order = self.make_order()
        frappe.db.set_value("Restaurant Order Item", order.items[1].name, "kds_status", "Pendiente")
        self.assertEqual(
            [row["name"] for row in self.order_state(order)["items"]], [order.items[0].name]
        )
        with self.assertRaises(frappe.ValidationError):
            self.mark(order, 1)

    def test_cannot_dismiss_incomplete_ticket_and_reset_restores_first_stage(self):
        order = self.make_order()
        with self.assertRaises(frappe.ValidationError):
            kds.dismiss_ticket(self.display, order.name, expected_stage=self.stages[0])
        self.complete(order)
        kds.move_previous_stage(self.display, order.name, expected_stage=self.stages[2])
        self.assertEqual(self.order_state(order)["stage_index"], 1)
        self.assertEqual(self.order_state(order)["completed_item_names"], [])
        kds.reset_ticket(self.display, order.name, expected_stage=self.stages[1])
        self.assertEqual(self.order_state(order)["stage_index"], 0)
        self.assertFalse(self.ticket(order).completed_at)

    def test_configuration_validation_rejects_missing_stages_bad_color_and_negative_timer(self):
        with self.assertRaises(frappe.ValidationError):
            self.make_display(stages=self.stages[:2])
        with self.assertRaises(frappe.ValidationError):
            self.make_display(stages=[self.stages[0]] * 3)
        with self.assertRaises(frappe.ValidationError):
            kds.save_stage({"stage_name": "Color inválido " + self.suffix, "color": "red;position:fixed"})
        with self.assertRaises(frappe.ValidationError):
            kds.save_stage({"stage_name": "Tiempo inválido " + self.suffix, "alert_minutes": -1})

    def test_guest_and_nonoperational_roles_are_denied(self):
        for user, roles in (("Guest", ["System Manager"]), ("kds-reader@example.invalid", ["All"])):
            with self.subTest(user=user):
                with patch.dict(frappe.local.session, {"user": user}):
                    with patch("frappe.get_roles", return_value=roles):
                        with self.assertRaises(frappe.PermissionError):
                            kds.get_kds_state(display_name=self.display)

    def test_read_permission_is_enforced_for_selected_display(self):
        with patch("frappe.permissions.has_permission", return_value=False):
            with self.assertRaises(frappe.PermissionError):
                kds.get_kds_state(display_name=self.display)

    def test_automatic_retirement_uses_completion_time_and_preserves_orders(self):
        display = self.make_display(auto_clear=1, auto_clear_minutes=5)
        order = self.make_order()
        old_time = add_to_date(now_datetime(), minutes=-6)
        self.mark(order, 0, display=display)
        ticket = self.ticket(order, display)
        ticket.db_set("stage_started_at", old_time, update_modified=False)
        self.assertIsNotNone(self.order_state(order, display))
        self.mark(order, 1, display=display)
        self.mark(order, 0, stage=1, display=display)
        self.mark(order, 1, stage=1, display=display)
        self.assertIsNotNone(self.order_state(order, display))
        self.ticket(order, display).db_set("completed_at", old_time, update_modified=False)
        before = frappe.db.count("Restaurant Preparation Ticket")
        self.assertIsNone(self.order_state(order, display))
        self.assertEqual(frappe.db.count("Restaurant Preparation Ticket"), before)
        self.assertTrue(frappe.db.exists("Restaurant Order", order.name))

    def test_disabled_automatic_retirement_keeps_completed_ticket_visible(self):
        order = self.make_order()
        self.complete(order)
        self.ticket(order).db_set(
            "completed_at", add_to_date(now_datetime(), days=-2), update_modified=False
        )
        self.assertIsNotNone(self.order_state(order))
        self.assertEqual(self.order_state(order)["stage_index"], 2)

    def test_active_ticket_keeps_stage_snapshot_after_configuration_edit(self):
        order = self.make_order()
        self.mark(order, 0)
        stage = frappe.get_doc("Restaurant Preparation Stage", self.stages[0])
        kds.save_stage({
            "name": stage.name, "modified": str(stage.modified),
            "stage_name": "Preparación modificada " + self.suffix,
            "color": "#112233", "alert_minutes": 99,
        })
        state = self.order_state(order)
        self.assertEqual(state["stages"][0]["color"], "#9CA3AF")
        self.assertEqual(state["stages"][0]["alert_minutes"], 10)

    def test_existing_financial_order_is_not_rewritten_by_reading_display(self):
        order = self.make_order(status="Facturada")
        before = frappe.get_doc("Restaurant Order", order.name).as_dict()
        self.assertIsNotNone(self.order_state(order))
        self.assertEqual(frappe.get_doc("Restaurant Order", order.name).as_dict(), before)

    def test_pos_save_preserves_sent_row_identity_and_ignores_forged_kitchen_state(self):
        order = self.make_order()
        payload = _serialize_order(order)
        payload["items"][0]["kds_status"] = "Entregado"
        saved = save_pos_order(payload)["order"]
        self.assertEqual([row["name"] for row in saved["items"]], [row.name for row in order.items])
        self.assertEqual(saved["items"][0]["kds_status"], "En preparación")
        payload = _serialize_order(frappe.get_doc("Restaurant Order", order.name))
        payload["items"][0]["qty"] = 2
        with self.assertRaises(frappe.ValidationError):
            save_pos_order(payload)

    def test_new_sent_line_reopens_only_new_batch_after_completed_ticket_was_cleared(self):
        order = self.make_order()
        self.complete(order)
        kds.dismiss_ticket(self.display, order.name, expected_stage=self.stages[2])
        payload = _serialize_order(frappe.get_doc("Restaurant Order", order.name))
        payload["items"].append({"item_code": self.items[0], "qty": 1, "base_rate": 100})
        saved = save_pos_order(payload)["order"]
        self.assertIsNone(self.order_state(order))
        send_order_to_kitchen(order.name)
        state = self.order_state(order)
        self.assertEqual(state["stage_index"], 0)
        self.assertEqual([row["name"] for row in state["items"]], [saved["items"][-1]["name"]])
        self.assertEqual(state["completed_item_names"], [])

    def test_reprinting_does_not_reopen_completed_preparation(self):
        order = self.make_order()
        self.complete(order)
        frappe.db.set_value("Restaurant Order", order.name, "kds_status", "Entregado")
        send_order_to_kitchen(order.name, include_sent=1)
        self.assertEqual(frappe.db.get_value("Restaurant Order", order.name, "kds_status"), "Entregado")
        self.assertEqual(self.order_state(order)["stage_index"], 2)

    def test_legacy_order_with_new_sent_batch_does_not_reprepare_old_delivered_lines(self):
        order = self.make_order()
        frappe.db.set_value("Restaurant Order Item", order.items[0].name, "kds_status", "Entregado")
        state = self.order_state(order)
        self.assertEqual([row["name"] for row in state["items"]], [order.items[1].name])
        self.assertEqual(state["stage_index"], 0)

    def test_pos_cannot_forge_native_item_group_or_kitchen_routing(self):
        saved = save_pos_order({
            "order_name": "Ruta nativa " + self.suffix,
            "items": [{
                "item_code": self.items[0], "qty": 1, "base_rate": 100,
                "item_group": self.groups[1], "command_station": "Estación falsa",
            }],
        })["order"]
        self.assertEqual(saved["items"][0]["item_group"], self.groups[0])
        self.assertEqual(saved["items"][0]["command_station"], "Cocina General")

    def test_order_write_permission_is_required_before_kitchen_mutation(self):
        order = self.make_order()
        before = frappe.db.count("Restaurant Preparation Ticket")

        def permission(doctype, ptype="read", *args, **kwargs):
            return not (doctype == "Restaurant Order" and ptype == "write")

        with patch("frappe.permissions.has_permission", side_effect=permission):
            with self.assertRaises(frappe.PermissionError):
                self.mark(order, 0)
        self.assertEqual(frappe.db.count("Restaurant Preparation Ticket"), before)

    def test_invoicing_preserves_virtual_and_materialized_kitchen_progress(self):
        invoice_name = frappe.db.get_value("Sales Invoice", {}, "name")
        self.assertTrue(invoice_name, "Development must provide an existing invoice link for the mock")
        for marked in (False, True):
            with self.subTest(materialized=marked):
                order = self.make_order()
                if marked:
                    self.mark(order, 0)
                before = self.order_state(order)
                fake_invoice = frappe._dict({
                    "name": invoice_name, "customer": order.customer,
                    "customer_name": order.customer_name, "company": order.company,
                    "company_tax_id": "", "tax_id": "", "posting_date": "2026-11-06",
                    "cai": "PRUEBA-KDS", "due_date_cai": "2030-01-01",
                    "grand_total": order.grand_total, "net_total": order.subtotal,
                    "paid_amount": order.grand_total, "change_amount": 0,
                    "payments": [frappe._dict(amount=order.grand_total)],
                })
                for method in ("set_missing_values", "calculate_taxes_and_totals", "insert", "submit"):
                    fake_invoice[method] = Mock()
                real_get_doc = frappe.get_doc

                def get_doc(*args, **kwargs):
                    if args and isinstance(args[0], dict) and args[0].get("doctype") == "Sales Invoice":
                        return fake_invoice
                    return real_get_doc(*args, **kwargs)

                fiscal_info = {
                    "cai": "PRUEBA-KDS", "due_date_cai": "2030-01-01",
                    "authorized_range": "", "company_tax_id": "", "prefix": "",
                }
                with patch("restaurant.pos.frappe.get_doc", side_effect=get_doc), \
                        patch("restaurant.pos._resolve_tax_account", return_value=None), \
                        patch("restaurant.pos._resolve_payment_account", return_value=None), \
                        patch("restaurant.pos._resolve_sar_fiscal_info", return_value=fiscal_info):
                    response = pay_and_invoice_order(order.name)
                self.assertEqual(response["order"]["status"], "Facturada")
                self.assertEqual(response["order"]["kds_status"], "En preparación")
                after = self.order_state(order)
                self.assertEqual(after["stage_index"], before["stage_index"])
                self.assertEqual(after["completed_item_names"], before["completed_item_names"])
                fake_invoice.calculate_taxes_and_totals.assert_called_once()
                fake_invoice.insert.assert_called_once()
                fake_invoice.submit.assert_called_once()

    def test_split_preserves_active_kitchen_progress_with_or_without_ticket(self):
        for materialized in (False, True):
            order = self.make_order()
            if materialized:
                self.mark(order, 0)
            with self.subTest(materialized=materialized):
                result = split_order(order.name, [{"idx": 1, "qty": 1}])
                self.assertEqual(
                    [row["name"] for row in result["original_order"]["items"]], [order.items[1].name]
                )
                created = frappe.get_doc("Restaurant Order", result["new_order"]["name"])
                self.assertEqual(self.order_state(order)["stage_index"], 0)
                self.assertEqual(self.order_state(created)["stage_index"], 1 if materialized else 0)
                self.assertEqual(self.order_state(created)["completed_item_names"], [])
                self.assertAlmostEqual(
                    result["original_order"]["grand_total"] + result["new_order"]["grand_total"],
                    order.grand_total, places=2,
                )

    def test_simple_table_transfer_and_active_merge_preserve_independent_kitchen_tickets(self):
        source_table = self.make_table("Origen")
        empty_table = self.make_table("Destino libre")
        busy_table = self.make_table("Destino ocupado")
        order = self.make_order(restaurant_table=source_table)
        self.mark(order, 0)
        before = self.order_state(order)
        transferred = transfer_order_table(order.name, empty_table)
        self.assertFalse(transferred["merged"])
        after = self.order_state(order)
        self.assertEqual(after["restaurant_table"], empty_table)
        self.assertEqual(after["completed_item_names"], before["completed_item_names"])
        target = self.make_order(restaurant_table=busy_table)
        merged = transfer_order_table(order.name, busy_table)
        self.assertTrue(merged["merged"])
        self.assertNotEqual(frappe.db.get_value("Restaurant Order", order.name, "status"), "En curso")
        self.assertEqual(len(frappe.get_doc("Restaurant Order", target.name).items), 4)
        cards = [card for card in kds.get_kds_state(self.display)["orders"] if card["name"] == target.name]
        self.assertEqual(len(cards), 2)
        self.assertEqual(sorted(len(card["completed_item_names"]) for card in cards), [0, 1])

    def test_completed_split_keeps_remaining_line_identity_without_reopening_kitchen(self):
        self.isolate_display()
        order = self.make_order()
        self.complete(order)
        remaining_name = order.items[1].name
        self.assertEqual(frappe.db.get_value("Restaurant Order", order.name, "kds_status"), "Entregado")
        result = split_order(order.name, [{"idx": 1, "qty": 1}])
        self.assertEqual([row["name"] for row in result["original_order"]["items"]], [remaining_name])
        self.assertEqual(self.order_state(order)["stage_index"], 2)
        new_order = frappe.get_doc("Restaurant Order", result["new_order"]["name"])
        self.assertEqual(self.order_state(new_order)["stage_index"], 2)

    def test_reenabled_display_recovers_its_unfinished_ticket_after_other_display_retires(self):
        self.isolate_display()
        second_display = self.make_display()
        order = self.make_order()
        self.mark(order, 0, display=second_display)
        frappe.db.set_value("Restaurant Preparation Display", second_display, "enabled", 0)
        self.complete(order)
        kds.dismiss_ticket(self.display, order.name, expected_stage=self.stages[2])
        self.assertNotEqual(frappe.db.get_value("Restaurant Order", order.name, "kds_status"), "Cerrado")
        frappe.db.set_value("Restaurant Preparation Display", second_display, "enabled", 1)
        state = self.order_state(order, second_display)
        self.assertIsNotNone(state)
        self.assertEqual(state["stage_index"], 0)
        self.assertEqual(state["completed_item_names"], [order.items[0].name])

    def test_untouched_enabled_display_is_captured_before_peer_changes_global_state(self):
        self.isolate_display()
        second_display = self.make_display()
        order = self.make_order()
        self.mark(order, 0)
        self.assertEqual(self.ticket(order, second_display).stage_index, 0)
        frappe.db.set_value("Restaurant Preparation Display", second_display, "enabled", 0)
        self.complete(order)
        kds.dismiss_ticket(self.display, order.name, expected_stage=self.stages[2])
        frappe.db.set_value("Restaurant Preparation Display", second_display, "enabled", 1)
        state = self.order_state(order, second_display)
        self.assertIsNotNone(state)
        self.assertEqual(state["stage_index"], 0)
        self.assertEqual(state["completed_item_names"], [])
