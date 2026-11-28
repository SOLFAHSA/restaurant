"""The restaurant dashboard reads its sales from the issued native invoices (ADR 002)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from restaurant.dashboard import get_dashboard_data
from restaurant.tests import test_invoice_stock


class TestRestaurantDashboard(FrappeTestCase):
    def tearDown(self):
        frappe.set_user("Administrator")

    def test_manager_gets_all_sections(self):
        company = frappe.get_all("Company", limit=1, pluck="name")[0]
        data = get_dashboard_data(company)
        for key in ("tables", "open_orders", "kitchen", "sales", "top_items", "pending_tables", "recent_activity"):
            self.assertIn(key, data)
        self.assertEqual(data["company"], company)
        self.assertGreaterEqual(data["sales"]["today"], 0)

    def test_average_ticket_is_sales_divided_by_invoices(self):
        # Hand-computed: L 345.00 in 3 invoices = L 115.00 per invoice; no sales yesterday.
        company = frappe.get_all("Company", limit=1, pluck="name")[0]
        summaries = {True: (345.0, 3), False: (0.0, 0)}
        with patch("restaurant.dashboard._sales_summary", side_effect=lambda _company, date: summaries[date == frappe.utils.getdate()]):
            sales = get_dashboard_data(company)["sales"]
        self.assertEqual(sales["average_ticket"], 115.00)
        self.assertEqual(sales["invoices"], 3)
        self.assertIsNone(sales["change_percent"])

    def test_user_without_role_is_rejected(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            get_dashboard_data()


class TestDashboardSales(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.sale = test_invoice_stock.TestRestaurantInvoiceStock()
        self.addCleanup(self.sale.doCleanups)
        self.sale.setUp()

    def sales(self):
        data = get_dashboard_data(self.sale.company)
        return data["sales"], {row["item_code"]: row for row in data["top_items"]}

    def test_issued_invoice_counts_and_cancelled_invoice_does_not(self):
        item = self.sale.make_item("DASHBOARD", is_stock_item=0)
        before, _top = self.sales()

        # A large sale keeps the item in today's top five even if other tests sold today.
        invoice = self.sale.pay(self.sale.make_order({"item_code": item, "base_rate": 999999}))
        after, top = self.sales()
        self.assertEqual(flt(after["today"] - before["today"], 2), flt(invoice.grand_total, 2))
        self.assertEqual(after["invoices"], before["invoices"] + 1)
        self.assertIn(item, top)
        self.assertEqual(top[item]["amount"], flt(invoice.net_total, 2))

        invoice.cancel()
        cancelled, top = self.sales()
        self.assertEqual(flt(cancelled["today"], 2), flt(before["today"], 2))
        self.assertNotIn(item, top)
