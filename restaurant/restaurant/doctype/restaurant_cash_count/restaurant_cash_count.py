# Copyright (c) 2026, Grintsys and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from restaurant.cash_count import (
    close_linked_pos_shift_from_count,
    recalculate_cash_count_doc,
)


class RestaurantCashCount(Document):
    """Submittable cash audit document linked to a POS Opening Shift."""

    def validate(self):
        use_denom = bool(getattr(self.flags, "use_denomination_cash_total", False))
        recalculate_cash_count_doc(self, use_denomination_cash_total=use_denom)

    def before_submit(self):
        if self.count_type == "Arqueo de Cierre":
            shift_status = frappe.db.get_value(
                "POS Opening Shift", self.pos_opening_shift, "status"
            )
            if shift_status != "Open":
                frappe.throw(
                    _(
                        "El turno {0} ya se encuentra cerrado ({1}). "
                        "Usa Arqueo Parcial o selecciona un turno abierto."
                    ).format(self.pos_opening_shift, shift_status or _("Desconocido"))
                )

    def on_submit(self):
        if self.count_type == "Arqueo de Cierre":
            result = close_linked_pos_shift_from_count(self)
            closing_name = result.get("pos_closing_shift") or ""
            if closing_name:
                self.pos_closing_shift = closing_name
                self.db_set("pos_closing_shift", closing_name, update_modified=False)

    def on_cancel(self):
        if self.pos_closing_shift and frappe.db.exists(
            "POS Closing Shift", self.pos_closing_shift
        ):
            closing_docstatus = frappe.db.get_value(
                "POS Closing Shift", self.pos_closing_shift, "docstatus"
            )
            if closing_docstatus == 1:
                frappe.throw(
                    _(
                        "No puedes cancelar este arqueo mientras el cierre de caja {0} siga validado. "
                        "Cancela primero el cierre de caja."
                    ).format(self.pos_closing_shift)
                )

