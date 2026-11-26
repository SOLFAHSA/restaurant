"""Restaurant POS configuration per POS Profile and idle-screen settings."""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from restaurant.pos_context import (
    _get_default_company,
    _get_default_pos_profile,
    _require_manager_user,
    _require_pos_user,
)


def _get_effective_rpos_config(pos_profile=None):
    """Merge Restaurant Settings single doc with per-profile defaults."""
    cfg = {
        "pos_profile": pos_profile or "",
        "default_preset": "Comer en el local",
        "enable_self_order": 0,
        "self_order_channels": "Ambos canales",
        "enable_mobile_self_order": 0,
        "enable_kiosk_self_order": 0,
        "enabled_payments": [],
        "auto_validate_orders": 1,
        "tips_enabled": 1,
        "enable_rounded_total": 0,
        "show_product_images": 1,
        "show_category_images": 1,
        "group_by_category": 0,
        "large_scrollbars": 0,
        "share_open_orders": 1,
        "restrict_categories": 0,
        "allowed_categories": [],
        "allow_category_search": 1,
        "allow_line_discount": 1,
        "price_display_mode": "Precio con impuesto incluido",
        "allow_global_discount": 1,
        "enable_promotions_coupons": 0,
        "enable_gift_cards": 0,
        "enable_loyalty_program": 0,
        "allow_whatsapp_invoice": 0,
        "allow_email_invoice": 1,
        "enable_self_invoicing": 0,
        "idle_wallpaper_enabled": 1,
        "idle_wallpaper_show_clock": 1,
        "idle_wallpaper_timeout": 120,
        "idle_wallpaper_background_url": "/assets/restaurant/images/background-light.svg",
        "idle_wallpaper_logo_url": "",
    }

    if frappe.db.exists("DocType", "Restaurant Settings"):
        try:
            rs = frappe.get_single("Restaurant Settings")
            for key in (
                "default_preset", "enable_self_order", "self_order_channels",
                "enable_mobile_self_order", "enable_kiosk_self_order",
                "auto_validate_orders", "tips_enabled", "enable_rounded_total",
                "show_product_images", "show_category_images", "group_by_category",
                "large_scrollbars", "share_open_orders", "restrict_categories",
                "allow_category_search", "allow_line_discount", "price_display_mode",
                "allow_global_discount", "enable_promotions_coupons",
                "enable_gift_cards", "enable_loyalty_program",
                "allow_whatsapp_invoice", "allow_email_invoice", "enable_self_invoicing",
                "idle_wallpaper_enabled", "idle_wallpaper_show_clock",
            ):
                if hasattr(rs, key) and rs.get(key) is not None:
                    cfg[key] = rs.get(key)
            if hasattr(rs, "idle_wallpaper_minutes") and rs.idle_wallpaper_minutes:
                cfg["idle_wallpaper_timeout"] = int(round(max(0.1, flt(rs.idle_wallpaper_minutes)) * 60))
            if getattr(rs, "idle_wallpaper_background", None):
                cfg["idle_wallpaper_background_url"] = rs.idle_wallpaper_background
            if getattr(rs, "idle_wallpaper_logo", None):
                cfg["idle_wallpaper_logo_url"] = rs.idle_wallpaper_logo
            if cint(cfg.get("restrict_categories")) and getattr(rs, "allowed_categories", None):
                cfg["allowed_categories"] = [
                    r.item_group for r in rs.allowed_categories if r.item_group
                ]
        except Exception:
            pass

    if pos_profile:
        raw_pref = frappe.db.get_default(f"rpos_cfg_{pos_profile}")
        if raw_pref:
            try:
                pref = json.loads(raw_pref) if isinstance(raw_pref, str) else dict(raw_pref)
                for k, v in pref.items():
                    if k != "enabled_payments" and v is not None:
                        cfg[k] = v
            except Exception:
                pass
        if frappe.db.exists("POS Profile", pos_profile):
            prof_doc = frappe.get_doc("POS Profile", pos_profile)
            cfg["show_product_images"] = 0 if cint(prof_doc.hide_images) else cint(cfg.get("show_product_images", 1))
            cfg["enable_rounded_total"] = (
                0
                if (cint(prof_doc.disable_rounded_total) or not cint(cfg.get("enable_rounded_total", 0)))
                else 1
            )
            cfg["enabled_payments"] = [row.mode_of_payment for row in prof_doc.payments if row.mode_of_payment]

    return cfg


