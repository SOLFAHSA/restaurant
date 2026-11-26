"""Order lifecycle endpoints: save, send to kitchen, pre-check, reprint and self-order."""

import json
import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_datetime, now_datetime, nowdate, nowtime

from restaurant.orders.serialization import (
    _get_areas_with_live_tables,
    _load_orders_batch,
    _serialize_order,
    build_order_serialization_context,
)
from restaurant.pos_auth import (
    employee_has_pin,
    get_linked_employee_for_user,
    is_direct_cashier,
    is_order_unlocked_for_session,
    is_supervisor,
    is_waiter_only,
    log_restaurant_audit,
    mark_order_unlocked_for_session,
    user_can_invoice,
    verify_employee_pin,
    verify_supervisor_authorization,
)
from restaurant.pos_context import (
    _check_order_company,
    _clear_pin_failures,
    _enforce_pin_rate_limit,
    _get_active_opening_shift,
    _get_active_user_branch,
    _get_default_company,
    _get_order_company,
    _record_pin_failure,
    _require_pos_user,
)
from restaurant.pos_settings.config import _get_effective_rpos_config
from restaurant.pos_settings.stations import _row_stations, get_command_configs, get_command_stations


def _get_next_order_sequence_number():
    """Compute the next strict +1 sequential account number from the database."""
    rows = frappe.db.sql(
        "SELECT name, order_name FROM `tabRestaurant Order` ORDER BY creation DESC LIMIT 200 FOR UPDATE",
        as_dict=True,
    )
    max_seq = 1000
    for r in rows:
        m_id = re.search(r"(\d+)$", cstr(r.name or ""))
        if m_id:
            seq_from_id = 1000 + cint(m_id.group(1))
            if seq_from_id > max_seq:
                max_seq = seq_from_id
        raw_oname = cstr(r.order_name or "").strip()
        if re.match(r"^\d{4}$", raw_oname):
            num_val = cint(raw_oname)
            if 1000 <= num_val < 3000 and num_val > max_seq:
                max_seq = num_val
    return str(max_seq + 1)


