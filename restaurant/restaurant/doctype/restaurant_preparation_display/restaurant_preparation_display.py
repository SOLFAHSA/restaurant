"""Validate preparation screens through every native document write path."""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, get_datetime, now_datetime

from restaurant.location import _whole_number


class RestaurantPreparationDisplay(Document):
    def validate(self):
        self.display_name = cstr(self.display_name).strip()
        if not self.display_name or len(self.display_name) > 140:
            frappe.throw(_("Ingresa un nombre de pantalla de hasta 140 caracteres."))
        self.description = cstr(self.description).strip()
        if len(self.description) > 2000:
            frappe.throw(_("La descripción de la pantalla no puede superar 2000 caracteres."))
        for fieldname, label in (("enabled", _("Activa")), ("auto_clear", _("Eliminación automática"))):
            value = self.get(fieldname)
            if value not in (0, 1, "0", "1", False, True):
                frappe.throw(_("El valor de {0} no es válido.").format(label))
            self.set(fieldname, int(value))
        self.auto_clear_minutes = _whole_number(
            self.auto_clear_minutes if self.auto_clear_minutes not in (None, "") else 0,
            _("Minutos para retirar pedidos"), 1 if self.auto_clear else 0,
        )
        self._validate_selection("pos_profiles", "pos_profile", "POS Profile")
        self._validate_selection("item_groups", "item_group", "Item Group")
        self._validate_selection("stages", "stage", "Restaurant Preparation Stage")
        if len(self.get("stages") or []) < 3:
            frappe.throw(_("Selecciona al menos tres etapas de preparación en el orden del proceso."))
        before = self.get_doc_before_save()
        if before and [row.stage for row in before.stages] != [row.stage for row in self.stages]:
            if self._has_active_tickets(before):
                frappe.throw(_("Retira los pedidos activos de esta pantalla antes de cambiar el orden o la selección de etapas."))

    def _has_active_tickets(self, previous_policy):
        current_time = now_datetime()
        for ticket in frappe.get_all(
            "Restaurant Preparation Ticket",
            filters={"preparation_display": self.name, "cleared_at": ["is", "not set"]},
            fields=[
                "stage_index", "stages_json", "completed_at", "restaurant_order",
                "active_item_names_json", "included_item_names_json",
            ], limit_page_length=0,
        ):
            if _ticket_has_current_rows(ticket) and not _ticket_expired(ticket, previous_policy, current_time):
                return True
        return False

    def _validate_selection(self, fieldname, link_field, doctype):
        selected = set()
        for row in self.get(fieldname) or []:
            value = cstr(row.get(link_field)).strip()
            if not value or value in selected:
                frappe.throw(_("Selecciona registros válidos sin repetirlos en {0}.").format(_(self.meta.get_label(fieldname))))
            linked = frappe.get_doc(doctype, value)
            if not (linked.has_permission("read") or linked.has_permission("select")):
                frappe.throw(_("No tienes permiso para seleccionar ese registro."), frappe.PermissionError)
            if not frappe.permissions.has_user_permission(linked):
                frappe.throw(_("No tienes permiso para seleccionar ese registro."), frappe.PermissionError)
            row.set(link_field, value)
            selected.add(value)


def _ticket_has_current_rows(ticket):
    """Ignore historical source segments after their rows move to another order."""
    order = frappe.db.get_value(
        "Restaurant Order", ticket.restaurant_order, ["status", "docstatus"], as_dict=True,
    )
    if not order or order.status not in ("En curso", "Facturada") or cint(order.docstatus) == 2:
        return False
    try:
        names = json.loads(ticket.active_item_names_json or ticket.included_item_names_json or "[]")
    except (TypeError, ValueError):
        return True
    if not isinstance(names, list):
        return True
    if not names:
        return False
    return bool(frappe.db.exists("Restaurant Order Item", {
        "parent": ticket.restaurant_order, "parenttype": "Restaurant Order",
        "name": ["in", names],
    }))


def _ticket_expired(ticket, previous_policy, current_time):
    """Evaluate the saved retirement policy without modifying ticket history."""
    if not cint(previous_policy.auto_clear) or not ticket.completed_at:
        return False
    try:
        stages = json.loads(ticket.stages_json or "[]")
        if not isinstance(stages, list) or not stages:
            return False
        if cint(ticket.stage_index) != len(stages) - 1:
            return False
        elapsed = (current_time - get_datetime(ticket.completed_at)).total_seconds()
        return elapsed >= cint(previous_policy.auto_clear_minutes) * 60
    except (TypeError, ValueError):
        return False

