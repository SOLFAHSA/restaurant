"""Global and per-profile settings controller for LEAF Restaurant module."""

import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


ALLOWED_SETTINGS_ROLES = {"System Manager", "Restaurant Manager", "Administrator"}


def _assert_settings_admin():
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not (user_roles & ALLOWED_SETTINGS_ROLES):
        frappe.throw(_("No tienes permisos suficientes para modificar la configuración del Restaurante."), frappe.PermissionError)


class RestaurantSettings(Document):
    def validate(self):
        _assert_settings_admin()
        self._sync_self_order_flags()
        self._sync_wallpaper_defaults()
        self._sync_pos_profile_and_config()
        frappe.clear_cache()

    def _sync_self_order_flags(self):
        if not cint(self.enable_self_order):
            self.enable_mobile_self_order = 0
            self.enable_kiosk_self_order = 0
            return

        channels = self.self_order_channels or "Ambos canales"
        if channels == "Autopedido por celular":
            self.enable_mobile_self_order = 1
            self.enable_kiosk_self_order = 0
        elif channels == "Autopedido por kiosco":
            self.enable_mobile_self_order = 0
            self.enable_kiosk_self_order = 1
        else:
            if not cint(self.enable_mobile_self_order) and not cint(self.enable_kiosk_self_order):
                self.enable_mobile_self_order = 1
                self.enable_kiosk_self_order = 1

    def _sync_wallpaper_defaults(self):
        minutes = flt(self.idle_wallpaper_minutes or 2.0)
        if minutes < 0.1:
            minutes = 2.0
            self.idle_wallpaper_minutes = minutes
        timeout_seconds = int(round(minutes * 60))

        frappe.db.set_default("rpos_idle_wallpaper_enabled", "1" if cint(self.idle_wallpaper_enabled) else "0")
        frappe.db.set_default("rpos_idle_wallpaper_show_clock", "1" if cint(self.idle_wallpaper_show_clock) else "0")
        frappe.db.set_default("rpos_idle_wallpaper_timeout_seconds", str(timeout_seconds))
        if self.idle_wallpaper_background:
            frappe.db.set_default("rpos_idle_wallpaper_background_url", str(self.idle_wallpaper_background))
        if self.idle_wallpaper_logo:
            frappe.db.set_default("rpos_idle_wallpaper_logo_url", str(self.idle_wallpaper_logo))

    def _build_config_payload(self):
        minutes = flt(self.idle_wallpaper_minutes or 2.0)
        timeout_seconds = int(round(max(0.1, minutes) * 60))

        enabled_payments = []
        default_payment = None
        for row in (self.payment_methods or []):
            if cint(row.enabled) and row.mode_of_payment:
                if row.mode_of_payment not in enabled_payments:
                    enabled_payments.append(row.mode_of_payment)
                if cint(row.is_default) and not default_payment:
                    default_payment = row.mode_of_payment

        allowed_categories = []
        if cint(self.restrict_categories):
            for row in (self.allowed_categories or []):
                if row.item_group and row.item_group not in allowed_categories:
                    allowed_categories.append(row.item_group)

        return {
            "pos_profile": self.pos_profile or "",
            "company": self.company or "",
            "default_preset": self.default_preset or "Comer en el local",
            # Self-order
            "enable_self_order": cint(self.enable_self_order),
            "self_order_channels": self.self_order_channels or "Ambos canales",
            "enable_mobile_self_order": cint(self.enable_mobile_self_order),
            "enable_kiosk_self_order": cint(self.enable_kiosk_self_order),
            # Payments
            "enabled_payments": enabled_payments,
            "default_payment": default_payment or (enabled_payments[0] if enabled_payments else ""),
            "auto_validate_orders": cint(self.auto_validate_orders),
            "tips_enabled": cint(self.tips_enabled),
            "enable_rounded_total": cint(self.enable_rounded_total),
            # POS UI
            "show_product_images": cint(self.show_product_images),
            "show_category_images": cint(self.show_category_images),
            "group_by_category": cint(self.group_by_category),
            "large_scrollbars": cint(self.large_scrollbars),
            # Open orders
            "share_open_orders": cint(self.share_open_orders),
            # Categories
            "restrict_categories": cint(self.restrict_categories),
            "allowed_categories": allowed_categories,
            "allow_category_search": cint(self.allow_category_search),
            # Pricing & Discounts
            "allow_line_discount": cint(self.allow_line_discount),
            "price_display_mode": self.price_display_mode or "Precio con impuesto incluido",
            "allow_global_discount": cint(self.allow_global_discount),
            "enable_promotions_coupons": cint(self.enable_promotions_coupons),
            "enable_gift_cards": cint(self.enable_gift_cards),
            "enable_loyalty_program": cint(self.enable_loyalty_program),
            # Invoices & Receipts
            "allow_whatsapp_invoice": cint(self.allow_whatsapp_invoice),
            "allow_email_invoice": cint(self.allow_email_invoice),
            "enable_self_invoicing": cint(self.enable_self_invoicing),
            # Wallpaper
            "idle_wallpaper_enabled": cint(self.idle_wallpaper_enabled),
            "idle_wallpaper_show_clock": cint(self.idle_wallpaper_show_clock),
            "idle_wallpaper_timeout": timeout_seconds,
            "idle_wallpaper_background_url": self.idle_wallpaper_background or "/assets/restaurant/images/background-light.svg",
            "idle_wallpaper_logo_url": self.idle_wallpaper_logo or "",
        }

    def _sync_pos_profile_and_config(self):
        payload = self._build_config_payload()

        if self.pos_profile and frappe.db.exists("POS Profile", self.pos_profile):
            prof_doc = frappe.get_doc("POS Profile", self.pos_profile)
            prof_doc.hide_images = 0 if cint(self.show_product_images) else 1
            prof_doc.disable_rounded_total = 0 if cint(self.enable_rounded_total) else 1

            enabled_payments = payload["enabled_payments"]
            if enabled_payments:
                default_mop = payload["default_payment"]
                prof_doc.set("payments", [])
                for idx, mop in enumerate(enabled_payments):
                    if frappe.db.exists("Mode of Payment", mop):
                        prof_doc.append("payments", {
                            "mode_of_payment": mop,
                            "default": 1 if (mop == default_mop or (not default_mop and idx == 0)) else 0,
                        })

            prof_doc.save(ignore_permissions=True)

            pref_key = f"rpos_cfg_{self.pos_profile}"
            raw_existing = frappe.db.get_default(pref_key)
            existing = {}
            if raw_existing:
                try:
                    existing = json.loads(raw_existing) if isinstance(raw_existing, str) else dict(raw_existing)
                except Exception:
                    existing = {}
            existing.update(payload)
            frappe.db.set_default(pref_key, json.dumps(existing))
        else:
            frappe.db.set_default("rpos_cfg_global", json.dumps(payload))


