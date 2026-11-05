# Copyright (c) 2026, Grintsys and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from restaurant.pos import sync_table_status_for_order, validate_order


class RestaurantOrder(Document):
    def validate(self):
        validate_order(self)

    def on_update(self):
        sync_table_status_for_order(self)

    def after_delete(self):
        sync_table_status_for_order(self, deleted=True)

