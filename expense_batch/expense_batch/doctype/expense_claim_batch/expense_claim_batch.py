import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from expense_batch.services import payable, taxes
from expense_batch.services.splitter import build_plan

DETAIL = "Expense Claim Batch Detail"
PARENT = "Expense Claim Batch"

# Once a row has produced a claim, these can no longer change on the batch
LOCKED_FIELDS = (
	"employee",
	"expense_date",
	"invoice_reference",
	"expense_type",
	"amount",
	"has_tax",
	"item_tax_template",
	"cost_center",
	"project",
	"description",
	"attachment",
)


class ExpenseClaimBatch(Document):
	def validate(self):
		self.set_company()
		self.validate_payable_account()
		self.restore_system_fields()
		self.prepare_rows()
		self.set_totals()
		self.set_counters()

	def before_submit(self):
		if not self.details:
			frappe.throw(_("Add at least one invoice before submitting."))

		plan = build_plan(self)
		if plan["invalid"]:
			lines = "".join(
				"<li>{0} {1}: {2}</li>".format(
					_("Row"),
					row["idx"],
					frappe.utils.escape_html("; ".join(i["msg"] for i in row["issues"] if i["level"] == "error")),
				)
				for row in plan["invalid"][:15]
			)
			more = len(plan["invalid"]) - 15
			if more > 0:
				lines += "<li>{0}</li>".format(_("... and {0} more rows").format(more))
			frappe.throw(
				_("Fix these rows before submitting:") + f"<ul>{lines}</ul>", title=_("Invoices need attention")
			)

	def before_update_after_submit(self):
		self.validate_payable_account()
		self.restore_system_fields()
		self.validate_locked_rows()
		self.prepare_rows()
		self.set_totals()
		self.set_counters()

	def before_cancel(self):
		live = []
		for row in frappe.get_all(
			DETAIL, filters={"parent": self.name, "parenttype": PARENT}, fields=["generated_claim"]
		):
			if row.generated_claim and row.generated_claim not in live:
				if frappe.db.get_value("Expense Claim", row.generated_claim, "docstatus") in (0, 1):
					live.append(row.generated_claim)
		if live:
			frappe.throw(
				_("Cancel or delete these Expense Claims first: {0}").format(
					", ".join(frappe.utils.get_link_to_form("Expense Claim", c) for c in live)
				)
			)

	# ------------------------------------------------------------ helpers

	def validate_payable_account(self):
		if not self.payable_account:
			return
		info = frappe.db.get_value("Account", self.payable_account, ["company", "is_group"], as_dict=True)
		if not info:
			frappe.throw(_("Payable Account {0} does not exist").format(self.payable_account))
		if info.company != self.company:
			frappe.throw(
				_("Payable Account {0} belongs to {1}, not {2}").format(self.payable_account, info.company, self.company)
			)
		if info.is_group:
			frappe.throw(_("Payable Account {0} is a group account. Choose a ledger account.").format(self.payable_account))

	def set_company(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company")

	def restore_system_fields(self):
		"""Generation state is owned by the server. A form that was open while a
		batch was being generated must not be able to overwrite it."""
		if self.is_new():
			return

		stored = {
			r.name: r
			for r in frappe.get_all(
				DETAIL,
				filters={"parent": self.name, "parenttype": PARENT},
				fields=["name", "row_status", "generated_claim", "error_message"],
			)
		}
		for row in self.details or []:
			saved = stored.get(row.name)
			if saved:
				row.row_status = saved.row_status
				row.generated_claim = saved.generated_claim
				row.error_message = saved.error_message

		flags = frappe.db.get_value(PARENT, self.name, ["is_processing", "processing_since"], as_dict=True)
		if flags:
			self.is_processing = flags.is_processing
			self.processing_since = flags.processing_since

	def validate_locked_rows(self):
		stored = frappe.get_all(
			DETAIL,
			filters={"parent": self.name, "parenttype": PARENT, "row_status": "Generated"},
			fields=["name", "idx", "generated_claim", *LOCKED_FIELDS],
		)
		current = {r.name: r for r in self.details or []}
		for old in stored:
			row = current.get(old.name)
			if not row:
				frappe.throw(
					_("Row {0} already produced {1} and cannot be removed. Cancel or delete that claim first.").format(
						old.idx, old.generated_claim
					)
				)
			for field in LOCKED_FIELDS:
				if _normalise(field, old.get(field)) != _normalise(field, row.get(field)):
					frappe.throw(
						_("Row {0} already produced {1} and can no longer be changed ({2}). Cancel or delete that claim first.").format(
							old.idx, old.generated_claim, frappe.unscrub(field)
						)
					)

	def prepare_rows(self):
		settings = payable.get_settings()
		defaults = {d.company: d.default_item_tax_template for d in settings.company_defaults or []}
		includes_tax = cint(self.amounts_include_tax)
		company_cost_center = frappe.get_cached_value("Company", self.company, "cost_center") if self.company else None
		cache = {}

		for row in self.details or []:
			if row.row_status == "Generated":
				continue

			if not row.employee and self.default_employee:
				row.employee = self.default_employee
			if not row.cost_center:
				row.cost_center = self.default_cost_center or company_cost_center
			if not row.project and self.default_project:
				row.project = self.default_project

			if cint(row.has_tax):
				if not row.item_tax_template and defaults.get(self.company):
					row.item_tax_template = defaults[self.company]
			else:
				row.item_tax_template = None

			line = taxes.compute_line(row.amount, row.item_tax_template, includes_tax, cache)
			row.net_amount = line["net"]
			row.tax_amount = line["tax"]

	def set_totals(self):
		net = sum(flt(r.net_amount) for r in self.details or [])
		tax = sum(flt(r.tax_amount) for r in self.details or [])
		self.total_net = flt(net, self.precision("total_net"))
		self.total_tax = flt(tax, self.precision("total_tax"))
		self.grand_total = flt(net + tax, self.precision("grand_total"))

	def set_counters(self):
		rows = self.details or []
		total = len(rows)
		generated = sum(1 for r in rows if r.row_status == "Generated")
		failed = sum(1 for r in rows if r.row_status == "Failed")
		self.total_rows, self.generated_rows, self.failed_rows = total, generated, failed

		if cint(self.is_processing):
			self.generation_status = "Processing"
		elif total and generated == total:
			self.generation_status = "Generated"
		elif generated:
			self.generation_status = "Partly Generated"
		elif failed:
			self.generation_status = "Failed"
		else:
			self.generation_status = "Pending"


def _normalise(field, value):
	if field == "amount":
		return flt(value, 6)
	if field == "has_tax":
		return cint(value)
	if field == "expense_date":
		return str(value or "")
	return (value or "").strip() if isinstance(value, str) else (value or "")
