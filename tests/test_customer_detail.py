from decimal import Decimal
from datetime import date, time, timedelta
from types import SimpleNamespace

from app.extensions import db
from app.models import Appointment, Customer, CustomerNote, QuoteRequest, RecurringWork, User


def test_customer_list_hides_last_activity_column(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
    )
    with app.app_context():
        customer = Customer(primary_name='List Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.get('/admin/customers')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Customer directory' in body
    assert '<th>Last activity</th>' not in body


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


def test_customer_detail_uses_inline_activity_summary_and_no_shortcuts_card(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Layout Customer', primary_city='City')
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
    assert 'Workflow shortcuts' not in body
    assert 'Last activity: No recent activity' in body
    assert 'Jump to:' in body


def test_create_customer_from_request_guesses_business_name(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
    )
    with app.app_context():
        quote_request = QuoteRequest(
            full_name='Bright Window Cleaning LLC',
            city='Metro City',
            phone='555-0199',
            email='hello@brightwindows.example',
        )
        db.session.add(quote_request)
        db.session.commit()
        request_id = quote_request.id

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.post(
        f'/admin/requests/{request_id}/create-customer',
        data={'create-customer-submit': 'Add Customer'},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        quote_request = db.session.get(QuoteRequest, request_id)
        customer = quote_request.customer
        assert customer is not None
        assert customer.business_name == 'Bright Window Cleaning LLC'
        assert customer.individual_name is None
        assert customer.display_name_preference == 'business'
        assert customer.primary_name == 'Bright Window Cleaning LLC'


def test_customer_merge_page_shows_source_target_and_final_account_flow(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
    )
    with app.app_context():
        source = Customer(primary_name='Source Customer', primary_city='Source City', primary_email='source@example.com')
        target = Customer(primary_name='Target Customer', primary_city='Target City', primary_email='target@example.com')
        db.session.add_all([source, target])
        db.session.commit()
        source_id = source.id

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.get(f'/admin/customers/{source_id}/merge')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Source customer' in body
    assert 'Surviving customer' in body
    assert 'Merge into' in body
    assert 'Final account' in body
    assert body.count('Target Customer') >= 3


def test_customer_detail_can_choose_business_display_name(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
    )
    with app.app_context():
        customer = Customer(
            primary_name='Jamie Rivera',
            individual_name='Jamie Rivera',
            display_name_preference='individual',
            primary_city='City',
        )
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.post(
        f'/admin/customers/{customer_id}/info',
        data={
            'customer-info-individual_name': 'Jamie Rivera',
            'customer-info-business_name': 'Rivera Property Services',
            'customer-info-display_name_preference': 'business',
            'customer-info-primary_phone': '555-0100',
            'customer-info-primary_email': 'jamie@example.com',
            'customer-info-primary_city': 'City',
            'customer-info-submit': 'Save Customer',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        customer = db.session.get(Customer, customer_id)
        assert customer.individual_name == 'Jamie Rivera'
        assert customer.business_name == 'Rivera Property Services'
        assert customer.display_name_preference == 'business'
        assert customer.primary_name == 'Rivera Property Services'


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


def test_customer_detail_billing_section_aggregates_recurring_work_values(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Billing Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

        db.session.add_all(
            [
                RecurringWork(
                    customer_id=customer_id,
                    title='Weekly exterior windows',
                    frequency='weekly',
                    day_of_week=4,
                    starts_on=date(2026, 5, 1),
                    status='active',
                    billing_amount=Decimal('125.00'),
                    billing_frequency='monthly',
                ),
                RecurringWork(
                    customer_id=customer_id,
                    title='Lobby touchups',
                    frequency='monthly',
                    day_of_month=15,
                    starts_on=date(2026, 5, 1),
                    status='active',
                    billing_amount=Decimal('75.00'),
                    billing_frequency='per_job',
                ),
            ]
        )
        db.session.commit()

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.get(f'/admin/customers/{customer_id}')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Recurring work billing' in body
    assert 'Weekly exterior windows' in body
    assert 'Lobby touchups' in body
    assert '125.00 / monthly' in body
    assert '75.00 / per_job' in body
    assert 'Total recurring billing' in body
    assert '200.00' in body


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
        ENABLE_SCHEDULING=True,
        ENABLE_SERVICES=True,
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
            'recurring-work-title': 'Window Cleaning',
            'recurring-work-frequency': 'weekly',
            'recurring-work-recurrence_unit': 'week',
            'recurring-work-recurrence_interval': '1',
            'recurring-work-weekdays': ['4'],
            'recurring-work-month_day_primary': '0',
            'recurring-work-month_day_secondary': '0',
            'recurring-work-starts_on': '2026-05-01',
            'recurring-work-ends_on': '',
            'recurring-work-start_time_hour': '9',
            'recurring-work-start_time_minute': '0',
            'recurring-work-end_time_hour': '11',
            'recurring-work-end_time_minute': '0',
            'recurring-work-billing_amount': '125.00',
            'recurring-work-billing_frequency': 'monthly',
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
        assert work.title == 'Window Cleaning'
        assert work.frequency == 'weekly'
        assert work.day_of_week == 4
        assert work.recurrence_config == {'unit': 'week', 'interval': 1, 'weekdays': [4], 'month_days': []}
        assert work.start_time == time(9, 0)
        assert work.end_time == time(11, 0)
        assert work.billing_amount == Decimal('125.00')
        assert work.billing_frequency == 'monthly'
        assert Appointment.query.filter_by(recurring_work_id=work.id).count() > 0


def test_recurring_work_detail_shows_generation_links_and_customer_context(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
        ENABLE_SCHEDULING=True,
        ENABLE_CALENDAR=True,
        ENABLE_SERVICES=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Recurring Flow Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

        work = RecurringWork(
            customer_id=customer_id,
            title='Window Cleaning',
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

    response = client.get(f'/admin/recurring-work/{work_id}?source=customer&customer_id={customer_id}')
    assert response.status_code == 200

    with app.app_context():
        appointment = Appointment.query.filter_by(recurring_work_id=work_id).first()
        assert appointment is not None
        appointment_id = appointment.id
        scheduled_date = appointment.scheduled_date

    body = response.get_data(as_text=True)
    assert 'Back to Customer' in body
    assert 'View Generated Events' in body
    assert body.count('View Customer') == 1
    assert 'Schedule sync' in body
    assert 'Future impact' in body
    assert 'Sync Upcoming Events' in body
    assert 'Archive Plan and Remove Future Managed Events' in body
    assert 'Mark Exception' in body
    assert 'Save Recurring Work' not in body
    assert 'Generated appointments' in body
    assert 'Back to Customer Record' not in body
    assert 'Calendar View' not in body
    assert 'List View' not in body
    assert 'recurring-generated-dialog' in body
    assert f'/admin/appointments/{appointment_id}?source=day&amp;date={scheduled_date.isoformat()}&amp;year={scheduled_date.year}&amp;month={scheduled_date.month}&amp;day={scheduled_date.day}' in body
    assert f'/admin/calendar/{scheduled_date.year}/{scheduled_date.month}/{scheduled_date.day}' in body
    assert f'/admin/customers/{customer_id}#recurring-work' in body


def test_recurring_work_preview_endpoint_reports_pending_child_changes(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
        ENABLE_SCHEDULING=True,
        ENABLE_SERVICES=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Preview Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

        work = RecurringWork(
            customer_id=customer_id,
            title='Window Cleaning',
            frequency='weekly',
            day_of_week=date.today().weekday(),
            starts_on=date.today(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            status='active',
        )
        db.session.add(work)
        db.session.commit()
        work_id = work.id

        db.session.add_all(
            [
                Appointment(
                    customer_id=customer_id,
                    recurring_work_id=work_id,
                    title='Window Cleaning',
                    scheduled_date=date.today(),
                    start_time=time(9, 0),
                    end_time=time(11, 0),
                    status='Scheduled',
                ),
                Appointment(
                    customer_id=customer_id,
                    recurring_work_id=work_id,
                    title='Window Cleaning',
                    scheduled_date=date.today().replace(day=date.today().day) + timedelta(days=1),
                    start_time=time(9, 0),
                    end_time=time(11, 0),
                    status='Scheduled',
                ),
            ]
        )
        db.session.commit()

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.post(
        f'/admin/recurring-work/{work_id}/impact-preview',
        data={
            'recurring-work-title': 'Window Cleaning',
            'recurring-work-frequency': 'weekly',
            'recurring-work-recurrence_unit': 'week',
            'recurring-work-recurrence_interval': '1',
            'recurring-work-weekdays': [str(date.today().weekday())],
            'recurring-work-month_day_primary': '0',
            'recurring-work-month_day_secondary': '0',
            'recurring-work-starts_on': date.today().isoformat(),
            'recurring-work-ends_on': '',
            'recurring-work-start_time_hour': '10',
            'recurring-work-start_time_minute': '0',
            'recurring-work-end_time_hour': '12',
            'recurring-work-end_time_minute': '0',
            'recurring-work-billing_amount': '',
            'recurring-work-billing_frequency': '',
            'recurring-work-status': 'active',
            'recurring-work-notes': '',
            'preview-days-ahead': '30',
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ok'] is True
    assert payload['updated'] == 1
    assert payload['deleted'] == 1
    assert payload['created'] > 0


def test_recurring_work_edit_autosave_returns_json(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
        ENABLE_SCHEDULING=True,
        ENABLE_SERVICES=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Autosave Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

        work = RecurringWork(
            customer_id=customer_id,
            title='Window Cleaning',
            frequency='weekly',
            recurrence_config={'unit': 'week', 'interval': 1, 'weekdays': [date.today().weekday()], 'month_days': []},
            day_of_week=date.today().weekday(),
            starts_on=date.today(),
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
        f'/admin/recurring-work/{work_id}/edit?source=customer&customer_id={customer_id}',
        data={
            'recurring-work-title': 'Window Cleaning',
            'recurring-work-frequency': 'biweekly',
            'recurring-work-recurrence_unit': 'week',
            'recurring-work-recurrence_interval': '2',
            'recurring-work-weekdays': [str(date.today().weekday())],
            'recurring-work-month_day_primary': '0',
            'recurring-work-month_day_secondary': '0',
            'recurring-work-starts_on': date.today().isoformat(),
            'recurring-work-ends_on': '',
            'recurring-work-start_time_hour': '10',
            'recurring-work-start_time_minute': '0',
            'recurring-work-end_time_hour': '12',
            'recurring-work-end_time_minute': '0',
            'recurring-work-billing_amount': '',
            'recurring-work-billing_frequency': '',
            'recurring-work-status': 'active',
            'recurring-work-notes': 'Autosaved change',
        },
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ok'] is True
    assert payload['message'] == 'Recurring work saved.'
    assert payload['work']['frequency_label'] == 'Biweekly'
    assert payload['work']['time_summary'] == '10:00 – 12:00'

    with app.app_context():
        refreshed = db.session.get(RecurringWork, work_id)
        assert refreshed is not None
        assert refreshed.frequency == 'biweekly'
        assert refreshed.recurrence_config == {'unit': 'week', 'interval': 2, 'weekdays': [date.today().weekday()], 'month_days': []}
        assert refreshed.start_time == time(10, 0)
        assert refreshed.end_time == time(12, 0)
        assert refreshed.notes == 'Autosaved change'


def test_admin_can_mark_recurring_child_event_as_exception(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
        ENABLE_SCHEDULING=True,
        ENABLE_SERVICES=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Exception Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

        work = RecurringWork(
            customer_id=customer_id,
            title='Window Cleaning',
            frequency='weekly',
            day_of_week=date.today().weekday(),
            starts_on=date.today(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            status='active',
        )
        db.session.add(work)
        db.session.commit()
        work_id = work.id

        appointment = Appointment(
            customer_id=customer_id,
            recurring_work_id=work_id,
            title='Window Cleaning',
            scheduled_date=date.today(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            status='Scheduled',
        )
        db.session.add(appointment)
        db.session.commit()
        appointment_id = appointment.id

    client.post(
        '/auth/login',
        data={'email': admin_user, 'password': 'password123', 'remember_me': 'y'},
        follow_redirects=True,
    )

    response = client.post(
        f'/admin/appointments/{appointment_id}/recurring-exception?source=customer&customer_id={customer_id}',
        data={'is_exception': '1'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert f'/admin/recurring-work/{work_id}?source=customer&customer_id={customer_id}#generated-appointments' in response.headers['Location']

    with app.app_context():
        refreshed = db.session.get(Appointment, appointment_id)
        assert refreshed is not None
        assert refreshed.recurring_exception is True

    detail_response = client.get(f'/admin/recurring-work/{work_id}?source=customer&customer_id={customer_id}')
    assert detail_response.status_code == 200
    detail_body = detail_response.get_data(as_text=True)
    assert 'Resume Sync' in detail_body


def test_recurring_work_list_shows_scannable_plan_columns(client, app, admin_user):
    app.config.update(
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_RECURRING_WORK=True,
        ENABLE_SERVICES=True,
    )
    with app.app_context():
        customer = Customer(primary_name='Recurring Flow Customer', primary_city='City')
        db.session.add(customer)
        db.session.commit()

        work = RecurringWork(
            customer_id=customer.id,
            title='Inspection',
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
    assert 'Service' in body
    assert 'Cadence' in body
    assert 'Default time' in body
    assert 'Generated' in body
    assert 'Recurring Flow Customer' in body
    assert 'Open Plan' not in body


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