@frappe.whitelist()
def load_profile_settings(pos_profile=None):
    """Return saved settings and available ERPNext Mode of Payment rows for a POS Profile."""
    _assert_settings_admin()
    all_mops = frappe.get_all(
        "Mode of Payment",
        filters={"enabled": 1},
        pluck="name",
        order_by="name asc",
    )

    if not pos_profile or not frappe.db.exists("POS Profile", pos_profile):
        return {
            "all_mops": all_mops,
            "profile_payments": [{"mode_of_payment": m, "enabled": 1, "is_default": 1 if i == 0 else 0} for i, m in enumerate(all_mops)],
            "config": {},
        }

    prof_doc = frappe.get_doc("POS Profile", pos_profile)
    prof_enabled_map = {row.mode_of_payment: cint(row.default) for row in (prof_doc.payments or [])}

    payment_rows = []
    for idx, mop in enumerate(all_mops):
        is_enabled = 1 if (not prof_enabled_map or mop in prof_enabled_map) else 0
        is_def = cint(prof_enabled_map.get(mop, 1 if idx == 0 else 0))
        payment_rows.append({
            "mode_of_payment": mop,
            "enabled": is_enabled,
            "is_default": is_def,
        })

    pref_key = f"rpos_cfg_{pos_profile}"
    raw_pref = frappe.db.get_default(pref_key)
    pref = {}
    if raw_pref:
        try:
            pref = json.loads(raw_pref) if isinstance(raw_pref, str) else dict(raw_pref)
        except Exception:
            pref = {}

    return {
        "company": prof_doc.company,
        "all_mops": all_mops,
        "profile_payments": payment_rows,
        "config": pref,
    }
