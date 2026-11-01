"""Native persistence, validation, permission, and concurrency regression tests."""

from copy import deepcopy
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant.location import get_editor_context, save_location


class TestRestaurantArea(FrappeTestCase):
    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.savepoint = "restaurant_area_test"
        frappe.db.savepoint(self.savepoint)
        self.suffix = uuid4().hex[:10]
        self.branch = frappe.get_doc({
            "doctype": "Branch", "branch": "_Test Restaurant " + self.suffix,
        }).insert().name
        self.location_count = frappe.db.count("Location")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=self.savepoint)
        frappe.clear_cache(doctype="Restaurant Area")
        frappe.set_user(self.original_user)

    def make_payload(self, **values):
        payload = get_editor_context()["doc"]
        payload.update({
            "area_name": "_Test Area " + self.suffix,
            "branch": self.branch,
            "capacity": 24,
        })
        payload.update(values)
        return payload

    def test_round_trip_uses_independent_doctype(self):
        saved = save_location(self.make_payload(description="Área al aire libre.", notes="Prueba"))
        loaded = get_editor_context(saved.name)["doc"]
        self.assertEqual(loaded.area_name, saved.area_name)
        self.assertEqual(loaded.branch, self.branch)
        self.assertEqual(loaded.capacity, 24)
        self.assertEqual(loaded.description, "Área al aire libre.")
        self.assertEqual(frappe.db.count("Location"), self.location_count)
        self.assertFalse(get_editor_context(saved.name)["kds_available"])
        self.assertFalse(get_editor_context(saved.name)["tables_available"])

    def test_invalid_values_rejected_by_native_controller(self):
        for field, value in (
            ("capacity", 0), ("capacity", 2.5), ("display_order", -1),
            ("display_order", 1.5), ("description", "a" * 501),
            ("notes", "a" * 301), ("color", "red"),
            ("area_type", "Warehouse"), ("status", "Unknown"),
            ("icon", "invalid"), ("visible_in_pos", 3),
        ):
            with self.subTest(field=field, value=str(value)[:30]):
                payload = self.make_payload(**{field: value})
                doc = frappe.get_doc(payload)
                with self.assertRaises(frappe.ValidationError):
                    doc.run_method("validate")

    def test_external_or_missing_images_rejected(self):
        for image in ("https://example.com/image.png", "/files/missing.png", "/files/../private.png"):
            with self.subTest(image=image):
                with self.assertRaises(frappe.ValidationError):
                    save_location(self.make_payload(image=image))

    def test_guest_cannot_create_or_read(self):
        payload = self.make_payload()
        saved = save_location(payload)
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            get_editor_context()
        with self.assertRaises(frappe.PermissionError):
            get_editor_context(saved.name)
        with self.assertRaises(frappe.PermissionError):
            save_location(payload)

    def test_stale_update_uses_native_timestamp_check(self):
        saved = save_location(self.make_payload())
        stale = deepcopy(saved)
        current = deepcopy(saved)
        current.description = "Cambio más reciente"
        updated = save_location(current)
        self.assertNotEqual(str(updated.modified), str(stale.modified))
        stale.description = "Cambio obsoleto"
        with self.assertRaises(frappe.TimestampMismatchError):
            save_location(stale)
        self.assertEqual(frappe.db.get_value("Restaurant Area", saved.name, "description"), "Cambio más reciente")

    def test_missing_timestamp_cannot_overwrite(self):
        saved = save_location(self.make_payload())
        del saved["modified"]
        with self.assertRaises(frappe.ValidationError):
            save_location(saved)

    def test_payload_cannot_escalate_permissions(self):
        payload = self.make_payload()
        payload["flags"] = {"ignore_permissions": True}
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            save_location(payload)

    def test_wrong_document_type_rejected(self):
        payload = self.make_payload()
        payload["doctype"] = "Location"
        with self.assertRaises(frappe.ValidationError):
            save_location(payload)

    def test_branch_user_permission_is_enforced(self):
        other_branch = frappe.get_doc({
            "doctype": "Branch", "branch": "_Test Restricted " + self.suffix,
        }).insert().name
        user_name = "restaurant-area-" + self.suffix + "@example.invalid"
        frappe.get_doc({
            "doctype": "User", "email": user_name, "first_name": "Prueba",
            "send_welcome_email": 0,
            "roles": [{"role": "Restaurant Manager"}],
        }).insert()
        frappe.get_doc({
            "doctype": "User Permission", "user": user_name,
            "allow": "Branch", "for_value": self.branch, "apply_to_all_doctypes": 1,
        }).insert()
        allowed_payload = self.make_payload()
        restricted_payload = self.make_payload(branch=other_branch, area_name="_Test Restricted Area " + self.suffix)
        frappe.set_user(user_name)
        selection_rule = frappe.db.get_value("Custom DocPerm", {
            "parent": "Employee", "role": "Restaurant Manager", "permlevel": 0,
        }, ["select", "read"], as_dict=True)
        self.assertEqual(selection_rule.select, 1)
        self.assertFalse(selection_rule.read)
        self.assertEqual(save_location(allowed_payload).branch, self.branch)
        with self.assertRaises(frappe.PermissionError):
            save_location(restricted_payload)

    def test_read_only_user_can_open_list_but_not_create(self):
        role = "Restaurant Area Reader " + self.suffix
        frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()
        from frappe.permissions import add_permission
        add_permission("Restaurant Area", role, ptype="read")
        frappe.clear_cache(doctype="Restaurant Area")
        user_name = "restaurant-reader-" + self.suffix + "@example.invalid"
        frappe.get_doc({
            "doctype": "User", "email": user_name, "first_name": "Prueba",
            "send_welcome_email": 0, "roles": [{"role": role}],
        }).insert()
        frappe.set_user(user_name)
        context = get_editor_context(for_list=1)
        self.assertFalse(context["can_create"])
        self.assertEqual(context["doc"]["doctype"], "Restaurant Area")
        with self.assertRaises(frappe.PermissionError):
            get_editor_context()
