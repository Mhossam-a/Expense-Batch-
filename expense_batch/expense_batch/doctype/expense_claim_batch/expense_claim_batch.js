(function () {
// Expense Claim Batch - one Client Script for the whole form:
// company filters, row shortcuts, the Split Map, and the Generate action.

const EB_COPY_FROM_PREVIOUS = [
	"employee",
	"expense_date",
	"expense_type",
	"has_tax",
	"item_tax_template",
	"cost_center",
	"project",
];

frappe.ui.form.on("Expense Claim Batch", {
	setup(frm) {
		const by_company = (extra) => () => ({ filters: Object.assign({ company: frm.doc.company }, extra) });

		frm.set_query("cost_center", "details", by_company({ is_group: 0 }));
		frm.set_query("project", "details", by_company({}));
		frm.set_query("item_tax_template", "details", by_company({ disabled: 0 }));
		frm.set_query("employee", "details", by_company({ status: "Active" }));
		frm.set_query("expense_type", "details", () => ({
			query: "expense_batch.api.expense_types_for_company",
			filters: { company: frm.doc.company },
		}));
		frm.set_query("default_cost_center", by_company({ is_group: 0 }));
		frm.set_query("default_project", by_company({}));
		frm.set_query("payable_account", by_company({ report_type: "Balance Sheet", account_type: "Payable", is_group: 0 }));
		frm.set_query("default_employee", by_company({ status: "Active" }));
	},

	onload(frm) {
		if (frm._eb_realtime) return;
		frm._eb_realtime = true;

		// The form object is shared between documents, so the handler checks which batch it is for.
		frappe.realtime.on("expense_batch_progress", (data) => {
			if (!data || data.batch !== frm.doc.name) return;

			if (data.finished) {
				frm._eb_progress = null;
				frm.reload_doc();
				frappe.show_alert(
					{
						message: __("Created {0} Expense Claims, {1} failed", [data.created || 0, data.failed || 0]),
						indicator: data.failed ? "orange" : "green",
					},
					8
				);
				return;
			}
			frm._eb_progress = { current: data.current, total: data.total };
			EB.render(frm);
		});
	},

	refresh(frm) {
		EB.addButtons(frm);
		EB.addIndicators(frm);
		EB.refreshMap(frm, 0);
	},

	company(frm) {
		EB.refreshMap(frm, 200);
	},

	split_mode(frm) {
		EB.refreshMap(frm, 0);
	},

	amounts_include_tax(frm) {
		(frm.doc.details || []).forEach((row) => EB.calcRow(frm, row.doctype, row.name));
	},

	default_employee(frm) {
		if (!frm.doc.default_employee) return;
		(frm.doc.details || []).forEach((row) => {
			if (!row.employee && row.row_status !== "Generated") {
				frappe.model.set_value(row.doctype, row.name, "employee", frm.doc.default_employee);
			}
		});
	},

	default_cost_center(frm) {
		EB.refreshMap(frm, 200);
	},

	payable_account(frm) {
		EB.refreshMap(frm, 200);
	},
});

frappe.ui.form.on("Expense Claim Batch Detail", {
	details_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const previous = (frm.doc.details || [])[row.idx - 2];

		if (!row.employee && frm.doc.default_employee) {
			frappe.model.set_value(cdt, cdn, "employee", frm.doc.default_employee);
		}
		if (!previous) return;

		// A run of invoices usually shares most of its fields with the one above it.
		EB_COPY_FROM_PREVIOUS.forEach((field) => {
			if (previous[field] && !row[field]) frappe.model.set_value(cdt, cdn, field, previous[field]);
		});
	},

	details_remove(frm) {
		EB.updateTotals(frm);
		EB.refreshMap(frm, 400);
	},

	has_tax(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.has_tax) {
			frappe.model.set_value(cdt, cdn, "item_tax_template", "");
			return EB.calcRow(frm, cdt, cdn);
		}
		if (row.item_tax_template || !frm.doc.company) return EB.calcRow(frm, cdt, cdn);

		EB.companyTemplate(frm).then((template) => {
			if (template) frappe.model.set_value(cdt, cdn, "item_tax_template", template);
			else EB.calcRow(frm, cdt, cdn);
		});
	},

	item_tax_template(frm, cdt, cdn) {
		EB.calcRow(frm, cdt, cdn);
	},

	amount(frm, cdt, cdn) {
		EB.calcRow(frm, cdt, cdn);
	},

	employee: (frm) => EB.refreshMap(frm, 600),
	expense_date: (frm) => EB.refreshMap(frm, 600),
	expense_type: (frm) => EB.refreshMap(frm, 600),
	cost_center: (frm) => EB.refreshMap(frm, 600),
	invoice_reference: (frm) => EB.refreshMap(frm, 600),
	attachment: (frm) => EB.refreshMap(frm, 600),
});

