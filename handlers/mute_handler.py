import asyncio
import logging
import random
from datetime import datetime, timedelta
from telegram import Update, User
from telegram.ext import ContextTypes

from config.config_loader import load_config
from utils.time_parser import parse_duration, parse_until

logger = logging.getLogger(__name__)


class MuteManager:
    def __init__(self, config_getter):
        self.get_cfg = config_getter
        # active_gags: user_id -> {'job': Job, 'expires': datetime}
        self.active_gags: dict[int, dict] = {}

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if not msg or not msg.text:
            return

        text = msg.text
        lower = text.lower()
        cfg = self.get_cfg()
        uid = msg.from_user.id

        # A. Сначала команды на снятие кляпа
        for cmd in cfg.get('UNGAGS', []):
            if lower.startswith(cmd):
                return await self._ungag(msg, context)

        # B. Потом команды на надеть кляп
        for cmd in cfg.get('GAGS', []):
            if lower.startswith(cmd):
                return await self._gag(msg, context)

        # C. Если пользователь под кляпом, удаляем его сообщение и «мямлим»
        if uid in self.active_gags:
            try:
                await msg.delete()
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение пользователя {uid}: {e}")

            mumble = random.choice(cfg.get('MUMBLES', []))
            try:
                sent = await context.bot.send_message(
                    chat_id=msg.chat.id,
                    text=f"{self._format_mention(msg.from_user)}: {mumble}"
                )
                # Удалим «мямление» через 5 секунд
                asyncio.create_task(self._delayed_delete(msg.chat.id, sent.message_id, 5, context))
            except Exception as e:
                logger.error(f"Ошибка при отправке «мямления» для {uid}: {e}")
            return

        # D. Иначе – пропускаем дальше
        return

    async def _gag(self, msg: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        target = await self._get_target(msg, context)
        if not target:
            await msg.reply_text("⚠️ Не найден пользователь для кляпа. Используй reply или @username.")
            return

        # Парсим время: либо «10с», «5м», либо «до HH:MM»
        dur = parse_duration(msg.text)
        until = parse_until(msg.text)
        if dur is None and until is None:
            await msg.reply_text("⚠️ Укажи время: «10с», «5м», «2ч» или «до HH:MM»")
            return

        seconds = dur if dur else int((until - datetime.now()).total_seconds())
        if seconds <= 0:
            await msg.reply_text("⚠️ Неправильное время.")
            return

        try:
            await msg.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить команду для кляпа: {e}")

        admin = msg.from_user
        try:
            await context.bot.send_message(
                chat_id=msg.chat.id,
                text=(
                    f"{self._format_mention(admin)} надел кляп "
                    f"на {self._format_mention(target)} на {self._format_time_fmt(seconds)}"
                )
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение о кляпе: {e}")

        job = context.job_queue.run_once(
            self._expire_gag, seconds,
            data={'user_id': target.id}
        )
        self.active_gags[target.id] = {
            'job': job,
            'expires': datetime.now() + timedelta(seconds=seconds)
        }

    async def _ungag(self, msg: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = msg.from_user.id
        cfg = load_config()  # получаем свежий config, чтобы знать актуальных ADMINS
        admins = cfg.get("ADMINS", [])

        target = await self._get_target(msg, context)
        if not target:
            await msg.reply_text("⚠️ Не найден пользователь для снятия кляпа.")
            return

        # Если юзер хочет снять чужой кляп, проверяем права
        if target.id != user_id and user_id not in admins:
            await msg.reply_text("🚫 Только админ может снять кляп с другого пользователя.")
            return

        try:
            await msg.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить команду для снять кляп: {e}")

        rec = self.active_gags.pop(target.id, None)
        if rec:
            rec['job'].schedule_removal()
            await context.bot.send_message(
                chat_id=msg.chat.id,
                text=f"✅ {self._format_mention(target)} освобождён(а) от кляпа"
            )
        else:
            await context.bot.send_message(
                chat_id=msg.chat.id,
                text=f"⚠️ {self._format_mention(target)} не был(а) в кляпе"
            )

    async def _expire_gag(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = context.job.data['user_id']
        self.active_gags.pop(uid, None)

    async def _get_target(self, msg: Update, context: ContextTypes.DEFAULT_TYPE) -> User | None:
        # Если reply — цель в reply_to_message
        if msg.reply_to_message:
            return msg.reply_to_message.from_user

        # Проверяем TextMention (он всегда содержит объект User)
        for ent in msg.entities or []:
            if ent.type == 'text_mention' and ent.user:
                return ent.user

        # Иначе ищем упоминание @username в entities
        for ent in msg.entities or []:
            if ent.type == 'mention':
                uname = msg.text[ent.offset:ent.offset + ent.length]  # вида "@username"
                # Убираем "@"
                username = uname.lstrip('@')
                try:
                    member = await context.bot.get_chat_member(msg.chat.id, username)
                    return member.user
                except Exception as e:
                    logger.warning(f"Не удалось найти пользователя {username} в чате: {e}")
                    return None
        return None

    def _format_mention(self, user: User) -> str:
        return f"@{user.username}" if user.username else (user.first_name or "user")

    def _format_time_fmt(self, seconds: int) -> str:
        mins, secs = divmod(seconds, 60)
        parts = []
        if mins:
            parts.append(f"{mins}м")
        if secs or not parts:
            parts.append(f"{secs}с")
        return "".join(parts)

    async def _delayed_delete(
        self, chat_id: int, message_id: int, delay: int, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await asyncio.sleep(delay)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.debug(f"Не удалось удалить мямление {message_id}: {e}")
