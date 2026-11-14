"""Restaurant configuration backed by inactive native Product Bundles."""

from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import cint, cstr, get_datetime

MAX_RECIPE_ROWS = 100
MAX_GROUP_OPTIONS = 50
MAX_ITEM_GROUPS = 25
MAX_QUANTITY = Decimal("1000000000")
MISSING = object()
EFFECTS = ("Solo indicación", "Sustituir componente", "Agregar componente", "Incluir en combo")
GROUP_FIELDS = ("group_name", "min_selections", "max_selections", "currency", "disabled")
OPTION_FIELDS = ("option_label", "effect", "item_code", "replaces_item", "qty", "uom", "additional_amount", "is_default")


@frappe.whitelist()
def get_configuration(item_code):
    """Read configuration without changing Item, stock, or sales."""
    item = _read_item(item_code)
    can_write = item.has_permission("write")
    can_read_currency = frappe.has_permission("Currency", "read")
    bundle = _get_bundle(item.name)
    recipe = {"exists": bool(bundle), "name": None, "modified": None,
              "editable": bool(can_write and frappe.has_permission("Product Bundle", "create")),
              "readonly_reason": "", "rows": []}
    if bundle and bundle.has_permission("read"):
        reason = _bundle_readonly_reason(bundle)
        recipe.update({"name": bundle.name, "modified": bundle.modified,
                       "editable": bool(can_write and bundle.has_permission("write") and not reason),
                       "readonly_reason": reason})
        for row in bundle.items:
            ingredient = _read_item(row.item_code)
            uom, factor = _snapshot_unit(row, ingredient.stock_uom)
            recipe["rows"].append({"item_code": row.item_code,
                                   "qty": float(Decimal(str(row.qty)) / factor), "uom": uom,
                                   "stock_qty": row.qty, "stock_uom": ingredient.stock_uom})
    elif bundle:
        recipe["editable"] = False
        recipe["readonly_reason"] = _("No tienes permiso para consultar la receta nativa de este producto.")
    if not bundle and cint(item.get("restaurant_recipe_enabled")) and _recipe_item_used(item.name):
        recipe.update({"editable": False, "readonly_reason": _("El producto ya se utiliza en documentos. Configura la receta en un producto nuevo para preservar sus históricos.")})
    groups = []
    if frappe.has_permission("Restaurant Option Group", "read"):
        for record in frappe.get_list("Restaurant Option Group", filters={"main_item": item.name},
                                      fields=["name"], order_by="creation asc", limit_page_length=MAX_ITEM_GROUPS):
            group = frappe.get_doc("Restaurant Option Group", record.name)
            group.check_permission("read")
            group.apply_fieldlevel_read_permissions()
            group_data = group.as_dict()
            group_data["_can_write"] = bool(can_write and can_read_currency and group.has_permission("write"))
            groups.append(group_data)
    return {"item": {"name": item.name, "item_name": item.item_name or item.name,
                     "base_price": _base_price(item),
                     "modified": item.modified, "is_stock_item": item.is_stock_item,
                     "restaurant_recipe_enabled": cint(item.get("restaurant_recipe_enabled")),
                     "restaurant_options_enabled": cint(item.get("restaurant_options_enabled"))},
            "recipe": recipe, "groups": groups,
            "currency": frappe.defaults.get_global_default("currency") or "", "can_write": bool(can_write),
            "can_create_option_group": bool(can_write and can_read_currency and frappe.has_permission("Restaurant Option Group", "create"))}


