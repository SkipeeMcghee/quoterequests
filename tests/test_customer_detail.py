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


def test_customer_detail_can_add_multiple_addresses_and_mark_billing(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Address Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.post(
        f'/admin/customers/{customer_id}/addresses',
        data={
            'customer-address-address_line_1': '123 Main St',
            'customer-address-address_line_2': 'Suite 100',
            'customer-address-state': 'CA',
            'customer-address-zip_code': '90210',
            'customer-address-is_billing': 'y',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        customer = Customer.query.get(customer_id)
        assert len(customer.addresses) == 1
        assert customer.billing_address is not None
        assert customer.billing_address.address_line_1 == '123 Main St'
        assert customer.billing_address.is_billing is True

    response = client.post(
        f'/admin/customers/{customer_id}/addresses',
        data={
            'customer-address-address_line_1': '456 Oak Ave',
            'customer-address-state': 'CA',
            'customer-address-zip_code': '90001',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        customer = Customer.query.get(customer_id)
        assert len(customer.addresses) == 2
        billing_addresses = [address for address in customer.addresses if address.is_billing]
        assert len(billing_addresses) == 1

        new_address = next(address for address in customer.addresses if address.address_line_1 == '456 Oak Ave')

    response = client.post(
        f'/admin/customers/{customer_id}/addresses/{new_address.id}/billing',
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        customer = Customer.query.get(customer_id)
        billing_addresses = [address for address in customer.addresses if address.is_billing]
        assert len(billing_addresses) == 1
        assert billing_addresses[0].address_line_1 == '456 Oak Ave'


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
