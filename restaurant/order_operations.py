"""Atomic redistribution of unbilled restaurant accounts and kitchen progress."""

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_datetime

from restaurant.pos import _get_areas_with_live_tables, _require_pos_user, _serialize_order, validate_order

ORDER = "Restaurant Order"
TABLE = "Restaurant Table"
COMPATIBILITY_FIELDS = ("company", "currency", "pos_profile", "selling_price_list", "pos_opening_shift")
HEADER_FIELDS = (
    "reference_note", "service_type", "restaurant_area", "restaurant_table", "guests",
    "waiter", "customer", "tax_id", "pos_profile", "pos_opening_shift", "company",
    "currency", "selling_price_list", "scheduled_time", "customer_note", "tip_percentage",
    "tip_amount", "kds_status", "sent_to_kitchen_at",
)
ITEM_FIELDS = (
    "item_code", "item_name", "item_group", "qty", "uom", "base_rate", "options_rate",
    "discount_percentage", "rate", "amount", "tax_rate", "options_summary",
    "selected_options_json", "note", "command_station", "kds_status",
)


@contextmanager
def _atomic_operation():
    """Preserve the caller transaction while undoing an incomplete operation."""
    savepoint = "restaurant_operation_" + uuid4().hex
    frappe.db.savepoint(savepoint)
    try:
        yield
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise


