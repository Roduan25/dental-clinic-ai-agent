import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class ServiceType(StrEnum):
    CONSULTATION = "فحص الأسنان والاستشارة"
    CLEANING = "تنظيف الأسنان وإزالة الجير"
    FILLING = "حشوة الأسنان"
    TOOTHACHE = "علاج ألم الأسنان"
    EXTRACTION = "خلع الأسنان البسيط"
    FOLLOW_UP = "متابعة العلاج"
    ORTHODONTICS = "استشارة تقويم الأسنان"


class AppointmentStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ClinicModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", use_enum_values=True)


class PatientInfo(ClinicModel):
    full_name: Annotated[str, Field(min_length=2, max_length=100, description="الاسم الكامل للمريض")]

    phone_number: Annotated[str, Field(description=("رقم هاتف سعودي بصيغة 05XXXXXXXX أو +9665XXXXXXXX"))]

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        normalized_name = " ".join(value.split())

        if len(normalized_name) < 2:
            raise ValueError("يجب إدخال اسم مريض صحيح.")

        return normalized_name

    @field_validator("phone_number")
    @classmethod
    def normalize_phone_number(cls, value: str) -> str:
        cleaned_phone = re.sub(r"[\s\-()]", "", value)

        if cleaned_phone.startswith("00966"):
            cleaned_phone = f"+966{cleaned_phone[5:]}"

        if cleaned_phone.startswith("05"):
            cleaned_phone = f"+966{cleaned_phone[1:]}"

        if not re.fullmatch(r"\+9665\d{8}", cleaned_phone):
            raise ValueError("رقم الهاتف غير صالح. استخدم 05XXXXXXXX أو +9665XXXXXXXX.")

        return cleaned_phone


class AppointmentCreate(ClinicModel):
    patient: PatientInfo

    service: ServiceType = Field(description="الخدمة المطلوبة من العيادة")

    start_time: datetime = Field(description=("موعد بداية الحجز، ويجب أن يحتوي على المنطقة الزمنية"))

    duration_minutes: int = Field(ge=15, le=120, description="مدة الموعد بالدقائق")

    note: str | None = Field(default=None, max_length=300, description=("ملاحظة إدارية قصيرة عن سبب الزيارة، من دون معلومات طبية حساسة"))

    @field_validator("start_time")
    @classmethod
    def validate_start_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("يجب أن يتضمن وقت الموعد المنطقة الزمنية.")

        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized_note = " ".join(value.split())
        return normalized_note or None


class AppointmentUpdate(ClinicModel):
    event_id: str = Field(min_length=1, description="معرّف الموعد داخل Google Calendar")

    new_start_time: datetime = Field(description=("موعد البداية الجديد، ويجب أن يحتوي على المنطقة الزمنية"))

    duration_minutes: int = Field(ge=15, le=120, description="مدة الموعد الجديدة بالدقائق")

    @field_validator("new_start_time")
    @classmethod
    def validate_new_start_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("يجب أن يتضمن وقت الموعد الجديد المنطقة الزمنية.")

        return value


class AppointmentCancellation(ClinicModel):
    event_id: str = Field(min_length=1, description="معرّف الموعد المراد إلغاؤه")

    reason: str | None = Field(default=None, max_length=200, description="سبب الإلغاء بصورة اختيارية")

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized_reason = " ".join(value.split())
        return normalized_reason or None


class AvailableSlot(ClinicModel):
    start_time: datetime = Field(description="وقت بداية الموعد المتاح")

    end_time: datetime = Field(description="وقت نهاية الموعد المتاح",)

class AppointmentRecord(ClinicModel):
    event_id: str = Field(description="معرّف الموعد داخل Google Calendar")

    patient_name: str = Field(description="اسم المريض")

    phone_number: str = Field(description="رقم هاتف المريض")

    service: str = Field(description="الخدمة المحجوزة")

    start_time: datetime = Field(description="وقت بداية الموعد")

    end_time: datetime = Field(description="وقت نهاية الموعد")

    status: AppointmentStatus = Field(default=AppointmentStatus.CONFIRMED, description="حالة الموعد")

    note: str | None = Field(default=None, description="الملاحظة الإدارية المرتبطة بالحجز",)

class CalendarOperationResult(ClinicModel):
    success: bool = Field(description="هل نجحت العملية؟",)

    message: str = Field(description="رسالة واضحة تصف نتيجة العملية",)

    appointment: AppointmentRecord | None = Field(
        default=None,
        description=("بيانات الموعد عند نجاح الحجز أو التعديل"),
    )

class ClinicAgentResponse(ClinicModel):
    message: str = Field(description="الرد العربي النهائي الموجّه للمريض",)