@frappe.whitelist()
def get_pos_idle_settings():
    """Return configured POS inactivity wallpaper settings."""
    _require_pos_user()
    if frappe.db.exists("DocType", "Restaurant Settings"):
        try:
            settings = frappe.get_single("Restaurant Settings")
            return {
                "enabled": cint(bool(settings.idle_wallpaper_enabled)),
                "timeout_seconds": max(5, int(round(flt(settings.idle_wallpaper_minutes or 2) * 60))),
                "background_url": settings.idle_wallpaper_background or "/assets/restaurant/images/background-light.svg",
                "logo_url": settings.idle_wallpaper_logo or "",
                "show_clock": cint(bool(settings.idle_wallpaper_show_clock)),
            }
        except Exception:
            pass

    raw_enabled = frappe.db.get_default("rpos_idle_wallpaper_enabled")
    raw_timeout = frappe.db.get_default("rpos_idle_wallpaper_timeout_seconds")
    raw_show_clock = frappe.db.get_default("rpos_idle_wallpaper_show_clock")
    bg_url = frappe.db.get_default("rpos_idle_wallpaper_background_url") or "/assets/restaurant/images/background-light.svg"
    logo_url = frappe.db.get_default("rpos_idle_wallpaper_logo_url") or ""
    enabled = 1 if raw_enabled is None else cint(raw_enabled)
    show_clock = 1 if raw_show_clock is None else cint(raw_show_clock)
    timeout_seconds = cint(raw_timeout) if raw_timeout is not None else 120
    if timeout_seconds < 5:
        timeout_seconds = 120
    return {
        "enabled": cint(bool(enabled)),
        "timeout_seconds": timeout_seconds,
        "background_url": bg_url,
        "logo_url": logo_url,
        "show_clock": cint(bool(show_clock)),
    }


@frappe.whitelist(methods=["POST"])
def save_pos_idle_settings(enabled=1, timeout_seconds=120, background_url=None, logo_url=None, show_clock=1):
    """Persist POS inactivity wallpaper settings in global defaults."""
    _require_manager_user()
    clean_enabled = 1 if cint(enabled) else 0
    clean_show_clock = 1 if cint(show_clock) else 0
    clean_timeout = max(5, min(7200, cint(timeout_seconds or 120)))
    frappe.db.set_default("rpos_idle_wallpaper_enabled", str(clean_enabled))
    frappe.db.set_default("rpos_idle_wallpaper_timeout_seconds", str(clean_timeout))
    frappe.db.set_default("rpos_idle_wallpaper_show_clock", str(clean_show_clock))
    if background_url is not None:
        frappe.db.set_default("rpos_idle_wallpaper_background_url", str(background_url or ""))
    if logo_url is not None:
        frappe.db.set_default("rpos_idle_wallpaper_logo_url", str(logo_url or ""))
    frappe.clear_cache()
    return {
        "enabled": clean_enabled,
        "timeout_seconds": clean_timeout,
        "background_url": background_url or "",
        "logo_url": logo_url or "",
        "show_clock": clean_show_clock,
    }


