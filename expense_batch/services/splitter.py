"""The split planner.

`build_plan()` is a dry run of the generation: it decides which invoice rows end
up in which Expense Claim, validates every row, and totals everything. The same
plan feeds the "Split Map" on the form and the real generator, so what the user
previews is what gets created.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from expense_batch.services import payable, taxes

MODE_ROW = "Each Row"
MODE_EMPLOYEE_DATE = "Employee + Date"
MODE_EMPLOYEE = "Employee"
MODES = (MODE_ROW, MODE_EMPLOYEE_DATE, MODE_EMPLOYEE)

# Row states whose invoices still need a claim
OPEN_STATES = ("Pending", "Failed", "Cancelled", "", None)


def build_plan(batch, settings=None):
	settings = settings or payable.get_settings()
	company = batch.company
	mode = batch.get("split_mode") if batch.get("split_mode") in MODES else MODE_ROW
	includes_tax = cint(batch.get("amounts_include_tax"))
	precision = taxes.get_precision()
	tax_cache = {}
	employee_cache = {}

	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None

	valid, invalid, done_rows = [], [], []
	seen = {}

	for row in batch.get("details") or []:
		status = row.get("row_status") or "Pending"
		if status == "Generated":
			done_rows.append(row)
			continue

		info = _row_info(row, batch, includes_tax, tax_cache, precision)
		issues = _validate_row(info, batch, settings, employee_cache)

		# duplicates inside this batch
		dup_key = (info.employee, str(info.date), info.expense_type, flt(info.amount, precision))
		if dup_key in seen:
			issues.append(_issue("warn", _("Same employee, date, type and amount as row {0}").format(seen[dup_key])))
		else:
			seen[dup_key] = info.idx

		# duplicates against claims that already exist
		if cint(settings.warn_duplicates) and not _has_error(issues):
			existing = _find_existing_claim(info, precision)
			if existing:
				issues.append(_issue("warn", _("Looks like {0} already has this expense").format(existing)))

		info.issues = issues
		if _has_error(issues):
			invalid.append(info)
		else:
			valid.append(info)

	groups = _group(valid, mode, batch, tax_cache, precision)
	done = _done_claims(done_rows)

	summary = {
		"rows": len(batch.get("details") or []),
		"open_rows": len(valid) + len(invalid),
		"claims_to_create": len(groups),
		"invalid_rows": len(invalid),
		"claims_done": len(done),
		"net": flt(sum(g["net"] for g in groups), precision),
		"tax": flt(sum(g["tax"] for g in groups), precision),
		"total": flt(sum(g["total"] for g in groups), precision),
		"warnings": sum(1 for g in groups for i in g["issues"] if i["level"] == "warn"),
	}

	return {
		"mode": mode,
		"currency": currency,
		"groups": groups,
		"invalid": [_row_view(i) for i in invalid],
		"done": done,
		"summary": summary,
	}


# ---------------------------------------------------------------- rows


def status_of(row):
	return row.get("row_status") or "Pending"


def _row_info(row, batch, includes_tax, tax_cache, precision):
	template = row.get("item_tax_template") if cint(row.get("has_tax")) else None
	company_cost_center = frappe.get_cached_value("Company", batch.company, "cost_center") if batch.company else None
	line = taxes.compute_line(row.get("amount"), template, includes_tax, tax_cache, precision)
	return frappe._dict(
		idx=row.get("idx"),
		name=row.get("name"),
		employee=row.get("employee") or batch.get("default_employee"),
		date=getdate(row.get("expense_date")) if row.get("expense_date") else None,
		expense_type=row.get("expense_type"),
		amount=flt(row.get("amount"), precision),
		has_tax=cint(row.get("has_tax")),
		template=template,
		description=row.get("description"),
		reference=row.get("invoice_reference"),
		cost_center=row.get("cost_center") or batch.get("default_cost_center") or company_cost_center,
		project=row.get("project") or batch.get("default_project"),
		attachment=row.get("attachment"),
		last_error=row.get("error_message") if status_of(row) == "Failed" else None,
		net=line["net"],
		tax=line["tax"],
		gross=line["gross"],
		parts=line["parts"],
		payable_account=None,
		payable_source=None,
		issues=[],
	)


def _issue(level, message):
	return {"level": level, "msg": message}


def _has_error(issues):
	return any(i["level"] == "error" for i in issues)


def _validate_row(info, batch, settings, employee_cache):
	issues = []
	company = batch.company

	if not info.employee:
		issues.append(_issue("error", _("Employee is missing (set it on the row or as the default employee)")))
	else:
		employee = employee_cache.get(info.employee)
		if employee is None:
			employee = (
				frappe.db.get_value(
					"Employee", info.employee, ["employee_name", "status", "company"], as_dict=True
				)
				or {}
			)
			employee_cache[info.employee] = employee
		if not employee:
			issues.append(_issue("error", _("Employee {0} does not exist").format(info.employee)))
		else:
			info.employee_name = employee.employee_name
			if employee.status != "Active":
				issues.append(_issue("error", _("Employee {0} is not active").format(info.employee)))
			elif employee.company and employee.company != company:
				issues.append(
					_issue("error", _("Employee belongs to {0}, not {1}").format(employee.company, company))
				)

	if not info.date:
		issues.append(_issue("error", _("Expense date is missing")))
	elif info.date > getdate(nowdate()):
		issues.append(_issue("warn", _("Expense date is in the future")))

	if flt(info.amount) <= 0:
		issues.append(_issue("error", _("Amount must be greater than zero")))

	if not info.expense_type:
		issues.append(_issue("error", _("Expense type is missing")))
	else:
		if not payable.get_type_expense_account(info.expense_type, company):
			issues.append(
				_issue(
					"error",
					_("{0} has no expense account for {1} (Expense Claim Type > Accounts)").format(
						info.expense_type, company
					),
				)
			)
		info.payable_account, info.payable_source = payable.resolve_payable_account(
			info.expense_type, company, settings
		)
		if not info.payable_account:
			issues.append(
				_issue(
					"error",
					_("No payable account for {0} in {1}. Set it on the Expense Claim Type.").format(
						info.expense_type, company
					),
				)
			)

	if not info.cost_center:
		issues.append(_issue("error", _("Cost center is missing (set it on the row, as the batch default, or on the Company)")))
	else:
		cost_center_company = frappe.db.get_value("Cost Center", info.cost_center, "company")
		if cost_center_company and cost_center_company != company:
			issues.append(
				_issue("error", _("{0} belongs to {1}, not {2}").format(info.cost_center, cost_center_company, company))
			)

	if info.has_tax:
		if not info.template:
			issues.append(_issue("error", _("Tax is ticked but no Item Tax Template is chosen")))
		else:
			template = frappe.db.get_value(
				"Item Tax Template", info.template, ["company", "disabled"], as_dict=True
			)
			if not template:
				issues.append(_issue("error", _("Item Tax Template {0} does not exist").format(info.template)))
			elif template.company != company:
				issues.append(
					_issue("error", _("{0} belongs to {1}, not {2}").format(info.template, template.company, company))
				)
			elif cint(template.disabled):
				issues.append(_issue("error", _("{0} is disabled").format(info.template)))
			elif not info.parts:
				issues.append(_issue("warn", _("{0} has no applicable tax rate, so no tax is added").format(info.template)))

	if not info.attachment:
		level = "error" if cint(settings.require_attachment) else "warn"
		issues.append(_issue(level, _("No attachment")))

	return issues


def _find_existing_claim(info, precision):
	if not (info.employee and info.date and info.expense_type):
		return None
	rows = frappe.db.sql(
		"""
		select c.name from `tabExpense Claim` c
		join `tabExpense Claim Detail` d on d.parent = c.name
		where c.employee = %s and d.expense_date = %s and d.expense_type = %s
			and d.amount = %s and c.docstatus < 2
		limit 1
		""",
		(info.employee, info.date, info.expense_type, flt(info.net, precision)),
	)
	return rows[0][0] if rows else None


# ---------------------------------------------------------------- groups


def _group_key(mode, info):
	if mode == MODE_ROW:
		return ("row", info.idx)
	if mode == MODE_EMPLOYEE_DATE:
		return (info.employee, str(info.date), info.payable_account)
	return (info.employee, info.payable_account)


def _group(valid, mode, batch, tax_cache, precision):
	buckets, order = {}, []
	for info in valid:
		key = _group_key(mode, info)
		if key not in buckets:
			buckets[key] = []
			order.append(key)
		buckets[key].append(info)

	use_expense_date = cint(batch.get("use_expense_date_as_posting_date"))
	groups = []
	for number, key in enumerate(order, start=1):
		rows = buckets[key]
		first = rows[0]
		dates = [r.date for r in rows]

		tax_rows = taxes.aggregate_tax_rows(
			[
				{
					"sanctioned_amount": r.net,
					"item_tax_template": r.template,
					"cost_center": r.cost_center,
					"project": r.project,
				}
				for r in rows
			],
			tax_cache,
			precision,
		)
		net = flt(sum(r.net for r in rows), precision)
		tax = flt(sum(t["tax_amount"] for t in tax_rows), precision)

		issues = []
		for r in rows:
			if r.last_error:
				issues.append(
					{"level": "warn", "msg": _("Last attempt failed: {0}").format(r.last_error), "row": r.idx}
				)
			for issue in r.issues:
				issues.append({"level": issue["level"], "msg": issue["msg"], "row": r.idx})

		groups.append(
			{
				"id": f"g{number}",
				"employee": first.employee,
				"employee_name": getattr(first, "employee_name", None) or first.employee,
				"posting_date": str(max(dates)) if use_expense_date else nowdate(),
				"date_from": str(min(dates)),
				"date_to": str(max(dates)),
				"payable_account": first.payable_account,
				"payable_source": first.payable_source,
				"net": net,
				"tax": tax,
				"total": flt(net + tax, precision),
				"tax_rows": tax_rows,
				"attachments": sum(1 for r in rows if r.attachment),
				"cost_centers": sorted({r.cost_center for r in rows if r.cost_center}),
				"rows": [_row_view(r) for r in rows],
				"row_names": [r.name for r in rows],
				"issues": issues,
				"state": "warn" if any(i["level"] == "warn" for i in issues) else "ready",
			}
		)
	return groups


def _row_view(info):
	return {
		"idx": info.idx,
		"name": info.name,
		"employee": info.employee,
		"employee_name": getattr(info, "employee_name", None) or info.employee,
		"date": str(info.date) if info.date else None,
		"expense_type": info.expense_type,
		"reference": info.reference,
		"description": info.description,
		"amount": info.amount,
		"net": info.net,
		"tax": info.tax,
		"gross": info.gross,
		"cost_center": info.cost_center,
		"project": info.project,
		"template": info.template,
		"attachment": info.attachment,
		"payable_account": info.payable_account,
		"issues": info.issues,
	}


def _done_claims(done_rows):
	claims = {}
	for row in done_rows:
		claim = row.get("generated_claim")
		if not claim:
			continue
		claims.setdefault(claim, []).append(row)

	done = []
	for claim, rows in claims.items():
		data = frappe.db.get_value(
			"Expense Claim",
			claim,
			["docstatus", "status", "grand_total", "employee_name", "posting_date"],
			as_dict=True,
		)
		if not data:
			continue
		done.append(
			{
				"claim": claim,
				"docstatus": data.docstatus,
				"status": data.status,
				"grand_total": flt(data.grand_total),
				"employee_name": data.employee_name,
				"posting_date": str(data.posting_date),
				"rows": [
					{
						"idx": r.get("idx"),
						"reference": r.get("invoice_reference"),
						"expense_type": r.get("expense_type"),
						"amount": flt(r.get("amount")),
						"date": str(r.get("expense_date")) if r.get("expense_date") else None,
					}
					for r in rows
				],
			}
		)
	return done
