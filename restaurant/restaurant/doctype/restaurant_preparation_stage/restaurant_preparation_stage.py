"""Preparation stage configuration independent of financial documents."""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

from restaurant.location import _whole_number


class RestaurantPreparationStage(Document):
    def validate(self):
        self.stage_name = cstr(self.stage_name).strip()
        if not self.stage_name or len(self.stage_name) > 140:
            frappe.throw(_("Ingresa un nombre de etapa de hasta 140 caracteres."))
        self.color = cstr(self.color or "#9CA3AF").strip().upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", self.color):
            frappe.throw(_("El color de la etapa debe usar el formato #RRGGBB."))
        self.alert_minutes = _whole_number(
            self.alert_minutes if self.alert_minutes not in (None, "") else 0,
            _("Temporizador de alerta"), 0,
        )

