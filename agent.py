from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence
import time

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    FunctionToolset,
    ModelRetry,
    RunContext,
    ToolDenied,
)
from pydantic_ai.messages import ModelMessage

from calendar_service import (
    cancel_appointment,
    create_appointment,
    find_appointments_by_phone,
    find_available_slots,
    update_appointment,
)
from models import (
    AppointmentCancellation,
    AppointmentCreate,
    AppointmentUpdate,
    ClinicAgentResponse,
    PatientInfo,
    ServiceType,
)
from rag import (
    format_search_results,
    search_knowledge,
)
from settings import settings


@dataclass
class AgentDependencies:
    telegram_user_id: int | None = None
    telegram_username: str | None = None
    knowledge_search_used: bool = False


knowledge_toolset = FunctionToolset[AgentDependencies](
    max_retries=0,
    instructions=(
        "استخدم أداة المعرفة مرة واحدة فقط للإجابة عن "
        "الخدمات والأسعار وساعات العمل وسياسات العيادة. "
        "لا تكرر استدعاء الأداة لنفس السؤال."
    ),
)


calendar_toolset = FunctionToolset[AgentDependencies](
    max_retries=2,
    instructions=(
        "استخدم أداة التقويم المناسبة مرة واحدة فقط لكل خطوة. "
        "بعد نجاح إنشاء الموعد أو تعديله أو إلغائه، لا تستدعِ أي أداة "
        "كتابة أخرى، بل أنشئ الرد النهائي للمستخدم مباشرة. "
        "لا تكرر استدعاء الأداة نفسها بالمعاملات نفسها. "
        "أدوات الكتابة تستخدم موافقة بشرية مؤجلة، لذلك لا تطلب "
        "تأكيدًا نصيًا قبل استدعائها."
    ),
)


knowledge_calls = 0


@knowledge_toolset.tool
def search_clinic_information(ctx: RunContext[AgentDependencies], query: str) -> str:
    import time

    global knowledge_calls

    if ctx.deps.knowledge_search_used:
        return (
            "تم البحث في قاعدة المعرفة مسبقًا لهذا الطلب. "
            "لا تستدعِ أداة البحث مرة أخرى. "
            "أجب باستخدام النتيجة السابقة، وإذا لم تحتوِ على "
            "المعلومة المطلوبة فقل إن المعلومة غير متوفرة."
        )

    ctx.deps.knowledge_search_used = True

    knowledge_calls += 1
    started_at = time.perf_counter()

    print(
        f"بدء RAG رقم {knowledge_calls}: {query}",
        flush=True,
    )

    results = search_knowledge(query=query, results_count=4)

    output = format_search_results(results)

    if not output.strip():
        output = (
            "لم يتم العثور على معلومة مطابقة في قاعدة المعرفة. "
            "لا تكرر البحث، وأخبر المستخدم أن المعلومة غير متوفرة."
        )

    print(
        f"انتهاء RAG رقم {knowledge_calls} خلال "
        f"{time.perf_counter() - started_at:.2f} ثانية",
        flush=True,
    )

    return (
        "نتائج البحث في قاعدة معرفة العيادة:\n\n"
        f"{output}\n\n"
        "تعليمات: لا تستدعِ أداة البحث مرة أخرى في هذا الطلب. "
        "إذا لم تتضمن النتائج الإجابة، قل إن المعلومة غير متوفرة."
    )


@calendar_toolset.tool
def get_available_appointments(ctx: RunContext[AgentDependencies], requested_date: date) -> str:
    """
    اعرض المواعيد المتاحة في يوم محدد.

    لا تنشئ موعدًا من خلال هذه الأداة، بل استخدمها للاستعلام فقط.
    """
    del ctx

    slots = find_available_slots(
        requested_date=requested_date,
        duration_minutes=(
            settings.appointment_duration_minutes
        ),
        maximum_results=15,
    )

    if not slots:
        return (
            "لا توجد مواعيد متاحة في هذا اليوم، "
            "أو أن العيادة مغلقة."
        )

    formatted_slots = [slot.start_time.strftime("%Y-%m-%d %H:%M") for slot in slots]

    return "\n".join(formatted_slots)


