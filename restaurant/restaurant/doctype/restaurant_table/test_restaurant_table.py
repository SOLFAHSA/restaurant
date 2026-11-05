"""Unit tests for Restaurant Table and the interactive Floor Map Designer."""

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant.location import get_editor_context, save_location
from restaurant.table_management import (
    delete_table,
    get_area_tables,
    get_map_context,
    save_area_map,
    save_table,
    update_table_status,
)


class TestRestaurantTable(FrappeTestCase):
    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.savepoint = "restaurant_table_test"
        frappe.db.savepoint(self.savepoint)
        self.suffix = uuid4().hex[:8]
        self.branch = frappe.get_doc({
            "doctype": "Branch",
            "branch": "_Test Branch " + self.suffix,
        }).insert().name
        self.area = save_location({
            "doctype": "Restaurant Area",
            "area_name": "Salón Principal " + self.suffix,
            "branch": self.branch,
            "capacity": 40,
            "status": "Activa",
            "icon": "Salón",
            "color": "#22C55E",
            "visible_in_pos": 1,
            "allow_open_accounts": 1,
            "display_order": 1,
        }).name

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=self.savepoint)
        frappe.set_user(self.original_user)

    def test_table_creation_and_branch_inheritance(self):
        res = save_table({
            "doctype": "Restaurant Table",
            "restaurant_area": self.area,
            "table_number": "1",
            "seats": 4,
            "shape": "Cuadrada",
            "status": "Disponible",
        })
        table = res["table"]
        self.assertEqual(table["restaurant_area"], self.area)
        self.assertEqual(table["branch"], self.branch)
        self.assertEqual(table["table_number"], "1")
        self.assertEqual(table["seats"], 4)
        self.assertEqual(len(res["tables"]), 1)

        editor_ctx = get_editor_context(self.area)
        self.assertTrue(editor_ctx["tables_available"])
        self.assertEqual(len(editor_ctx["tables"]), 1)
        self.assertEqual(editor_ctx["tables"][0]["table_number"], "1")

    def test_duplicate_table_number_in_same_area_rejected(self):
        save_table({
            "restaurant_area": self.area,
            "table_number": "M-10",
            "seats": 4,
        })
        with self.assertRaises(frappe.ValidationError):
            save_table({
                "restaurant_area": self.area,
                "table_number": "m-10",
                "seats": 6,
            })

    def test_invalid_table_fields_rejected(self):
        for field, value in (
            ("table_number", ""),
            ("seats", 0),
            ("seats", 600),
            ("shape", "Triangular"),
            ("status", "Cerrada"),
            ("color", "verde"),
        ):
            with self.subTest(field=field, value=value):
                payload = {
                    "restaurant_area": self.area,
                    "table_number": f"T-{field}",
                    "seats": 4,
                    "shape": "Cuadrada",
                    "status": "Disponible",
                    "color": "#22C55E",
                    field: value,
                }
                with self.assertRaises(frappe.ValidationError):
                    save_table(payload)

    def test_floor_map_round_trip_and_table_assignment(self):
        t1 = save_table({
            "restaurant_area": self.area,
            "table_number": "1",
            "seats": 4,
            "shape": "Cuadrada",
        })["table"]
        t2 = save_table({
            "restaurant_area": self.area,
            "table_number": "2",
            "seats": 6,
            "shape": "Redonda",
        })["table"]

        elements = [
            {
                "id": "el_table_1",
                "category": "tables",
                "subtype": "table_square_wood",
                "x": 120,
                "y": 90,
                "width": 90,
                "height": 90,
                "rotation": 0,
                "table_name": t1["name"],
            },
            {
                "id": "el_table_2",
                "category": "tables",
                "subtype": "table_court_soccer",
                "x": 280,
                "y": 90,
                "width": 96,
                "height": 96,
                "rotation": 90,
                "table_name": t2["name"],
            },
            {
                "id": "el_chair_1",
                "category": "chairs",
                "subtype": "chair_armchair_red",
                "x": 120,
                "y": 40,
                "width": 54,
                "height": 54,
                "rotation": 180,
            },
            {
                "id": "el_plant_1",
                "category": "decor",
                "subtype": "decor_palm",
                "x": 420,
                "y": 60,
                "width": 86,
                "height": 86,
                "rotation": 0,
            },
        ]

        saved_ctx = save_area_map(
            area_name=self.area,
            floor_background="Césped",
            elements=elements,
        )
        self.assertEqual(saved_ctx["area"]["floor_background"], "Césped")
        self.assertEqual(len(saved_ctx["elements"]), 4)
        # Assigning a soccer court element updates the linked table shape
        updated_t2 = frappe.get_doc("Restaurant Table", t2["name"])
        self.assertEqual(updated_t2.shape, "Cancha fútbol")

        # Duplicate table assignment on the same map is rejected
        with self.assertRaises(frappe.ValidationError):
            save_area_map(
                area_name=self.area,
                floor_background="Césped",
                elements=[
                    elements[0],
                    {**elements[1], "table_name": t1["name"]},
                ],
            )

        # Updating operational status works
        status_res = update_table_status(t1["name"], "Ocupada")
        self.assertEqual(status_res["table"]["status"], "Ocupada")

        # Deleting a table detaches it from the floor map
        delete_table(t1["name"])
        reloaded = get_map_context(self.area)
        self.assertEqual(len(get_area_tables(self.area)), 1)
        el1 = next(item for item in reloaded["elements"] if item["id"] == "el_table_1")
        self.assertNotIn("table_name", el1)

