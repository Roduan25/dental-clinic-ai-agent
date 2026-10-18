from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from models import (
    AppointmentCancellation,
    AppointmentCreate,
    AppointmentRecord,
    AppointmentStatus,
    AppointmentUpdate,
    AvailableSlot,
    CalendarOperationResult,
    PatientInfo,
)
from settings import settings


SCOPES = ["https://www.googleapis.com/auth/calendar"]
WORKING_DAYS = {6, 0, 1, 2, 3}


@lru_cache
def get_calendar_service():
    credentials_file = settings.resolved_google_credentials_file
    token_file = settings.resolved_google_token_file
    credentials = None

    token_file.parent.mkdir(parents=True, exist_ok=True)

    if token_file.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except ValueError:
            token_file.unlink(missing_ok=True)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
        credentials = flow.run_local_server(port=0)

    token_file.write_text(credentials.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _event_datetime(data: dict) -> datetime:
    return datetime.fromisoformat(data["dateTime"].replace("Z", "+00:00")).astimezone(ZoneInfo(settings.clinic_timezone))


def _event_record(event: dict) -> AppointmentRecord:
    private = event.get("extendedProperties", {}).get("private", {})

    return AppointmentRecord(
        event_id=event["id"],
        patient_name=private.get("patient_name", "غير معروف"),
        phone_number=private.get("patient_phone", "غير معروف"),
        service=private.get("service", "موعد عيادة"),
        start_time=_event_datetime(event["start"]),
        end_time=_event_datetime(event["end"]),
        status=AppointmentStatus.CONFIRMED,
        note=private.get("note"),
    )


def _working_periods(day: date):
    if day.weekday() not in WORKING_DAYS:
        return []

    timezone = ZoneInfo(settings.clinic_timezone)

    def at(hour: int):
        return datetime.combine(day, time(hour), tzinfo=timezone)

    return [
        (
            at(settings.clinic_open_hour),
            at(settings.break_start_hour),
        ),
        (
            at(settings.break_end_hour),
            at(settings.clinic_close_hour),
        ),
    ]


def _slot_available(start_time: datetime, duration: int, exclude_event_id: str | None = None,) -> bool:
    timezone = ZoneInfo(settings.clinic_timezone)
    start_time = start_time.astimezone(timezone)
    end_time = start_time + timedelta(minutes=duration)

    if start_time <= datetime.now(timezone):
        return False

    if not any(start_time >= start and end_time <= end for start, end in _working_periods(start_time.date())):
        return False

    events = get_calendar_service().events().list(
        calendarId=settings.google_calendar_id,
        timeMin=start_time.isoformat(),
        timeMax=end_time.isoformat(),
        singleEvents=True,
        showDeleted=False,
    ).execute().get("items", [])

    for event in events:
        if event.get("id") == exclude_event_id:
            continue

        event_start = _event_datetime(event["start"])
        event_end = _event_datetime(event["end"])

        if event_start < end_time and event_end > start_time:
            return False

    return True


def find_available_slots(requested_date: date, duration_minutes: int | None = None, maximum_results: int = 6) -> list[AvailableSlot]:
    duration = (duration_minutes or settings.appointment_duration_minutes)

    timezone = ZoneInfo(settings.clinic_timezone)
    day_start = datetime.combine(requested_date, time.min, tzinfo=timezone)
    day_end = day_start + timedelta(days=1)

    events = get_calendar_service().events().list(
        calendarId=settings.google_calendar_id,
        timeMin=day_start.isoformat(),
        timeMax=day_end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        showDeleted=False,
    ).execute().get("items", [])

    busy = [(_event_datetime(event["start"]), _event_datetime(event["end"])) for event in events]

    slots = []
    now = datetime.now(timezone)

    for period_start, period_end in _working_periods(requested_date):
        start = period_start

        while start + timedelta(minutes=duration) <= period_end:
            end = start + timedelta(minutes=duration)

            occupied = any(busy_start < end and busy_end > start for busy_start, busy_end in busy)

            if not occupied and start > now:
                slots.append(AvailableSlot(start_time=start, end_time=end))

            if len(slots) >= maximum_results:
                return slots

            start = end

    return slots


from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from models import (
    AppointmentCancellation,
    AppointmentCreate,
    AppointmentRecord,
    AppointmentStatus,
    AppointmentUpdate,
    AvailableSlot,
    CalendarOperationResult,
    PatientInfo,
)
from settings import settings


SCOPES = ["https://www.googleapis.com/auth/calendar"]
WORKING_DAYS = {6, 0, 1, 2, 3}


@lru_cache
def get_calendar_service():
    credentials_file = settings.resolved_google_credentials_file
    token_file = settings.resolved_google_token_file
    credentials = None

    token_file.parent.mkdir(parents=True, exist_ok=True)

    if token_file.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except ValueError:
            token_file.unlink(missing_ok=True)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
        credentials = flow.run_local_server(port=0)

    token_file.write_text(credentials.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _event_datetime(data: dict) -> datetime:
    return datetime.fromisoformat(data["dateTime"].replace("Z", "+00:00")).astimezone(ZoneInfo(settings.clinic_timezone))


def _event_record(event: dict) -> AppointmentRecord:
    private = event.get("extendedProperties", {}).get("private", {})

    return AppointmentRecord(
        event_id=event["id"],
        patient_name=private.get("patient_name", "غير معروف"),
        phone_number=private.get("patient_phone", "غير معروف"),
        service=private.get("service", "موعد عيادة"),
        start_time=_event_datetime(event["start"]),
        end_time=_event_datetime(event["end"]),
        status=AppointmentStatus.CONFIRMED,
        note=private.get("note"),
    )


def _working_periods(day: date):
    if day.weekday() not in WORKING_DAYS:
        return []

    timezone = ZoneInfo(settings.clinic_timezone)

    def at(hour: int):
        return datetime.combine(day, time(hour), tzinfo=timezone)

    return [
        (
            at(settings.clinic_open_hour),
            at(settings.break_start_hour),
        ),
        (
            at(settings.break_end_hour),
            at(settings.clinic_close_hour),
        ),
    ]


def _slot_available(start_time: datetime, duration: int, exclude_event_id: str | None = None,) -> bool:
    timezone = ZoneInfo(settings.clinic_timezone)
    start_time = start_time.astimezone(timezone)
    end_time = start_time + timedelta(minutes=duration)

    if start_time <= datetime.now(timezone):
        return False

    if not any(start_time >= start and end_time <= end for start, end in _working_periods(start_time.date())):
        return False

    events = get_calendar_service().events().list(
        calendarId=settings.google_calendar_id,
        timeMin=start_time.isoformat(),
        timeMax=end_time.isoformat(),
        singleEvents=True,
        showDeleted=False,
    ).execute().get("items", [])

    for event in events:
        if event.get("id") == exclude_event_id:
            continue

        event_start = _event_datetime(event["start"])
        event_end = _event_datetime(event["end"])

        if event_start < end_time and event_end > start_time:
            return False

    return True


def find_available_slots(requested_date: date, duration_minutes: int | None = None, maximum_results: int = 6) -> list[AvailableSlot]:
    duration = (duration_minutes or settings.appointment_duration_minutes)

    timezone = ZoneInfo(settings.clinic_timezone)
    day_start = datetime.combine(requested_date, time.min, tzinfo=timezone)
    day_end = day_start + timedelta(days=1)

    events = get_calendar_service().events().list(
        calendarId=settings.google_calendar_id,
        timeMin=day_start.isoformat(),
        timeMax=day_end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        showDeleted=False,
    ).execute().get("items", [])

    busy = [(_event_datetime(event["start"]), _event_datetime(event["end"])) for event in events]

    slots = []
    now = datetime.now(timezone)

    for period_start, period_end in _working_periods(requested_date):
        start = period_start

        while start + timedelta(minutes=duration) <= period_end:
            end = start + timedelta(minutes=duration)

            occupied = any(busy_start < end and busy_end > start for busy_start, busy_end in busy)

            if not occupied and start > now:
                slots.append(AvailableSlot(start_time=start, end_time=end))

            if len(slots) >= maximum_results:
                return slots

            start = end

    return slots


def create_appointment(appointment: AppointmentCreate) -> CalendarOperationResult:
    start = appointment.start_time.astimezone(ZoneInfo(settings.clinic_timezone))
    duration = appointment.duration_minutes

    if not _slot_available(start, duration):
        return CalendarOperationResult(success=False, message="الموعد المطلوب غير متاح.")

    end = start + timedelta(minutes=duration)

    private = {
        "patient_name": appointment.patient.full_name,
        "patient_phone": appointment.patient.phone_number,
        "service": str(appointment.service),
    }

    if appointment.note:
        private["note"] = appointment.note

    event = {
        "summary": (f"{appointment.service} - " f"{appointment.patient.full_name}"),
        "start": {"dateTime": start.isoformat(), "timeZone": settings.clinic_timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": settings.clinic_timezone},
        "extendedProperties": {"private": private},
    }

    created = get_calendar_service().events().insert(calendarId=settings.google_calendar_id, body=event).execute()

    return CalendarOperationResult(success=True, message="تم حجز الموعد بنجاح.", appointment=_event_record(created))


def find_appointments_by_phone(phone_number: str, include_past: bool = False) -> list[AppointmentRecord]:
    phone = PatientInfo(full_name="مريض", phone_number=phone_number).phone_number

    params = {
        "calendarId": settings.google_calendar_id,
        "singleEvents": True,
        "orderBy": "startTime",
        "showDeleted": False,
        "privateExtendedProperty": (f"patient_phone={phone}"),
    }

    if not include_past:
        params["timeMin"] = datetime.now(ZoneInfo(settings.clinic_timezone)).isoformat()

    events = get_calendar_service().events().list(**params).execute().get("items", [])

    return [_event_record(event) for event in events]


def update_appointment(appointment_update: AppointmentUpdate) -> CalendarOperationResult:
    start = appointment_update.new_start_time.astimezone(ZoneInfo(settings.clinic_timezone))
    duration = appointment_update.duration_minutes

    if not _slot_available( start, duration, appointment_update.event_id):
        return CalendarOperationResult(success=False, message="الموعد الجديد غير متاح.")

    service = get_calendar_service()

    event = service.events().get(calendarId=settings.google_calendar_id, eventId=appointment_update.event_id).execute()

    event["start"] = {"dateTime": start.isoformat(), "timeZone": settings.clinic_timezone}
    event["end"] = {"dateTime": (start + timedelta(minutes=duration)).isoformat(), "timeZone": settings.clinic_timezone}

    updated = service.events().update( calendarId=settings.google_calendar_id, eventId=appointment_update.event_id, body=event).execute()

    return CalendarOperationResult( success=True, message="تم تعديل الموعد بنجاح.", appointment=_event_record(updated))


def cancel_appointment(cancellation: AppointmentCancellation) -> CalendarOperationResult:
    service = get_calendar_service()

    event = service.events().get( calendarId=settings.google_calendar_id, eventId=cancellation.event_id).execute()

    appointment = _event_record(event)

    service.events().delete( calendarId=settings.google_calendar_id, eventId=cancellation.event_id,).execute()

    appointment.status = AppointmentStatus.CANCELLED

    return CalendarOperationResult(success=True, message="تم إلغاء الموعد بنجاح.", appointment=appointment,)

def test_calendar_connection() -> str:
    service = get_calendar_service()

    calendar = service.calendars().get(calendarId=settings.google_calendar_id).execute()

    calendar_name = calendar.get("summary", settings.google_calendar_id,)

    return f"تم الاتصال بنجاح بتقويم: {calendar_name}"


if __name__ == "__main__":
    try:
        print(test_calendar_connection())

        today = datetime.now(ZoneInfo(settings.clinic_timezone)).date()

        slots = find_available_slots(
            requested_date=today
        )

        if slots:
            print("\nالمواعيد المتاحة اليوم:")

            for slot in slots:
                print(slot.start_time.strftime("%Y-%m-%d %H:%M"))
        else:
            print("لا توجد مواعيد متاحة اليوم.")

    except Exception as error:
        print(f"حدث خطأ: {error}")