@calendar_toolset.tool
def get_patient_appointments(ctx: RunContext[AgentDependencies], phone_number: str) -> str:
    del ctx

    if not phone_number.strip():
        raise ModelRetry(
            "رقم الهاتف غير موجود. "
            "اطلب من المستخدم رقم الهاتف قبل البحث عن مواعيده."
        )

    started_at = time.perf_counter()

    print(
        f"بدء البحث عن المواعيد: {phone_number}",
        flush=True,
    )

    appointments = find_appointments_by_phone(phone_number=phone_number, include_past=False)

    print(
        "انتهاء البحث عن المواعيد خلال "
        f"{time.perf_counter() - started_at:.2f} ثانية، "
        f"العدد: {len(appointments)}",
        flush=True,
    )

    if not appointments:
        return (
            "لم يتم العثور على مواعيد قادمة "
            "مرتبطة برقم الهاتف."
        )

    formatted_appointments: list[str] = []

    for appointment in appointments:
        formatted_appointments.append(
            "\n".join(
                [
                    f"معرّف الموعد: {appointment.event_id}",
                    f"الخدمة: {appointment.service}",
                    (
                        "الموعد: "
                        f"{appointment.start_time:%Y-%m-%d %H:%M}"
                    ),
                ]
            )
        )

    return "\n\n---\n\n".join(formatted_appointments)

@calendar_toolset.tool(requires_approval=True)
def book_appointment(
    ctx: RunContext[AgentDependencies],
    patient_name: str,
    phone_number: str,
    service: ServiceType,
    start_time: datetime,
    note: str | None = None,
) -> str:
    """
    أنشئ موعدًا جديدًا بعد موافقة المريض.

    يجب جمع اسم المريض ورقم الهاتف والخدمة والموعد، والتحقق من
    توفر الموعد قبل استدعاء هذه الأداة.
    """
    del ctx

    appointment = AppointmentCreate(
        patient=PatientInfo(full_name=patient_name, phone_number=phone_number),
        service=service,
        start_time=start_time,
        duration_minutes=(settings.appointment_duration_minutes),
        note=note,
    )

    result = create_appointment(appointment)

    if not result.success:
        raise ModelRetry( f"{result.message} " "ابحث عن موعد متاح آخر واعرضه على المريض.")

    if result.appointment is None:
        raise ModelRetry("تم تنفيذ العملية، لكن لم تُرجع بيانات الموعد.")

    return "\n".join(
        [
            result.message,
            ("الخدمة: " f"{result.appointment.service}"),
            ("التاريخ: " f"{result.appointment.start_time:%Y-%m-%d}"),
            ("الوقت: " f"{result.appointment.start_time:%H:%M}"),
        ]
    )


@calendar_toolset.tool(requires_approval=True)
def reschedule_appointment(ctx: RunContext[AgentDependencies],event_id: str,new_start_time: datetime) -> str:
    """
    عدّل موعدًا موجودًا بعد موافقة المريض.

    يجب البحث عن موعد المريض أولًا ثم التحقق من توفر الوقت الجديد.
    """
    del ctx

    appointment_update = AppointmentUpdate(
        event_id=event_id,
        new_start_time=new_start_time,
        duration_minutes=(settings.appointment_duration_minutes),
    )

    result = update_appointment(appointment_update)

    if not result.success:
        raise ModelRetry(
            f"{result.message} "
            "ابحث عن وقت متاح آخر."
        )

    if result.appointment is None:
        raise ModelRetry("تم تنفيذ التعديل، لكن لم تُرجع بيانات الموعد.")

    return "\n".join(
        [
            result.message,
            (
                "الموعد الجديد: "
                f"{result.appointment.start_time:%Y-%m-%d %H:%M}"
            ),
        ]
    )


@calendar_toolset.tool(requires_approval=True,)
def remove_appointment(ctx: RunContext[AgentDependencies],event_id: str,reason: str | None = None,) -> str:
    del ctx

    print(f"طلب إلغاء الموعد: {event_id}", flush=True)

    cancellation = AppointmentCancellation(event_id=event_id,reason=reason)

    result = cancel_appointment(cancellation)

    if not result.success:
        raise ModelRetry(result.message)

    return result.message


openai_model = OpenAIChatModel(
    settings.openai_model.removeprefix("openai:"),
    provider=OpenAIProvider(api_key=settings.openai_api_key),
)


