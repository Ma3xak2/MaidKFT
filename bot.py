import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from config.config_loader import load_config
from handlers.admin_handler import add_action, delete_action
from handlers.command_handler import CustomCommandHandler
from handlers.mute_handler import MuteManager
from handlers.actions_handler import handle_actions  # handle_actions всегда подгружает свежий actions.yaml

# Новые импорты для листинга действий
from handlers.actions_list_handler import list_actions, get_actions_callback_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальная переменная с конфигом, которую будем перезагружать по команде
CONFIG = load_config()


def get_config() -> dict:
    return CONFIG


def reload_config() -> None:
    global CONFIG
    CONFIG = load_config()
    # При перезагрузке конфига имеет смысл очистить кэш админов, если он где-то кэшируется.
    # В handlers/admin_handler.ADMINS_CACHE можно, например, сбрасывать:
    try:
        from handlers.admin_handler import ADMINS_CACHE
        ADMINS_CACHE = None
    except ImportError:
        pass

    logger.info("🔄 Конфиг перезагружен")


async def reload_command(update, context) -> None:
    user_id = update.effective_user.id
    admins = get_config().get("ADMINS", [])
    if user_id not in admins:
        await update.message.reply_text("🚫 У вас нет доступа к этой команде.")
        return

    reload_config()
    await update.message.reply_text("🔄 Конфигурация перезагружена.")


def main() -> None:
    logger.info("🚀 Бот запущен")
    config = get_config()
    token = config.get("BOT_TOKEN")
    if not token:
        logger.error("❌ BOT_TOKEN не задан в config.yaml")
        return

    app = ApplicationBuilder().token(token).build()

    # 0. Менеджер «кляпа»
    mute_mgr = MuteManager(get_config)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, mute_mgr.handle_message),
        group=0
    )

    # 1. RP-действия (handle_actions каждый раз читает свежий actions.yaml)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_actions),
        group=1
    )

    # 2. Команды из CONFIG["COMMANDS_CONFIG"]
    cmd_handler = CustomCommandHandler(get_config)
    for cmd_name in config.get("COMMANDS_CONFIG", {}):
        app.add_handler(
            CommandHandler(cmd_name, cmd_handler.handle, block=False),
            group=2
        )

    # 3. Админ-команды: /reload, /addact, /delact
    app.add_handler(CommandHandler("reload", reload_command), group=2)
    app.add_handler(CommandHandler("addact", add_action), group=2)
    app.add_handler(CommandHandler("delact", delete_action), group=2)

    # 4. Новая команда /actions — выводит список действий с кнопками пагинации
    app.add_handler(CommandHandler("actions", list_actions), group=2)
    # 5. Обработчик нажатий на inline-кнопки (CallbackQuery) от /actions
    app.add_handler(get_actions_callback_handler(), group=2)

    app.run_polling()


if __name__ == "__main__":
    main()
