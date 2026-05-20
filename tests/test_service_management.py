from __future__ import annotations

from app.extensions import db
from app.models import QuoteRequest, ServiceOption


def _login_as_admin(client, admin_user):
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )


def test_dashboard_omits_settings_section(client, app, admin_user):
    app.config["ENABLE_SERVICES"] = True
    _login_as_admin(client, admin_user)

    response = client.get("/admin/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Manage operational lists that drive public intake and internal scheduling." not in body
    assert "Manage Services" not in body

    response = client.get("/admin/settings/services")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Add service" in body
    assert "Service catalog" in body


def test_admin_can_create_update_archive_and_reactivate_services(client, app, admin_user):
    app.config["ENABLE_SERVICES"] = True
    _login_as_admin(client, admin_user)

    create_response = client.post(
        "/admin/settings/services",
        data={
            "service-create-name": "Gutter Cleaning",
            "service-create-description": "Seasonal gutter clearing and debris removal.",
            "service-create-display_order": "2",
            "service-create-submit": "Add Service",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 302

    with app.app_context():
        service = ServiceOption.query.filter_by(name="Gutter Cleaning").one()
        assert service.description == "Seasonal gutter clearing and debris removal."
        assert service.display_order == 2
        assert service.is_active is True
        service_id = service.id

    response = client.get("/quote-request")
    assert response.status_code == 200
    assert "Gutter Cleaning" in response.get_data(as_text=True)

    update_response = client.post(
        f"/admin/settings/services/{service_id}",
        data={
            f"service-{service_id}-name": "Seasonal Gutter Cleaning",
            f"service-{service_id}-description": "Spring and fall gutter service.",
            f"service-{service_id}-display_order": "1",
            f"service-{service_id}-submit": "Save Changes",
        },
        follow_redirects=False,
    )
    assert update_response.status_code == 302

    with app.app_context():
        service = db.session.get(ServiceOption, service_id)
        assert service is not None
        assert service.name == "Seasonal Gutter Cleaning"
        assert service.description == "Spring and fall gutter service."
        assert service.display_order == 1

    archive_response = client.post(
        f"/admin/settings/services/{service_id}/status",
        data={},
        follow_redirects=False,
    )
    assert archive_response.status_code == 302

    with app.app_context():
        service = db.session.get(ServiceOption, service_id)
        assert service is not None
        assert service.is_active is False

    response = client.get("/quote-request")
    assert response.status_code == 200
    assert "Seasonal Gutter Cleaning" not in response.get_data(as_text=True)

    reactivate_response = client.post(
        f"/admin/settings/services/{service_id}/status",
        data={},
        follow_redirects=False,
    )
    assert reactivate_response.status_code == 302

    with app.app_context():
        service = db.session.get(ServiceOption, service_id)
        assert service is not None
        assert service.is_active is True

    response = client.get("/quote-request")
    assert response.status_code == 200
    assert "Seasonal Gutter Cleaning" in response.get_data(as_text=True)


def test_archived_services_are_hidden_from_public_forms_but_remain_on_request_history(client, app, admin_user):
    app.config["ENABLE_SERVICES"] = True
    with app.app_context():
        service = ServiceOption.query.filter_by(name="Painting").one()
        quote_request = QuoteRequest(
            full_name="Morgan Client",
            phone="555-888-1212",
            email="morgan@example.com",
            city="Testville",
            services=[service],
        )
        db.session.add(quote_request)
        db.session.flush()
        request_id = quote_request.id
        service.is_active = False
        db.session.commit()

    public_response = client.get("/quote-request")
    assert public_response.status_code == 200
    public_body = public_response.get_data(as_text=True)
    assert "Painting" not in public_body

    services_response = client.get("/services")
    assert services_response.status_code == 200
    assert "Painting" not in services_response.get_data(as_text=True)

    _login_as_admin(client, admin_user)
    history_response = client.get(f"/admin/requests/{request_id}")
    assert history_response.status_code == 200
    assert "Painting" in history_response.get_data(as_text=True)


def test_quote_request_submission_rejects_archived_service_choice(client, app):
    app.config["ENABLE_SERVICES"] = True
    with app.app_context():
        service = ServiceOption.query.filter_by(name="Inspection").one()
        service.is_active = False
        db.session.commit()

    response = client.post(
        "/quote-request",
        data={
            "full_name": "Jordan Harper",
            "phone": "555-333-2222",
            "services": ["Inspection"],
            "city": "14 Maple Ln",
        },
        follow_redirects=False,
    )

    assert response.status_code == 200

    with app.app_context():
        assert QuoteRequest.query.count() == 0


def test_services_feature_flag_hides_public_and_admin_service_surfaces(client, app, admin_user):
    app.config["ENABLE_SERVICES"] = False

    public_response = client.get("/quote-request")
    assert public_response.status_code == 200
    public_body = public_response.get_data(as_text=True)
    assert '<span>Services</span>' not in public_body
    assert 'href="/services"' not in public_body

    services_response = client.get("/services")
    assert services_response.status_code == 404

    _login_as_admin(client, admin_user)
    dashboard_response = client.get("/admin/")
    assert dashboard_response.status_code == 200
    dashboard_body = dashboard_response.get_data(as_text=True)
    assert 'href="/admin/settings/services"' not in dashboard_body

    service_settings_response = client.get("/admin/settings/services")
    assert service_settings_response.status_code == 404