@frappe.whitelist(methods=["POST"])
def save_recipe(item_code, rows, item_modified, bundle_modified=None):
    """Save an inactive bundle, preserving the native document as the source."""
    item = _locked_item(item_code, item_modified)
    if not cint(item.get("restaurant_recipe_enabled")):
        frappe.throw(_("Guarda el producto con Activar receta habilitado antes de configurar componentes."))
    _validate_recipe_parent(item)
    rows = _parse_list(rows, MAX_RECIPE_ROWS, _("componentes"))
    if not rows:
        frappe.throw(_("Agrega al menos un componente a la receta."))
    normalized, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            frappe.throw(_("Los componentes de la receta no son válidos."))
        ingredient, quantity, factor = _component(item.name, row.get("item_code"), row.get("qty"), row.get("uom"))
        if ingredient.name in seen:
            frappe.throw(_("Cada componente debe aparecer una sola vez en la receta."))
        seen.add(ingredient.name)
        normalized.append({"item_code": ingredient.name, "qty": float(quantity * factor),
                           "uom": ingredient.stock_uom, "restaurant_input_uom": row.get("uom") or ingredient.stock_uom,
                           "restaurant_input_factor": float(factor)})
    if not all(frappe.get_meta("Product Bundle Item").has_field(field) for field in ("restaurant_input_uom", "restaurant_input_factor")) or not frappe.get_meta("Product Bundle").has_field("restaurant_managed"):
        frappe.throw(_("Actualiza el esquema de Restaurante antes de guardar la receta."))
    _validate_recipe_references(item.name, seen)
    bundle = _get_bundle(item.name, for_update=True)
    if bundle:
        bundle.check_permission("write")
        _check_modified(bundle.modified, bundle_modified, _("La receta"))
        reason = _bundle_readonly_reason(bundle)
        if reason:
            frappe.throw(reason)
    else:
        if _recipe_item_used(item.name):
            frappe.throw(_("El producto ya se utiliza en documentos. No se puede crear su receta desde este editor."))
        if bundle_modified:
            frappe.throw(_("La receta cambió. Recarga la configuración antes de continuar."), frappe.TimestampMismatchError)
        if not frappe.has_permission("Product Bundle", "create"):
            frappe.throw(_("No tienes permiso para crear recetas nativas."), frappe.PermissionError)
        bundle = frappe.new_doc("Product Bundle")
        bundle.new_item_code = item.name
        bundle.disabled = 1
        bundle.restaurant_managed = 1
    bundle.set("items", normalized)
    bundle.save()
    return get_configuration(item.name)


@frappe.whitelist(methods=["POST"])
def save_option_group(item_code, group, item_modified):
    """Write only supported fields and keep the owning Item immutable."""
    item = _locked_item(item_code, item_modified)
    if not cint(item.get("restaurant_options_enabled")):
        frappe.throw(_("Guarda el producto con Activar opciones del platillo habilitado antes de configurar grupos."))
    group = _parse_dict(group)
    if group.get("name"):
        document = frappe.get_doc("Restaurant Option Group", group["name"], for_update=True)
        document.check_permission("write")
        if document.main_item != item.name:
            frappe.throw(_("El grupo no pertenece al producto seleccionado."), frappe.PermissionError)
        _check_modified(document.modified, group.get("modified"), _("El grupo"))
    else:
        if not frappe.has_permission("Restaurant Option Group", "create"):
            frappe.throw(_("No tienes permiso para crear grupos de opciones."), frappe.PermissionError)
        document = frappe.new_doc("Restaurant Option Group")
        document.main_item = item.name
    for field in GROUP_FIELDS:
        if field in group:
            document.set(field, group[field])
    options = _parse_list(group.get("options"), MAX_GROUP_OPTIONS, _("opciones"))
    if any(not isinstance(row, dict) for row in options):
        frappe.throw(_("Las opciones del grupo no son válidas."))
    document.set("options", [{field: row[field] for field in OPTION_FIELDS if field in row} for row in options])
    document.save()
    return get_configuration(item.name)


def validate_item(doc, method=None):
    """Opt-in validation never changes native Item flags or existing recipes."""
    for field in ("restaurant_recipe_enabled", "restaurant_options_enabled"):
        value = doc.get(field)
        if value is not None and value not in (0, 1, "0", "1", False, True):
            frappe.throw(_("Las opciones de Restaurante deben estar activadas o desactivadas."))
    if cint(doc.get("restaurant_recipe_enabled")):
        _validate_recipe_parent(doc)


