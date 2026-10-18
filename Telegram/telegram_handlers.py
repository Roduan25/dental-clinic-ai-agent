import logging
from typing import Any

from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ModelMessage
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from agent import (
    AgentDependencies,
    resolve_tool_approval,
    run_reception_agent,
)

logger = logging.getLogger(__name__)


HISTORY_KEY = "message_history"
DEFERRED_REQUEST_KEY = "deferred_request"
DEFERRED_HISTORY_KEY = "deferred_history"


def get_dependencies(update: Update) -> AgentDependencies:
    user = update.effective_user

    return AgentDependencies(
        telegram_user_id=(user.id if user is not None else None),
        telegram_username=(user.username if user is not None else None),
    )

def get_message_history(context: ContextTypes.DEFAULT_TYPE) -> list[ModelMessage]:
    history = context.user_data.get(HISTORY_KEY, [])

    if isinstance(history, list):
        return history

    return []


def get_approval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="✅ تأكيد",
                    callback_data="approval:yes",
                ),
                InlineKeyboardButton(
                    text="❌ إلغاء",
                    callback_data="approval:no",
                ),
            ]
        ]
    )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()

    message = update.effective_message

    if message is None:
        return

    await message.reply_text(
        "مرحبًا بك في مساعد عيادة الأسنان 🦷\n\n"
        "اكتب سؤالك أو طلبك بصورة طبيعية."
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()

    message = update.effective_message

    if message is None:
        return

    await message.reply_text("تم مسح المحادثة السابقة.")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE,) -> None:
    message = update.effective_message

    if message is None or not message.text:
        return

    processing_message = await message.reply_text("⏳ جارٍ معالجة طلبك...")

    try:
        result = await run_reception_agent(
            message=message.text.strip(),
            dependencies=get_dependencies(update),
            message_history=get_message_history(context),
        )

        if isinstance(result.output, DeferredToolRequests):
            context.user_data[DEFERRED_REQUEST_KEY] = (result.output)

            context.user_data[DEFERRED_HISTORY_KEY] = (result.all_messages())

            await processing_message.edit_text(
                text=(
                    "العملية جاهزة للتنفيذ.\n\n"
                    "هل تريد تأكيد العملية؟"
                ),
                reply_markup=get_approval_keyboard(),
            )

            return

        context.user_data[HISTORY_KEY] = (result.all_messages())

        await processing_message.edit_text(result.output.message)

    except Exception:
        logger.exception("حدث خطأ أثناء تشغيل الوكيل.")

        await processing_message.edit_text("عذرًا، حدث خطأ أثناء معالجة طلبك.")


async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if query is None or query.data is None:
        return

    await query.answer()

    deferred_request = context.user_data.get(DEFERRED_REQUEST_KEY)

    deferred_history = context.user_data.get(DEFERRED_HISTORY_KEY)

    if (not isinstance(deferred_request, DeferredToolRequests) or not isinstance(deferred_history, list)):
        await query.edit_message_text("انتهت صلاحية طلب التأكيد.")

        return

    approved = query.data == "approval:yes"

    await query.edit_message_text("⏳ جارٍ تنفيذ العملية..." if approved else "⏳ جارٍ إلغاء العملية...")

    try:
        result = await resolve_tool_approval(
            message_history=deferred_history,
            deferred_requests=deferred_request,
            dependencies=get_dependencies(update),
            approved=approved,
        )

        context.user_data.pop(DEFERRED_REQUEST_KEY, None)
        context.user_data.pop(DEFERRED_HISTORY_KEY, None)

        if isinstance(result.output, DeferredToolRequests):
            context.user_data[DEFERRED_REQUEST_KEY] = (result.output)
            context.user_data[DEFERRED_HISTORY_KEY] = (result.all_messages())

            await query.edit_message_text(
                text="توجد عملية أخرى تحتاج إلى موافقتك.",
                reply_markup=get_approval_keyboard(),
            )
            return

        context.user_data[HISTORY_KEY] = (result.all_messages())

        await query.edit_message_text(result.output.message)

    except Exception:
        logger.exception("حدث خطأ أثناء تنفيذ العملية المؤجلة.")

        await query.edit_message_text("تعذر تنفيذ العملية. يرجى المحاولة مرة أخرى.")