const EB = {
	// ------------------------------------------------------------ row maths

	calcRow(frm, cdt, cdn) {
		const row = locals[cdt] && locals[cdt][cdn];
		if (!row || row.row_status === "Generated") return;

		clearTimeout(EB._rowTimers && EB._rowTimers[cdn]);
		EB._rowTimers = EB._rowTimers || {};
		EB._rowTimers[cdn] = setTimeout(() => {
			frappe.call({
				method: "expense_batch.api.compute_row_tax",
				args: {
					amount: row.amount || 0,
					template: row.has_tax ? row.item_tax_template : null,
					includes_tax: frm.doc.amounts_include_tax ? 1 : 0,
				},
				callback: (r) => {
					if (!r.message) return;
					frappe.model.set_value(cdt, cdn, { net_amount: r.message.net, tax_amount: r.message.tax });
					EB.updateTotals(frm);
					EB.refreshMap(frm, 500);
				},
			});
		}, 250);
	},

	updateTotals(frm) {
		let net = 0;
		let tax = 0;
		(frm.doc.details || []).forEach((row) => {
			net += flt(row.net_amount);
			tax += flt(row.tax_amount);
		});
		frm.set_value("total_net", flt(net, precision("total_net")));
		frm.set_value("total_tax", flt(tax, precision("total_tax")));
		frm.set_value("grand_total", flt(net + tax, precision("grand_total")));
		frm.set_value("total_rows", (frm.doc.details || []).length);
	},

	companyTemplate(frm) {
		frm._eb_templates = frm._eb_templates || {};
		const company = frm.doc.company;
		if (company in frm._eb_templates) return Promise.resolve(frm._eb_templates[company]);

		return frappe
			.xcall("expense_batch.api.get_company_default_template", { company })
			.then((template) => (frm._eb_templates[company] = template || null));
	},

	// ------------------------------------------------------------ buttons

	addButtons(frm) {
		if (frm.is_new() || frm.doc.docstatus === 2) return;

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Bulk edit rows"), () => EB.bulkEdit(frm));
			return;
		}

		const finished = frm.doc.generation_status === "Generated";
		const busy = !!frm.doc.is_processing;

		if (!finished && !busy) {
			frm.add_custom_button(__("Generate Expense Claims"), () => EB.generate(frm)).addClass("btn-primary");
		}
		if (frm.doc.generated_rows) {
			frm.add_custom_button(__("Delete draft claims"), () => EB.undo(frm), __("Actions"));
		}
		frm.add_custom_button(__("Bulk edit rows"), () => EB.bulkEdit(frm), __("Actions"));
	},

	addIndicators(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1) return;
		const generated = frm.doc.generated_rows || 0;
		const total = frm.doc.total_rows || 0;
		const color = frm.doc.is_processing ? "blue" : generated === total && total ? "green" : "orange";
		frm.dashboard.add_indicator(__("{0} of {1} invoices have a claim", [generated, total]), color);
		if (frm.doc.failed_rows) {
			frm.dashboard.add_indicator(__("{0} failed", [frm.doc.failed_rows]), "red");
		}
	},

	generate(frm) {
		if (frm.is_dirty()) {
			frappe.msgprint({
				title: __("Save first"),
				message: __("You have unsaved changes. Click Update, then generate, so the claims match what you see in the Split Map."),
				indicator: "orange",
			});
			return;
		}
		const plan = frm._eb_plan;
		const summary = plan && plan.summary;
		const count = summary ? summary.claims_to_create : null;

		if (summary && summary.invalid_rows) {
			frappe.msgprint({
				title: __("Some invoices need attention"),
				message: __(
					"{0} invoices cannot be turned into claims yet. They are listed in the Split Map and will be marked Failed if you continue.",
					[summary.invalid_rows]
				),
				indicator: "orange",
			});
		}

		const message =
			count === null
				? __("Create the Expense Claims for this batch?")
				: __("Create {0} Expense Claims as drafts?", [count]);

		frappe.confirm(message, () => {
			frappe.call({
				method: "expense_batch.services.generator.generate",
				args: { batch: frm.doc.name },
				freeze: true,
				freeze_message: __("Creating Expense Claims..."),
				callback: (r) => {
					const out = r.message || {};
					if (out.queued) {
						frm._eb_progress = { current: 0, total: out.steps };
						frappe.show_alert({ message: __("Running in the background. You can keep working."), indicator: "blue" }, 6);
						frm.reload_doc();
						return;
					}
					const result = out.result || { created: [], failed: [] };
					frappe.show_alert(
						{
							message: __("Created {0} Expense Claims, {1} failed", [result.created.length, result.failed.length]),
							indicator: result.failed.length ? "orange" : "green",
						},
						8
					);
					frm.reload_doc();
				},
			});
		});
	},

	undo(frm) {
		frappe.confirm(
			__("Delete the Expense Claims of this batch that are still drafts? Submitted claims are not touched."),
			() => {
				frappe.call({
					method: "expense_batch.services.generator.undo_drafts",
					args: { batch: frm.doc.name },
					freeze: true,
					callback: (r) => {
						const out = r.message || { removed: [], kept: [] };
						frappe.show_alert(
							{
								message: __("Deleted {0} draft claims. Kept {1} that are already submitted.", [
									out.removed.length,
									out.kept.length,
								]),
								indicator: "green",
							},
							6
						);
						frm.reload_doc();
					},
				});
			}
		);
	},

	// ------------------------------------------------------------ bulk edit

	bulkEdit(frm) {
		const grid = frm.fields_dict.details.grid;
		const selected = grid.get_selected_children().filter((r) => r.row_status !== "Generated");
		const targets = selected.length
			? selected
			: (frm.doc.details || []).filter((r) => r.row_status !== "Generated");

		if (!targets.length) {
			frappe.show_alert({ message: __("There are no editable rows."), indicator: "orange" });
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Bulk edit {0} rows", [targets.length]),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted small">${
						selected.length
							? __("Applies to the rows you ticked. Empty fields are left as they are.")
							: __("No rows are ticked, so this applies to every open row. Empty fields are left as they are.")
					}</p>`,
				},
				{ fieldname: "employee", fieldtype: "Link", label: __("Employee"), options: "Employee", get_query: () => ({ filters: { company: frm.doc.company, status: "Active" } }) },
				{ fieldname: "expense_date", fieldtype: "Date", label: __("Expense Date") },
				{ fieldname: "expense_type", fieldtype: "Link", label: __("Expense Type"), options: "Expense Claim Type", get_query: () => ({ query: "expense_batch.api.expense_types_for_company", filters: { company: frm.doc.company } }) },
				{ fieldname: "cost_center", fieldtype: "Link", label: __("Cost Center"), options: "Cost Center", get_query: () => ({ filters: { company: frm.doc.company, is_group: 0 } }) },
				{ fieldname: "project", fieldtype: "Link", label: __("Project"), options: "Project", get_query: () => ({ filters: { company: frm.doc.company } }) },
				{ fieldname: "tax", fieldtype: "Select", label: __("Tax"), options: ["", __("Add tax"), __("No tax")].join("\n") },
				{ fieldname: "item_tax_template", fieldtype: "Link", label: __("Item Tax Template"), options: "Item Tax Template", depends_on: `eval:doc.tax==="${__("Add tax")}"`, get_query: () => ({ filters: { company: frm.doc.company, disabled: 0 } }) },
			],
			primary_action_label: __("Apply"),
			primary_action(values) {
				const add_tax = values.tax === __("Add tax");
				const no_tax = values.tax === __("No tax");

				targets.forEach((row) => {
					["employee", "expense_date", "expense_type", "cost_center", "project"].forEach((field) => {
						if (values[field]) frappe.model.set_value(row.doctype, row.name, field, values[field]);
					});
					if (add_tax) {
						frappe.model.set_value(row.doctype, row.name, "has_tax", 1);
						if (values.item_tax_template) {
							frappe.model.set_value(row.doctype, row.name, "item_tax_template", values.item_tax_template);
						}
					} else if (no_tax) {
						frappe.model.set_value(row.doctype, row.name, "has_tax", 0);
					}
				});

				dialog.hide();
				frm.refresh_field("details");
				frappe.show_alert({ message: __("Updated {0} rows. Save to keep the changes.", [targets.length]), indicator: "green" });
			},
		});
		dialog.show();
	},

	// ------------------------------------------------------------ split map

	refreshMap(frm, delay) {
		clearTimeout(frm._eb_timer);
		frm._eb_timer = setTimeout(() => EB.loadPlan(frm), delay || 0);
	},

	loadPlan(frm) {
		if (!frm.get_field("split_map") || frm.doc.docstatus === 2) return;
		if (!frm.doc.company) {
			frm._eb_plan = null;
			return EB.render(frm);
		}

		const token = (frm._eb_token = (frm._eb_token || 0) + 1);
		frappe.call({
			method: "expense_batch.api.get_plan",
			args: { doc: frm.doc },
			callback: (r) => {
				if (token !== frm._eb_token) return; // a newer request is on its way
				frm._eb_plan = r.message;
				EB.render(frm);
			},
		});
	},

	render(frm) {
		const $wrapper = frm.get_field("split_map").$wrapper;
		const plan = frm._eb_plan;
		const esc = frappe.utils.escape_html;
		const money = (value) => format_currency(value || 0, plan && plan.currency);

		if (!plan || !plan.summary || !plan.summary.rows) {
			$wrapper.html(
				`<div class="eb-map"><p class="eb-empty">${esc(
					frm.doc.company
						? __("Add your invoices in the table below. The split appears here as you type.")
						: __("Choose a company, then add your invoices.")
				)}</p></div>`
			);
			return;
		}

		const s = plan.summary;
		const locked = frm.doc.docstatus === 2;
		const open_claims = s.claims_to_create;

		let headline;
		if (!s.open_rows && s.claims_done) headline = __("All invoices have a claim");
		else if (!open_claims) headline = __("No claim can be created yet");
		else headline = __("{0} claims will be created from {1} invoices", [open_claims, s.open_rows - s.invalid_rows]);

		const sub = [];
		if (open_claims) sub.push(__("Total {0}", [money(s.total)]));
		if (s.tax) sub.push(__("including tax {0}", [money(s.tax)]));
		if (s.warnings) sub.push(__("{0} notes to check", [s.warnings]));
		if (s.claims_done) sub.push(__("{0} claims already created", [s.claims_done]));

		const modes = [
			["Each Row", __("One claim per invoice"), __("Every invoice becomes its own claim")],
			["Employee + Date", __("Per employee, per day"), __("Invoices of the same employee on the same day share a claim")],
			["Employee", __("Per employee"), __("One claim for all of an employee's invoices")],
		]
			.map(
				([value, label, hint]) =>
					`<button type="button" role="radio" class="eb-mode${plan.mode === value ? " is-active" : ""}" aria-checked="${
						plan.mode === value
					}" data-mode="${value}" title="${esc(hint)}"${locked ? " disabled" : ""}>${esc(label)}</button>`
			)
			.join("");

		const progress = frm._eb_progress
			? (() => {
					const pct = frm._eb_progress.total ? Math.round((100 * frm._eb_progress.current) / frm._eb_progress.total) : 0;
					return `<div class="eb-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}">
						${esc(__("Creating claims: {0} of {1}", [frm._eb_progress.current, frm._eb_progress.total]))}
						<div class="eb-progress-track"><div class="eb-progress-fill" style="width:${pct}%"></div></div></div>`;
			  })()
			: "";

		$wrapper.html(
			`<div class="eb-map">
				<div class="eb-head">
					<div>
						<p class="eb-headline">${esc(headline)}</p>
						<p class="eb-subline">${esc(sub.join("  |  "))}</p>
					</div>
					<div class="eb-modes" role="radiogroup" aria-label="${esc(__("Split mode"))}">${modes}</div>
				</div>
				${progress}
				${EB.bar(plan, esc, money)}
				${EB.attention(plan, esc)}
				${EB.tickets(plan, esc, money)}
				${EB.done(plan, esc, money)}
			</div>`
		);

		EB.bind(frm, $wrapper);
	},

	bar(plan, esc, money) {
		const segments = [];
		const share = (value) => Math.max(flt(value), 0.0001);

		(plan.done || []).forEach((c) => {
			segments.push({ kind: "done", weight: share(c.grand_total), target: c.claim, title: `${c.claim}  ${money(c.grand_total)}` });
		});
		(plan.groups || []).forEach((g) => {
			segments.push({ kind: g.state === "warn" ? "warn" : "ready", weight: share(g.total), target: g.id, title: `${g.employee_name}  ${money(g.total)}` });
		});
		const blocked = (plan.invalid || []).reduce((sum, r) => sum + flt(r.amount), 0);
		if (blocked) {
			segments.push({ kind: "blocked", weight: share(blocked), target: "attention", title: __("{0} invoices need attention", [plan.invalid.length]) });
		}
		if (!segments.length) return "";

		const counts = {
			done: (plan.done || []).length,
			ready: (plan.groups || []).filter((g) => g.state === "ready").length,
			warn: (plan.groups || []).filter((g) => g.state === "warn").length,
			blocked: (plan.invalid || []).length,
		};
		const legend = [
			["done", __("Claim exists"), counts.done],
			["ready", __("Ready"), counts.ready],
			["warn", __("Check the note"), counts.warn],
			["blocked", __("Needs a fix"), counts.blocked],
		]
			.filter((item) => item[2])
			.map(([kind, label, n]) => `<li><span class="eb-dot eb-dot--${kind}"></span>${esc(label)} (${n})</li>`)
			.join("");

		return `<div class="eb-bar" role="img" aria-label="${esc(__("The batch divided into claims, sized by amount"))}">${segments
			.map(
				(s) =>
					`<button type="button" class="eb-seg eb-seg--${s.kind}" style="flex-grow:${s.weight}" data-target="${esc(
						s.target
					)}" title="${esc(s.title)}" aria-label="${esc(s.title)}"></button>`
			)
			.join("")}</div><ul class="eb-legend">${legend}</ul>`;
	},

	attention(plan, esc) {
		if (!(plan.invalid || []).length) return "";
		const items = plan.invalid
			.map((row) => {
				const messages = row.issues
					.filter((i) => i.level === "error")
					.map((i) => `<li class="is-error"><span>${esc(i.msg)}</span></li>`)
					.join("");
				return `<li><button type="button" class="eb-link" data-jump="${row.idx}">${esc(__("Row {0}", [row.idx]))}</button>
					${esc(row.reference || row.expense_type || "")}<ul class="eb-issues">${messages}</ul></li>`;
			})
			.join("");
		return `<div id="eb-attention" class="eb-ticket eb-ticket--blocked">
			<div class="eb-body" style="border:0;padding-top:10px"><strong>${esc(__("Fix these invoices first"))}</strong>
			<ul class="eb-issues" style="margin-top:6px">${items}</ul></div></div>`;
	},

	tickets(plan, esc, money) {
		if (!(plan.groups || []).length) return "";

		const date = (value) => (value ? frappe.datetime.str_to_user(value) : "");
		const body = plan.groups
			.map((g) => {
				const when = g.date_from === g.date_to ? date(g.date_from) : `${date(g.date_from)} - ${date(g.date_to)}`;
				const meta = [
					when,
					g.rows.length === 1 ? __("1 invoice") : __("{0} invoices", [g.rows.length]),
					g.payable_account,
				].filter(Boolean);

				const rows = g.rows
					.map(
						(r) => `<tr>
							<td><button type="button" class="eb-link" data-jump="${r.idx}">${r.idx}</button></td>
							<td>${esc(date(r.date))}</td>
							<td>${esc([r.reference, r.expense_type].filter(Boolean).join("  "))}</td>
							<td class="eb-num">${esc(money(r.net))}</td>
							<td class="eb-num">${r.tax ? esc(money(r.tax)) : ""}</td>
						</tr>`
					)
					.join("");

				const notes = g.issues.length
					? `<ul class="eb-issues">${g.issues
							.map((i) => `<li class="is-${i.level === "error" ? "error" : "warn"}"><span>${esc(__("Row {0}", [i.row]))}: ${esc(i.msg)}</span></li>`)
							.join("")}</ul>`
					: "";

				const tax = (g.tax_rows || [])
					.map((t) => `${esc(t.description)} ${esc(money(t.tax_amount))}`)
					.join("  |  ");

				return `<details class="eb-ticket eb-ticket--${g.state}" id="eb-${g.id}" data-id="${g.id}"${g.issues.length ? " open" : ""}>
					<summary>
						<span class="eb-who">${esc(g.employee_name)}</span>
						<span class="eb-meta">${esc(meta.join("  |  "))}</span>
						<span class="eb-sum"><strong>${esc(money(g.total))}</strong>${g.tax ? `<small>${esc(__("tax {0}", [money(g.tax)]))}</small>` : ""}</span>
					</summary>
					<div class="eb-body">
						<table class="eb-rows"><thead><tr><th>#</th><th>${esc(__("Date"))}</th><th>${esc(__("Invoice"))}</th><th class="eb-num">${esc(__("Amount"))}</th><th class="eb-num">${esc(__("Tax"))}</th></tr></thead><tbody>${rows}</tbody></table>
						${tax ? `<p class="eb-meta" style="margin:8px 0 0">${tax}</p>` : ""}
						${notes}
					</div>
				</details>`;
			})
			.join("");

		return `<p class="eb-section-title">${esc(__("Claims that will be created"))}</p>${body}`;
	},

	done(plan, esc, money) {
		if (!(plan.done || []).length) return "";
		const state = { 0: [__("Draft"), ""], 1: [__("Submitted"), "submitted"], 2: [__("Cancelled"), "cancelled"] };

		const items = plan.done
			.map((c) => {
				const [label, css] = state[c.docstatus] || state[0];
				return `<details class="eb-ticket eb-ticket--done" id="eb-${esc(c.claim)}">
					<summary>
						<span class="eb-who"><a href="/app/expense-claim/${encodeURIComponent(c.claim)}">${esc(c.claim)}</a></span>
						<span class="eb-meta">${esc(c.employee_name || "")}  <span class="eb-state eb-state--${css}">${esc(label)}</span></span>
						<span class="eb-sum"><strong>${esc(money(c.grand_total))}</strong></span>
					</summary>
					<div class="eb-body"><table class="eb-rows"><tbody>${c.rows
						.map((r) => `<tr><td>${r.idx}</td><td>${esc(r.reference || r.expense_type || "")}</td><td class="eb-num">${esc(money(r.amount))}</td></tr>`)
						.join("")}</tbody></table></div>
				</details>`;
			})
			.join("");

		return `<p class="eb-section-title">${esc(__("Claims already created"))}</p>${items}`;
	},

	bind(frm, $wrapper) {
		$wrapper.find(".eb-mode").on("click", function () {
			if (frm.doc.docstatus === 2) return;
			frm.set_value("split_mode", $(this).data("mode"));
		});

		$wrapper.find(".eb-seg").on("click", function () {
			const target = $(this).attr("data-target");
			const $ticket = $wrapper.find(`[id="eb-${target}"]`).first();
			if (!$ticket.length) return;
			$ticket.attr("open", true);
			frappe.utils.scroll_to($ticket, true, 120);
			$wrapper.find(".is-lit").removeClass("is-lit");
			$ticket.addClass("is-lit");
			setTimeout(() => $ticket.removeClass("is-lit"), 1600);
		});

		$wrapper.find("[data-jump]").on("click", function (event) {
			event.preventDefault();
			event.stopPropagation();
			const grid = frm.fields_dict.details.grid;
			const grid_row = grid.grid_rows[parseInt($(this).attr("data-jump"), 10) - 1];
			if (!grid_row) return;
			try {
				grid_row.toggle_view(true);
				frappe.utils.scroll_to(grid_row.row, true, 120);
			} catch (e) {
				frm.scroll_to_field("details");
			}
		});
	},
};

})();
