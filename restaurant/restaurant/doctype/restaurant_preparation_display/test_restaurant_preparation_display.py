"""Screen validation protects filter links and active stage sequences."""

from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from restaurant.restaurant.doctype.restaurant_preparation_display.restaurant_preparation_display import (
    _ticket_has_current_rows,
)


class TestRestaurantPreparationDisplay(FrappeTestCase):
    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        frappe.db.savepoint("preparation_display_test")
        self.stage_names = [frappe.get_doc({
            "doctype": "Restaurant Preparation Stage", "stage_name": f"Etapa {index} {uuid4().hex[:8]}",
            "color": color, "alert_minutes": minutes,
        }).insert().name for index, (color, minutes) in enumerate((
            ("#9CA3AF", 10), ("#3B82F6", 5), ("#55A61C", 0),
        ))]

    def tearDown(self):
        frappe.db.rollback(save_point="preparation_display_test")
        frappe.set_user(self.original_user)

    def make_display(self):
        return frappe.get_doc({
            "doctype": "Restaurant Preparation Display", "display_name": "Pantalla de prueba",
            "enabled": 1, "auto_clear": 0, "auto_clear_minutes": 10,
            "stages": [{"stage": name} for name in self.stage_names],
        })

    def test_optional_filters_mean_all_and_auto_clear_requires_positive_minutes(self):
        doc = self.make_display().insert()
        self.assertFalse(doc.pos_profiles)
        self.assertFalse(doc.item_groups)
        doc.auto_clear = 1
        for minutes in (0, -1, 1.5):
            doc.auto_clear_minutes = minutes
            with self.assertRaises(frappe.ValidationError):
                doc.validate()
        doc.auto_clear_minutes = 2
        doc.save()
        self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, "auto_clear_minutes"), 2)

    def test_duplicate_or_missing_stages_are_rejected(self):
        doc = self.make_display()
        doc.set("stages", [{"stage": self.stage_names[0]}] * 3)
        with self.assertRaises(frappe.ValidationError):
            doc.insert()
        doc = self.make_display()
        doc.set("stages", [{"stage": name} for name in self.stage_names[:2]])
        with self.assertRaises(frappe.ValidationError):
            doc.insert()

    def test_expired_tickets_allow_reordering_using_previous_retirement_policy(self):
        doc = self.make_display()
        doc.auto_clear = 1
        doc.auto_clear_minutes = 10
        doc.insert()
        previous = deepcopy(doc)
        doc._doc_before_save = previous
        doc.auto_clear = 0
        doc.auto_clear_minutes = 60
        doc.set("stages", [{"stage": name} for name in reversed(self.stage_names)])
        current_time = now_datetime()
        ticket = frappe._dict({
            "stage_index": 2, "stages_json": json.dumps(self.stage_names),
            "completed_at": current_time - timedelta(minutes=10),
        })
        module = "restaurant.restaurant.doctype.restaurant_preparation_display.restaurant_preparation_display"
        with patch(module + ".frappe.get_all", return_value=[ticket]) as get_tickets:
            with patch(module + ".now_datetime", return_value=current_time), \
                    patch(module + "._ticket_has_current_rows", return_value=True):
                original_ticket = dict(ticket)
                doc.validate()
                self.assertEqual(dict(ticket), original_ticket)
                self.assertEqual(get_tickets.call_args.kwargs["fields"], [
                    "stage_index", "stages_json", "completed_at", "restaurant_order",
                    "active_item_names_json", "included_item_names_json",
                ])
                ticket.completed_at = current_time - timedelta(minutes=9)
                with self.assertRaises(frappe.ValidationError):
                    doc.validate()
                ticket.completed_at = None
                with self.assertRaises(frappe.ValidationError):
                    doc.validate()
                ticket.completed_at = current_time - timedelta(minutes=11)
                ticket.stage_index = 1
                with self.assertRaises(frappe.ValidationError):
                    doc.validate()
                ticket.stage_index = 2
                previous.auto_clear = 0
                with self.assertRaises(frappe.ValidationError):
                    doc.validate()

    def test_moved_segments_and_cancelled_orders_do_not_block_stage_configuration(self):
        module = "restaurant.restaurant.doctype.restaurant_preparation_display.restaurant_preparation_display"
        ticket = frappe._dict({
            "restaurant_order": "ORD-TEST", "active_item_names_json": '["row-a"]',
            "included_item_names_json": '["row-a"]',
        })
        with patch(module + ".frappe.db.get_value", return_value=frappe._dict({
            "status": "Cancelada", "docstatus": 0,
        })):
            self.assertFalse(_ticket_has_current_rows(ticket))
        with patch(module + ".frappe.db.get_value", return_value=frappe._dict({
            "status": "En curso", "docstatus": 0,
        })), patch(module + ".frappe.db.exists", return_value=False) as row_exists:
            self.assertFalse(_ticket_has_current_rows(ticket))
            self.assertEqual(row_exists.call_args.args[1]["parent"], "ORD-TEST")
        with patch(module + ".frappe.db.get_value", return_value=frappe._dict({
            "status": "En curso", "docstatus": 0,
        })), patch(module + ".frappe.db.exists", return_value=True):
            self.assertTrue(_ticket_has_current_rows(ticket))

