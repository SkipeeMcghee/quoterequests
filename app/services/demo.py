"""Synthetic, repeatable demo records; never sends email or changes admin accounts."""

from datetime import date, time, timedelta
from decimal import Decimal

from sqlalchemy import update

from app.extensions import db
from app.models import Appointment, Customer, CustomerPhoto, GalleryItem, QuoteRequest, RequestPhoto, RequestQuote, ServiceOption
from app.services.uploads import delete_upload_file
from app.tenancy import tenant_config

DEMO_EMAIL = "alex.homeowner@example.test"


def seed_demo(*, reset: bool = False, force: bool = False, confirmation: str | None = None) -> bool:
    from app.tenancy import get_current_tenant

    slug = get_current_tenant().slug
    if reset and not tenant_config("DEMO_TENANT", False) and not (force and confirmation == slug):
        raise ValueError("Reset requires DEMO_TENANT=true, or --force --confirm <exact tenant slug>.")
    if not reset:
        if Customer.query.filter_by(primary_email=DEMO_EMAIL).first() is not None:
            return False
        if Customer.query.first() is not None or QuoteRequest.query.first() is not None or Appointment.query.first() is not None or GalleryItem.query.first() is not None:
            raise ValueError("Tenant already contains business records. Use the guarded --reset workflow.")

    old_files = []
    try:
        if reset:
            old_files = [row.file_path for row in RequestPhoto.query.all()] + [row.file_path for row in CustomerPhoto.query.all()]
            old_files += [row.image_path for row in GalleryItem.query.all() if row.image_path.startswith("uploads/")]
            # Break the nullable appointment/recurring-work cycle before deleting business data.
            db.session.execute(update(Appointment).values(recurring_work_id=None, previous_appointment_id=None))
            from app.models import RecurringWork
            db.session.execute(update(RecurringWork).values(source_appointment_id=None))
            # Explicit order covers the cyclic models while preserving all admin accounts.
            order = (
                "appointment_staff_assignments", "appointment_service_options", "staff_service_options",
                "staff_availabilities", "customer_photos", "customer_notes", "customer_fields",
                "customer_addresses", "request_photos", "request_notes", "request_quotes",
                "quote_request_service_options", "appointments", "recurring_works", "gallery_items",
                "quote_requests", "customers", "staff_members", "service_options",
            )
            for name in order:
                db.session.execute(db.metadata.tables[name].delete())

        services = []
        for index, (name, description) in enumerate((
            ("Window Cleaning", "Interior and exterior glass cleaning."),
            ("Pressure Washing", "Careful driveway and patio washing."),
            ("Gutter Clearing", "Seasonal debris removal and downspout checks."),
        )):
            service = ServiceOption.query.filter_by(name=name).first()
            if service is None:
                service = ServiceOption(name=name)
                db.session.add(service)
            service.description, service.display_order, service.is_active = description, index, True
            services.append(service)
        customer = Customer(primary_name="Alex Homeowner", primary_email=DEMO_EMAIL,
                            primary_phone="(555) 010-0140", primary_city="Sample City")
        business = Customer(primary_name="Harbor Property Services", primary_email="office@harbor.example.test",
                            primary_phone="(555) 010-0141", primary_city="Sample City")
        db.session.add_all([customer, business])
        for index, status in enumerate(("New", "Viewed", "Contacted", "Quoted", "Accepted", "Rejected", "Scheduled")):
            inquiry = QuoteRequest(full_name=customer.primary_name, email=customer.primary_email,
                                   phone=customer.primary_phone, city="Sample City", customer=customer,
                                   status=status, additional_notes="Synthetic demo: please do not contact.",
                                   services=[services[index % len(services)]])
            db.session.add(inquiry)
            db.session.flush()
            if status in ("Quoted", "Accepted", "Rejected", "Scheduled"):
                inquiry.quotes.append(RequestQuote(amount=Decimal("185.00"), description="Exterior cleaning",
                                                    decision={"Accepted": "Accepted", "Rejected": "Rejected"}.get(status, "Sent")))
            if status == "Scheduled":
                inquiry.appointments.append(Appointment(customer=customer, title="Exterior window cleaning",
                    status="Scheduled", scheduled_date=date.today() + timedelta(days=2),
                    confirmed_date=date.today() + timedelta(days=2), start_time=time(9), end_time=time(11),
                    confirmed_time=time(9), services=[services[0]]))
        db.session.add(Appointment(customer=business, title="Patio washing request", status="Requested",
                                   requested_date=date.today() + timedelta(days=4), services=[services[1]]))
        db.session.add(GalleryItem(title="Sample service showcase", caption="Demo illustration, not customer work.",
                                  image_path="assets/images/Logowhite.png", service=services[0], featured=True))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    for key in old_files:
        delete_upload_file(key)
    return True
