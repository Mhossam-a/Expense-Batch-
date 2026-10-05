"""Payable account per Expense Claim Type (per company).

Instead of one Payable Account on the Company, every Expense Claim Type can
carry its own, in the same per-company table that already holds its expense
account (custom field `default_payable_account` on "Expense Claim Account").
"""

import frappe
from frappe import _
from frappe.utils import cint


def get_settings():
	return frappe.get_cached_doc("Expense Batch Settings")


def get_type_payable_account(expense_type, company):
	if not expense_type or not company:
		return None
	return frappe.db.get_value(
		"Expense Claim Account",
		{"parent": expense_type, "parenttype": "Expense Claim Type", "company": company},
		"default_payable_account",
	)


def get_type_expense_account(expense_type, company):
	if not expense_type or not company:
		return None
	return frappe.db.get_value(
		"Expense Claim Account",
		{"parent": expense_type, "parenttype": "Expense Claim Type", "company": company},
		"default_account",
	)


def get_company_default(company):
	return frappe.get_cached_value("Company", company, "default_expense_claim_payable_account") if company else None


def is_pinned(values, company):
	"""True when someone chose this claim's payable account on purpose.

	The app only ever overwrites an account it filled in itself (remembered in
	`auto_payable_account`), an empty one, or the plain company default that HRMS
	puts on every new claim. Anything else, for instance an intermediate account
	picked by hand, is left exactly as it is.
	"""
	current = values.get("payable_account")
	if not current:
		return False
	if cint(values.get("payable_account_pinned")):
		return True
	if current == values.get("auto_payable_account"):
		return False
	return current != get_company_default(company)


def resolve_payable_account(expense_type, company, settings=None, override=None):
	"""(account, source) where source is 'batch', 'type', 'company' or None.

	An account chosen on the batch itself wins over everything else."""
	if override:
		return override, "batch"
	account = get_type_payable_account(expense_type, company)
	if account:
		return account, "type"

	settings = settings or get_settings()
	if cint(settings.fallback_to_company_payable):
		account = get_company_default(company)
		if account:
			return account, "company"
	return None, None


def resolve_for_types(expense_types, company, settings=None):
	"""Payable account for a set of expense types that share one claim.

	Returns (account or None, conflicts) where conflicts maps account -> [types]
	when the types would need different payable accounts.
	"""
	by_account = {}
	for expense_type in expense_types:
		account, _source = resolve_payable_account(expense_type, company, settings)
		if account:
			by_account.setdefault(account, []).append(expense_type)

	if len(by_account) > 1:
		return None, by_account
	return (next(iter(by_account)) if by_account else None), {}


def conflict_message(conflicts):
	parts = [f"{account}: {', '.join(sorted(set(types)))}" for account, types in conflicts.items()]
	return _(
		"These expense types post to different payable accounts and cannot share one Expense Claim: {0}. "
		"Create a separate claim for each (the Expense Claim Batch does this for you)."
	).format("; ".join(parts))
