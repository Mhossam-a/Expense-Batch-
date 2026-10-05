frappe.listview_settings["Expense Claim Batch"] = {
	add_fields: ["generation_status", "docstatus", "total_rows", "generated_rows"],
	get_indicator(doc) {
		if (doc.docstatus === 0) return [__("Draft"), "red", "docstatus,=,0"];
		if (doc.docstatus === 2) return [__("Cancelled"), "gray", "docstatus,=,2"];

		const by_status = {
			Pending: [__("Not generated"), "orange"],
			Processing: [__("Generating"), "blue"],
			"Partly Generated": [__("{0} of {1} generated", [doc.generated_rows, doc.total_rows]), "yellow"],
			Generated: [__("Generated"), "green"],
			Failed: [__("Failed"), "red"],
		};
		const [label, color] = by_status[doc.generation_status] || by_status.Pending;
		return [label, color, `generation_status,=,${doc.generation_status}`];
	},
};
