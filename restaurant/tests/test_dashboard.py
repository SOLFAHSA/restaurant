"""The restaurant dashboard reads its sales from the issued native invoices (ADR 002)."""

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
        self.assertEqual(after["average_ticket"], flt(after["today"] / after["invoices"], 2))
        self.assertIn(item, top)
        self.assertEqual(top[item]["amount"], flt(invoice.net_total, 2))

        invoice.cancel()
        cancelled, top = self.sales()
        self.assertEqual(flt(cancelled["today"], 2), flt(before["today"], 2))
        self.assertNotIn(item, top)
