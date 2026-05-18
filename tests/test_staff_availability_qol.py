from __future__ import annotations

from app.extensions import db
from app.models import StaffMember


def _login_as_admin(client, admin_user):
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )


def test_staff_detail_renders_day_copy_controls(client, admin_user, app):
    app.config.update(ENABLE_SCHEDULING=True, ENABLE_STAFF_MANAGEMENT=True)

    with app.app_context():
        staff_member = StaffMember(
            display_name="Jamie Rivera",
            email="jamie@example.com",
            worker_type="employee",
            status="active",
        )
        db.session.add(staff_member)
        db.session.commit()
        staff_member_id = staff_member.id

    _login_as_admin(client, admin_user)
    response = client.get(f"/admin/staff/{staff_member_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-availability-copy-to-next="0"' in body
    assert 'data-availability-copy-from-previous="1"' in body
    assert 'data-availability-copy-from-previous="0"' in body
    assert 'data-availability-copy-to-next="6"' in body
    assert 'title="Copy Sunday availability to Monday"' in body
    assert 'title="Copy Sunday availability to Monday" disabled' not in body
    assert 'title="Copy Saturday availability to Sunday" disabled' not in body