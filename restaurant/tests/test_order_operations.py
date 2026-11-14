"""Rollback-only order transfer and split integration regression coverage."""

import json
from collections import defaultdict
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant import kds, pos
from restaurant.tests import test_kds as preparation_fixtures


class TestOrderOperations(FrappeTestCase):
    transaction_doctypes = preparation_fixtures.TestPreparationDisplay.transaction_doctypes
    make_order = preparation_fixtures.TestPreparationDisplay.make_order
    make_display = preparation_fixtures.TestPreparationDisplay.make_display
    make_table = preparation_fixtures.TestPreparationDisplay.make_table
    isolate_display = preparation_fixtures.TestPreparationDisplay.isolate_display
    ticket = preparation_fixtures.TestPreparationDisplay.ticket
    mark = preparation_fixtures.TestPreparationDisplay.mark
    complete = preparation_fixtures.TestPreparationDisplay.complete
    tearDown = preparation_fixtures.TestPreparationDisplay.tearDown

    def setUp(self):
        preparation_fixtures.TestPreparationDisplay.setUp(self)
        self.isolate_display()
        self.fractional_uom = frappe.db.get_value("UOM", {"must_be_whole_number": 0}, "name")
        self.assertTrue(self.fractional_uom, "Native UOM configuration must allow fractional quantities")
        for item in self.items:
            frappe.db.set_value("Item", item, "stock_uom", self.fractional_uom)

    def rich_order(self, **values):
        target_status = values.pop("status", None)
        order = self.make_order(groups=(0, 1), **values)
        first, second = order.items
        first.qty = 2
        first.base_rate = 80
        first.options_rate = 20
        first.discount_percentage = 10
        first.tax_rate = 15
        first.options_summary = "Queso extra"
        first.selected_options_json = json.dumps([{
            "group_name": "Adicionales", "option_label": "Queso extra", "additional_amount": 20,
        }])
        second.qty = 3
        second.base_rate = 100
        second.tax_rate = 18
        order.tip_percentage = 10
        order.save()
        if target_status and target_status != order.status:
            frappe.db.set_value("Restaurant Order", order.name, "status", target_status)
            order.reload()
        return order

    def document(self, name):
        return frappe.get_doc("Restaurant Order", name)

    def token(self, order):
        return str(self.document(order.name).modified)

    def selection(self, order, index=0, qty=1):
        return [{"item_name": order.items[index].name, "qty": qty}]

    def kitchen_cards(self, order, display=None):
        result = kds.get_kds_state(display_name=display or self.display)
        return [row for row in result["orders"] if row["name"] == order.name]

    def row_quantities(self, orders):
        result = defaultdict(float)
        for order in orders:
            for row in order.items:
                signature = (
                    row.item_code, row.options_summary, row.selected_options_json or "[]",
                    row.note, row.base_rate, row.options_rate, row.discount_percentage, row.tax_rate,
                )
                result[signature] += row.qty
        return dict(result)

    def assert_conserved(self, original, current):
        self.assertEqual(self.row_quantities(original), self.row_quantities(current))
        for field in ("subtotal", "tax_amount", "tip_amount", "grand_total"):
            self.assertAlmostEqual(
                sum(float(doc.get(field) or 0) for doc in original),
                sum(float(doc.get(field) or 0) for doc in current), places=2, msg=field,
            )

    def operation_snapshot(self, orders):
        names = [order.name for order in orders]
        return {
            "orders": [self.document(name).as_dict() for name in names],
            "tickets": frappe.get_all(
                "Restaurant Preparation Ticket", filters={"restaurant_order": ["in", names]},
                fields=["*"], order_by="name", limit_page_length=0,
            ),
            "order_count": frappe.db.count("Restaurant Order"),
            "tables": [frappe.get_doc("Restaurant Table", row.name).as_dict() for row in frappe.get_all(
                "Restaurant Table", filters={"restaurant_area": self.test_area},
                fields=["name"], order_by="name", limit_page_length=0,
            )] if getattr(self, "test_area", None) else [],
        }

    def test_context_and_split_preview_are_read_only(self):
        order = self.rich_order()
        before = self.operation_snapshot([order])
        context = pos.get_order_operation_context(order.name)
        preview = pos.preview_split_order(
            order.name, self.selection(order, qty=0.5), expected_modified=self.token(order)
        )
        self.assertEqual(context["order"]["name"], order.name)
        self.assertIsInstance(context["tables"], list)
        self.assertIsInstance(context["orders"], list)
        self.assertTrue(preview["can_split"])
        self.assertFalse(preview["all_selected"])
        self.assertAlmostEqual(preview["selected_qty"], 0.5)
        self.assertGreater(preview["selected_total"], 0)
        self.assertAlmostEqual(
            preview["selected_total"] + preview["remaining_total"], preview["original_total"], places=2
        )
        self.assertEqual(self.operation_snapshot([order]), before)

    def test_partial_split_preserves_quantities_options_taxes_tips_and_remaining_row_identity(self):
        order = self.rich_order()
        original = self.document(order.name)
        row_names = [row.name for row in original.items]
        result = pos.split_order(
            order.name, self.selection(order, qty=0.5), new_order_name="Cuenta separada " + self.suffix,
            expected_modified=self.token(order),
        )
        remaining = self.document(result["original_order"]["name"])
        created = self.document(result["new_order"]["name"])
        self.assert_conserved([original], [remaining, created])
        self.assertEqual([row.name for row in remaining.items], row_names)
        self.assertEqual(created.order_name, "Cuenta separada " + self.suffix)
        self.assertEqual(created.items[0].qty, 0.5)
        self.assertEqual(remaining.items[0].qty, 1.5)
        self.assertNotIn(created.items[0].name, row_names)

    def test_fixed_tip_is_partitioned_without_duplication(self):
        order = self.rich_order()
        order.tip_percentage = 0
        order.tip_amount = 7.5
        order.save()
        original = self.document(order.name)
        result = pos.split_order(
            order.name, self.selection(order, qty=0.5), expected_modified=self.token(order)
        )
        self.assert_conserved([original], [
            self.document(result["original_order"]["name"]), self.document(result["new_order"]["name"]),
        ])

    def test_invalid_split_quantities_are_rejected_without_mutation(self):
        order = self.rich_order()
        before = self.operation_snapshot([order])
        for quantity in (0, -1, 2.1, True, "NaN", "Infinity", "abc"):
            with self.subTest(quantity=quantity):
                with self.assertRaises(frappe.ValidationError):
                    pos.split_order(
                        order.name, self.selection(order, qty=quantity), expected_modified=self.token(order)
                    )
                self.assertEqual(self.operation_snapshot([order]), before)

    def test_duplicate_foreign_and_missing_lines_are_rejected(self):
        order = self.rich_order()
        other = self.make_order()
        before = self.operation_snapshot([order, other])
        for selection in (
            [], self.selection(order) * 2, self.selection(other),
            [{"item_name": "missing-kds-line", "qty": 1}],
        ):
            with self.subTest(selection=selection):
                with self.assertRaises(frappe.ValidationError):
                    pos.split_order(order.name, selection, expected_modified=self.token(order))
                self.assertEqual(self.operation_snapshot([order, other]), before)

    def test_selecting_every_quantity_cannot_leave_an_empty_split_account(self):
        order = self.rich_order()
        selection = [{"item_name": row.name, "qty": row.qty} for row in order.items]
        before = self.operation_snapshot([order])
        preview = pos.preview_split_order(order.name, selection, expected_modified=self.token(order))
        self.assertTrue(preview["all_selected"])
        self.assertFalse(preview["can_split"])
        with self.assertRaises(frappe.ValidationError):
            pos.split_order(order.name, selection, expected_modified=self.token(order))
        self.assertEqual(self.operation_snapshot([order]), before)

    def test_stale_source_version_is_rejected_for_preview_split_and_transfer(self):
        order = self.rich_order()
        target_table = self.make_table("Destino")
        old_token = self.token(order)
        order.reference_note = "Cambio concurrente"
        order.save()
        before = self.operation_snapshot([order])
        for operation in (
            lambda: pos.preview_split_order(order.name, self.selection(order), expected_modified=old_token),
            lambda: pos.split_order(order.name, self.selection(order), expected_modified=old_token),
            lambda: pos.transfer_order_table(order.name, target_table=target_table, expected_modified=old_token),
        ):
            with self.assertRaises(frappe.TimestampMismatchError):
                operation()
            self.assertEqual(self.operation_snapshot([order]), before)

    def test_billed_and_cancelled_accounts_cannot_be_split_or_transferred(self):
        target_table = self.make_table("Destino")
        for status in ("Facturada", "Cancelada"):
            order = self.rich_order(status=status)
            before = self.operation_snapshot([order])
            with self.subTest(status=status):
                with self.assertRaises(frappe.ValidationError):
                    pos.split_order(order.name, self.selection(order), expected_modified=self.token(order))
                with self.assertRaises(frappe.ValidationError):
                    pos.transfer_order_table(
                        order.name, target_table=target_table, expected_modified=self.token(order)
                    )
                self.assertEqual(self.operation_snapshot([order]), before)

    def test_guest_and_order_write_denied_cannot_split(self):
        order = self.rich_order()
        before = self.operation_snapshot([order])
        with patch.dict(frappe.local.session, {"user": "Guest"}):
            with self.assertRaises(frappe.PermissionError):
                pos.split_order(order.name, self.selection(order), expected_modified=self.token(order))

        def permission(doctype, ptype="read", *args, **kwargs):
            return not (doctype == "Restaurant Order" and ptype == "write")

        with patch("frappe.permissions.has_permission", side_effect=permission):
            with self.assertRaises(frappe.PermissionError):
                pos.split_order(order.name, self.selection(order), expected_modified=self.token(order))
        self.assertEqual(self.operation_snapshot([order]), before)

    def test_transfer_to_empty_table_preserves_order_lines_and_kitchen_progress(self):
        source_table = self.make_table("Origen")
        target_table = self.make_table("Destino libre")
        order = self.rich_order(restaurant_table=source_table)
        self.mark(order, 0)
        before = self.document(order.name)
        ticket = self.ticket(order).as_dict()
        count = frappe.db.count("Restaurant Order")
        result = pos.transfer_order_table(
            order.name, target_table=target_table, expected_modified=self.token(order)
        )
        self.assertFalse(result["merged"])
        after = self.document(result["order"]["name"])
        self.assertEqual(after.name, order.name)
        self.assertEqual(after.restaurant_table, target_table)
        self.assertEqual([row.name for row in after.items], [row.name for row in before.items])
        self.assert_conserved([before], [after])
        self.assertEqual(self.ticket(order).stage_started_at, ticket["stage_started_at"])
        self.assertEqual(self.ticket(order).completed_items_json, ticket["completed_items_json"])
        self.assertEqual(frappe.db.count("Restaurant Order"), count)

    def test_full_merge_to_occupied_table_preserves_amounts_and_target_line_ids(self):
        target_table = self.make_table("Mesa ocupada")
        source = self.rich_order()
        target = self.rich_order(restaurant_table=target_table)
        originals = [self.document(source.name), self.document(target.name)]
        target_names = [row.name for row in target.items]
        result = pos.transfer_order_table(
            source.name, target_table=target_table, expected_modified=self.token(source),
            target_order=target.name, target_modified=self.token(target),
        )
        self.assertTrue(result["merged"])
        after = self.document(target.name)
        self.assertEqual(result["order"]["name"], target.name)
        self.assert_conserved(originals, [after])
        self.assertTrue(set(target_names).issubset({row.name for row in after.items}))
        self.assertNotEqual(self.document(source.name).status, "En curso")
        self.assertEqual(self.kitchen_cards(source), [])

    def test_target_account_without_table_can_receive_a_full_transfer(self):
        source = self.rich_order()
        target = self.rich_order()
        originals = [self.document(source.name), self.document(target.name)]
        result = pos.transfer_order_table(
            source.name, target_order=target.name, expected_modified=self.token(source),
            target_modified=self.token(target),
        )
        after = self.document(result["order"]["name"])
        self.assertEqual(after.name, target.name)
        self.assertFalse(after.restaurant_table)
        self.assert_conserved(originals, [after])

    def test_partial_transfer_to_empty_table_creates_only_one_new_account(self):
        source = self.rich_order()
        target_table = self.make_table("Destino parcial")
        original = self.document(source.name)
        before_count = frappe.db.count("Restaurant Order")
        result = pos.transfer_order_table(
            source.name, target_table=target_table, split_items=self.selection(source, qty=0.5),
            expected_modified=self.token(source),
        )
        target = self.document(result["order"]["name"])
        self.assertNotEqual(target.name, source.name)
        self.assertEqual(target.restaurant_table, target_table)
        self.assertEqual(frappe.db.count("Restaurant Order"), before_count + 1)
        self.assert_conserved([original], [self.document(source.name), target])

    def test_partial_transfer_to_existing_account_does_not_create_an_orphan_order(self):
        source = self.rich_order()
        target = self.rich_order()
        original = [self.document(source.name), self.document(target.name)]
        count = frappe.db.count("Restaurant Order")
        result = pos.transfer_order_table(
            source.name, target_order=target.name, split_items=self.selection(source, qty=0.5),
            expected_modified=self.token(source), target_modified=self.token(target),
        )
        self.assertEqual(result["order"]["name"], target.name)
        self.assertEqual(frappe.db.count("Restaurant Order"), count)
        self.assert_conserved(original, [self.document(source.name), self.document(target.name)])
        self.assertEqual(self.document(source.name).status, "En curso")

    def test_stale_or_closed_target_is_rejected_before_changing_source(self):
        source = self.rich_order()
        target = self.rich_order()
        old_token = self.token(target)
        target.reference_note = "Edición concurrente"
        target.save()
        before = self.operation_snapshot([source, target])
        with self.assertRaises(frappe.TimestampMismatchError):
            pos.transfer_order_table(
                source.name, target_order=target.name, expected_modified=self.token(source),
                target_modified=old_token,
            )
        self.assertEqual(self.operation_snapshot([source, target]), before)
        for status in ("Facturada", "Cancelada"):
            frappe.db.set_value("Restaurant Order", target.name, "status", status)
            target.reload()
            before = self.operation_snapshot([source, target])
            with self.assertRaises(frappe.ValidationError):
                pos.transfer_order_table(
                    source.name, target_order=target.name, expected_modified=self.token(source),
                    target_modified=self.token(target),
                )
            self.assertEqual(self.operation_snapshot([source, target]), before)

    def test_partial_split_normalizes_already_marked_subset_without_repreparation(self):
        source = self.rich_order()
        self.mark(source, 0)
        source_timer = self.ticket(source).stage_started_at
        result = pos.split_order(
            source.name, self.selection(source, qty=0.5), expected_modified=self.token(source)
        )
        created = self.document(result["new_order"]["name"])
        remaining_cards = self.kitchen_cards(source)
        moved_cards = self.kitchen_cards(created)
        self.assertEqual(len(remaining_cards), 1)
        self.assertEqual(remaining_cards[0]["stage_index"], 0)
        self.assertEqual(remaining_cards[0]["completed_item_names"], [source.items[0].name])
        self.assertEqual(self.ticket(source).stage_started_at, source_timer)
        self.assertEqual(len(moved_cards), 1)
        self.assertEqual(moved_cards[0]["stage_index"], 1)
        self.assertEqual(moved_cards[0]["completed_item_names"], [])
        self.assertEqual(moved_cards[0]["items"][0]["qty"], 0.5)

    def test_merge_preserves_independent_segments_at_different_preparation_stages(self):
        source = self.rich_order()
        target = self.rich_order()
        self.mark(source, 0)
        self.mark(source, 1)
        self.mark(target, 0)
        source_timer = self.ticket(source).stage_started_at
        target_timer = self.ticket(target).stage_started_at
        pos.transfer_order_table(
            source.name, target_order=target.name, expected_modified=self.token(source),
            target_modified=self.token(target),
        )
        cards = self.kitchen_cards(target)
        self.assertEqual(len(cards), 2)
        self.assertEqual(len({card["ticket_name"] for card in cards}), 2)
        self.assertEqual(sorted(card["stage_index"] for card in cards), [0, 1])
        original_card = next(card for card in cards if card["stage_index"] == 0)
        moved_card = next(card for card in cards if card["stage_index"] == 1)
        self.assertEqual(original_card["completed_item_names"], [target.items[0].name])
        self.assertEqual(original_card["kds_timer_start"], str(target_timer))
        self.assertEqual(moved_card["kds_timer_start"], str(source_timer))
        self.assertEqual(sum(len(card["items"]) for card in cards), 4)
        kds.toggle_item(
            self.display, target.name, moved_card["items"][0]["name"],
            expected_stage=self.stages[1], completed=1, ticket_id=moved_card["ticket_name"],
        )
        refreshed = {card["ticket_name"]: card for card in self.kitchen_cards(target)}
        self.assertEqual(
            refreshed[original_card["ticket_name"]]["completed_item_names"],
            original_card["completed_item_names"],
        )
        with self.assertRaises(frappe.ValidationError):
            kds.toggle_item(
                self.display, target.name, original_card["items"][0]["name"],
                expected_stage=self.stages[1], completed=1, ticket_id=moved_card["ticket_name"],
            )

    def test_splitting_completed_ticket_does_not_reopen_delivered_food(self):
        order = self.rich_order()
        self.complete(order)
        completed_at = self.ticket(order).completed_at
        result = pos.split_order(
            order.name, self.selection(order, qty=0.5), expected_modified=self.token(order)
        )
        created = self.document(result["new_order"]["name"])
        self.assertEqual(self.kitchen_cards(order)[0]["stage_index"], 2)
        self.assertEqual(self.kitchen_cards(created)[0]["stage_index"], 2)
        self.assertEqual(self.kitchen_cards(created)[0]["completed_at"], str(completed_at))

    def test_retired_ticket_stays_retired_when_quantities_are_split(self):
        order = self.rich_order()
        self.complete(order)
        kds.dismiss_ticket(self.display, order.name, expected_stage=self.stages[2])
        result = pos.split_order(
            order.name, self.selection(order, qty=0.5), expected_modified=self.token(order)
        )
        created = self.document(result["new_order"]["name"])
        self.assertEqual(self.kitchen_cards(order), [])
        self.assertEqual(self.kitchen_cards(created), [])

    def test_split_preserves_distinct_stages_and_native_category_filters_on_multiple_displays(self):
        display_doc = frappe.get_doc("Restaurant Preparation Display", self.display)
        display_doc.set("item_groups", [{"item_group": self.groups[0]}])
        display_doc.save()
        second_display = self.make_display(item_groups=[self.groups[1]])
        source = self.rich_order()
        self.mark(source, 0)
        self.mark(source, 1, display=second_display)
        self.mark(source, 1, stage=1, display=second_display)
        selection = self.selection(source, index=0, qty=0.5) + self.selection(source, index=1, qty=0.5)
        result = pos.split_order(source.name, selection, expected_modified=self.token(source))
        created = self.document(result["new_order"]["name"])
        for order in (source, created):
            food = self.kitchen_cards(order)[0]
            drink = self.kitchen_cards(order, second_display)[0]
            self.assertEqual(food["stage_index"], 1)
            self.assertEqual(drink["stage_index"], 2)
            self.assertEqual({row["item_group"] for row in food["items"]}, {self.groups[0]})
            self.assertEqual({row["item_group"] for row in drink["items"]}, {self.groups[1]})

    def test_merge_with_different_currency_is_rejected_without_mutation(self):
        source = self.rich_order()
        target = self.rich_order(currency="USD")
        self.assertNotEqual(source.currency, target.currency)
        before = self.operation_snapshot([source, target])
        with self.assertRaises(frappe.ValidationError):
            pos.transfer_order_table(
                source.name, target_order=target.name, expected_modified=self.token(source),
                target_modified=self.token(target),
            )
        self.assertEqual(self.operation_snapshot([source, target]), before)

    def test_target_write_permission_is_required_before_merging(self):
        source = self.rich_order()
        target = self.rich_order()
        before = self.operation_snapshot([source, target])

        def permission(doctype, ptype="read", doc=None, *args, **kwargs):
            return not (
                doctype == "Restaurant Order" and ptype == "write"
                and getattr(doc, "name", None) == target.name
            )

        with patch("frappe.permissions.has_permission", side_effect=permission):
            with self.assertRaises(frappe.PermissionError):
                pos.transfer_order_table(
                    source.name, target_order=target.name, expected_modified=self.token(source),
                    target_modified=self.token(target),
                )
        self.assertEqual(self.operation_snapshot([source, target]), before)

    def test_source_cannot_be_its_own_target(self):
        order = self.rich_order()
        before = self.operation_snapshot([order])
        with self.assertRaises(frappe.ValidationError):
            pos.transfer_order_table(
                order.name, target_order=order.name, expected_modified=self.token(order),
                target_modified=self.token(order),
            )
        self.assertEqual(self.operation_snapshot([order]), before)

    def test_native_whole_number_uom_rejects_fractional_selection(self):
        order = self.rich_order()
        whole_uom = frappe.db.get_value("UOM", {"must_be_whole_number": 1}, "name")
        self.assertTrue(whole_uom, "Native UOM configuration must provide a whole-number unit")
        order.items[0].uom = whole_uom
        order.save()
        before = self.operation_snapshot([order])
        with self.assertRaises(frappe.ValidationError):
            pos.split_order(order.name, self.selection(order, qty=0.5), expected_modified=self.token(order))
        self.assertEqual(self.operation_snapshot([order]), before)

    def test_split_rolls_back_order_creation_and_tickets_if_kitchen_remap_fails(self):
        source = self.rich_order()
        self.mark(source, 0)
        before = self.operation_snapshot([source])
        with patch("restaurant.order_kds.remap_order_kds", side_effect=RuntimeError("Injected KDS failure")):
            with self.assertRaises(RuntimeError):
                pos.split_order(
                    source.name, self.selection(source, qty=0.5), expected_modified=self.token(source)
                )
        self.assertEqual(self.operation_snapshot([source]), before)

    def test_partial_merge_rolls_back_both_accounts_and_tables_if_kitchen_remap_fails(self):
        source = self.rich_order(restaurant_table=self.make_table("Origen"))
        target = self.rich_order(restaurant_table=self.make_table("Destino"))
        self.mark(source, 0)
        self.mark(target, 0)
        before = self.operation_snapshot([source, target])
        with patch("restaurant.order_kds.remap_order_kds", side_effect=RuntimeError("Injected KDS failure")):
            with self.assertRaises(RuntimeError):
                pos.transfer_order_table(
                    source.name, target_order=target.name, split_items=self.selection(source, qty=0.5),
                    expected_modified=self.token(source), target_modified=self.token(target),
                )
        self.assertEqual(self.operation_snapshot([source, target]), before)

    def test_sent_food_remains_visible_when_merged_into_an_unsent_account(self):
        source = self.rich_order()
        self.mark(source, 0)
        target = self.make_order(sent=False)
        pending_names = {row.name for row in target.items}
        pos.transfer_order_table(
            source.name, target_order=target.name, expected_modified=self.token(source),
            target_modified=self.token(target),
        )
        cards = self.kitchen_cards(target)
        self.assertEqual(len(cards), 1)
        self.assertEqual(len(cards[0]["items"]), 2)
        self.assertEqual(cards[0]["stage_index"], 0)
        self.assertEqual(len(cards[0]["completed_item_names"]), 1)
        self.assertFalse(pending_names.intersection(row["name"] for row in cards[0]["items"]))
        self.assertNotEqual(self.document(target.name).kds_status, "Sin enviar")

    def test_unsent_food_does_not_enter_kitchen_when_merged_into_a_sent_account(self):
        source = self.rich_order(sent=False)
        target = self.rich_order()
        self.mark(target, 0)
        original_names = {row.name for row in target.items}
        pos.transfer_order_table(
            source.name, target_order=target.name, expected_modified=self.token(source),
            target_modified=self.token(target),
        )
        cards = self.kitchen_cards(target)
        self.assertEqual(len(cards), 1)
        self.assertEqual({row["name"] for row in cards[0]["items"]}, original_names)
        self.assertEqual(cards[0]["completed_item_names"], [target.items[0].name])
        pending = [row for row in self.document(target.name).items if row.name not in original_names]
        self.assertTrue(all(row.kds_status == "Pendiente" for row in pending))

    def test_empty_open_target_account_can_receive_food_and_its_kitchen_progress(self):
        source = self.rich_order()
        self.mark(source, 0)
        target = self.make_order(groups=(), sent=False)
        original = self.document(source.name)
        pos.transfer_order_table(
            source.name, target_order=target.name, expected_modified=self.token(source),
            target_modified=self.token(target),
        )
        self.assert_conserved([original], [self.document(target.name)])
        cards = self.kitchen_cards(target)
        self.assertEqual(len(cards), 1)
        self.assertEqual(len(cards[0]["items"]), 2)
        self.assertEqual(len(cards[0]["completed_item_names"]), 1)

    def test_split_preview_matches_persisted_totals_and_exposes_rounding_difference(self):
        source = self.rich_order()
        source.items[0].qty = 1
        source.items[0].base_rate = 99.99
        source.items[0].options_rate = 0
        source.items[0].discount_percentage = 0
        source.tip_percentage = 0
        source.tip_amount = 0
        prev_flag = getattr(frappe.flags, "in_restaurant_order_operation", False)
        frappe.flags.in_restaurant_order_operation = True
        try:
            source.save()
        finally:
            frappe.flags.in_restaurant_order_operation = prev_flag
        selection = self.selection(source, qty=0.5)
        preview = pos.preview_split_order(source.name, selection, expected_modified=self.token(source))
        result = pos.split_order(source.name, selection, expected_modified=self.token(source))
        self.assertEqual(result["new_order"]["grand_total"], preview["selected_total"])
        self.assertEqual(result["original_order"]["grand_total"], preview["remaining_total"])
        self.assertAlmostEqual(
            result["new_order"]["grand_total"] + result["original_order"]["grand_total"]
            - preview["original_total"], preview["rounding_difference"], places=2,
        )

    def test_invoice_link_is_rejected_even_if_account_status_still_says_open(self):
        invoice_name = frappe.db.get_value("Sales Invoice", {}, "name")
        self.assertTrue(invoice_name, "Development must provide an existing invoice link")
        source = self.rich_order()
        target = self.rich_order()
        source.sales_invoice = invoice_name
        source.save()
        before = self.operation_snapshot([source, target])
        with self.assertRaises(frappe.ValidationError):
            pos.split_order(source.name, self.selection(source), expected_modified=self.token(source))
        self.assertEqual(self.operation_snapshot([source, target]), before)
        source.sales_invoice = None
        source.save()
        target.sales_invoice = invoice_name
        target.save()
        before = self.operation_snapshot([source, target])
        with self.assertRaises(frappe.ValidationError):
            pos.transfer_order_table(
                source.name, target_order=target.name, expected_modified=self.token(source),
                target_modified=self.token(target),
            )
        self.assertEqual(self.operation_snapshot([source, target]), before)

    def test_fractional_native_quantity_survives_split_response_and_pos_save_roundtrip(self):
        source = self.rich_order(sent=False)
        original_quantities = self.row_quantities([source])
        result = pos.split_order(
            source.name, self.selection(source, qty=0.001), expected_modified=self.token(source)
        )
        self.assertEqual(result["new_order"]["items"][0]["qty"], 0.001)
        self.assertEqual(result["original_order"]["items"][0]["qty"], 1.999)
        saved = pos.save_pos_order(result["new_order"])["order"]
        self.assertEqual(saved["items"][0]["qty"], 0.001)
        self.assertEqual(self.row_quantities([
            self.document(source.name), self.document(saved["name"]),
        ]), original_quantities)

    def test_moving_current_batch_does_not_reopen_older_delivered_rows_remaining_at_source(self):
        display = frappe.get_doc("Restaurant Preparation Display", self.display)
        display.set("item_groups", [{"item_group": group} for group in self.groups])
        display.save()
        source = self.rich_order()
        self.complete(source)
        source.reload()
        source.append("items", {
            "item_code": self.items[0], "qty": 1, "base_rate": 100,
            "kds_status": "Pendiente", "command_station": "Cocina General",
        })
        source.save()
        pos.send_order_to_kitchen(source.name)
        source.reload()
        selection = [{"item_name": source.items[-1].name, "qty": 1}]
        result = pos.split_order(source.name, selection, expected_modified=self.token(source))
        created = self.document(result["new_order"]["name"])
        self.assertTrue(all(card["stage_index"] == 2 for card in self.kitchen_cards(source)))
        self.assertEqual(self.document(source.name).kds_status, "Entregado")
        self.assertEqual(len(self.kitchen_cards(created)), 1)
        self.assertEqual(self.kitchen_cards(created)[0]["stage_index"], 0)
        state = kds.get_kds_state(self.display)
        own_display = next(row for row in state["displays"] if row["name"] == self.display)
        self.assertEqual(own_display["in_progress_count"], 1)

    def test_split_then_pay_calls_native_invoice_lifecycle_with_exact_fractional_quantity(self):
        source = self.rich_order(sent=False)
        split = pos.split_order(
            source.name, self.selection(source, qty=0.001), expected_modified=self.token(source)
        )
        created = self.document(split["new_order"]["name"])
        invoice_name = frappe.db.get_value("Sales Invoice", {}, "name")
        self.assertTrue(invoice_name, "Development must provide an existing invoice link for the mock")
        fake_invoice = frappe._dict({
            "name": invoice_name, "customer": created.customer, "customer_name": created.customer_name,
            "company": created.company, "company_tax_id": "", "tax_id": "",
            "posting_date": frappe.utils.nowdate(), "cai": "PRUEBA-DIVISION",
            "due_date_cai": "2030-01-01", "grand_total": created.grand_total,
            "net_total": created.subtotal, "paid_amount": created.grand_total, "change_amount": 0,
            "payments": [frappe._dict(amount=created.grand_total)],
        })
        for method in ("set_missing_values", "calculate_taxes_and_totals", "insert", "submit"):
            fake_invoice[method] = Mock()
        real_get_doc = frappe.get_doc
        invoice_payloads = []

        def get_doc(*args, **kwargs):
            if args and isinstance(args[0], dict) and args[0].get("doctype") == "Sales Invoice":
                invoice_payloads.append(args[0])
                return fake_invoice
            return real_get_doc(*args, **kwargs)

        fiscal_info = {
            "cai": "PRUEBA-DIVISION", "due_date_cai": "2030-01-01",
            "authorized_range": "", "company_tax_id": "", "prefix": "",
        }
        with patch("restaurant.pos.frappe.get_doc", side_effect=get_doc), \
                patch("restaurant.pos._resolve_tax_account", return_value=None), \
                patch("restaurant.pos._resolve_payment_account", return_value=None), \
                patch("restaurant.pos._resolve_sar_fiscal_info", return_value=fiscal_info):
            paid = pos.pay_and_invoice_order(created.name)
        self.assertEqual(len(invoice_payloads), 1)
        self.assertEqual(invoice_payloads[0]["items"][0]["qty"], 0.001)
        fake_invoice.calculate_taxes_and_totals.assert_called_once()
        fake_invoice.insert.assert_called_once()
        fake_invoice.submit.assert_called_once()
        self.assertEqual(paid["order"]["status"], "Facturada")
        self.assertEqual(paid["order"]["sales_invoice"], invoice_name)
        self.assertEqual(paid["order"]["kds_status"], "Sin enviar")
        self.assertEqual(self.document(source.name).status, "En curso")

    def test_ticket_identifier_from_another_order_or_display_is_rejected_without_writes(self):
        second_display = self.make_display()
        source = self.rich_order()
        other = self.rich_order()
        self.mark(source, 0)
        self.mark(other, 0)
        foreign_tickets = (self.ticket(other).name, self.ticket(source, second_display).name)
        before = self.operation_snapshot([source, other])
        for foreign_ticket in foreign_tickets:
            with self.subTest(ticket_id=foreign_ticket):
                with self.assertRaises(frappe.PermissionError):
                    kds.toggle_item(
                        self.display, source.name, source.items[1].name, expected_stage=self.stages[0],
                        completed=1, ticket_id=foreign_ticket,
                    )
                self.assertEqual(self.operation_snapshot([source, other]), before)
