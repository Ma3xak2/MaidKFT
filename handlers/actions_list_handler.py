# handlers/actions_list_handler.py

import math
import logging

from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CallbackQueryHandler

from config.config_loader import load_actions_normalized

logger = logging.getLogger(__name__)

# Сколько элементов показываем на странице
ITEMS_PER_PAGE = 20

# Через сколько секунд удалять сообщение с листингом
ACTION_DELETE_TIMEOUT = 180

# Словарь для хранения запущенных задач (job) удаления:
# ключ = (chat_id, message_id), значение = Job
ACTION_JOBS: dict[tuple[int, int], object] = {}


def _build_page_text(actions_dict: dict[str, str], page: int) -> tuple[str, int]:
    """
    Возвращает (текст_страницы, total_pages).
    """
    keys = sorted(actions_dict.keys())
    total_items = len(keys)
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1

    # Нормализуем номер страницы в диапазоне [0, total_pages-1]
    page = page % total_pages

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    slice_keys = keys[start:end]

    if not slice_keys:
        text = "❗️ Действий не найдено."
    else:
        lines = []
        for key in slice_keys:
            template = actions_dict[key]
            lines.append(f"• <b>{key}</b>: {template}")
        text = "\n".join(lines)

    return text, total_pages


def _build_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    prev_page = (page - 1) % total_pages
    next_page = (page + 1) % total_pages

    buttons = [
        InlineKeyboardButton("⬅️ Назад", callback_data=f"actions:page:{prev_page}"),
        InlineKeyboardButton("❌ Убрать", callback_data="actions:delete"),
        InlineKeyboardButton("Вперёд ➡️", callback_data=f"actions:page:{next_page}")
    ]
    return InlineKeyboardMarkup([buttons])


async def _delete_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Задача, которую запускает job_queue: удаляет сообщение и очищает запись из ACTION_JOBS.
    """
    data = context.job.data
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")

    if chat_id is None or message_id is None:
        return

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение (job): {e}")

    # Удаляем из словаря запоминающих задач
    ACTION_JOBS.pop((chat_id, message_id), None)


async def list_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Отправляет пользователю первое сообщение с листингом действий из actions.yaml,
    удаляет команду пользователя и сразу ставит задачу на удаление списка через ACTION_DELETE_TIMEOUT секунд.
    """
    # Сразу удаляем сообщение с командой, чтобы не засорять чат
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass

    actions = load_actions_normalized()
    page = 0
    text, total_pages = _build_page_text(actions, page)
    keyboard = _build_keyboard(page, total_pages)

    try:
        bot_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                f"📖 Список действий "
                f"(страница <b>{page+1}</b> из <b>{total_pages}</b>):\n\n"
                f"{text}"
            ),
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Не удалось отправить список действий: {e}")
        return

    # Планируем удаление через ACTION_DELETE_TIMEOUT секунд
    job = context.job_queue.run_once(
        _delete_message_job,
        ACTION_DELETE_TIMEOUT,
        data={'chat_id': bot_message.chat.id, 'message_id': bot_message.message_id}
    )
    ACTION_JOBS[(bot_message.chat.id, bot_message.message_id)] = job


async def actions_pagination_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обрабатывает нажатия по inline-кнопкам «⬅️ Назад», «Вперёд ➡️» и «❌ Убрать».
    При перелистывании отменяет старую задачу удаления и ставит новую.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data  # строка вида "actions:page:2" или "actions:delete"
    await query.answer()  # скрываем «часики»

    chat_id = query.message.chat.id
    message_id = query.message.message_id

    # Если нажали «❌ Убрать» — просто удаляем сразу сообщение и отменяем job
    if data == "actions:delete":
        # Отменяем ранее запланированную задачу удаления (если есть)
        job = ACTION_JOBS.pop((chat_id, message_id), None)
        if job:
            job.schedule_removal()
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение с листингом: {e}")
        return

    # Если нажатие «actions:page:N» — перелистываем страницу
    if data.startswith("actions:page:"):
        try:
            page = int(data.split(":")[-1])
        except ValueError:
            return

        actions = load_actions_normalized()
        text, total_pages = _build_page_text(actions, page)
        keyboard = _build_keyboard(page, total_pages)

        new_text = (
            f"📖 Список действий "
            f"(страница <b>{page+1}</b> из <b>{total_pages}</b>):\n\n"
            f"{text}"
        )

        # Отменяем старую задачу удаления (если была)
        old_job = ACTION_JOBS.pop((chat_id, message_id), None)
        if old_job:
            old_job.schedule_removal()

        try:
            # Редактируем текст и клавиатуру в том же сообщении
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=new_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.warning(f"Не удалось обновить страницу списка действий: {e}")
            return

        # Ставим новую задачу удаления для обновлённого сообщения
        job = context.job_queue.run_once(
            _delete_message_job,
            ACTION_DELETE_TIMEOUT,
            data={'chat_id': chat_id, 'message_id': message_id}
        )
        ACTION_JOBS[(chat_id, message_id)] = job
        return

    # В остальных случаях ничего не делаем
    return


def get_actions_callback_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(actions_pagination_handler, pattern=r"^actions:(?:page:\d+|delete)$")
