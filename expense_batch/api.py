"""Small whitelisted helpers used by the forms."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from expense_batch.services import payable, taxes
from expense_batch.services.splitter import build_plan


@frappe.whitelist()
def get_plan(doc):
	"""Dry-run of the split for the batch as it currently looks on screen."""
	frappe.has_permission("Expense Claim Batch", "read", throw=True)
	data = frappe.parse_json(doc)
	data["doctype"] = "Expense Claim Batch"
	batch = frappe.get_doc(data)
	if not batch.company:
		return {"groups": [], "invalid": [], "done": [], "summary": {"rows": 0}, "mode": batch.split_mode}
	return build_plan(batch)


@frappe.whitelist()
def compute_row_tax(amount, template=None, includes_tax=0):
	frappe.has_permission("Expense Claim Batch", "read", throw=True)
	line = taxes.compute_line(flt(amount), template, cint(includes_tax))
	return {"net": line["net"], "tax": line["tax"]}


@frappe.whitelist()
def get_company_default_template(company):
	if not (
		frappe.has_permission("Expense Claim Batch", "read") or frappe.has_permission("Expense Claim", "read")
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	settings = payable.get_settings()
	for row in settings.company_defaults or []:
		if row.company == company:
			return row.default_item_tax_template
	return None


@frappe.whitelist()
def get_tax_rows(expenses, company=None):
	"""Tax rows, and the tax of every line, for an Expense Claim being edited."""
	frappe.has_permission("Expense Claim", "read", throw=True)
	lines = frappe.parse_json(expenses) or []
	rows, per_line = taxes.aggregate_with_lines(lines)
	return {"rows": rows, "lines": per_line}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def expense_types_for_company(doctype, txt, searchfield, start, page_len, filters):
	"""Link search: only expense types that have an expense account for the company,
	because HRMS refuses to save a claim line whose type has none."""
	company = filters.get("company") if isinstance(filters, dict) else None
	values = {"txt": f"%{txt}%", "start": cint(start), "page_len": cint(page_len), "company": company}
	company_condition = (
		"and exists (select 1 from `tabExpense Claim Account` a where a.parent = t.name "
		"and a.parenttype = 'Expense Claim Type' and a.company = %(company)s)"
		if company
		else ""
	)
	return frappe.db.sql(
		f"""
		select t.name, t.description from `tabExpense Claim Type` t
		where (t.name like %(txt)s or ifnull(t.description, '') like %(txt)s) {company_condition}
		order by t.name limit %(start)s, %(page_len)s
		""",
		values,
	)


@frappe.whitelist()
def resolve_payable(expense_types, company):
	"""Payable account for the expense types on a claim, or the reason they clash."""
	frappe.has_permission("Expense Claim", "read", throw=True)
	if not cint(payable.get_settings().apply_to_manual_claims):
		return {"account": None, "conflict": None}
	types = {t for t in (frappe.parse_json(expense_types) or []) if t}
	account, conflicts = payable.resolve_for_types(types, company)
	return {"account": account, "conflict": payable.conflict_message(conflicts) if conflicts else None}
