// Expense Claim (HRMS): company filters, per-line "Has Tax" + Item Tax Template, and
// the payable account of the expense type.
//
// The server hooks (expense_batch.overrides.expense_claim) are the source of truth;
// this script only shows the same result live while the user types.
(function () {
	frappe.ui.form.on("Expense Claim", {
		setup(frm) {
			// Everything company-specific is limited to the claim's company, and only
			// ledger (non-group) accounts and cost centers can be picked.
			const by_company = (extra) => () => ({
				filters: Object.assign({ company: frm.doc.company }, extra),
			});

			frm.set_query("item_tax_template", "expenses", by_company({ disabled: 0 }));
			frm.set_query("cost_center", "expenses", by_company({ is_group: 0 }));
			frm.set_query("cost_center", by_company({ is_group: 0 }));
			frm.set_query("project", "expenses", by_company({}));
			frm.set_query("project", by_company({}));
			frm.set_query("expense_type", "expenses", () => ({
				query: "expense_batch.api.expense_types_for_company",
				filters: { company: frm.doc.company },
			}));
		}
	});

	frappe.ui.form.on("Expense Claim Detail", {
		has_tax(frm, cdt, cdn) {
			const row = locals[cdt][cdn];

			if (!row.has_tax) {
				frappe.model.set_value(cdt, cdn, { item_tax_template: "", line_tax_amount: 0 });
				return sync_item_taxes(frm);
			}
			if (row.item_tax_template || !frm.doc.company) return sync_item_taxes(frm);

			// Ticking the box fills the company's default template, when one is set.
			frappe
				.xcall("expense_batch.api.get_company_default_template", { company: frm.doc.company })
				.then((template) => {
					if (template) {
						frappe.model.set_value(cdt, cdn, "item_tax_template", template);
					} else {
						frappe.show_alert(
							{
								message: __("No default Item Tax Template for {0}. Choose one in this row.", [frm.doc.company]),
								indicator: "orange",
							},
							7
						);
					}
				});
		},

		item_tax_template(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			if (row.item_tax_template && !row.has_tax) frappe.model.set_value(cdt, cdn, "has_tax", 1);
			sync_item_taxes(frm);
		},

		sanctioned_amount: (frm) => sync_item_taxes(frm),
		cost_center: (frm) => sync_item_taxes(frm),
		project: (frm) => sync_item_taxes(frm),
		expenses_remove: (frm) => {
			sync_item_taxes(frm);
			sync_payable_account(frm);
		},
		expense_type: (frm) => sync_payable_account(frm),
	});

	function sync_item_taxes(frm) {
		if (frm.doc.docstatus !== 0) return;
		clearTimeout(frm._eb_tax_timer);

		frm._eb_tax_timer = setTimeout(() => {
			const expenses = frm.doc.expenses || [];
			const lines = expenses.map((row) => ({
				sanctioned_amount: row.sanctioned_amount,
				item_tax_template: row.item_tax_template,
				cost_center: row.cost_center,
				project: row.project,
			}));
			const had_auto_rows = (frm.doc.taxes || []).some((t) => t.from_item_tax_template);
			if (!had_auto_rows && !lines.some((l) => l.item_tax_template)) return;

			frappe.call({
				method: "expense_batch.api.get_tax_rows",
				args: { expenses: lines, company: frm.doc.company },
				callback: (r) => {
					const out = r.message || { rows: [], lines: [] };

					out.lines.forEach((amount, i) => {
						const row = expenses[i];
						if (row && flt(row.line_tax_amount) !== flt(amount)) {
							frappe.model.set_value(row.doctype, row.name, "line_tax_amount", amount);
						}
					});

					// keep rows typed by hand, replace only the ones that came from templates
					frm.doc.taxes = (frm.doc.taxes || []).filter((t) => !t.from_item_tax_template);
					out.rows.forEach((row) => frm.add_child("taxes", row));
					frm.refresh_field("taxes");
					recalculate_totals(frm);
				},
			});
		}, 300);
	}

	function recalculate_totals(frm) {
		const sanctioned = flt(frm.doc.total_sanctioned_amount);
		let taxes = 0;
		(frm.doc.taxes || []).forEach((t) => {
			taxes += flt(t.tax_amount);
			frappe.model.set_value(t.doctype, t.name, "total", flt(sanctioned + flt(t.tax_amount)));
		});
		frm.set_value("total_taxes_and_charges", flt(taxes, precision("total_taxes_and_charges")));
		frm.set_value(
			"grand_total",
			flt(sanctioned + taxes - flt(frm.doc.total_advance_amount), precision("grand_total"))
		);
	}

	function sync_payable_account(frm) {
		if (frm.doc.docstatus !== 0 || !frm.doc.company) return;
		const types = [...new Set((frm.doc.expenses || []).map((r) => r.expense_type).filter(Boolean))];
		if (!types.length) return;

		frappe.call({
			method: "expense_batch.api.resolve_payable",
			args: {
				expense_types: types,
				company: frm.doc.company,
				current: frm.doc.payable_account,
				auto: frm.doc.auto_payable_account,
				pinned: frm.doc.payable_account_pinned ? 1 : 0,
			},
			callback: (r) => {
				const out = r.message || {};
				// an account chosen by hand is never replaced
				if (out.pinned) return;

				if (out.conflict) {
					frappe.msgprint({ title: __("Different payable accounts"), message: out.conflict, indicator: "orange" });
				} else if (out.account && out.account !== frm.doc.payable_account) {
					frm.set_value("payable_account", out.account);
					frm.set_value("auto_payable_account", out.account);
					frm.set_value("payable_account_pinned", 0);
				}
			},
		});
	}
})();