clinic_agent = Agent[AgentDependencies, ClinicAgentResponse | DeferredToolRequests](
    model=openai_model,
    deps_type=AgentDependencies,
    output_type=[ClinicAgentResponse,DeferredToolRequests],
    toolsets=[knowledge_toolset,calendar_toolset],
    retries={"tools": 0,"output": 0},
    tool_timeout=30,
    instructions="""
    أنت مساعد استقبال إداري لعيادة أسنان في الرياض.

    - جميع الأوقات التي يذكرها المستخدم تُفسَّر بتوقيت الرياض.
    - عند إنشاء قيمة datetime للحجز أو التعديل، استخدم توقيت Asia/Riyadh ولا تستخدم UTC.    

    مهامك:
    - الإجابة عن أسئلة العيادة باستخدام قاعدة المعرفة.
    - عرض المواعيد المتاحة.
    - مساعدة المريض في الحجز والتعديل والإلغاء.

    قاعدة المعرفة:
    - استخدم أداة المعرفة فقط لأسئلة الخدمات والأسعار وساعات العمل والسياسات.
    - استدعِ أداة المعرفة مرة واحدة فقط لكل طلب.
    - أجب اعتمادًا على النتائج المسترجعة فقط.
    - إذا لم تتوفر المعلومة، أخبر المستخدم بذلك بوضوح.

    المواعيد:
    - جميع المواعيد حسب توقيت الرياض.
    - قبل الحجز، يجب توفر: الاسم، رقم الهاتف، الخدمة، التاريخ والوقت.
    - إذا كانت بيانات الحجز ناقصة، اطلب فقط البيانات الناقصة ولا تستخدم الأدوات.
    - لا تتحقق من التوفر قبل أن يحدد المستخدم تاريخًا ووقتًا واضحين.
    - بعد اكتمال بيانات الحجز، تحقق من توفر الموعد مرة واحدة.
    - إذا كان الموعد متاحًا، استدعِ أداة الحجز مرة واحدة فقط.

    البحث عن مواعيد المريض:
    - استخدم رقم الهاتف الموجود في الرسالة الحالية أو في سجل المحادثة.
    - إذا لم يتوفر رقم الهاتف، اطلبه من المستخدم ولا تستدعِ أداة البحث.
    - استدعِ أداة البحث عن مواعيد المريض مرة واحدة فقط لكل طلب.
    - بعد عودة نتائج البحث، استخدمها مباشرة ولا تكرر البحث.
    - إذا لم توجد مواعيد، أخبر المستخدم بذلك مباشرة.

    التعديل والإلغاء:
    - قبل التعديل أو الإلغاء، حدد الموعد المطلوب من نتائج البحث الحالية أو السابقة.
    - إذا وُجد أكثر من موعد ولم يكن المقصود واضحًا، اطلب من المستخدم تحديد الموعد.
    - بعد تحديد الموعد، استخدم معرّفه مباشرة مع أداة التعديل أو الإلغاء.
    - استدعِ أداة التعديل أو الإلغاء مرة واحدة فقط.

    الموافقة البشرية:
    - الحجز والتعديل والإلغاء تستخدم موافقة بشرية مؤجلة داخل الأدوات.
    - لا تطلب من المستخدم تأكيدًا نصيًا قبل استدعاء أداة الكتابة.
    - واجهة Telegram تعرض أزرار التأكيد والإلغاء تلقائيًا.
    - بعد نجاح الحجز أو التعديل أو الإلغاء، أعطِ الرد النهائي مباشرة ولا تستدعِ أداة أخرى.

    قواعد عامة للأدوات:
    - لا تستدعِ الأداة نفسها أكثر من مرة بالمعاملات نفسها.
    - إذا أعادت الأداة نتيجة ناجحة، استخدم النتيجة مباشرة في الرد النهائي.

    السلامة:
    - أنت مساعد إداري ولست طبيبًا.
    - لا تقدم تشخيصًا أو وصفات أو جرعات علاجية.
    - عند وجود حالة طارئة أو أعراض خطيرة، وجّه المستخدم إلى خدمات الطوارئ أو أقرب منشأة صحية.

    الرد:
    - استخدم العربية الواضحة.
    - اجعل الرد مختصرًا ومباشرًا.
    - لا تعرض معرّفات Google Calendar الداخلية للمستخدم.
    """
)


async def run_reception_agent(message: str,dependencies: AgentDependencies,message_history: Sequence[ModelMessage] | None = None):
    return await clinic_agent.run(message,deps=dependencies,message_history=message_history)


async def resolve_tool_approval(
    message_history: Sequence[ModelMessage],
    deferred_requests: DeferredToolRequests,
    dependencies: AgentDependencies,
    approved: bool,
):
    deferred_results = DeferredToolResults()

    for call in deferred_requests.approvals:
        if approved:
            deferred_results.approvals[call.tool_call_id] = True
        else:
            deferred_results.approvals[call.tool_call_id] = ToolDenied(
                "رفض المريض تنفيذ العملية."
            )

    return await clinic_agent.run(
        deps=dependencies,
        message_history=message_history,
        deferred_tool_results=deferred_results,
    )


if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        dependencies = AgentDependencies()

        result = await run_reception_agent(
            message="كم سعر تنظيف الأسنان؟",
            dependencies=dependencies,
        )

        if isinstance(result.output, DeferredToolRequests):
            print("تحتاج العملية إلى موافقة.")
        else:
            print(result.output.message)

    asyncio.run(main())