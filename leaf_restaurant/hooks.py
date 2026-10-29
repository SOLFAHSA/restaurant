app_name = "leaf_restaurant"
app_title = "Leaf Restaurant"
app_publisher = "Grintsys"
app_description = "Restaurant management module for LEAF ERP"
app_email = "juanm.padilla13@hotmail.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/leaf_restaurant/css/leaf_restaurant.css"
# app_include_js = "/assets/leaf_restaurant/js/leaf_restaurant.js"

# include js, css files in header of web template
# web_include_css = "/assets/leaf_restaurant/css/leaf_restaurant.css"
# web_include_js = "/assets/leaf_restaurant/js/leaf_restaurant.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "leaf_restaurant/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "leaf_restaurant.utils.jinja_methods",
# 	"filters": "leaf_restaurant.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "leaf_restaurant.install.before_install"
# after_install = "leaf_restaurant.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "leaf_restaurant.uninstall.before_uninstall"
# after_uninstall = "leaf_restaurant.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "leaf_restaurant.utils.before_app_install"
# after_app_install = "leaf_restaurant.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "leaf_restaurant.utils.before_app_uninstall"
# after_app_uninstall = "leaf_restaurant.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "leaf_restaurant.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"leaf_restaurant.tasks.all"
# 	],
# 	"daily": [
# 		"leaf_restaurant.tasks.daily"
# 	],
# 	"hourly": [
# 		"leaf_restaurant.tasks.hourly"
# 	],
# 	"weekly": [
# 		"leaf_restaurant.tasks.weekly"
# 	],
# 	"monthly": [
# 		"leaf_restaurant.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "leaf_restaurant.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "leaf_restaurant.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "leaf_restaurant.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["leaf_restaurant.utils.before_request"]
# after_request = ["leaf_restaurant.utils.after_request"]

# Job Events
# ----------
# before_job = ["leaf_restaurant.utils.before_job"]
# after_job = ["leaf_restaurant.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"leaf_restaurant.auth.validate"
# ]
