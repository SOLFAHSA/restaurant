"""Regression tests for safe, repeatable development demonstration data."""

from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant import demo_data


class TestDemoData(FrappeTestCase):
    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.savepoint = "restaurant_seed_test"
        frappe.db.savepoint(self.savepoint)
        self.counts = {dt: frappe.db.count(dt) for dt in demo_data.DOCTYPES}
        prefix = "DEMO-REST-TEST-" + uuid4().hex[:10]
        self.patchers = [
            patch.object(demo_data, "PREFIX", prefix),
            patch.object(demo_data, "UNIT", prefix + " Unidad"),
            patch.object(demo_data, "GROUP", prefix + " Menú"),
            patch.object(demo_data, "PRICE_LIST", prefix + " Precios HNL"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=self.savepoint)
        frappe.set_user(self.original_user)

    def test_repeat_execution_preserves_records_and_native_links(self):
        native_items = frappe.get_all("Item", fields=["name", "item_name", "item_group", "stock_uom", "modified"])
        native_prices = frappe.get_all("Item Price", fields=["name", "item_code", "price_list", "price_list_rate", "modified"])
        first = demo_data.seed()
        expected = {"UOM": 1, "Item Group": 1, "Price List": 1, "Branch": 4,
                    "Restaurant Area": 24, "Item": 12, "Item Price": 12}
        self.assertEqual(first["created"], expected)
        second = demo_data.seed()
        self.assertEqual(second["total_created"], 0)
        self.assertEqual(second["existing"], expected)
        self.assertEqual(first["records"], second["records"])
        for original in native_items:
            current = frappe.db.get_value("Item", original.name, list(original), as_dict=True)
            self.assertEqual(current, original)
        for original in native_prices:
            current = frappe.db.get_value("Item Price", original.name, list(original), as_dict=True)
            self.assertEqual(current, original)
        for name in first["records"]["Restaurant Area"]:
            self.assertIn(frappe.db.get_value("Restaurant Area", name, "branch"), first["records"]["Branch"])
        for name in first["records"]["Item Price"]:
            price = frappe.get_doc("Item Price", name)
            self.assertIn(price.item_code, first["records"]["Item"])
            self.assertEqual(price.price_list, demo_data.PRICE_LIST)
            self.assertEqual(price.currency, "HNL")
        self.assertEqual(frappe.db.count("Item", {"name": ["not like", demo_data.PREFIX + "%"]}), self.counts["Item"])
        self.assertFalse(frappe.db.exists("Item", {"name": ["like", demo_data.PREFIX + "%"], "is_stock_item": 1}))

    def test_existing_modified_demo_record_is_not_overwritten(self):
        initial = demo_data.seed()
        area_name = initial["records"]["Restaurant Area"][0]
        area = frappe.get_doc("Restaurant Area", area_name)
        area.capacity = 99
        area.save()
        with self.assertRaises(frappe.ValidationError):
            demo_data.seed()
        self.assertEqual(frappe.db.get_value("Restaurant Area", area_name, "capacity"), 99)

    def test_failed_run_rolls_back_new_records(self):
        original_ensure = demo_data._ensure
        calls = 0

        def fail_after_native_insert(*args, **kwargs):
            nonlocal calls
            result = original_ensure(*args, **kwargs)
            calls += 1
            if calls == 5:
                raise RuntimeError("Injected failure after native inserts")
            return result

        with patch.object(demo_data, "_ensure", side_effect=fail_after_native_insert):
            with self.assertRaises(RuntimeError):
                demo_data.seed()
        self.assertEqual({dt: frappe.db.count(dt) for dt in demo_data.DOCTYPES}, self.counts)

    def test_other_sites_and_disabled_developer_mode_are_rejected(self):
        with patch.object(frappe.local, "site", "production"):
            with self.assertRaises(frappe.PermissionError):
                demo_data.seed()
        with patch.dict(frappe.conf, {"developer_mode": 0}):
            with self.assertRaises(frappe.PermissionError):
                demo_data.seed()
        self.assertEqual({dt: frappe.db.count(dt) for dt in demo_data.DOCTYPES}, self.counts)

    def test_guest_cannot_load_demonstration_data(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            demo_data.seed()
        frappe.set_user("Administrator")
        self.assertEqual({dt: frappe.db.count(dt) for dt in demo_data.DOCTYPES}, self.counts)
