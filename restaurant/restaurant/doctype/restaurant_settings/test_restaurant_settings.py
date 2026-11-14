"""Unit tests for Restaurant Settings single DocType and effective POS config."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestRestaurantSettings(FrappeTestCase):
    def test_restaurant_settings_exists_and_persists_all_sections(self):
        doc = frappe.get_single("Restaurant Settings")
        self.assertIsNotNone(doc)

        doc.enable_self_order = 1
        doc.self_order_channels = "Autopedido por celular"
        doc.auto_validate_orders = 1
        doc.tips_enabled = 0
        doc.show_product_images = 0
        doc.show_category_images = 1
        doc.group_by_category = 1
        doc.large_scrollbars = 1
        doc.share_open_orders = 1
        doc.restrict_categories = 0
        doc.allow_category_search = 1
        doc.allow_line_discount = 0
        doc.price_display_mode = "Precio sin impuesto incluido"
        doc.allow_global_discount = 0
        doc.enable_promotions_coupons = 1
        doc.enable_gift_cards = 1
        doc.enable_loyalty_program = 1
        doc.allow_whatsapp_invoice = 1
        doc.allow_email_invoice = 1
        doc.enable_self_invoicing = 1
        doc.idle_wallpaper_enabled = 1
        doc.idle_wallpaper_show_clock = 1
        doc.idle_wallpaper_minutes = 3.5
        doc.save(ignore_permissions=True)

        loaded = frappe.get_single("Restaurant Settings")
        self.assertEqual(loaded.enable_mobile_self_order, 1)
        self.assertEqual(loaded.enable_kiosk_self_order, 0)
        self.assertEqual(loaded.tips_enabled, 0)
        self.assertEqual(loaded.group_by_category, 1)
        self.assertEqual(loaded.large_scrollbars, 1)
        self.assertEqual(loaded.allow_line_discount, 0)
        self.assertEqual(loaded.price_display_mode, "Precio sin impuesto incluido")
        self.assertEqual(loaded.enable_gift_cards, 1)
        self.assertEqual(loaded.allow_whatsapp_invoice, 1)
        self.assertEqual(loaded.enable_self_invoicing, 1)
