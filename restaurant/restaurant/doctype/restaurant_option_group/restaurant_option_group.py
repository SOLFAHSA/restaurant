"""Customer option groups with server-side ownership and ingredient validation."""

from frappe.model.document import Document

from restaurant.item_configuration import _locked_item, validate_option_group


class RestaurantOptionGroup(Document):
    def validate(self):
        validate_option_group(self)

    def on_trash(self):
        _locked_item(self.main_item)
