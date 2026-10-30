"""Migrate an existing site to the restaurant app identifier without uninstalling it."""

import json

import frappe
from frappe.model.rename_doc import rename_doc


def execute():
    """Preserve installed app order and rename module links through Frappe APIs."""
    old_app = "leaf_restaurant"
    new_app = "restaurant"
    old_module = "Leaf Restaurant"
    new_module = "Restaurant"
    registry_filters = {"defkey": "installed_apps", "parent": "__global"}
    installed = json.loads(frappe.db.get_value("DefaultValue", registry_filters, "defvalue") or "[]")
    if old_app not in installed and new_app not in installed:
        frappe.throw("La app de Restaurante no está instalada en este sitio.")
    old_owner = frappe.db.get_value("Module Def", old_module, "app_name")
    if old_owner and old_owner not in (old_app, new_app):
        frappe.throw("El módulo anterior de Restaurante pertenece a otra aplicación.")
    target_app = frappe.db.get_value("Module Def", new_module, "app_name")
    if target_app and target_app not in (old_app, new_app):
        frappe.throw("El módulo Restaurant pertenece a otra aplicación.")
    if frappe.db.exists("Module Def", old_module) and target_app:
        frappe.throw("Existen ambos módulos de Restaurante; revise los datos antes de continuar.")

    updated = []
    for app in installed:
        app = new_app if app == old_app else app
        if app not in updated:
            updated.append(app)
    # Update the existing registry row without importing hooks from the old app.
    registry = frappe.db.get_value("DefaultValue", {"defkey": "installed_apps", "parent": "__global"}, "name")
    if not registry:
        frappe.throw("No se encontró el registro de aplicaciones instaladas.")
    frappe.db.set_value("DefaultValue", registry, "defvalue", json.dumps(updated), update_modified=False)
    frappe.cache().hdel("defaults", "__global")
    getattr(frappe.local, "request_cache", {}).clear()
    for module in frappe.get_all("Module Def", filters={"app_name": old_app}, pluck="name"):
        frappe.db.set_value("Module Def", module, "app_name", new_app, update_modified=False)
    if frappe.db.exists("Module Def", old_module):
        rename_doc("Module Def", old_module, new_module, force=True, ignore_permissions=True, show_alert=False)
    if frappe.db.exists("Module Def", new_module):
        frappe.db.set_value("Module Def", new_module, {"module_name": new_module, "app_name": new_app}, update_modified=False)
    frappe.clear_cache()
    frappe.setup_module_map()
    frappe.get_single("Installed Applications").update_versions()
    print("Registro de la app restaurant sincronizado; documentos existentes conservados.")


if __name__ == "__main__":
    import argparse
    import os
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Migrate the restaurant app registration.")
    parser.add_argument("--site", required=True)
    args = parser.parse_args()
    os.chdir(Path(__file__).resolve().parents[3] / "sites")
    frappe.init(site=args.site)
    frappe.connect()
    try:
        execute()
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.cache().hdel("defaults", "__global")
        getattr(frappe.local, "request_cache", {}).clear()
        raise
    finally:
        frappe.destroy()