def validate_managed_bundle(doc, method=None):
    """Keep native-form and import writes within the inactive configuration scope."""
    if not frappe.get_meta("Product Bundle").has_field("restaurant_managed"):
        return
    previous = None
    if not doc.is_new():
        previous = frappe.db.get_value(
            "Product Bundle", doc.name,
            ["restaurant_managed", "new_item_code"], as_dict=True,
        )
    was_managed = bool(previous and cint(previous.restaurant_managed))
    is_managed = bool(cint(doc.get("restaurant_managed")))
    if not (was_managed or is_managed):
        return
    _check_flag(doc.get("restaurant_managed"))
    _check_flag(doc.disabled)
    if was_managed and not is_managed:
        frappe.throw(_("No puedes retirar la identificación de una receta del restaurante."))
    if previous and not was_managed:
        frappe.throw(_("No puedes convertir una receta nativa existente en configuración del restaurante."))
    if previous and previous.new_item_code != doc.new_item_code:
        frappe.throw(_("No puedes trasladar una receta del restaurante a otro producto."))
    if not cint(doc.disabled):
        frappe.throw(_("Las recetas del restaurante deben permanecer inactivas hasta integrar el flujo de ventas."))
    item = _locked_item(doc.new_item_code)
    if not cint(item.get("restaurant_recipe_enabled")):
        frappe.throw(_("El producto debe tener Activar receta habilitado para configurar sus componentes."))
    _validate_recipe_parent(item)
    if _recipe_item_used(item.name):
        frappe.throw(_("El producto ya se utiliza en documentos. Su receta se conserva en modo de consulta."))
    if not doc.items or len(doc.items) > MAX_RECIPE_ROWS:
        frappe.throw(_("La receta debe contener entre 1 y 100 componentes."))
    components = set()
    for row in doc.items:
        ingredient, _qty, _uom = _component(item.name, row.item_code, row.qty, row.uom)
        if row.uom and row.uom != ingredient.stock_uom:
            frappe.throw(_("Los componentes de la receta nativa deben guardarse en su unidad de inventario."))
        if ingredient.name in components:
            frappe.throw(_("Cada componente debe aparecer una sola vez en la receta."))
        components.add(ingredient.name)
        row.uom = ingredient.stock_uom
        _number(row.get("restaurant_input_factor") or 1, _("Factor de conversión"))
        if row.get("restaurant_input_uom"):
            _read_document("UOM", row.restaurant_input_uom)
    _validate_recipe_references(item.name, components)


