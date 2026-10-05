import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Expense Batch"


def amount_options(doctype, fieldname, fallback="Company:company:default_currency"):
	"""Currency options of a core amount field, so ours is formatted the same way on
	every version (v15 reads the company currency, v16 the claim's currency)."""
	meta = frappe.get_meta(doctype)
	field = meta.get_field(fieldname) if meta else None
	return (field.options if field and field.options else None) or fallback


def get_custom_fields():
	return {
		"Expense Claim Account": [
			{
				"fieldname": "default_payable_account",
				"label": "Default Payable Account",
				"fieldtype": "Link",
				"options": "Account",
				"insert_after": "default_account",
				"in_list_view": 1,
				"description": "Payable account credited by claims of this type in this company.",
			}
		],
		"Expense Claim Detail": [
			{
				"fieldname": "tax_section",
				"label": "Tax",
				"fieldtype": "Section Break",
				"insert_after": "description",
			},
			{
				"fieldname": "has_tax",
				"label": "Has Tax",
				"fieldtype": "Check",
				"insert_after": "tax_section",
				"in_list_view": 1,
				"columns": 1,
				"description": "Tick it when this invoice carries tax. The Item Tax Template then decides the accounts and rates.",
			},
			{
				"fieldname": "tax_column",
				"fieldtype": "Column Break",
				"insert_after": "has_tax",
			},
			{
				"fieldname": "item_tax_template",
				"label": "Item Tax Template",
				"fieldtype": "Link",
				"options": "Item Tax Template",
				"insert_after": "tax_column",
				"depends_on": "eval:doc.has_tax",
				"in_list_view": 0,
				"columns": 0,
			},
			{
				"fieldname": "tax_amount_column",
				"fieldtype": "Column Break",
				"insert_after": "item_tax_template",
			},
			{
				"fieldname": "line_tax_amount",
				"label": "Tax Amount",
				"fieldtype": "Currency",
				"options": amount_options("Expense Claim Detail", "sanctioned_amount"),
				"insert_after": "tax_amount_column",
				"read_only": 1,
				"no_copy": 1,
				"depends_on": "eval:doc.has_tax",
			},
		],
		"Expense Taxes and Charges": [
			{
				"fieldname": "from_item_tax_template",
				"label": "Added from Item Tax Template",
				"fieldtype": "Check",
				"insert_after": "project",
				"hidden": 1,
				"read_only": 1,
			}
		],
		"Expense Claim": [
			{
				"fieldname": "expense_batch",
				"label": "Expense Claim Batch",
				"fieldtype": "Link",
				"options": "Expense Claim Batch",
				"insert_after": "remark",
				"read_only": 1,
				"no_copy": 1,
				"in_standard_filter": 1,
				"print_hide": 1,
			}
		],
	}


def ensure_doctypes():
	"""Custom fields below link to Expense Claim Batch, so make sure it exists even
	if the installer reaches this hook before the DocTypes were synced."""
	for folder in (
		"expense_batch_company_default",
		"expense_batch_settings",
		"expense_claim_batch_detail",
		"expense_claim_batch",
	):
		doctype = frappe.unscrub(folder)
		if not frappe.db.exists("DocType", doctype):
			frappe.reload_doc("expense_batch", "doctype", folder, force=True)


def after_install():
	ensure_doctypes()
	create_custom_fields(get_custom_fields(), update=True)
	frappe.clear_cache()


def after_migrate():
	ensure_doctypes()
	create_custom_fields(get_custom_fields(), update=True)


def before_uninstall():
	for doctype, fields in get_custom_fields().items():
		for field in fields:
			name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": field["fieldname"]})
			if name:
				frappe.delete_doc("Custom Field", name, force=True)
	frappe.clear_cache()
