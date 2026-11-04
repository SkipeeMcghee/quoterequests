"""Regression tests for the four issues found in the pre-deployment audit.

Each test here failed (or would have failed) before the fix, and is written against the
behaviour a customer deployment depends on rather than implementation detail.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.extensions import db
from app.models import (
    Appointment,
    Customer,
    CustomerAddress,
    CustomerField,
    CustomerNote,
    CustomerPhoto,
    QuoteRequest,
    RecurringWork,
    RequestQuote,
    ServiceOption,
    User,
)
from app.services.admin_requests import merge_customers


def sign_in(client, app, email="admin@example.com"):
    with app.app_context():
        user_id = User.query.filter_by(email=email).first().id
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_a_disabled_account_cannot_keep_using_its_session(client, app, admin_user):
    sign_in(client, app, admin_user)
    assert client.get("/admin/").status_code == 200

    # The app fixture keeps a context (and therefore a session) open for the whole test,
    # so expire it explicitly rather than relying on a separate session seeing the change.
    user = User.query.filter_by(email=admin_user).first()
    user.is_active = False
    db.session.commit()
    db.session.expire_all()

    response = client.get("/admin/", follow_redirects=False)

    assert response.status_code == 302
    assert "/admin" in response.headers["Location"]
    assert client.get("/admin/customers", follow_redirects=False).status_code == 302


def test_a_crafted_post_cannot_reach_a_disabled_module(client, app, admin_user):
    app.config.update(ENABLE_SCHEDULING=False, ENABLE_STAFF_MANAGEMENT=False)
    sign_in(client, app, admin_user)

    with app.app_context():
        db.session.add(Customer(primary_name="Probe", primary_city="Daytona"))
        db.session.commit()
        before = Appointment.query.count()

    response = client.post(
        "/admin/scheduled-work/new",
        data={
            "scheduled-work-customer_id": "1",
            "scheduled-work-title": "Should never exist",
            "scheduled-work-scheduled_date": date.today().isoformat(),
            "scheduled-work-start_time_hour": "9",
            "scheduled-work-start_time_minute": "0",
            "scheduled-work-end_time_hour": "10",
            "scheduled-work-end_time_minute": "0",
        },
        follow_redirects=False,
    )

    assert response.status_code in (302, 404)
    with app.app_context():
        assert Appointment.query.count() == before
        assert Appointment.query.filter_by(title="Should never exist").first() is None


def test_public_pages_of_disabled_modules_are_not_served(client, app):
    app.config.update(ENABLE_SERVICES=False, ENABLE_GALLERY=False, ENABLE_SCHEDULING=False)

    assert client.get("/services").status_code == 404
    assert client.get("/gallery").status_code == 404
    assert client.get("/schedule-work", follow_redirects=False).status_code == 302


def test_a_zero_amount_quote_is_not_accepted(client, app, admin_user):
    app.config.update(ENABLE_CUSTOMER_RECORDS=True)
    sign_in(client, app, admin_user)

    with app.app_context():
        quote_request = QuoteRequest(request_number=0, full_name="Zero", city="Daytona")
        db.session.add(quote_request)
        db.session.commit()
        request_id = quote_request.id

    client.post(
        f"/admin/requests/{request_id}/quotes",
        data={"request-quote-amount": "0", "request-quote-billing_frequency": "Monthly"},
    )

    with app.app_context():
        assert RequestQuote.query.count() == 0


def test_merging_customers_keeps_every_customer_owned_record(app):
    """Photos and recurring plans cascade-delete with the customer, appointments null out."""

    with app.app_context():
        user = User.query.first()
        if user is None:
            user = User(email="merge@example.test")
            user.set_password("merge-pass-1")
            db.session.add(user)
            db.session.commit()
        source = Customer(primary_name="Source", primary_city="Daytona Beach")
        target = Customer(primary_name="Target", primary_city="Daytona Beach")
        db.session.add_all([source, target])
        db.session.flush()

        with db.session.no_autoflush:
            db.session.add_all(
                [
                    CustomerField(customer=source, kind="email", value="s@example.test", is_primary=True),
                    CustomerAddress(customer=source, address_line_1="1 Test Street"),
                    CustomerNote(customer=source, note_text="keep me", created_by=user.id),
                    CustomerPhoto(customer=source, file_path="uploads/customers/1/p.jpg"),
                ]
            )
        plan = RecurringWork(
            customer=source,
            title="Monthly clean",
            frequency="monthly",
            day_of_month=1,
            starts_on=date.today(),
        )
        appointment = Appointment(customer=source, scheduled_date=date.today(), status="Scheduled")
        quote_request = QuoteRequest(request_number=0, full_name="Source", city="Daytona")
        quote_request.customer = source
        db.session.add_all([plan, appointment, quote_request])
        db.session.commit()

        source_id, target_id = source.id, target.id
        plan_id, appointment_id, quote_request_id = plan.id, appointment.id, quote_request.id
        photo_id = CustomerPhoto.query.one().id
        field_id = CustomerField.query.one().id
        note_id = CustomerNote.query.one().id
        address_id = CustomerAddress.query.one().id

        merge_customers(source_id, target_id)
        db.session.expire_all()

        assert db.session.get(Customer, source_id) is None
        assert db.session.get(CustomerPhoto, photo_id).customer_id == target_id
        assert db.session.get(RecurringWork, plan_id).customer_id == target_id
        assert db.session.get(Appointment, appointment_id).customer_id == target_id
        assert db.session.get(QuoteRequest, quote_request_id).customer_id == target_id
        assert db.session.get(CustomerField, field_id).customer_id == target_id
        assert db.session.get(CustomerNote, note_id).customer_id == target_id
        assert db.session.get(CustomerAddress, address_id).customer_id == target_id


def test_merging_customers_keeps_service_links_on_the_moved_request(app):
    with app.app_context():
        source = Customer(primary_name="Source", primary_city="Daytona Beach")
        target = Customer(primary_name="Target", primary_city="Daytona Beach")
        service = ServiceOption.query.first()
        db.session.add_all([source, target])
        db.session.flush()

        quote_request = QuoteRequest(request_number=0, full_name="Source", city="Daytona")
        quote_request.customer = source
        quote_request.services.append(service)
        db.session.add(quote_request)
        db.session.commit()

        request_id = quote_request.id
        source_id, target_id = source.id, target.id

        merge_customers(source_id, target_id)
        db.session.expire_all()

        moved = db.session.get(QuoteRequest, request_id)
        assert moved.customer_id == target_id
        assert [item.id for item in moved.services] == [service.id]
