"""Configuration validation applies to native forms and imports alike."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestRestaurantPreparationStage(FrappeTestCase):
    def test_color_and_timer_are_validated_before_persistence(self):
        stage = frappe.get_doc({
            "doctype": "Restaurant Preparation Stage", "stage_name": "Preparación de prueba",
            "color": "#aabbcc", "alert_minutes": 0,
        })
        stage.validate()
        self.assertEqual(stage.color, "#AABBCC")
        for color in ("red", "#FFF", "#000000;display:none"):
            stage.color = color
            with self.assertRaises(frappe.ValidationError):
                stage.validate()
        stage.color = "#AABBCC"
        for minutes in (-1, 1.5, "NaN", True):
            stage.alert_minutes = minutes
            with self.assertRaises(frappe.ValidationError):
                stage.validate()

