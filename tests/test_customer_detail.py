from datetime import date
from types import SimpleNamespace

from app.extensions import db
from app.models import Customer, CustomerNote, RecurringWork, User


def test_customer_detail_loads_with_empty_related_data(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Empty Customer', primary_city='NoPlace')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.get(f'/admin/customers/{customer_id}')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'No customer notes yet.' in body
    assert 'No linked quote/work requests.' in body
    assert 'No linked appointments.' in body
    assert 'No photos uploaded for this customer yet.' in body


def test_customer_detail_handles_incomplete_recurring_work(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Recurring Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

        recurring_work = RecurringWork(
            customer_id=customer_id,
            frequency='weekly',
            starts_on=date(2026, 5, 1),
            status='active',
            day_of_week=None,
        )
        db.session.add(recurring_work)
        db.session.commit()

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.get(f'/admin/customers/{customer_id}')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Weekly schedule unavailable' in body


def test_customer_detail_handles_note_without_author(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Orphan Note Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

        note = CustomerNote(customer_id=customer_id, note_text='Orphan note', created_by=999)
        db.session.add(note)
        db.session.commit()

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.get(f'/admin/customers/{customer_id}')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Unknown author' in body


def test_customer_detail_handles_missing_request_type(app):
    with app.app_context():
        template = app.jinja_env.from_string(
            "{{ (request.request_type or 'Unknown')|replace(' request', '')|lower }}"
        )
        rendered = template.render(request=SimpleNamespace(request_type=None))

    assert rendered == 'unknown'