def validate_option_group(doc):
    """Enforce identical rules for the API, native form, and import."""
    item = _locked_item(doc.main_item)
    if not cint(item.get("restaurant_options_enabled")):
        frappe.throw(_("El producto debe tener habilitadas las opciones del cliente."))
    if not doc.is_new() and frappe.db.get_value(doc.doctype, doc.name, "main_item") != doc.main_item:
        frappe.throw(_("No puedes trasladar un grupo de opciones a otro producto."))
    doc.group_name = cstr(doc.group_name).strip()
    if not doc.group_name or len(doc.group_name) > 140:
        frappe.throw(_("Ingresa un nombre de grupo de hasta 140 caracteres."))
    existing = frappe.get_all(doc.doctype, filters={"main_item": item.name}, fields=["name", "group_name"], limit_page_length=MAX_ITEM_GROUPS + 1)
    if doc.is_new() and len(existing) >= MAX_ITEM_GROUPS:
        frappe.throw(_("Un producto admite hasta 25 grupos de opciones."))
    if any(row.name != doc.name and cstr(row.group_name).casefold() == doc.group_name.casefold() for row in existing):
        frappe.throw(_("Ya existe un grupo con ese nombre para el producto."))
    doc.min_selections = _integer(doc.min_selections, _("Mínimo de selecciones"), 0)
    doc.max_selections = _integer(doc.max_selections, _("Máximo de selecciones"), 1)
    if not doc.options or len(doc.options) > MAX_GROUP_OPTIONS:
        frappe.throw(_("El grupo debe contener entre 1 y 50 opciones."))
    if doc.min_selections > doc.max_selections or doc.max_selections > len(doc.options):
        frappe.throw(_("El mínimo no puede superar al máximo ni el máximo al número de opciones."))
    _check_flag(doc.disabled)
    if not doc.currency:
        frappe.throw(_("Selecciona la moneda del grupo."))
    _read_document("Currency", doc.currency)
    bundle = _get_bundle(item.name)
    base_items = {row.item_code for row in bundle.items} if bundle else set()
    labels, defaults = set(), 0
    for row in doc.options:
        row.option_label = cstr(row.option_label).strip()
        if not row.option_label or len(row.option_label) > 140 or row.option_label.casefold() in labels:
            frappe.throw(_("Cada opción requiere un nombre único de hasta 140 caracteres."))
        labels.add(row.option_label.casefold())
        if row.effect not in EFFECTS:
            frappe.throw(_("Selecciona un efecto válido para cada opción."))
        row.additional_amount = float(_number(row.additional_amount if row.additional_amount is not None else 0, _("Importe adicional"), allow_zero=True))
        _check_flag(row.is_default)
        defaults += cint(row.is_default)
        if row.effect == "Solo indicación":
            if row.item_code or row.replaces_item or row.uom or _number(row.qty if row.qty is not None else 0, _("Cantidad"), allow_zero=True):
                frappe.throw(_("Las opciones Solo indicación no deben incluir componentes ni cantidades."))
            continue
        if row.effect == "Incluir en combo":
            if row.replaces_item:
                frappe.throw(_("Una opción Incluir en combo no debe indicar un componente a sustituir."))
            combo_item, combo_qty, combo_uom = _combo_component(item.name, row.item_code, row.qty, row.uom)
            row.item_code = combo_item.name
            row.qty = float(combo_qty)
            row.uom = combo_uom
            continue
        if not cint(item.get("restaurant_recipe_enabled")) or not bundle or not base_items:
            frappe.throw(_("Las opciones que afectan componentes requieren una receta configurada y habilitada."))
        bundle.check_permission("read")
        ingredient, _qty, _uom = _component(item.name, row.item_code, row.qty, row.uom)
        row.uom = row.uom or ingredient.stock_uom
        if row.effect == "Sustituir componente":
            if not row.replaces_item or row.replaces_item not in base_items:
                frappe.throw(_("El componente a sustituir debe pertenecer a la receta base."))
            if row.replaces_item == row.item_code:
                frappe.throw(_("El componente sustituto debe ser distinto del componente original."))
        elif row.replaces_item:
            frappe.throw(_("Una opción Agregar componente no debe indicar un componente a sustituir."))
    if defaults > doc.max_selections:
        frappe.throw(_("Las opciones predeterminadas no pueden superar el máximo de selecciones."))


def _base_price(item):
    if frappe.has_permission("Item Price", "read"):
        price_list = frappe.defaults.get_global_default("selling_price_list")
        filters = {"item_code": item.name, "selling": 1}
        if price_list:
            rate = frappe.db.get_value("Item Price", {**filters, "price_list": price_list}, "price_list_rate")
            if rate is not None:
                return float(rate)
        rate = frappe.db.get_value("Item Price", filters, "price_list_rate")
        if rate is not None:
            return float(rate)
    return float(item.get("standard_rate") or 0)


def _combo_component(parent_item, item_code, qty, uom):
    item = _read_item(item_code)
    if item.name == parent_item or cint(item.disabled) or cint(item.has_variants) or cint(item.is_fixed_asset) or not (cint(item.is_sales_item) or cint(item.is_stock_item)):
        frappe.throw(_("Selecciona un producto o platillo activo válido, distinto del combo y sin plantilla de variantes."))
    quantity = _number(1 if qty in (None, "") else qty, _("Cantidad"))
    uom = uom or item.stock_uom
    uom_doc = _read_document("UOM", uom)
    if uom_doc.get("enabled") == 0:
        frappe.throw(_("La unidad de medida está deshabilitada."))
    if cint(uom_doc.must_be_whole_number) and quantity != quantity.to_integral_value():
        frappe.throw(_("Esta unidad de medida requiere cantidades enteras."))
    return item, quantity, uom


