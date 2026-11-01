# Copyright (c) 2026, Grintsys and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from restaurant.location import validate_area


class RestaurantArea(Document):
    def validate(self):
        validate_area(self)
