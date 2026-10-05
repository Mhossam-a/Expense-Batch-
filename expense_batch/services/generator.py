"""Creates the Expense Claims of a submitted Expense Claim Batch.

Runs inline for small batches and as a background job for large ones; either
way it publishes `expense_batch_progress` so the form can show a live bar. Every
claim is created inside its own savepoint, so one bad claim never blocks or
corrupts the others.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, strip_html

from expense_batch.services import payable
from expense_batch.services.splitter import build_plan

DETAIL = "Expense Claim Batch Detail"
PARENT = "Expense Claim Batch"
STALE_MINUTES = 45


# ---------------------------------------------------------------- entry points


@frappe.whitelist()
def generate(batch):
	"""Whitelisted entry: validates, then runs inline or queues a background job."""
	doc = frappe.get_doc(PARENT, batch)
	doc.check_permission("write")
	frappe.has_permission("Expense Claim", "create", throw=True)

	if doc.docstatus != 1:
		frappe.throw(_("Submit the batch before generating Expense Claims."))
	if _is_busy(doc):
		frappe.throw(_("This batch is already being processed. Please wait for it to finish."))

	settings = payable.get_settings()
	plan = build_plan(doc, settings)
	steps = plan["summary"]["claims_to_create"] + plan["summary"]["invalid_rows"]
	if not steps:
		frappe.throw(_("There is nothing left to generate in this batch."))

	frappe.db.set_value(
		PARENT,
		doc.name,
		{"is_processing": 1, "processing_since": now_datetime(), "generation_status": "Processing"},
		update_modified=False,
	)

	threshold = cint(settings.background_threshold) or 15
	if steps > threshold:
		frappe.enqueue(
			"expense_batch.services.generator.run_generation",
			queue="long",
			timeout=3600,
			batch=doc.name,
			user=frappe.session.user,
			enqueue_after_commit=True,
		)
		return {"queued": True, "steps": steps}

	result = run_generation(doc.name, frappe.session.user)
	return {"queued": False, "steps": steps, "result": result}


def run_generation(batch, user=None):
	user = user or frappe.session.user
	result = {"created": [], "failed": []}
	frappe.clear_messages()

	try:
		doc = frappe.get_doc(PARENT, batch)
		plan = build_plan(doc, payable.get_settings())
		total = len(plan["groups"]) + len(plan["invalid"])

		# rows that cannot be generated are reported, not silently skipped
		for row in plan["invalid"]:
			message = "; ".join(i["msg"] for i in row["issues"] if i["level"] == "error")
			_fail_rows([row["name"]], message)
			result["failed"].append({"rows": [row["idx"]], "error": message})
		frappe.db.commit()

		done_steps = len(plan["invalid"])
		_publish(user, batch, done_steps, total)

		for group in plan["groups"]:
			frappe.db.savepoint("eb_group")
			try:
				claim = _create_claim(doc, group)
				_link_rows(group["row_names"], claim.name)
				frappe.db.commit()
				result["created"].append(claim.name)
			except Exception as exc:
				frappe.db.rollback(save_point="eb_group")
				frappe.clear_messages()
				message = _clean(exc)
				frappe.log_error(title=f"Expense Batch {batch}", message=frappe.get_traceback())
				_fail_rows(group["row_names"], message)
				frappe.db.commit()
				result["failed"].append({"rows": [r["idx"] for r in group["rows"]], "error": message})

			done_steps += 1
			_publish(user, batch, done_steps, total, claim=result["created"][-1] if result["created"] else None)
	finally:
		refresh_summary(batch, processing_done=True)
		frappe.db.commit()
		frappe.publish_realtime(
			"expense_batch_progress",
			{"batch": batch, "finished": True, "created": len(result["created"]), "failed": len(result["failed"])},
			user=user,
		)
	return result


# ---------------------------------------------------------------- claim creation


def _create_claim(batch, group):
	claim = frappe.new_doc("Expense Claim")
	claim.employee = group["employee"]
	claim.company = batch.company
	claim.posting_date = group["posting_date"]
	claim.payable_account = group["payable_account"]
	if group["payable_source"] == "type":
		# derived from the expense type: later edits of the lines may re-derive it
		claim.auto_payable_account = group["payable_account"]
	else:
		# chosen on the batch (or the company): keep it whatever the lines say
		claim.payable_account_pinned = 1
	claim.expense_batch = batch.name
	claim.remark = _remark(batch, group)

	for row in group["rows"]:
		claim.append(
			"expenses",
			{
				"expense_date": row["date"],
				"expense_type": row["expense_type"],
				"description": _line_description(row),
				"amount": row["net"],
				"sanctioned_amount": row["net"],
				"cost_center": row["cost_center"],
				"project": row["project"],
				"has_tax": 1 if row.get("template") else 0,
				"item_tax_template": row.get("template"),
			},
		)

	claim.insert()

	for row in group["rows"]:
		if row["attachment"]:
			_attach(row["attachment"], claim.doctype, claim.name)
	return claim


def _remark(batch, group):
	refs = [r["reference"] for r in group["rows"] if r["reference"]]
	text = _("Generated from {0}").format(batch.name)
	return f"{text}: {', '.join(refs)}" if refs else text


def _line_description(row):
	parts = [row.get("reference"), row.get("description")]
	return " - ".join(p for p in parts if p) or None


def _attach(file_url, doctype, name):
	"""Attach the invoice file to the new claim.

	The new File record points at the same stored file, so nothing is uploaded or
	duplicated on disk. If Frappe refuses that, fall back to an independent copy.
	"""
	source = frappe.db.get_value(
		"File", {"file_url": file_url}, ["name", "file_name"], as_dict=True, order_by="creation asc"
	)
	file_name = (source.file_name if source else None) or file_url.rsplit("/", 1)[-1]
	values = {
		"doctype": "File",
		"file_name": file_name,
		"is_private": cint(file_url.startswith("/private")),
		"attached_to_doctype": doctype,
		"attached_to_name": name,
	}

	try:
		frappe.db.savepoint("eb_attach")
		linked = frappe.get_doc({**values, "file_url": file_url})
		linked.flags.ignore_permissions = True
		linked.insert()
	except Exception:
		frappe.db.rollback(save_point="eb_attach")
		if not source:
			raise
		content = frappe.get_doc("File", source.name).get_content()
		copy = frappe.get_doc({**values, "content": content})
		copy.flags.ignore_permissions = True
		copy.insert()


# ---------------------------------------------------------------- status bookkeeping


def _link_rows(row_names, claim):
	for name in row_names:
		frappe.db.set_value(
			DETAIL,
			name,
			{"row_status": "Generated", "generated_claim": claim, "error_message": ""},
			update_modified=False,
		)


def _fail_rows(row_names, message):
	for name in row_names:
		frappe.db.set_value(
			DETAIL,
			name,
			{"row_status": "Failed", "error_message": (message or "")[:1000]},
			update_modified=False,
		)


def refresh_summary(batch, processing_done=False):
	rows = frappe.get_all(
		DETAIL, filters={"parent": batch, "parenttype": PARENT}, fields=["row_status"]
	)
	total = len(rows)
	generated = sum(1 for r in rows if r.row_status == "Generated")
	failed = sum(1 for r in rows if r.row_status == "Failed")

	if total and generated == total:
		status = "Generated"
	elif generated:
		status = "Partly Generated"
	elif failed:
		status = "Failed"
	else:
		status = "Pending"

	values = {
		"total_rows": total,
		"generated_rows": generated,
		"failed_rows": failed,
		"generation_status": status,
	}
	if processing_done:
		values.update({"is_processing": 0, "processing_since": None})
	frappe.db.set_value(PARENT, batch, values, update_modified=False)
	return status


def reset_rows_for_claim(claim, new_status="Pending", keep_link=False, note=None):
	"""Called when a generated Expense Claim is deleted or cancelled."""
	rows = frappe.get_all(DETAIL, filters={"generated_claim": claim}, fields=["name", "parent"])
	batches = set()
	for row in rows:
		values = {"row_status": new_status, "error_message": note or ""}
		if not keep_link:
			values["generated_claim"] = None
		frappe.db.set_value(DETAIL, row.name, values, update_modified=False)
		batches.add(row.parent)
	for batch in batches:
		refresh_summary(batch)


@frappe.whitelist()
def undo_drafts(batch):
	"""Delete the still-Draft claims of a batch and put their rows back to Pending."""
	doc = frappe.get_doc(PARENT, batch)
	doc.check_permission("write")
	if not frappe.has_permission("Expense Claim", "delete"):
		frappe.throw(_("You need permission to delete Expense Claims to undo a generation."), frappe.PermissionError)
	if _is_busy(doc):
		frappe.throw(_("This batch is being processed right now."))

	claims = {
		r.generated_claim
		for r in frappe.get_all(
			DETAIL,
			filters={"parent": batch, "parenttype": PARENT, "row_status": "Generated"},
			fields=["generated_claim"],
		)
		if r.generated_claim
	}

	removed, kept = [], []
	for claim in sorted(claims):
		if frappe.db.get_value("Expense Claim", claim, "docstatus") == 0:
			frappe.delete_doc("Expense Claim", claim)
			removed.append(claim)
		else:
			kept.append(claim)

	refresh_summary(batch)
	return {"removed": removed, "kept": kept}


# ---------------------------------------------------------------- helpers


def _is_busy(doc):
	if not cint(doc.get("is_processing")):
		return False
	since = doc.get("processing_since")
	if not since:
		return False
	return (now_datetime() - frappe.utils.get_datetime(since)).total_seconds() < STALE_MINUTES * 60


def _publish(user, batch, current, total, claim=None):
	frappe.publish_realtime(
		"expense_batch_progress",
		{"batch": batch, "current": current, "total": total, "claim": claim, "finished": False},
		user=user,
	)


def _clean(exc):
	text = strip_html(frappe.as_unicode(str(exc))).strip()
	return text or exc.__class__.__name__
