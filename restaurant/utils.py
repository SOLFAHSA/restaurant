"""Shared validation and conversion helpers for the Restaurant app."""

from decimal import Decimal, InvalidOperation

import frappe
from frappe import _


def parse_whole_number(value, label, minimum=0):
	"""Validate and return an integer within [minimum, 2147483647]."""
	try:
		number = Decimal(str(value))
		if isinstance(value, bool) or not number.is_finite() or number != number.to_integral_value():
			raise InvalidOperation
		if number < minimum or number > 2147483647:
			raise InvalidOperation
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("{0} debe ser un número entero mayor o igual a {1}.").format(label, minimum))
	return int(number)


def validate_bool_flag(value, label, allow_none=False):
	"""Validate a Frappe Check flag (0/1/bool) and return 0 or 1."""
	if allow_none and value is None:
		return 0
	if value not in (0, 1, "0", "1", False, True):
		frappe.throw(_("El valor de {0} no es válido.").format(label))
	return int(value)


def check_readable_link(doctype, name):
	"""Verify read/select and User Permission access to a linked document."""
	doc = frappe.get_doc(doctype, name)
	allowed = frappe.has_permission(doctype, "read", doc=doc)
	if doctype in ("Branch", "Employee"):
		allowed = allowed or frappe.has_permission(doctype, "select", doc=doc)
	if not allowed or not frappe.permissions.has_user_permission(doc):
		frappe.throw(_("No tienes permiso para seleccionar ese registro."), frappe.PermissionError)
	return doc

