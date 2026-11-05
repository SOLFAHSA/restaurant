# Copyright (c) 2026, Grintsys and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from restaurant.table_management import validate_table


class RestaurantTable(Document):
    def validate(self):
        validate_table(self)

