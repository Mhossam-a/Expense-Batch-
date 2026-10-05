"""Hooks on the standard HRMS Expense Claim.

They only act on drafts and only when they have something to do: tax is handled
when a line is marked "Has Tax" or carries an Item Tax Template (or when we added
tax rows earlier), and the payable account is only set when an expense type maps
to one. Submitted and cancelled claims are never touched.
"""

import frappe
from frappe import _
from frappe.utils import cint

from expense_batch.services import payable, taxes
from expense_batch.services.generator import reset_rows_for_claim


def before_validate(doc, method=None):
	if doc.docstatus != 0:
		return

	settings = payable.get_settings()
	normalise_tax_lines(doc, settings)
	sync_tax_rows(doc)

	if cint(settings.apply_to_manual_claims) or doc.get("expense_batch"):
		sync_payable_account(doc, settings)


def normalise_tax_lines(doc, settings):
	"""Keep "Has Tax" and the Item Tax Template of every line consistent.

	A template makes the line taxable; "Has Tax" without a template takes the
	company's default template; neither means no tax. A template must belong to the
	claim's company and be enabled.
	"""
	defaults = {d.company: d.default_item_tax_template for d in settings.company_defaults or []}

	for row in doc.get("expenses") or []:
		template = row.get("item_tax_template")

		if template:
			row.has_tax = 1
		elif cint(row.get("has_tax")):
			template = defaults.get(doc.company)
			if not template:
				frappe.throw(
					_(
						"Row {0}: Has Tax is ticked, but no Item Tax Template is chosen and none is set as the default for {1} in Expense Batch Settings."
					).format(row.idx, doc.company),
					title=_("Item Tax Template missing"),
				)
			row.item_tax_template = template
		else:
			row.has_tax = 0
			row.item_tax_template = None
			row.line_tax_amount = 0
			continue

		info = frappe.db.get_value("Item Tax Template", template, ["company", "disabled"], as_dict=True)
		if not info:
			frappe.throw(_("Row {0}: Item Tax Template {1} does not exist").format(row.idx, template))
		if info.company != doc.company:
			frappe.throw(
				_("Row {0}: {1} belongs to {2}, not {3}").format(row.idx, template, info.company, doc.company),
				title=_("Item Tax Template"),
			)
		if cint(info.disabled):
			frappe.throw(_("Row {0}: {1} is disabled").format(row.idx, template), title=_("Item Tax Template"))


def sync_tax_rows(doc):
	"""Rebuild the tax rows that come from line Item Tax Templates and fill each
	line's own tax amount.

	Rows typed by hand are left alone. Tax is stored as an amount (rate stays 0),
	so the standard "rate x total" recalculation can never change it, and a line
	without a template simply adds nothing.
	"""
	expenses = doc.get("expenses") or []
	current = doc.get("taxes") or []
	auto_rows = [t for t in current if cint(t.get("from_item_tax_template"))]
	if not (auto_rows or any(r.get("item_tax_template") for r in expenses)):
		return

	rejected = doc.get("approval_status") == "Rejected"
	lines = [
		{
			"sanctioned_amount": 0 if rejected else r.get("sanctioned_amount"),
			"item_tax_template": r.get("item_tax_template"),
			"cost_center": r.get("cost_center"),
			"project": r.get("project"),
		}
		for r in expenses
	]
	rows, per_line = taxes.aggregate_with_lines(lines)

	for row, amount in zip(expenses, per_line):
		row.line_tax_amount = amount if row.get("item_tax_template") else 0

	doc.set("taxes", [t for t in current if not cint(t.get("from_item_tax_template"))])
	for row in rows:
		doc.append("taxes", row)


def sync_payable_account(doc, settings=None):
	types = {r.expense_type for r in doc.get("expenses") or [] if r.expense_type}
	if not types or not doc.company:
		return

	account, conflicts = payable.resolve_for_types(types, doc.company, settings)
	if conflicts:
		frappe.throw(payable.conflict_message(conflicts), title=_("Different payable accounts"))
	if account:
		doc.payable_account = account


def before_cancel(doc, method=None):
	# The batch rows point at this claim; that link must not block cancelling it.
	if doc.get("expense_batch"):
		doc.flags.ignore_links = True


def on_cancel(doc, method=None):
	if doc.get("expense_batch"):
		reset_rows_for_claim(
			doc.name, new_status="Cancelled", keep_link=True, note=_("The claim was cancelled")
		)


def on_trash(doc, method=None):
	# Runs before Frappe's link check, so clearing the link here lets the delete through.
	if doc.get("expense_batch"):
		reset_rows_for_claim(doc.name, new_status="Pending", keep_link=False)
