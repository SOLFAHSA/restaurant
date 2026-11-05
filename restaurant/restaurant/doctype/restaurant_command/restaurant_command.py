from frappe.model.document import Document

from restaurant.commands import validate_command


class RestaurantCommand(Document):
    def validate(self):
        validate_command(self)
