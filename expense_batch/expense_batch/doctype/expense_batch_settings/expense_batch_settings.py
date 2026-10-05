import frappe
from frappe import _
from frappe.model.document import Document


class ExpenseBatchSettings(Document):
	def validate(self):
		seen = set()
		for row in self.company_defaults or []:
			if row.company in seen:
				frappe.throw(_("Row {0}: {1} appears more than once").format(row.idx, row.company))
			seen.add(row.company)

			template_company = frappe.db.get_value("Item Tax Template", row.default_item_tax_template, "company")
			if template_company != row.company:
				frappe.throw(
					_("Row {0}: {1} belongs to {2}, not {3}").format(
						row.idx, row.default_item_tax_template, template_company, row.company
					)
				)