@frappe.whitelist(methods=["POST"])
def save_pos_order(order):
    """Create or update a Restaurant Order and return its updated state."""
    _require_pos_user()
    payload = frappe.parse_json(order) if isinstance(order, str) else order
    if not isinstance(payload, dict):
        frappe.throw(_("Los datos de la orden no tienen un formato válido."))
    if is_direct_cashier() and payload.get("restaurant_table"):
        frappe.throw(
            _("Tu perfil de facturación directa no permite asignar mesas."),
            frappe.PermissionError,
        )

    active_shift = _get_active_opening_shift(frappe.session.user)
    company = active_shift["company"] if active_shift else _get_default_company()
    if not company or (payload.get("company") and payload["company"] != company):
        frappe.throw(_("La empresa indicada no coincide con la empresa activa."), frappe.PermissionError)
    for field, doctype in (("pos_profile", "POS Profile"), ("pos_opening_shift", "POS Opening Shift")):
        if payload.get(field) and frappe.db.get_value(doctype, payload[field], "company") != company:
            frappe.throw(_("El perfil o turno no pertenece a la empresa activa."), frappe.PermissionError)

    order_id = cstr(payload.get("name") or "").strip()
    if order_id:
        if not frappe.db.get_value("Restaurant Order", order_id, "name", for_update=True):
            frappe.throw(_("La cuenta u orden solicitada no existe."), frappe.DoesNotExistError)
        doc = frappe.get_doc("Restaurant Order", order_id, for_update=True)
        _check_order_company(doc, company)
        doc.check_permission("write")
        if doc.status == "Facturada":
            frappe.throw(_("Esta orden ya fue facturada y no puede modificarse."))
        token = cstr(payload.get("expected_modified") or payload.get("modified") or "").strip()
        if "expected_modified" in payload or "modified" in payload:
            try:
                token_matches = bool(token) and get_datetime(token) == get_datetime(doc.modified)
            except (TypeError, ValueError, OverflowError):
                token_matches = False
            if not token_matches:
                frappe.throw(
                    _("Esta orden fue modificada recientemente por otro usuario. Recarga la cuenta antes de guardar cambios."),
                    frappe.TimestampMismatchError,
                )
    else:
        if not frappe.has_permission("Restaurant Order", "create"):
            frappe.throw(_("No tienes permisos para abrir cuentas u órdenes."), frappe.PermissionError)
        doc = frappe.new_doc("Restaurant Order")

    doc.company = company
    effective_profile = (
        payload.get("pos_profile")
        or doc.pos_profile
        or (active_shift["pos_profile"] if active_shift else None)
    )
    rpos_cfg = _get_effective_rpos_config(effective_profile)

    if order_id and not cint(rpos_cfg.get("share_open_orders", 1)) and doc.owner != frappe.session.user:
        user_roles = set(frappe.get_roles(frappe.session.user))
        if not (user_roles & {"System Manager", "Restaurant Manager", "Administrator"}):
            frappe.throw(_("No tienes autorización para modificar órdenes abiertas de otro usuario."), frappe.PermissionError)


    linked_waiter = get_linked_employee_for_user()
    if is_waiter_only():
        if linked_waiter:
            if order_id and doc.waiter and doc.waiter != linked_waiter["name"]:
                frappe.throw(
                    _("Esta cuenta pertenece a otro mesero y no puedes modificarla."),
                    frappe.PermissionError,
                )
        elif order_id and doc.waiter and employee_has_pin(doc.waiter):
            if not is_order_unlocked_for_session(doc.name):
                waiter_pin = payload.get("waiter_pin")
                pin_cache_key = _enforce_pin_rate_limit(f"waiter:{doc.waiter}")
                if waiter_pin and verify_employee_pin(doc.waiter, waiter_pin):
                    _clear_pin_failures(pin_cache_key)
                    mark_order_unlocked_for_session(doc.name)
                else:
                    _record_pin_failure(pin_cache_key)
                    frappe.throw(
                        _("Código incorrecto. Solo el mesero asignado ({0}) o un supervisor puede abrir esta cuenta.").format(
                            doc.waiter_name or doc.waiter
                        ),
                        frappe.PermissionError,
                    )

    if not cint(rpos_cfg.get("tips_enabled", 1)):
        if flt(payload.get("tip_amount")) > 0 or flt(payload.get("tip_percentage")) > 0:
            frappe.throw(_("Las propinas están deshabilitadas en la configuración del POS."))

    if not cint(rpos_cfg.get("allow_line_discount", 1)):
        for row in (payload.get("items") or []):
            if isinstance(row, dict) and flt(row.get("discount_percentage")) > 0:
                frappe.throw(_("Los descuentos por línea están deshabilitados en la configuración del POS."), frappe.PermissionError)

    if is_waiter_only() and "selling_price_list" in payload:
        incoming_pl = cstr(payload.get("selling_price_list") or "").strip()
        current_pl = cstr(doc.selling_price_list or "").strip()
        if order_id and incoming_pl and current_pl and incoming_pl != current_pl:
            frappe.throw(_("Tu rol de mesero no tiene permiso para cambiar la lista de precios."), frappe.PermissionError)

    editable_fields = (
        "order_name",
        "reference_note",
        "service_type",
        "restaurant_area",
        "restaurant_table",
        "guests",
        "waiter",
        "customer",
        "tax_id",
        "pos_profile",
        "pos_opening_shift",
        "selling_price_list",
        "scheduled_time",
        "customer_note",
        "tip_percentage",
        "tip_amount",
    )
    for field in editable_fields:
        if field in payload:
            doc.set(field, payload.get(field))

    if is_waiter_only() and linked_waiter and not order_id:
        doc.waiter = linked_waiter["name"]

    raw_order_name = cstr(doc.order_name or "").strip()
    if not raw_order_name or re.match(r"^orden\s+\d{4}$", raw_order_name, flags=re.IGNORECASE):
        if doc.restaurant_table:
            tbl_num = frappe.db.get_value("Restaurant Table", doc.restaurant_table, "table_number") or doc.restaurant_table
            doc.order_name = f"Mesa {tbl_num}"
        else:
            doc.order_name = _get_next_order_sequence_number()

    if active_shift and (not order_id or not doc.pos_opening_shift):
        doc.pos_opening_shift = active_shift["name"]
        doc.pos_profile = active_shift["pos_profile"]

    if "items" in payload and isinstance(payload.get("items"), list):
        existing_rows = {r.name: r for r in (doc.items or []) if getattr(r, "name", None)}
        incoming_names = {
            cstr(r.get("name") or "").strip()
            for r in payload["items"]
            if isinstance(r, dict) and r.get("item_code") and cstr(r.get("name") or "").strip()
        }
        for old_name, old_row in existing_rows.items():
            old_kds = cstr(getattr(old_row, "kds_status", "") or "Pendiente")
            old_cancelled = cint(getattr(old_row, "is_cancelled", 0)) or old_kds == "Cancelado"
            if old_kds not in ("", "Pendiente") and not old_cancelled and old_name not in incoming_names:
                log_restaurant_audit(
                    "Intento de eliminar producto enviado a cocina",
                    f"Usuario {frappe.session.user} intentó eliminar {old_row.item_name or old_row.item_code} sin autorización.",
                    order_name=doc.name,
                    result="Bloqueado",
                    item_code=old_row.item_code,
                    item_name=old_row.item_name,
                    affected_qty=old_row.qty,
                    previous_state=old_kds,
                    resulting_state=old_kds,
                )
                frappe.throw(
                    _("No puedes eliminar '{0}' porque ya fue enviado a cocina. Solicita autorización de un supervisor.").format(
                        old_row.item_name or old_row.item_code
                    ),
                    frappe.PermissionError,
                )

        item_rows = []
        for raw_row in payload["items"]:
            if not isinstance(raw_row, dict) or not raw_row.get("item_code"):
                continue
            row_name = cstr(raw_row.get("name") or "").strip()
            old_row = existing_rows.get(row_name)
            if old_row and (cint(getattr(old_row, "is_cancelled", 0)) or old_row.kds_status == "Cancelado"):
                item_rows.append(old_row)
                continue

            selected_options = raw_row.get("selected_options") or []
            if isinstance(selected_options, str):
                try:
                    selected_options = json.loads(selected_options)
                except Exception:
                    selected_options = []
            options_rate = 0.0
            summary_parts = []
            for opt in selected_options:
                if isinstance(opt, dict):
                    label = cstr(opt.get("option_label") or "").strip()
                    add_amt = flt(opt.get("additional_amount"), 2)
                    options_rate += add_amt
                    if label:
                        summary_parts.append(
                            f"{label} (+L {add_amt:.2f})" if add_amt > 0 else label
                        )
            if raw_row.get("options_rate") is not None and not selected_options:
                options_rate = flt(raw_row.get("options_rate"), 2)

            qty = flt(raw_row.get("qty") or 1)
            kds_status = raw_row.get("kds_status") or "Pendiente"
            if old_row:
                if old_row.kds_status not in (None, "", "Pendiente"):
                    if abs(flt(old_row.qty) - qty) > 0.001:
                        frappe.throw(_("No se puede modificar la cantidad de un platillo que ya fue enviado a cocina."), frappe.ValidationError)
                    kds_status = old_row.kds_status

            row_data = {
                "item_code": raw_row.get("item_code"),
                "item_name": raw_row.get("item_name"),
                "item_group": raw_row.get("item_group"),
                "qty": qty,
                "uom": raw_row.get("uom"),
                "base_rate": flt(raw_row.get("base_rate") if raw_row.get("base_rate") is not None else raw_row.get("rate") or 0),
                "options_rate": flt(options_rate, 2),
                "discount_percentage": flt(raw_row.get("discount_percentage") or 0),
                "tax_rate": raw_row.get("tax_rate"),
                "options_summary": raw_row.get("options_summary") or ", ".join(summary_parts),
                "selected_options_json": json.dumps(selected_options, ensure_ascii=False),
                "note": cstr(raw_row.get("note") or "").strip(),
                "command_station": raw_row.get("command_station"),
                "kds_status": kds_status,
            }
            if old_row:
                row_data["name"] = old_row.name
            item_rows.append(row_data)

        for old_name, old_row in existing_rows.items():
            if (cint(getattr(old_row, "is_cancelled", 0)) or old_row.kds_status == "Cancelado") and old_name not in incoming_names:
                item_rows.append(old_row)

        doc.set("items", item_rows)

    if doc.is_new():
        doc.insert()
        if doc.waiter:
            mark_order_unlocked_for_session(doc.name)
    else:
        doc.save()

    return {
        "order": _serialize_order(doc),
        "areas": _get_areas_with_live_tables(),
    }