@frappe.whitelist()
def get_restaurant_pos_config(pos_profile=None):
    """Retrieve full configuration matching the Odoo-style restaurant POS settings screen."""
    _require_pos_user()
    company = _get_default_company()
    all_profiles = frappe.get_all(
        "POS Profile",
        filters={"disabled": 0},
        fields=["name", "company", "currency", "customer"],
        order_by="name asc",
    )
    if not pos_profile or not frappe.db.exists("POS Profile", pos_profile):
        default_p = _get_default_pos_profile(company)
        pos_profile = default_p.name if default_p else (all_profiles[0].name if all_profiles else None)

    if not pos_profile:
        return {
            "pos_profiles": [],
            "selected_profile": "",
            "company": company,
            "currency": "HNL",
            "has_active_shift": False,
            "active_shift": None,
            "is_bar_restaurant": 1,
            "areas": [],
            "enabled_areas": [],
            "presets": [],
            "enabled_presets": [],
            "default_preset": "Comer en el local",
            "payments": [],
            "all_payment_methods": [],
            "enable_rounded_total": 0,
            "max_difference_enabled": 0,
            "write_off_limit": 0.0,
            "auto_validate_orders": 1,
            "one_click_pay": 0,
            "tips_enabled": 1,
            "tip_after_payment": 0,
            "employee_login_required": 0,
            "show_product_images": 1,
            "show_category_images": 1,
            "group_by_category": 0,
            "large_scrollbars": 0,
            "online_reservation": 0,
            "default_screen": "Caja",
            "idle_wallpaper_enabled": 1,
            "idle_wallpaper_timeout": 60,
        }

    prof_doc = frappe.get_doc("POS Profile", pos_profile)

    shifts = frappe.get_all(
        "POS Opening Shift",
        filters={"pos_profile": pos_profile, "docstatus": 1, "status": "Open"},
        fields=["name", "user", "period_start_date"],
        limit=1,
    )
    active_shift = shifts[0] if shifts else None

    payments = [
        {"mode_of_payment": row.mode_of_payment, "default": cint(row.default)}
        for row in (prof_doc.payments or [])
    ]
    all_payment_methods = frappe.get_all(
        "Mode of Payment", filters={"enabled": 1}, pluck="name", order_by="name asc"
    )

    area_fields = ["name", "area_name"]
    if frappe.db.table_exists("Restaurant Area"):
        area_meta = frappe.get_meta("Restaurant Area")
        if area_meta.has_field("status"):
            area_fields.append("status")
        areas = frappe.get_all("Restaurant Area", fields=area_fields, order_by="area_name asc")
    else:
        areas = []
    for a in areas:
        a["disabled"] = 1 if a.get("status") == "Inactiva" else 0

    preset_fields = ["name", "preset_name", "color_bg", "color_border"]
    if frappe.db.table_exists("Restaurant Order Preset"):
        preset_meta = frappe.get_meta("Restaurant Order Preset")
        if preset_meta.has_field("enabled"):
            preset_fields.append("enabled")
        if preset_meta.has_field("enable_scheduling"):
            preset_fields.append("enable_scheduling")
        presets = frappe.get_all(
            "Restaurant Order Preset",
            fields=preset_fields,
            order_by="idx asc, creation asc" if preset_meta.has_field("idx") else "creation asc",
        )
    else:
        presets = []
    for p in presets:
        p["disabled"] = 0 if cint(p.get("enabled", 1)) else 1

    pref_key = f"rpos_cfg_{pos_profile}"
    raw_pref = frappe.db.get_default(pref_key)
    pref = {}
    if raw_pref:
        try:
            pref = json.loads(raw_pref) if isinstance(raw_pref, str) else raw_pref
        except Exception:
            pref = {}

    idle_settings = get_pos_idle_settings()

    return {
        "pos_profiles": [p.name for p in all_profiles],
        "selected_profile": pos_profile,
        "company": prof_doc.company,
        "currency": prof_doc.currency or "HNL",
        "has_active_shift": bool(active_shift),
        "active_shift": active_shift,
        "is_bar_restaurant": cint(pref.get("is_bar_restaurant", 1)),
        "areas": areas,
        "enabled_areas": pref.get("enabled_areas", [a.name for a in areas if not a.get("disabled")]),
        "presets": presets,
        "enabled_presets": pref.get("enabled_presets", [p.preset_name for p in presets if not p.get("disabled")]),
        "default_preset": pref.get("default_preset", "Comer en el local"),
        "payments": payments,
        "all_payment_methods": all_payment_methods,
        "enable_rounded_total": 0 if cint(prof_doc.disable_rounded_total) else 1,
        "max_difference_enabled": 1 if flt(prof_doc.write_off_limit) > 0 else cint(pref.get("max_difference_enabled", 0)),
        "write_off_limit": flt(prof_doc.write_off_limit or 0),
        "auto_validate_orders": cint(pref.get("auto_validate_orders", 1)),
        "one_click_pay": cint(pref.get("one_click_pay", 0)),
        "tips_enabled": cint(pref.get("tips_enabled", 1)),
        "tip_after_payment": cint(pref.get("tip_after_payment", 0)),
        "employee_login_required": cint(pref.get("employee_login_required", 0)),
        "show_product_images": 0 if cint(prof_doc.hide_images) else cint(pref.get("show_product_images", 1)),
        "show_category_images": cint(pref.get("show_category_images", 1)),
        "group_by_category": cint(pref.get("group_by_category", 0)),
        "large_scrollbars": cint(pref.get("large_scrollbars", 0)),
        "online_reservation": cint(pref.get("online_reservation", 0)),
        "default_screen": pref.get("default_screen", "Caja"),
        "idle_wallpaper_enabled": cint(pref.get("idle_wallpaper_enabled", idle_settings["enabled"])),
        "idle_wallpaper_timeout": cint(pref.get("idle_wallpaper_timeout", idle_settings["timeout_seconds"])),
        "idle_wallpaper_background_url": pref.get("idle_wallpaper_background_url", idle_settings.get("background_url", "/assets/restaurant/images/background-light.svg")),
        "idle_wallpaper_logo_url": pref.get("idle_wallpaper_logo_url", idle_settings.get("logo_url", "")),
        "idle_wallpaper_show_clock": cint(pref.get("idle_wallpaper_show_clock", idle_settings.get("show_clock", 1))),
    }


