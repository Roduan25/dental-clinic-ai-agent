from models import (
    AppointmentCreate,
    PatientInfo,
    ServiceType,
)


patient = PatientInfo(
    full_name="  أحمد    محمد  ",
    phone_number="+966515987563",
)

appointment = AppointmentCreate(
    patient=patient,
    service=ServiceType.CLEANING,
    start_time="2026-08-10T10:00:00",
    duration_minutes=30,
    note="  زيارة    أولى  ",
)

print(appointment.model_dump())