def _read_document(doctype, name, for_update=False):
    if not isinstance(name, str) or not name.strip() or len(name) > 140:
        frappe.throw(_("Selecciona un registro válido."))
    doc = frappe.get_doc(doctype, name, for_update=for_update)
    doc.check_permission("read")
    return doc


def _read_item(item_code):
    return _read_document("Item", item_code)


def _locked_item(item_code, modified=MISSING):
    item = _read_document("Item", item_code, for_update=True)
    item.check_permission("write")
    if modified is not MISSING:
        _check_modified(item.modified, modified, _("El producto"))
    if cint(item.disabled):
        frappe.throw(_("No puedes configurar un producto deshabilitado."))
    return item


def _check_modified(current, expected, label):
    try:
        matches = bool(expected) and get_datetime(current) == get_datetime(expected)
    except (TypeError, ValueError, OverflowError):
        matches = False
    if not matches:
        frappe.throw(_("{0} cambió. Recarga la configuración antes de continuar.").format(label), frappe.TimestampMismatchError)


def _validate_recipe_parent(item):
    if cint(item.is_stock_item) or cint(item.is_fixed_asset) or cint(item.has_variants):
        frappe.throw(_("La receta requiere un producto no inventariable, sin variantes de plantilla y que no sea activo fijo."))


def _get_bundle(item_code, for_update=False):
    names = frappe.db.get_values("Product Bundle", filters={"new_item_code": item_code},
                                 fieldname="name", pluck=True, limit=2, for_update=for_update)
    if len(names) > 1:
        frappe.throw(_("Hay más de una receta nativa para este producto. Revisa su configuración."))
    return frappe.get_doc("Product Bundle", names[0], for_update=for_update) if names else None


def _validate_recipe_references(item_code, new_components):
    groups = frappe.get_all("Restaurant Option Group", filters={"main_item": item_code}, pluck="name")
    if not groups:
        return
    references = frappe.get_all(
        "Restaurant Dish Option",
        filters={"parent": ["in", groups], "parenttype": "Restaurant Option Group",
                 "parentfield": "options", "effect": "Sustituir componente"},
        fields=["replaces_item"],
    )
    if any(row.replaces_item not in new_components for row in references):
        frappe.throw(_("No puedes quitar un componente utilizado por las opciones del platillo. Actualiza primero esas opciones."))


def _bundle_readonly_reason(bundle):
    if not cint(bundle.disabled):
        return _("La receta nativa está activa. Esta etapa solo permite editar configuraciones inactivas del restaurante.")
    if not cint(bundle.get("restaurant_managed")):
        return _("La receta nativa ya existía y no pertenece a este editor. Se conserva sin modificaciones.")
    if _recipe_item_used(bundle.new_item_code):
        return _("El producto ya se utiliza en documentos. Su receta se conserva en modo de consulta.")
    return ""


def _recipe_item_used(item_code):
    # Cancelled documents remain historical references and must also be preserved.
    child_doctypes = (
        "Quotation Item", "Sales Order Item", "Delivery Note Item", "Sales Invoice Item",
        "POS Invoice Item", "Purchase Receipt Item", "Purchase Invoice Item",
        "Stock Entry Detail", "Stock Reconciliation Item", "Purchase Order Item",
        "Material Request Item",
    )
    for doctype in child_doctypes:
        if frappe.db.exists(doctype, {"item_code": item_code}):
            return True
    return bool(frappe.db.exists("Packed Item", {"parent_item": item_code}))


def _snapshot_unit(row, stock_uom):
    try:
        factor = Decimal(str(row.get("restaurant_input_factor") or 0))
        if row.get("restaurant_input_uom") and factor.is_finite() and factor > 0:
            return row.restaurant_input_uom, factor
    except InvalidOperation:
        pass
    return stock_uom, Decimal(1)