def _dispatch_station_print_jobs(doc, stations, sent_at):
    """Non-blocking dispatch of station tickets to configured network/ESC-POS printers."""
    import socket

    configs = {cfg["command_name"]: cfg for cfg in get_command_configs()}
    results = {}
    for station_name, lines in (stations or {}).items():
        cfg = configs.get(station_name) or {
            "command_name": station_name,
            "print_mode": "Impresora del navegador (Ticket térmico)",
            "auto_print_on_send": 1,
            "paper_width_mm": "80mm",
        }
        mode = cfg.get("print_mode") or "Impresora del navegador (Ticket térmico)"
        auto_print = cint(cfg.get("auto_print_on_send", 1))
        entry = {
            "station": station_name,
            "print_mode": mode,
            "auto_print_on_send": auto_print,
            "paper_width_mm": cfg.get("paper_width_mm") or "80mm",
            "dispatched_to_hardware": False,
            "browser_print": bool(auto_print and mode == "Impresora del navegador (Ticket térmico)"),
            "warning": "",
        }
        if not auto_print or mode == "Solo KDS (Sin impresión automática)":
            results[station_name] = entry
            continue

        ip_addr = cstr(cfg.get("printer_ip") or "").strip()
        port_num = cint(cfg.get("printer_port") or 9100)
        if mode == "Network Printer Settings (Frappe Nativo)" and cfg.get("network_printer"):
            if frappe.db.exists("Network Printer Settings", cfg["network_printer"]):
                np_doc = frappe.db.get_value(
                    "Network Printer Settings",
                    cfg["network_printer"],
                    ["server_ip", "port"],
                    as_dict=True,
                )
                if np_doc and np_doc.server_ip:
                    ip_addr = cstr(np_doc.server_ip).strip()
                    port_num = cint(np_doc.port or 9100)

        if ip_addr and mode in (
            "Impresora de red directa (ESC/POS IP:Puerto)",
            "Network Printer Settings (Frappe Nativo)",
        ):
            try:
                header = (
                    f"\x1b@\x1ba\x01COMANDA - {station_name.upper()}\n"
                    f"\x1ba\x00Cuenta: {doc.order_name}\n"
                    f"Mesa/Servicio: {doc.table_label or doc.service_type}\n"
                    f"Hora: {sent_at}\n"
                    + ("-" * 32) + "\n"
                )
                body = ""
                for l in lines:
                    body += f"{l['qty']:g} x {l['item_name']}\n"
                    if l.get("options_summary"):
                        body += f"  - {l['options_summary']}\n"
                    if l.get("note"):
                        body += f"  ** {l['note']} **\n"
                footer = ("-" * 32) + "\n\n\n\x1dV\x00"
                raw_bytes = (header + body + footer).encode("cp850", errors="replace")
                with socket.create_connection((ip_addr, port_num), timeout=1.5) as sock:
                    sock.sendall(raw_bytes)
                entry["dispatched_to_hardware"] = True
            except Exception as exc:
                entry["warning"] = cstr(exc)[:140]
                entry["browser_print"] = True
        results[station_name] = entry
    return results