def _identifier(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 140:
        frappe.throw(_("Selecciona un registro válido para {0}.").format(label))
    return value.strip()


def check_order_version(doc, expected_modified):
    """Accept legacy callers without a token and reject every supplied stale token."""
    if expected_modified in (None, ""):
        return
    try:
        matches = isinstance(expected_modified, (str, datetime)) and get_datetime(expected_modified) == get_datetime(doc.modified)
    except (TypeError, ValueError, OverflowError):
        matches = False
    if not matches:
        frappe.throw(_("La cuenta cambió desde que la abriste. Actualiza la información y vuelve a intentarlo."), frappe.TimestampMismatchError)


def _check_open_order(doc, require_items=True):
    doc.check_permission("read")
    doc.check_permission("write")
    if doc.status != "En curso" or int(doc.docstatus) != 0 or doc.sales_invoice:
        frappe.throw(_("Solo puedes dividir o transferir cuentas abiertas que todavía no estén facturadas."))
    if require_items and not doc.items:
        frappe.throw(_("La cuenta debe contener al menos un platillo para dividirla o transferirla."))


def _load_source(order_name, expected_modified=None, for_update=False):
    name = _identifier(order_name, _("la cuenta de origen"))
    doc = frappe.get_doc(ORDER, name, for_update=for_update)
    _check_open_order(doc)
    check_order_version(doc, expected_modified)
    return doc


def _compatible(source, target):
    return all(cstr(source.get(field)) == cstr(target.get(field)) for field in COMPATIBILITY_FIELDS)


def _check_compatible(source, target):
    if not _compatible(source, target):
        frappe.throw(_("Las cuentas deben pertenecer a la misma empresa, moneda, punto de venta, lista de precios y turno de caja para poder fusionarlas."))


def _item_data(row, qty=None, keep_name=False):
    result = {field: row.get(field) for field in ITEM_FIELDS}
    if qty is not None:
        result["qty"] = float(qty)
    if keep_name:
        result["name"] = row.name
    return result


def _read_selection(doc, split_items, allow_all=False):
    # jQuery form encoding represents an optional null argument as an empty string.
    if allow_all and isinstance(split_items, str) and not split_items.strip():
        split_items = None
    if isinstance(split_items, str):
        try:
            split_items = frappe.parse_json(split_items)
        except (TypeError, ValueError):
            frappe.throw(_("La selección de platillos no tiene un formato válido."))
    if split_items is None and allow_all:
        return {row.name: Decimal(str(row.qty)) for row in doc.items}
    if not isinstance(split_items, list) or not split_items:
        frappe.throw(_("Selecciona al menos un platillo e indica la cantidad que deseas mover."))
    by_name = {row.name: row for row in doc.items}
    by_idx = {row.idx: row for row in doc.items}
    selection = {}
    for entry in split_items:
        if not isinstance(entry, dict):
            frappe.throw(_("Cada selección debe identificar un platillo y una cantidad válida."))
        row = None
        if entry.get("item_name"):
            row = by_name.get(entry["item_name"]) if isinstance(entry["item_name"], str) else None
        elif entry.get("idx") is not None:
            index = entry["idx"]
            if isinstance(index, bool) or not isinstance(index, (int, str)) or not str(index).isdigit():
                frappe.throw(_("El identificador de la línea seleccionada no es válido."))
            row = by_idx.get(int(index))
        if row is None or row.name in selection:
            frappe.throw(_("Selecciona platillos de esta cuenta sin repetir la misma línea."))
        if entry.get("item_name") and entry.get("idx") is not None and cstr(entry["idx"]) != cstr(row.idx):
            frappe.throw(_("La línea seleccionada cambió de posición. Actualiza la cuenta."), frappe.TimestampMismatchError)
        raw_qty = entry.get("qty")
        try:
            qty = Decimal(str(raw_qty)) if not isinstance(raw_qty, bool) else Decimal("NaN")
        except (TypeError, ValueError, InvalidOperation):
            qty = Decimal("NaN")
        if not qty.is_finite() or qty <= 0 or qty > Decimal(str(row.qty)):
            frappe.throw(_("La cantidad debe ser mayor que cero y no puede superar la cantidad del platillo."))
        if qty.normalize().as_tuple().exponent < -9:
            frappe.throw(_("La cantidad puede tener hasta nueve decimales."))
        if row.uom and frappe.db.get_value("UOM", row.uom, "must_be_whole_number") and qty != qty.to_integral_value():
            frappe.throw(_("La unidad de este platillo requiere cantidades enteras."))
        selection[row.name] = qty
    return selection


def _draft_order(source, rows, new_order_name=None):
    doc = frappe.new_doc(ORDER)
    for field in HEADER_FIELDS:
        doc.set(field, source.get(field))
    if new_order_name is not None and not isinstance(new_order_name, str):
        frappe.throw(_("El nombre de la cuenta nueva debe ser un texto."))
    label = cstr(new_order_name).strip()
    if len(label) > 140:
        frappe.throw(_("El nombre de la cuenta nueva no puede superar 140 caracteres."))
    suffix = " (Cuenta 2)"
    doc.order_name = label or source.order_name[:140 - len(suffix)] + suffix
    doc.status = "En curso"
    doc.set("items", rows)
    if doc.items and all(row.kds_status in (None, "", "Pendiente") for row in doc.items):
        doc.kds_status = "Sin enviar"
        doc.sent_to_kitchen_at = None
    return doc


def _split_drafts(source, selection, new_order_name=None):
    selected, remaining = [], []
    for row in source.items:
        qty = selection.get(row.name, Decimal(0))
        if qty:
            selected.append(_item_data(row, qty))
        rest = Decimal(str(row.qty)) - qty
        if rest:
            remaining.append(_item_data(row, rest, keep_name=True))
    selected_doc = _draft_order(source, selected, new_order_name)
    remaining_doc = _draft_order(source, remaining)
    # Use the existing order calculator for both previews and persisted results.
    validate_order(selected_doc)
    validate_order(remaining_doc)
    if not flt(source.tip_percentage):
        ratio = selected_doc.subtotal / source.subtotal if flt(source.subtotal) else (
            sum(float(value) for value in selection.values()) / sum(flt(row.qty) for row in source.items)
        )
        selected_doc.tip_amount = flt(flt(source.tip_amount) * ratio, 2)
        remaining_doc.tip_amount = flt(flt(source.tip_amount) - selected_doc.tip_amount, 2)
        validate_order(selected_doc)
        validate_order(remaining_doc)
    return selected_doc, remaining_doc


def _summary(doc, source=None):
    return {
        "name": doc.name, "order_name": doc.order_name, "table_label": doc.table_label or "",
        "restaurant_table": doc.restaurant_table or "", "service_type": doc.service_type,
        "status": doc.status or "En curso",
        "modified": str(doc.modified), "grand_total": flt(doc.grand_total, 2),
        "customer_name": doc.customer_name or doc.customer or "",
        "compatible": _compatible(source, doc) if source else True,
    }


def _is_active_destination_area(area_name, cache=None):
    if not area_name:
        return False
    if cache is not None and area_name in cache:
        return cache[area_name]
    if not frappe.db.exists("Restaurant Area", area_name):
        return False
    area = frappe.get_doc("Restaurant Area", area_name)
    active = (
        area.status == "Activa" and cint(area.visible_in_pos) == 1
        and area.has_permission("read")
    )
    if cache is not None:
        cache[area_name] = active
    return active


def _is_active_destination_table(table, cache=None):
    """Use persisted activity, rather than the occupancy derived for the map."""
    return table.status in ("Disponible", "Ocupada") and _is_active_destination_area(table.restaurant_area, cache=cache)


def _has_active_destination_table(account, cache=None):
    """Standalone open accounts remain valid destinations without a table."""
    if not account.restaurant_table:
        return not account.restaurant_area or _is_active_destination_area(account.restaurant_area, cache=cache)
    if not frappe.db.exists(TABLE, account.restaurant_table):
        return False
    table = frappe.get_doc(TABLE, account.restaurant_table)
    return table.has_permission("read") and table.has_permission("write") and _is_active_destination_table(table, cache=cache)


def get_context(order_name):
    _require_pos_user()
    source = _load_source(order_name)
    area_cache = {}
    account_rows = frappe.get_list(
        ORDER, filters={"status": "En curso", "docstatus": 0, "name": ["!=", source.name]},
        fields=["name"], order_by="modified desc", limit_page_length=0,
    )
    accounts = []
    for row in account_rows:
        account = frappe.get_doc(ORDER, row.name)
        if account.sales_invoice or not account.has_permission("write") or not _has_active_destination_table(account, cache=area_cache):
            continue
        account.check_permission("read")
        accounts.append(_summary(account, source))
    tables = []
    for row in frappe.get_list(
        TABLE, filters={"status": ["in", ["Disponible", "Ocupada"]]},
        fields=["name"], order_by="restaurant_area asc, display_order asc, table_number asc", limit_page_length=0,
    ):
        table = frappe.get_doc(TABLE, row.name)
        if not table.has_permission("write") or not _is_active_destination_table(table, cache=area_cache):
            continue
        table.check_permission("read")
        occupants = frappe.get_all(
            ORDER,
            filters={"restaurant_table": table.name, "status": "En curso", "docstatus": 0, "name": ["!=", source.name]},
            pluck="name",
        )
        visible_occupants = [account for account in accounts if account["restaurant_table"] == table.name]
        if set(occupants) - {account["name"] for account in visible_occupants}:
            # Do not advertise a private occupied table as an empty destination.
            continue
        area_name = frappe.db.get_value("Restaurant Area", table.restaurant_area, "area_name") or table.restaurant_area
        tables.append({
            "name": table.name, "table_number": table.table_number, "area_name": area_name,
            "restaurant_area": table.restaurant_area, "status": table.status,
            "orders": visible_occupants, "available": not bool(occupants),
        })
    return {
        "order": _serialize_order(source), "tables": tables,
        "orders": [account for account in accounts if account["compatible"]],
        "can_split": bool(frappe.has_permission(ORDER, "create")), "can_transfer": True,
    }


get_order_operation_context = get_context


def preview_split(order_name, split_items, expected_modified=None):
    _require_pos_user()
    source = _load_source(order_name, expected_modified)
    selection = _read_selection(source, split_items)
    selected, remaining = _split_drafts(source, selection)
    all_selected = not remaining.items
    return {
        "selected_total": flt(selected.grand_total, 2), "original_total": flt(source.grand_total, 2),
        "remaining_total": flt(remaining.grand_total, 2),
        "selected_qty": sum(float(value) for value in selection.values()),
        "selected_lines": len(selection), "can_split": not all_selected and bool(frappe.has_permission(ORDER, "create")),
        "all_selected": all_selected, "modified": str(source.modified),
        "rounding_difference": flt(selected.grand_total + remaining.grand_total - source.grand_total, 2),
    }


def _persist_remaining(source, remaining):
    source.set("items", [_item_data(row, keep_name=True) for row in remaining.items])
    source.tip_percentage = remaining.tip_percentage
    source.tip_amount = remaining.tip_amount
    if remaining.kds_status == "Sin enviar":
        source.kds_status = "Sin enviar"
        source.sent_to_kitchen_at = None
    source.save()


def _row_mapping(source, target, selection, offset=0):
    names = [row.name for row in source.items if row.name in selection]
    return {old_name: row.name for old_name, row in zip(names, target.items[offset:])}


def split_account(order_name, split_items, new_order_name=None, expected_modified=None):
    _require_pos_user()
    with _atomic_operation():
        source = _load_source(order_name, expected_modified, for_update=True)
        if not frappe.has_permission(ORDER, "create"):
            frappe.throw(_("No tienes permiso para crear una cuenta dividida."), frappe.PermissionError)
        selection = _read_selection(source, split_items)
        selected, remaining = _split_drafts(source, selection, new_order_name)
        if not remaining.items:
            frappe.throw(_("Ambas cuentas deben conservar al menos un platillo. Para mover toda la cuenta, utiliza Transferir."))
        from restaurant.order_kds import capture_order_kds, remap_order_kds
        snapshot = capture_order_kds(source)
        selected.insert()
        mapping = _row_mapping(source, selected, selection)
        _persist_remaining(source, remaining)
        remap_order_kds(snapshot, selected, mapping)
        source.reload()
        selected.reload()
        source.add_comment("Info", _("Se dividieron {0} líneas hacia la cuenta {1}.").format(len(mapping), selected.name))
        selected.add_comment("Info", _("Esta cuenta se creó al dividir la cuenta {0}.").format(source.name))
        return {
            "original_order": _serialize_order(source), "new_order": _serialize_order(selected),
            "areas": _get_areas_with_live_tables(),
        }


def _destination_table(target_table):
    name = _identifier(target_table, _("la mesa de destino"))
    doc = frappe.get_doc(TABLE, name, for_update=True)
    doc.check_permission("read")
    doc.check_permission("write")
    if not _is_active_destination_table(doc):
        frappe.throw(_("La mesa seleccionada no está activa o su área no está disponible en el POS."))
    return doc


def transfer_account(order_name, target_table=None, target_order=None, expected_modified=None,
                     target_modified=None, split_items=None, new_order_name=None):
    _require_pos_user()
    source_name = _identifier(order_name, _("la cuenta de origen"))
    with _atomic_operation():
        table = _destination_table(target_table) if target_table else None
        target_name = _identifier(target_order, _("la cuenta de destino")) if target_order else None
        if not table and not target_name and not new_order_name:
            frappe.throw(_("Selecciona una mesa, una cuenta de destino o indica el nombre de la nueva cuenta."))
        if table:
            occupied = frappe.db.get_values(
                ORDER, {"restaurant_table": table.name, "status": "En curso", "docstatus": 0, "name": ["!=", source_name]},
                ["name"], as_dict=True, for_update=True,
            )
            names = {row.name for row in occupied}
            if target_name and target_name not in names:
                frappe.throw(_("La cuenta seleccionada ya no pertenece a esa mesa. Actualiza los destinos."), frappe.TimestampMismatchError)
            if not target_name and len(names) > 1:
                frappe.throw(_("Esta mesa tiene varias cuentas abiertas. Selecciona la cuenta de destino."))
            if not target_name and names:
                target_name = next(iter(names))
        if target_name == source_name:
            frappe.throw(_("La cuenta de origen y la cuenta de destino deben ser diferentes."))
        locked = {}
        for name in sorted({source_name, target_name} - {None}):
            locked[name] = frappe.get_doc(ORDER, name, for_update=True)
        source = locked[source_name]
        _check_open_order(source)
        check_order_version(source, expected_modified)
        selection = _read_selection(source, split_items, allow_all=True)
        selected, remaining = _split_drafts(source, selection, new_order_name)
        full = not remaining.items
        target = locked.get(target_name)
        if target:
            _check_open_order(target, require_items=False)
            if not _has_active_destination_table(target):
                frappe.throw(_("La cuenta de destino pertenece a una mesa o área que no está disponible en el POS."))
            _check_compatible(source, target)
            check_order_version(target, target_modified)
        if not target and full and table and table.name == source.restaurant_table:
            frappe.throw(_("La cuenta ya pertenece a esa mesa."))
        if not table and not target and new_order_name:
            clean_new_name = str(new_order_name).strip()[:140]
            if full:
                source.order_name = clean_new_name
                source.restaurant_table = None
                source.restaurant_area = None
                source.table_label = None
                source.save()
                source.add_comment("Info", _("Se transfirió la cuenta completa a la nueva cuenta {0}.").format(clean_new_name))
                return {
                    "merged": False, "partial": False, "order": _serialize_order(source),
                    "original_order": _serialize_order(source), "areas": _get_areas_with_live_tables(),
                }
            else:
                return split_account(source_name, split_items, clean_new_name, expected_modified)
        from restaurant.order_kds import capture_order_kds, remap_order_kds
        snapshot = capture_order_kds(source)
        if target:
            capture_order_kds(target)
            offset = len(target.items)
            target.tip_amount = flt(target.tip_amount + selected.tip_amount, 2)
            target.tip_percentage = 0
            if any(row.kds_status not in (None, "", "Pendiente") for row in selected.items):
                target.kds_status = "En preparación"
                target.sent_to_kitchen_at = target.sent_to_kitchen_at or source.sent_to_kitchen_at or source.creation
            for row in selected.items:
                target.append("items", _item_data(row))
            # Child identities are assigned by the native document save.
            target.save()
            mapping = _row_mapping(source, target, selection, offset)
            if full:
                source.status = "Cancelada"
                source.restaurant_table = None
                source.save()
            else:
                _persist_remaining(source, remaining)
            remap_order_kds(snapshot, target, mapping)
            target.reload()
            source.reload()
            source.add_comment("Info", _("Se transfirieron {0} líneas a la cuenta {1}.").format(len(mapping), target.name))
            target.add_comment("Info", _("Se recibieron {0} líneas desde la cuenta {1}.").format(len(mapping), source.name))
            return {
                "merged": True, "partial": not full, "order": _serialize_order(target),
                "original_order": _serialize_order(source), "areas": _get_areas_with_live_tables(),
            }
        if full:
            source.restaurant_table = table.name
            source.restaurant_area = table.restaurant_area
            source.save()
            source.add_comment("Info", _("Se transfirió la cuenta completa a la mesa {0}.").format(table.table_number))
            return {
                "merged": False, "partial": False, "order": _serialize_order(source),
                "original_order": _serialize_order(source), "areas": _get_areas_with_live_tables(),
            }
        if not frappe.has_permission(ORDER, "create"):
            frappe.throw(_("No tienes permiso para abrir una cuenta en la mesa de destino."), frappe.PermissionError)
        selected.restaurant_table = table.name
        selected.restaurant_area = table.restaurant_area
        selected.insert()
        mapping = _row_mapping(source, selected, selection)
        _persist_remaining(source, remaining)
        remap_order_kds(snapshot, selected, mapping)
        source.reload()
        selected.reload()
        source.add_comment("Info", _("Se transfirieron {0} líneas hacia la cuenta {1} en otra mesa.").format(len(mapping), selected.name))
        selected.add_comment("Info", _("Esta cuenta recibió platillos de la cuenta {0}.").format(source.name))
        return {
            "merged": False, "partial": True, "order": _serialize_order(selected),
            "original_order": _serialize_order(source), "new_order": _serialize_order(selected),
            "areas": _get_areas_with_live_tables(),
        }
