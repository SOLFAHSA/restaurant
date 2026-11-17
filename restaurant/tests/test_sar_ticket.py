"""Tests for Honduras SAR Ticket Print Format, exact centavos, and exoneration traceability."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from restaurant.pos import _get_effective_rpos_config, pay_and_invoice_order
from restaurant.sar_format import format_lempiras_in_words, get_sar_ticket_context


class TestSarTicket(FrappeTestCase):
    """Verify SAR formatting, non-rounding behavior, custom fields, and Ticket rendering."""

    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        self.savepoint = "sar_ticket_test"
        frappe.db.savepoint(self.savepoint)

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=self.savepoint)
        frappe.set_user(self.original_user)

    def test_format_lempiras_in_words_exact_centavos(self):
        self.assertEqual(
            format_lempiras_in_words(485.00),
            "**CUATROCIENTOS OCHENTA Y CINCO LEMPIRAS EXACTOS**",
        )
        self.assertEqual(
            format_lempiras_in_words(17.83),
            "**DIECISIETE LEMPIRAS CON 83/100**",
        )
        self.assertEqual(
            format_lempiras_in_words(1.00),
            "**UN LEMPIRA EXACTO**",
        )
        self.assertEqual(
            format_lempiras_in_words(1.50),
            "**UN LEMPIRA CON 50/100**",
        )
        self.assertEqual(
            format_lempiras_in_words(100.00),
            "**CIEN LEMPIRAS EXACTOS**",
        )
        self.assertEqual(
            format_lempiras_in_words(1000000.00),
            "**UN MILLON DE LEMPIRAS EXACTOS**",
        )

    def test_sar_custom_fields_and_rounding_defaults(self):
        cust_meta = frappe.get_meta("Customer")
        si_meta = frappe.get_meta("Sales Invoice")
        self.assertTrue(cust_meta.has_field("custom_registro_sag"))
        for fname in (
            "custom_registro_sag",
            "restaurant_order",
            "restaurant_order_number",
            "restaurant_table_label",
            "restaurant_service_type",
            "restaurant_waiter_name",
        ):
            self.assertTrue(si_meta.has_field(fname), f"Missing Sales Invoice field: {fname}")

        cfg = _get_effective_rpos_config("POS 01 HNL" if frappe.db.exists("POS Profile", "POS 01 HNL") else None)
        self.assertEqual(int(cfg.get("enable_rounded_total", 0)), 0)

    def test_ticket_print_format_renders_historical_invoice_with_exact_cents(self):
        inv_name = "000-001-01-00000009"
        if not frappe.db.exists("Sales Invoice", inv_name):
            self.skipTest(f"Historical invoice {inv_name} not present in site DB")

        html = frappe.get_print("Sales Invoice", inv_name, "Ticket", no_letterhead=1)
        for expected in (
            f"FACTURA No. {inv_name}",
            "CAI",
            "No.OC Exenta",
            "No.CR Exonerado",
            "No.Reg.Sec.Agro",
            "DESCUENTOS Y REBAJAS L.",
            "EXENTO L.",
            "EXONERADO L.",
            "GRAVADO 15% L.",
            "GRAVADO 18% L.",
            "IMPTO. 15% L.",
            "IMPTO. 18% L.",
            "TOTAL FACTURA L.",
            "DIECISIETE LEMPIRAS CON 83/100",
            "Rango Autorizado",
            "Fecha Limite de Emision",
            "Original: Cliente",
            "Copia: Obligado tributario emisor.",
        ):
            self.assertIn(expected, html)

        self.assertNotIn("Constancia SAR / SAG / SEFIN", html)

    def test_pay_and_invoice_order_disables_rounding_and_renders_ticket(self):
        if not frappe.db.exists("Print Format", "Ticket"):
            self.fail("Print Format 'Ticket' must exist")

        company = frappe.db.get_default("company") or frappe.db.get_value("Company", {}, "name")
        pos_profile = frappe.db.get_value("POS Profile", {"disabled": 0}, "name")
        customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
        if not (company and pos_profile and customer):
            self.skipTest("Site missing baseline Company / POS Profile / Customer")

        test_item_code = "_TEST_SAR_PLATILLO"
        if not frappe.db.exists("Item", test_item_code):
            item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
            uom = frappe.db.get_value("UOM", {}, "name") or "Unidad"
            item = frappe.get_doc({
                "doctype": "Item",
                "item_code": test_item_code,
                "item_name": "Combo Familiar Prueba SAR",
                "item_group": item_group,
                "stock_uom": uom,
                "is_stock_item": 0,
                "is_sales_item": 1,
                "standard_rate": 15.50,
            }).insert(ignore_permissions=True)
        else:
            item = frappe.get_doc("Item", test_item_code)

        if not frappe.db.exists("POS Opening Shift", {"user": "Administrator", "status": "Open", "docstatus": 1}):
            shift = frappe.get_doc({
                "doctype": "POS Opening Shift",
                "period_start_date": frappe.utils.now_datetime(),
                "company": company,
                "user": "Administrator",
                "pos_profile": pos_profile,
                "balance_details": [{"mode_of_payment": "Efectivo", "opening_amount": 0}],
            })
            shift.insert(ignore_permissions=True)
            shift.submit()

        table_name = frappe.db.get_value("Restaurant Table", {}, "name") if frappe.db.exists("DocType", "Restaurant Table") else None
        order = frappe.get_doc({
            "doctype": "Restaurant Order",
            "order_name": "9991",
            "company": company,
            "pos_profile": pos_profile,
            "customer": customer,
            "service_type": "Comer en el local" if table_name else "Para llevar",
            "restaurant_table": table_name or "",
            "waiter_name": "Cajero SAR",
            "currency": "HNL",
            "items": [
                {
                    "item_code": item.name,
                    "item_name": item.item_name,
                    "qty": 1,
                    "uom": item.stock_uom,
                    "base_rate": 15.50,
                    "options_rate": 0,
                    "options_summary": "Papas Grandes, Sin Salsa",
                    "note": "Caliente",
                    "rate": 15.50,
                    "amount": 15.50,
                    "tax_rate": 15.0,
                }
            ],
        })
        order.insert(ignore_permissions=True)

        expected_grand = flt(order.grand_total, 2)
        result = pay_and_invoice_order(
            order_name=order.name,
            payments=[{"mode_of_payment": "Efectivo", "amount": expected_grand}],
            customer=customer,
        )
        inv_name = result["invoice"]["name"]
        si = frappe.get_doc("Sales Invoice", inv_name)

        self.assertEqual(int(si.disable_rounded_total), 1)
        self.assertEqual(flt(si.grand_total, 2), expected_grand)
        self.assertEqual(si.restaurant_order, order.name)
        self.assertEqual(si.restaurant_order_number, "9991")
        self.assertEqual(si.restaurant_table_label, order.table_label or "")
        self.assertEqual(si.restaurant_service_type, order.service_type)

        ctx = get_sar_ticket_context(si)
        expected_badge = "** COMER EN LOCAL **" if table_name else "** LLEVAR **"
        self.assertEqual(ctx["service_badge"], expected_badge)
        self.assertIn("PAPAS GRANDES", ctx["items"][0]["sublines"])

        html = frappe.get_print("Sales Invoice", si.name, "Ticket", no_letterhead=1)
        self.assertIn("ORDEN 9991", html)
        if order.table_label:
            expected_table_txt = order.table_label.upper() if order.table_label.upper().startswith("MESA") else f"MESA {order.table_label.upper()}"
            self.assertIn(expected_table_txt, html)
        self.assertIn(expected_badge, html)
        self.assertIn("PAPAS GRANDES", html)
        self.assertIn(format_lempiras_in_words(si.grand_total), html)