def _component(parent_item, item_code, qty, uom):
    item = _read_item(item_code)
    if item.name == parent_item or not cint(item.is_stock_item) or cint(item.disabled) or cint(item.has_variants) or cint(item.is_fixed_asset):
        frappe.throw(_("Selecciona un componente inventariable activo, distinto del platillo y sin plantilla de variantes."))
    if frappe.db.exists("Product Bundle", {"new_item_code": item.name}):
        frappe.throw(_("Un componente no puede ser otro paquete de productos."))
    quantity = _number(qty, _("Cantidad"))
    uom = uom or item.stock_uom
    uom_doc = _read_document("UOM", uom)
    if uom_doc.get("enabled") == 0:
        frappe.throw(_("La unidad de medida está deshabilitada."))
    if cint(uom_doc.must_be_whole_number) and quantity != quantity.to_integral_value():
        frappe.throw(_("Esta unidad de medida requiere cantidades enteras."))
    if uom == item.stock_uom:
        factor = Decimal(1)
    else:
        factor = next((row.conversion_factor for row in item.uoms if row.uom == uom), None)
        if factor is None and item.variant_of:
            template = _read_item(item.variant_of)
            factor = next((row.conversion_factor for row in template.uoms if row.uom == uom), None)
        if factor is None:
            from erpnext.stock.doctype.item.item import get_uom_conv_factor
            factor = get_uom_conv_factor(uom, item.stock_uom)
        if factor is None:
            frappe.throw(_("No existe una conversión válida entre la unidad seleccionada y la unidad de inventario del componente."))
        factor = _number(factor, _("Factor de conversión"))
    stock_quantity = quantity * factor
    if stock_quantity > MAX_QUANTITY:
        frappe.throw(_("La cantidad convertida supera el límite permitido."))
    stock_uom = _read_document("UOM", item.stock_uom)
    if cint(stock_uom.must_be_whole_number) and stock_quantity != stock_quantity.to_integral_value():
        frappe.throw(_("La cantidad convertida debe ser entera en la unidad de inventario."))
    return item, quantity, factor


def _number(value, label, allow_zero=False):
    try:
        number = Decimal(str(value))
        if isinstance(value, bool) or not number.is_finite() or number < 0 or (not allow_zero and number == 0) or number > MAX_QUANTITY:
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        frappe.throw(_("{0} debe ser un número válido {1}.").format(label, _("mayor o igual a cero") if allow_zero else _("mayor que cero")))
    return number


def _integer(value, label, minimum):
    number = _number(value, label, allow_zero=minimum == 0)
    if number != number.to_integral_value() or number < minimum or number > MAX_GROUP_OPTIONS:
        frappe.throw(_("{0} debe ser un entero entre {1} y 50.").format(label, minimum))
    return int(number)


def _check_flag(value):
    if value not in (0, 1, "0", "1", False, True, None):
        frappe.throw(_("Las casillas de configuración deben estar activadas o desactivadas."))


def _parse_list(value, maximum, label):
    if isinstance(value, str):
        if len(value) > 100000:
            frappe.throw(_("La configuración enviada supera el tamaño permitido."))
        value = frappe.parse_json(value)
    if not isinstance(value, list) or len(value) > maximum:
        frappe.throw(_("La lista de {0} no es válida o supera el límite permitido.").format(label))
    return value


def _parse_dict(value):
    if isinstance(value, str):
        if len(value) > 100000:
            frappe.throw(_("La configuración enviada supera el tamaño permitido."))
        value = frappe.parse_json(value)
    if not isinstance(value, dict):
        frappe.throw(_("La configuración del grupo no es válida."))
    return value

def prevent_managed_recipe_deletion(doc, method=None):
    """Keep saved configuration and option references intact in native deletion."""
    if cint(doc.get("restaurant_managed")):
        frappe.throw(_("La receta de Restaurante se conserva como configuración. Desactiva su casilla en el producto en lugar de eliminar el paquete."))
