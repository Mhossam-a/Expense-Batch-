from frappe import _


def get_data():
	return {
		"fieldname": "expense_batch",
		"transactions": [{"label": _("Expense Claims"), "items": ["Expense Claim"]}],
	}
