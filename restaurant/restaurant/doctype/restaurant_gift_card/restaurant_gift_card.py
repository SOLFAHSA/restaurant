"""Controller for Restaurant Gift Card balance and expiry validation."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today


class RestaurantGiftCard(Document):
    def validate(self):
        self.card_code = (self.card_code or "").strip().upper()
        if not self.card_code:
            frappe.throw(_("El código de la tarjeta de regalo es obligatorio."))
        if flt(self.initial_amount) <= 0:
            frappe.throw(_("El monto inicial debe ser mayor a cero."))
        if self.is_new() and flt(self.balance) == 0:
            self.balance = flt(self.initial_amount)
        if flt(self.balance) < 0:
            frappe.throw(_("El saldo disponible no puede ser negativo."))
        if self.expiry_date and getdate(self.expiry_date) < getdate(today()):
            self.enabled = 0

