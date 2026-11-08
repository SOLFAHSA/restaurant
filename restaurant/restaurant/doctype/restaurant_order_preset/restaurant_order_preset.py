# Copyright (c) 2026, Grintsys and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class RestaurantOrderPreset(Document):
    def validate(self):
        if self.is_default:
            # Only one default preset allowed
            frappe.db.sql(
                "UPDATE `tabRestaurant Order Preset` SET is_default = 0 WHERE name != %s",
                self.name or ""
            )

