from __future__ import annotations

import io

from app.extensions import db
from app.models import Customer, CustomerNote, ServiceOption, StaffMember


def _login_as_admin(client, admin_user):
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )


def _csv_file(headers: list[str], values: list[str], filename: str):
    csv_body = ",".join(headers) + "\n" + ",".join('"' + value.replace('"', '""') + '"' for value in values) + "\n"
    return {"file": (io.BytesIO(csv_body.encode("utf-8")), filename)}


def test_customer_and_staff_pages_render_import_triggers(client, admin_user, app):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
    )
    _login_as_admin(client, admin_user)

    customer_response = client.get("/admin/customers")
    assert customer_response.status_code == 200
    customer_body = customer_response.get_data(as_text=True)
    assert 'data-import-open="customer-import-modal"' in customer_body
    assert 'id="customer-import-modal"' in customer_body
    assert "/admin/imports/customers/template.csv" in customer_body

    staff_response = client.get("/admin/staff")
    assert staff_response.status_code == 200
    staff_body = staff_response.get_data(as_text=True)
    assert 'data-import-open="staff-import-modal"' in staff_body
    assert 'id="staff-import-modal"' in staff_body
    assert "/admin/imports/staff/template.csv" in staff_body


def test_customer_import_template_preview_and_commit_creates_customer(client, admin_user, app):
    app.config.update(ENABLE_CUSTOMER_RECORDS=True)
    _login_as_admin(client, admin_user)

    template_response = client.get("/admin/imports/customers/template.csv")
    assert template_response.status_code == 200
    template_body = template_response.get_data().decode("utf-8-sig")
    header_line = template_body.splitlines()[0]
    headers = header_line.split(",")
    assert headers == ["name", "phone", "email", "city", "notes", "billing_frequency", "billing_amount"]

    preview_response = client.post(
        "/admin/imports/customers/preview",
        data=_csv_file(
            headers,
            [
                "Morgan Client",
                "555-222-3333",
                "morgan@example.com",
                "Springfield",
                "Prefers afternoon visits",
                "monthly",
                "125.50",
            ],
            "customers.csv",
        ),
        content_type="multipart/form-data",
    )
    assert preview_response.status_code == 200
    preview_payload = preview_response.get_json()
    assert preview_payload["ok"] is True
    assert preview_payload["summary"]["totalRows"] == 1
    assert preview_payload["summary"]["readyRows"] == 1

    row = preview_payload["rows"][0]
    commit_response = client.post(
        "/admin/imports/customers/commit",
        json={
            "rows": [
                {
                    "rowNumber": row["rowNumber"],
                    "values": row["values"],
                    "action": "create",
                }
            ]
        },
    )
    assert commit_response.status_code == 200
    commit_payload = commit_response.get_json()
    assert commit_payload["ok"] is True
    assert commit_payload["summary"]["importedCount"] == 1
    assert commit_payload["summary"]["mergedCount"] == 0
    assert commit_payload["summary"]["skippedCount"] == 0

    with app.app_context():
        customer = Customer.query.filter_by(primary_email="morgan@example.com").one()
        assert customer.primary_name == "Morgan Client"
        assert customer.primary_phone == "555-222-3333"
        assert customer.primary_city == "Springfield"
        assert str(customer.billing_amount) == "125.50"
        assert customer.billing_frequency == "monthly"
        assert CustomerNote.query.filter_by(customer_id=customer.id).one().note_text == "Prefers afternoon visits"


def test_staff_import_review_and_commit_can_merge_existing_staff(client, admin_user, app):
    app.config.update(ENABLE_SERVICES=True, ENABLE_SCHEDULING=True, ENABLE_STAFF_MANAGEMENT=True)
    _login_as_admin(client, admin_user)

    with app.app_context():
        existing_service = ServiceOption.query.filter_by(name="Inspection").one()
        merge_target = StaffMember(
            display_name="Jamie Rivera",
            email="jamie@example.com",
            phone="555-101-2020",
            worker_type="employee",
            status="active",
            notes="Existing note",
            services=[existing_service],
        )
        db.session.add(merge_target)
        db.session.commit()
        merge_target_id = merge_target.id

    headers = ["name", "phone", "email", "services", "availability_notes"]
    preview_response = client.post(
        "/admin/imports/staff/preview",
        data=_csv_file(
            headers,
            [
                "Jamie Rivera",
                "555-101-2020",
                "jamie@example.com",
                "Inspection, Painting",
                "Available for weekend overflow",
            ],
            "staff.csv",
        ),
        content_type="multipart/form-data",
    )
    assert preview_response.status_code == 200
    preview_payload = preview_response.get_json()
    assert preview_payload["ok"] is True
    assert preview_payload["summary"]["duplicateRows"] == 1
    assert preview_payload["rows"][0]["duplicateCandidates"][0]["id"] == merge_target_id

    review_response = client.post(
        "/admin/imports/staff/review",
        json={
            "rows": [
                {
                    "rowNumber": preview_payload["rows"][0]["rowNumber"],
                    "values": preview_payload["rows"][0]["values"],
                }
            ]
        },
    )
    assert review_response.status_code == 200
    review_payload = review_response.get_json()
    assert review_payload["ok"] is True
    assert review_payload["rows"][0]["duplicateCandidates"][0]["id"] == merge_target_id

    commit_response = client.post(
        "/admin/imports/staff/commit",
        json={
            "rows": [
                {
                    "rowNumber": review_payload["rows"][0]["rowNumber"],
                    "values": review_payload["rows"][0]["values"],
                    "action": "merge",
                    "mergeTargetId": merge_target_id,
                }
            ]
        },
    )
    assert commit_response.status_code == 200
    commit_payload = commit_response.get_json()
    assert commit_payload["ok"] is True
    assert commit_payload["summary"]["mergedCount"] == 1
    assert commit_payload["summary"]["importedCount"] == 0
    assert commit_payload["summary"]["unresolvedIssueCount"] == 0

    with app.app_context():
        staff_member = db.session.get(StaffMember, merge_target_id)
        assert staff_member is not None
        assert staff_member.display_name == "Jamie Rivera"
        assert staff_member.notes == "Existing note\n\nAvailable for weekend overflow"
        assert [service.name for service in staff_member.services] == ["Inspection", "Painting"]