@frappe.whitelist(methods=["POST"])
def save_restaurant_pos_config(pos_profile, config):
    """Save full configuration matching the Odoo-style restaurant POS settings screen."""
    _require_manager_user()
    if isinstance(config, str):
        config = json.loads(config)

    if not pos_profile or not frappe.db.exists("POS Profile", pos_profile):
        frappe.throw(_("El Perfil de Punto de Venta especificado no existe."))

    prof_doc = frappe.get_doc("POS Profile", pos_profile)

    # 1. Update native POS Profile fields
    show_prod_imgs = cint(config.get("show_product_images", 1))
    prof_doc.hide_images = 0 if show_prod_imgs else 1
    prof_doc.disable_rounded_total = 0 if cint(config.get("enable_rounded_total", 0)) else 1

    if cint(config.get("max_difference_enabled", 0)):
        prof_doc.write_off_limit = max(0.0, flt(config.get("write_off_limit") or 0))
    else:
        prof_doc.write_off_limit = 0.0

    # Payments table
    incoming_payments = config.get("payments") or []
    if incoming_payments:
        clean_methods = []
        for p in incoming_payments:
            m = p if isinstance(p, str) else p.get("mode_of_payment")
            if m and frappe.db.exists("Mode of Payment", m) and m not in clean_methods:
                clean_methods.append(m)

        if clean_methods:
            prof_doc.set("payments", [])
            for idx, m in enumerate(clean_methods):
                prof_doc.append("payments", {
                    "mode_of_payment": m,
                    "default": 1 if idx == 0 else 0,
                })

    prof_doc.save(ignore_permissions=True)

    # 2. Persist extended profile configuration
    pref_key = f"rpos_cfg_{pos_profile}"
    profile_preferences = {key: value for key, value in config.items() if key not in ("payments", "enabled_payments")}
    frappe.db.set_default(pref_key, json.dumps(profile_preferences))

    # 3. Synchronize global wallpaper settings if provided
    if "idle_wallpaper_enabled" in config and "idle_wallpaper_timeout" in config:
        save_pos_idle_settings(
            enabled=config.get("idle_wallpaper_enabled"),
            timeout_seconds=config.get("idle_wallpaper_timeout"),
            background_url=config.get("idle_wallpaper_background_url"),
            logo_url=config.get("idle_wallpaper_logo_url"),
            show_clock=config.get("idle_wallpaper_show_clock", 1),
        )

    frappe.clear_cache()
    return get_restaurant_pos_config(pos_profile)


@frappe.whitelist()
def get_self_order_config(pos_profile=None):
    """Return active self-order channels and status for mobile/kiosk clients."""
    _require_pos_user()
    cfg = _get_effective_rpos_config(pos_profile)
    enabled = bool(cint(cfg.get("enable_self_order")))
    mobile_ok = enabled and bool(cint(cfg.get("enable_mobile_self_order")))
    kiosk_ok = enabled and bool(cint(cfg.get("enable_kiosk_self_order")))
    return {
        "enabled": enabled,
        "channels": cfg.get("self_order_channels") or "Ambos canales",
        "mobile_enabled": mobile_ok,
        "kiosk_enabled": kiosk_ok,
        "default_preset": cfg.get("default_preset") or "Comer en el local",
    }
