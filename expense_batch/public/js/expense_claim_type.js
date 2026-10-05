// Expense Claim Type: only offer real payable accounts of the row's company.
(function () {
	frappe.ui.form.on("Expense Claim Type", {
		setup(frm) {
			frm.set_query("default_payable_account", "accounts", (doc, cdt, cdn) => {
				const row = locals[cdt][cdn];
				return {
					filters: {
						report_type: "Balance Sheet",
						account_type: "Payable",
						company: row.company,
						is_group: 0,
					},
				};
			});
		},
	});
})();
