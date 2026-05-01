from datetime import date, time
from types import SimpleNamespace

from app.extensions import db
from app.models import Appointment, Customer, CustomerNote, RecurringWork, User


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
    assert 'No linked quote or work requests.' in body
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


def test_customer_detail_links_to_customer_scoped_recurring_work_flow(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Recurring Flow Customer', primary_city='City')
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
    assert 'Add Recurring Work' in body
    assert f'/admin/customers/{customer_id}/recurring-work/new' in body
    assert 'dedicated Add Recurring Work screen is not available' not in body


def test_admin_can_create_recurring_work_from_customer_context(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Recurring Flow Customer', primary_city='City', primary_email='customer@example.com')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.get(f'/admin/customers/{customer_id}/recurring-work/new')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Customer context' in body
    assert 'Recurring work details' in body
    assert 'Recurring Flow Customer' in body

    response = client.post(
        f'/admin/customers/{customer_id}/recurring-work/new',
        data={
            'recurring-work-title': 'Weekly window cleaning',
            'recurring-work-frequency': 'weekly',
            'recurring-work-day_of_week': '4',
            'recurring-work-day_of_month': '0',
            'recurring-work-starts_on': '2026-05-01',
            'recurring-work-ends_on': '',
            'recurring-work-start_time_hour': '9',
            'recurring-work-start_time_minute': '0',
            'recurring-work-end_time_hour': '11',
            'recurring-work-end_time_minute': '0',
            'recurring-work-status': 'active',
            'recurring-work-notes': 'Bring extension ladder.',
            'recurring-work-submit': 'Save Recurring Work',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert f'/admin/recurring-work/1?source=customer&customer_id={customer_id}' in response.headers['Location']

    with app.app_context():
        work = RecurringWork.query.one()
        assert work.customer_id == customer_id
        assert work.title == 'Weekly window cleaning'
        assert work.frequency == 'weekly'
        assert work.day_of_week == 4
        assert work.start_time == time(9, 0)
        assert work.end_time == time(11, 0)


def test_recurring_work_detail_shows_generation_links_and_customer_context(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
        ENABLE_SCHEDULING=True,
        ENABLE_CALENDAR=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Recurring Flow Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

        work = RecurringWork(
            customer_id=customer_id,
            title='Weekly window cleaning',
            frequency='weekly',
            day_of_week=4,
            starts_on=date(2026, 5, 1),
            start_time=time(9, 0),
            end_time=time(11, 0),
            status='active',
        )
        db.session.add(work)
        db.session.commit()
        work_id = work.id

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.post(
        f'/admin/recurring-work/{work_id}/generate?source=customer&customer_id={customer_id}',
        data={
            'generate-recurring-days_ahead': '30',
            'generate-recurring-submit': 'Generate Upcoming Appointments',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert f'/admin/recurring-work/{work_id}?source=customer&customer_id={customer_id}#generated-appointments' in response.headers['Location']

    with app.app_context():
        appointment = Appointment.query.filter_by(recurring_work_id=work_id).first()
        assert appointment is not None
        appointment_id = appointment.id
        scheduled_date = appointment.scheduled_date

    response = client.get(f'/admin/recurring-work/{work_id}?source=customer&customer_id={customer_id}')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Back to Customer' in body
    assert 'Generate upcoming appointments' in body
    assert 'Generated appointments' in body
    assert f'/admin/appointments/{appointment_id}?source=day&amp;date={scheduled_date.isoformat()}&amp;year={scheduled_date.year}&amp;month={scheduled_date.month}&amp;day={scheduled_date.day}' in body
    assert f'/admin/calendar/{scheduled_date.year}/{scheduled_date.month}/{scheduled_date.day}' in body
    assert f'/admin/customers/{customer_id}#recurring-work' in body


def test_recurring_work_list_shows_scannable_plan_columns(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Recurring Flow Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()

        work = RecurringWork(
            customer_id=customer.id,
            title='Monthly gutter cleaning',
            frequency='monthly',
            day_of_month=15,
            starts_on=date(2026, 5, 1),
            status='active',
        )
        db.session.add(work)
        db.session.commit()

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.get('/admin/recurring-work')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Recurring plan' in body
    assert 'Cadence' in body
    assert 'Default time' in body
    assert 'Generated' in body
    assert 'Recurring Flow Customer' in body
    assert 'Open Plan' in body


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
