# Copyright (c) 2026, Grintsys and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from restaurant.pos import sync_table_status_for_order, validate_order
from restaurant.pos_auth import is_supervisor


class RestaurantOrder(Document):
    def validate(self):
        validate_order(self)

    def on_update(self):
        sync_table_status_for_order(self)

    def on_trash(self):
        if self.status == "Facturada":
            frappe.throw(_("No se puede eliminar una orden ya facturada."), frappe.PermissionError)
        has_sent_items = any(
            getattr(row, "kds_status", None) not in (None, "", "Pendiente")
            for row in (self.items or [])
        )
        if has_sent_items and not is_supervisor():
            frappe.throw(
                _("No tienes permiso para eliminar una orden con platillos enviados a cocina. Usa cancelación autorizada."),
                frappe.PermissionError,
            )

    def after_delete(self):
        sync_table_status_for_order(self, deleted=True)