@frappe.whitelist(methods=["POST"])
def send_order_to_kitchen(order_name, station=None, include_sent=0):
    """Send pending lines of an order to one station (or all) and return printable station tickets.

    Only lines still in "Pendiente" are sent unless include_sent is set (reprint).
    """
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("Guarda la cuenta u orden antes de enviarla a cocina."))
    doc = frappe.get_doc("Restaurant Order", order_name)
    _check_order_company(doc)
    doc.check_permission("write")
    if not doc.items:
        frappe.throw(_("Agrega al menos un platillo o bebida antes de enviar la comanda a cocina."))

    target_station = cstr(station).strip()
    if target_station in ("", "ALL", "Todas"):
        target_station = ""
    reprint = cint(include_sent)

    stations = {}
    for row in doc.items:
        row_stations = _row_stations(row)
        if target_station and target_station not in row_stations:
            continue
        if not reprint and row.kds_status != "Pendiente":
            continue
        if row.kds_status == "Pendiente":
            row.kds_status = "En preparación"
        for station_name in row_stations:
            if target_station and station_name != target_station:
                continue
            stations.setdefault(station_name, []).append({
                "item_name": row.item_name,
                "qty": flt(row.qty),
                "options_summary": row.options_summary or "",
                "note": row.note or "",
            })

    if not stations:
        frappe.throw(
            _("No hay platillos pendientes de comandar para {0}.").format(
                target_station or _("ninguna estación")
            )
        )

    doc.sent_to_kitchen_at = now_datetime()
    if doc.kds_status == "Sin enviar":
        doc.kds_status = "En preparación"
    doc.save()
    sent_at_str = f"{nowdate()} {nowtime()[:8]}"
    print_jobs = _dispatch_station_print_jobs(doc, stations, sent_at_str)
    return {
        "order": _serialize_order(doc),
        "areas": _get_areas_with_live_tables(),
        "stations": stations,
        "print_jobs": print_jobs,
        "sent_at": sent_at_str,
    }


