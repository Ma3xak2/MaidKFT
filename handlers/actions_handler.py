import logging
from telegram import Update, MessageEntity
from telegram.ext import ContextTypes

from config.config_loader import load_actions_normalized

logger = logging.getLogger(__name__)


async def handle_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик RP-действий. На каждое входящее текстовое сообщение (не-команду)
    перечитываем актуальный список ACTIONS из actions.yaml, удаляем сообщение пользователя
    и отправляем только ответ бота.
    """
    ACTIONS = load_actions_normalized()  # каждый раз свежие данные из config/actions.yaml
    message = update.message
    if not message or not message.text:
        return

    text = message.text
    lower_text = text.lower()

    mentioned_user = None
    action_key = None

    # 1) Сначала ищем «text_mention» — это entity с готовым ent.user
    for ent in message.entities or []:
        if ent.type == "text_mention" and ent.user:
            mentioned_user = f"@{ent.user.username}" if ent.user.username else ent.user.first_name
            start = ent.offset + ent.length
            action_key = text[start:].strip().lower()
            break

    # 2) Если не было text_mention, ищем ручное @mention
    if not mentioned_user:
        for ent in message.entities or []:
            if ent.type == "mention":
                uname = text[ent.offset : ent.offset + ent.length]  # вида "@username"
                mentioned_user = uname
                start = ent.offset + ent.length
                action_key = text[start:].strip().lower()
                break

    # 3) Если mention не было, но сообщение – reply
    if not mentioned_user and message.reply_to_message:
        target = message.reply_to_message.from_user
        mentioned_user = f"@{target.username}" if target.username else target.first_name
        action_key = text.strip().lower()

    if not mentioned_user or not action_key:
        return

    # Убираем лишние пробелы и знаки
    action_key = action_key.strip().rstrip('.,!')

    template = ACTIONS.get(action_key)
    if not template:
        return

    sender = message.from_user
    sender_name = f"@{sender.username}" if sender.username else sender.first_name

    try:
        # Формируем ответ
        response = template.format(user1=sender_name, user2=mentioned_user)
    except KeyError as e:
        logger.error(f"Ошибка форматирования шаблона для действия «{action_key}»: отсутствует плейсхолдер {e}")
        return
    except Exception as e:
        logger.error(f"Не удалось сгенерировать ответ для действия «{action_key}»: {e}")
        return

    # Пытаемся удалить исходное сообщение
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение пользователя {message.from_user.id}: {e}")

    # Отправляем ответ бота (не как reply, а как обычное сообщение)
    try:
        await context.bot.send_message(chat_id=message.chat.id, text=response)
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа для действия «{action_key}»: {e}")
