app_name = "expense_batch"
app_title = "Expense Batch"
app_publisher = "Mhossam-a"
app_description = "Enter many invoices at once and split them into separate Expense Claims, with per-line tax, attachments and a payable account per expense type."
app_email = "mohammedhossam168@gmail.com"
app_license = "MIT"

required_apps = ["frappe/erpnext", "frappe/hrms"]

app_include_css = "/assets/expense_batch/css/expense_batch.css"

doctype_js = {
	"Expense Claim": "public/js/expense_claim.js",
	"Expense Claim Type": "public/js/expense_claim_type.js",
}

doc_events = {
	"Expense Claim": {
		"before_validate": "expense_batch.overrides.expense_claim.before_validate",
		"before_cancel": "expense_batch.overrides.expense_claim.before_cancel",
		"on_cancel": "expense_batch.overrides.expense_claim.on_cancel",
		"on_trash": "expense_batch.overrides.expense_claim.on_trash",
	}
}

after_install = "expense_batch.setup.install.after_install"
after_migrate = "expense_batch.setup.install.after_migrate"
before_uninstall = "expense_batch.setup.install.before_uninstall"
