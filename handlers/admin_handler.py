import logging
import re
from telegram import Update
from telegram.ext import ContextTypes

from config.config_loader import load_config, save_actions

logger = logging.getLogger(__name__)

ADMINS_CACHE: list[int] | None = None  # кэш админов при первом обращении


def _get_admins() -> list[int]:
    global ADMINS_CACHE
    if ADMINS_CACHE is None:
        cfg = load_config()
        ADMINS_CACHE = cfg.get("ADMINS", [])
    return ADMINS_CACHE


async def add_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in _get_admins():
        await update.message.reply_text("🚫 У вас нет доступа к этой команде.")
        return

    if len(context.args) == 0 or ':' not in ' '.join(context.args):
        await update.message.reply_text("Использование: /addact команда: шаблон")
        return

    text = ' '.join(context.args)
    parts = text.split(':', 1)
    action = parts[0].strip().lower()
    template = parts[1].strip()

    try:
        # Загрузим существующие действия, обновим и сохраним
        cfg = load_config()
        actions = cfg.get("ACTIONS", {})
        if action in actions:
            await update.message.reply_text(f"⚠️ Действие «{action}» уже существует.")
            return

        actions[action] = template
        save_actions(actions)
        # Сбросим кэш админов (на случай, если они редактировали ADMINS в config.yaml)
        global ADMINS_CACHE
        ADMINS_CACHE = None

        await update.message.reply_text(f"✅ Добавлено действие: «{action}»")
    except Exception as e:
        logger.error(f"Ошибка при добавлении действия: {e}")
        await update.message.reply_text("❌ Произошла ошибка при добавлении действия.")


async def delete_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in _get_admins():
        await update.message.reply_text("🚫 У вас нет доступа к этой команде.")
        return

    if len(context.args) == 0:
        await update.message.reply_text("Использование: /delact команда")
        return

    action = ' '.join(context.args).strip().lower()

    try:
        cfg = load_config()
        actions = cfg.get("ACTIONS", {})

        if action not in actions:
            await update.message.reply_text(f"❌ Действие «{action}» не найдено.")
            return

        del actions[action]
        save_actions(actions)
        # Сбросим кэш админов для перестраховки
        global ADMINS_CACHE
        ADMINS_CACHE = None

        await update.message.reply_text(f"🗑️ Действие «{action}» удалено.")
    except Exception as e:
        logger.error(f"Ошибка при удалении действия: {e}")
        await update.message.reply_text("❌ Произошла ошибка при удалении действия.")
