import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class CustomCommandHandler:
    def __init__(self, config_getter):
        self.get_config = config_getter
        # ключ: "<flag>_<user_id>"
        self.active_flags: dict[str, bool] = {}

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        config = self.get_config()
        commands = config.get("COMMANDS_CONFIG", {})

        text = update.message.text or ""
        # Уберём возможный «@BotUsername» после команды
        command_name = text.split('@')[0][1:].lower()
        user_id = update.message.from_user.id

        command_data = commands.get(command_name)
        if not command_data:
            return

        flag = command_data.get("flag")
        cache_key = f"{flag}_{user_id}"

        # Удаляем сообщение пользователя с командой (если есть права)
        await self._safe_delete(update.effective_chat.id, update.message.message_id, context)

        # Если флаг ещё активен — отправим warning
        if cache_key in self.active_flags:
            warning = command_data.get("warning", "⚠️ Команда уже была использована.")
            await self._send_temporary_message(update.effective_chat.id, warning, 5, context)
            return

        # Устанавливаем флаг и отправляем основной текст
        self.active_flags[cache_key] = True
        try:
            bot_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=command_data.get("text", ""),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение по команде /{command_name}: {e}")
            # Если не удалось отправить, сбрасываем флаг, чтобы не блокировать бесконечно
            self.active_flags.pop(cache_key, None)
            return

        # Через cooldown секунд вернём «флаг» свободным и удалим сообщение
        cooldown = command_data.get("cooldown", 180)
        context.job_queue.run_once(
            self._cleanup,
            cooldown,
            data={
                'chat_id': update.effective_chat.id,
                'message_id': bot_message.message_id,
                'cache_key': cache_key
            }
        )

    async def _send_temporary_message(
        self, chat_id: int, text: str, delay: int, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        try:
            msg = await context.bot.send_message(chat_id=chat_id, text=text)
            # Удалим предупреждение через delay секунд
            asyncio.create_task(self._safe_delete(chat_id, msg.message_id, context, delay))
        except Exception as e:
            logger.error(f"Не удалось отправить временное сообщение: {e}")

    async def _safe_delete(
        self, chat_id: int, message_id: int, context: ContextTypes.DEFAULT_TYPE, delay: int = 0
    ) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.debug(f"Не удалось удалить сообщение {message_id}: {e}")

    async def _cleanup(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        data = context.job.data
        await self._safe_delete(data['chat_id'], data['message_id'], context)
        self.active_flags.pop(data['cache_key'], None)
