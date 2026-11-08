"""Operational tickets cannot be edited through ordinary document APIs."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestRestaurantPreparationTicket(FrappeTestCase):
    def test_ticket_has_no_document_write_or_create_grants(self):
        meta = frappe.get_meta("Restaurant Preparation Ticket")
        self.assertFalse(meta.allow_import)
        for permission in meta.permissions:
            self.assertFalse(permission.write)
            self.assertFalse(permission.create)
            self.assertFalse(permission.delete)

