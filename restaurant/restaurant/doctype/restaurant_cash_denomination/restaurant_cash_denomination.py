# Copyright (c) 2026, Grintsys and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class RestaurantCashDenomination(Document):
    """Master catalog of bill and coin denominations used in Restaurant Cash Count."""

    def validate(self):
        if flt(self.unit_value) <= 0:
            frappe.throw(_("El valor unitario de la denominación debe ser mayor que cero."))
        self.denomination_label = (self.denomination_label or "").strip()
        if not self.denomination_label:
            prefix = "Billetes" if self.denomination_type == "Billete" else "Monedas"
            symbol = "L" if (self.currency or "HNL") == "HNL" else (self.currency or "")
            val = flt(self.unit_value)
            val_txt = str(int(val)) if val.is_integer() else f"{val:.2f}"
            self.denomination_label = f"{prefix} {symbol} {val_txt}".strip()