@frappe.whitelist(methods=["POST"])
def get_precuenta_data(order_name, tip_percentage=None, tip_amount=None):
    """Return formatted non-fiscal Pre-cuenta data for customer review before invoicing."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden solicitada no existe."), frappe.DoesNotExistError)
    doc = frappe.get_doc("Restaurant Order", order_name)
    _check_order_company(doc)
    doc.check_permission("read")

    if doc.status == "En curso" and doc.has_permission("write"):
        if tip_percentage is not None:
            doc.tip_percentage = max(0.0, flt(tip_percentage, 2))
            if doc.tip_percentage == 0 and tip_amount is not None:
                doc.tip_amount = max(0.0, flt(tip_amount, 2))
        elif tip_amount is not None:
            doc.tip_percentage = 0.0
            doc.tip_amount = max(0.0, flt(tip_amount, 2))
        doc.precuenta_printed = 1
        doc.save()

    company_name = doc.company or _get_default_company()
    company_rtn = cstr(frappe.db.get_value("Company", company_name, "tax_id")) if company_name else ""

    return {
        "company_name": company_name,
        "company_rtn": company_rtn,
        "printed_at": f"{nowdate()} {nowtime()[:8]}",
        "order": _serialize_order(doc),
    }


@frappe.whitelist(methods=["POST"])
def authorize_reprint_command(order_name, supervisor_user=None, supervisor_pin=None, reason=""):
    """Verify supervisor authorization to reprint kitchen commands for an order."""
    _require_pos_user()
    if not order_name or not frappe.db.exists("Restaurant Order", order_name):
        frappe.throw(_("La cuenta u orden no existe."), frappe.DoesNotExistError)
    _check_order_company(frappe.get_doc("Restaurant Order", order_name))
    if is_supervisor():
        log_restaurant_audit(
            "Reimprimir comandas",
            f"Supervisor {frappe.session.user} autorizó reimpresión de comandas.",
            order_name=order_name,
            supervisor_user=frappe.session.user,
        )
        return {"authorized": True, "supervisor": frappe.session.user}
    return verify_supervisor_authorization(
        supervisor_user,
        supervisor_pin,
        "Reimprimir comandas",
        order_name=order_name,
        reason=reason,
    )


@frappe.whitelist(methods=["POST"])
def save_customer_with_rtn(customer_name, tax_id=None, customer_id=None, email_id=None, mobile_no=None, address=None):
    """Create or update a Customer with their fiscal RTN, email, phone, and address directly from the Restaurant POS."""
    _require_pos_user()
    if not user_can_invoice():
        frappe.throw(
            _("Solo cajeros autorizados o supervisores pueden crear o editar clientes."),
            frappe.PermissionError,
        )
    clean_name = cstr(customer_name).strip()
    clean_rtn = cstr(tax_id).strip()[:60]
    clean_email = cstr(email_id).strip()[:140]
    clean_phone = cstr(mobile_no).strip()[:60]
    clean_addr = cstr(address).strip()[:200]
    if not clean_name:
        frappe.throw(_("El nombre o razón social del cliente es obligatorio."))

    cust_meta = frappe.get_meta("Customer")
    if customer_id and frappe.db.exists("Customer", customer_id):
        if customer_id.strip().upper() == "CONSUMIDOR FINAL":
            frappe.throw(_("No puedes sobrescribir el cliente genérico CONSUMIDOR FINAL."), frappe.PermissionError)
        doc = frappe.get_doc("Customer", customer_id)
        doc.check_permission("write")
        doc.customer_name = clean_name
        doc.tax_id = clean_rtn
        if email_id is not None and cust_meta.has_field("email_id"):
            doc.email_id = clean_email
        if mobile_no is not None and cust_meta.has_field("mobile_no"):
            doc.mobile_no = clean_phone
        if address is not None and cust_meta.has_field("primary_address"):
            doc.primary_address = clean_addr
        doc.save()
    else:
        if not frappe.has_permission("Customer", "create"):
            frappe.throw(_("No tienes permisos para registrar nuevos clientes."), frappe.PermissionError)
        group = (
            frappe.db.get_single_value("Selling Settings", "customer_group")
            or frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
            or "All Customer Groups"
        )
        territory = (
            frappe.db.get_single_value("Selling Settings", "territory")
            or frappe.db.get_value("Territory", {"is_group": 0}, "name")
            or "All Territories"
        )
        payload = {
            "doctype": "Customer",
            "customer_name": clean_name,
            "customer_type": "Individual",
            "customer_group": group,
            "territory": territory,
            "tax_id": clean_rtn,
        }
        if clean_email and cust_meta.has_field("email_id"):
            payload["email_id"] = clean_email
        if clean_phone and cust_meta.has_field("mobile_no"):
            payload["mobile_no"] = clean_phone
        if clean_addr and cust_meta.has_field("primary_address"):
            payload["primary_address"] = clean_addr
        doc = frappe.get_doc(payload)
        doc.insert()

    return {
        "name": doc.name,
        "customer_name": doc.customer_name,
        "tax_id": doc.tax_id or "",
        "email_id": cstr(getattr(doc, "email_id", "") or clean_email),
        "mobile_no": cstr(getattr(doc, "mobile_no", "") or clean_phone),
        "address": cstr(getattr(doc, "primary_address", "") or clean_addr),
    }


@frappe.whitelist()
def get_emitted_commands(limit=40):
    """Return orders that already have emitted kitchen commands for reprinting."""
    _require_pos_user()
    cmd_filters = {"status": ["in", ["En curso", "Facturada"]], "company": _get_order_company()}
    active_branch = _get_active_user_branch()
    if active_branch and frappe.get_meta("Restaurant Order").has_field("branch"):
        cmd_filters["branch"] = active_branch
    order_docs = _load_orders_batch(
        filters=cmd_filters,
        order_by="sent_to_kitchen_at desc, modified desc",
        limit_page_length=max(10, min(100, cint(limit or 40))),
        use_list_perms=True,
    )
    serial_ctx = build_order_serialization_context(order_docs)
    emitted = []
    for row in order_docs:
        serialized = _serialize_order(row, serial_ctx=serial_ctx)
        emitted_lines = [
            it for it in (serialized.get("items") or [])
            if (it.get("kds_status") and it.get("kds_status") != "Pendiente") or serialized.get("sent_to_kitchen_at")
        ]
        if not emitted_lines:
            continue
        stations = sorted({
            st.strip()
            for it in emitted_lines
            for st in cstr(it.get("command_station") or "Cocina General").split(",")
            if st.strip()
        })
        emitted.append({
            "name": serialized["name"],
            "order_name": serialized["order_name"],
            "table_label": serialized["table_label"],
            "service_type": serialized["service_type"],
            "waiter_name": serialized["waiter_name"],
            "status": serialized["status"],
            "kds_status": serialized["kds_status"],
            "sent_to_kitchen_at": serialized["sent_to_kitchen_at"] or serialized["modified"],
            "stations": stations or ["Cocina General"],
            "items": emitted_lines,
        })
    return {
        "commands": emitted,
        "command_stations": get_command_stations(),
    }


@frappe.whitelist(methods=["POST"])
def submit_self_order(order, channel="mobile", table=None):
    """Create a Restaurant Order from an authorized self-order channel (mobile or kiosk)."""
    _require_pos_user()
    payload = frappe.parse_json(order) if isinstance(order, str) else dict(order or {})
    pos_profile = payload.get("pos_profile")
    cfg = _get_effective_rpos_config(pos_profile)

    if not cint(cfg.get("enable_self_order")):
        frappe.throw(_("El autopedido está deshabilitado en la configuración del restaurante."), frappe.PermissionError)

    ch = cstr(channel or "mobile").strip().lower()
    if ch == "mobile" and not cint(cfg.get("enable_mobile_self_order")):
        frappe.throw(_("El canal de autopedido por celular no está habilitado."), frappe.PermissionError)
    if ch == "kiosk" and not cint(cfg.get("enable_kiosk_self_order")):
        frappe.throw(_("El canal de autopedido mediante kiosco no está habilitado."), frappe.PermissionError)
    if ch not in ("mobile", "kiosk"):
        frappe.throw(_("Canal de autopedido no válido."))

    if table and not payload.get("restaurant_table"):
        payload["restaurant_table"] = table
    if not payload.get("reference_note"):
        payload["reference_note"] = "Autopedido Celular" if ch == "mobile" else "Autopedido Kiosco"

    return save_pos_order(payload)
