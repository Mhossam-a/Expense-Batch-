"""Tax maths shared by the batch form, the split preview, the generator and the
Expense Claim hook, so that every screen shows exactly the same numbers.

Taxes always come from an Item Tax Template and are stored as **amounts**
(never as a rate on the claim), because one Expense Claim line may have tax and
the next one may not.
"""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe.utils import cint, flt


def _dec(value):
	return Decimal(str(flt(value, 9)))


def round_half_up(value, precision):
	"""Commercial rounding (x.5 always goes up), which is how suppliers round the
	VAT on an invoice. Done in Decimal so 1.305 is really 1.305, not 1.30499999."""
	quantum = Decimal(1).scaleb(-precision)
	return float(Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))


def get_precision():
	value = frappe.db.get_single_value("System Settings", "currency_precision")
	return cint(value) if str(value or "").strip() else 2


def get_template_rates(template, cache=None):
	"""[{account, rate}] for an Item Tax Template, skipping 'not applicable' rows."""
	if not template:
		return []
	if cache is not None and template in cache:
		return cache[template]

	rows = frappe.get_all(
		"Item Tax Template Detail",
		filters={"parent": template, "parenttype": "Item Tax Template"},
		fields=["tax_type", "tax_rate", "not_applicable"],
		order_by="idx",
	)
	rates = [{"account": r.tax_type, "rate": flt(r.tax_rate)} for r in rows if not r.not_applicable]
	if cache is not None:
		cache[template] = rates
	return rates


def tax_parts(net, rates, precision=None):
	"""Tax per account for a net amount: [(account, amount)]."""
	precision = precision if precision is not None else get_precision()
	return [
		(r["account"], round_half_up(_dec(net) * _dec(r["rate"]) / Decimal(100), precision)) for r in rates
	]


def split_inclusive(gross, rates, precision=None):
	"""Split a tax-inclusive total into (net, parts) so that net + tax equals the
	entered total to the last decimal. Expense Claim re-computes tax from the net
	amount on every save, so we look for the net that round-trips exactly."""
	precision = precision if precision is not None else get_precision()
	gross = flt(gross, precision)
	total_rate = sum(flt(r["rate"]) for r in rates)
	if not total_rate:
		return gross, []

	step = 10 ** (-precision)
	base = round_half_up(_dec(gross) / (Decimal(1) + _dec(total_rate) / Decimal(100)), precision)
	best = None
	for candidate in (base, flt(base - step, precision), flt(base + step, precision)):
		parts = tax_parts(candidate, rates, precision)
		total = flt(candidate + sum(p[1] for p in parts), precision)
		diff = abs(flt(total - gross, precision))
		if best is None or diff < best[0]:
			best = (diff, candidate, parts)
		if diff == 0:
			break
	return best[1], best[2]


def compute_line(amount, template=None, includes_tax=False, cache=None, precision=None):
	"""Return {net, tax, parts, gross} for one invoice line."""
	precision = precision if precision is not None else get_precision()
	amount = flt(amount, precision)
	rates = get_template_rates(template, cache) if template else []

	if not rates:
		return {"net": amount, "tax": 0.0, "parts": [], "gross": amount}

	if cint(includes_tax):
		net, parts = split_inclusive(amount, rates, precision)
	else:
		net, parts = amount, tax_parts(amount, rates, precision)

	tax = flt(sum(p[1] for p in parts), precision)
	return {"net": net, "tax": tax, "parts": parts, "gross": flt(net + tax, precision)}


def aggregate_tax_rows(lines, cache=None, precision=None):
	"""Tax rows only (see aggregate_with_lines)."""
	return aggregate_with_lines(lines, cache, precision)[0]


def aggregate_with_lines(lines, cache=None, precision=None):
	"""Group the tax of several expense lines.

	`lines` are dict-likes with sanctioned_amount, item_tax_template, cost_center,
	project. Returns (rows, per_line) where `rows` are Expense Taxes and Charges rows,
	one per (account, cost center, project) so each cost center keeps its own tax in
	the GL, and `per_line` is the tax amount of every input line, in order.
	"""
	precision = precision if precision is not None else get_precision()
	buckets = {}
	per_line = []
	for line in lines:
		template = line.get("item_tax_template")
		line_total = 0.0
		if template:
			for account, amount in tax_parts(
				flt(line.get("sanctioned_amount")), get_template_rates(template, cache), precision
			):
				key = (account, line.get("cost_center") or "", line.get("project") or "")
				buckets[key] = flt(buckets.get(key, 0) + amount, precision)
				line_total += amount
		per_line.append(flt(line_total, precision))

	account_names = {}
	rows = []
	for (account, cost_center, project), amount in buckets.items():
		if account not in account_names:
			account_names[account] = frappe.db.get_value("Account", account, "account_name") or account
		rows.append(
			{
				"account_head": account,
				"description": account_names[account],
				"rate": 0,
				"tax_amount": amount,
				"cost_center": cost_center or None,
				"project": project or None,
				"from_item_tax_template": 1,
			}
		)
	return rows, per_line
