import re
from datetime import datetime, timedelta


def parse_duration(text: str) -> int | None:
    """
    Ищет в тексте форматы:
      - «10с», «5м», «2ч» (буквами: с, м, ч)
      - «10 сек», «5 секунд», «2 мин», «3 минуты», «1 час», «4 часа»
    Возвращает количество секунд или None.
    """
    txt = text.lower()

    # Сначала ищем форматы с буквами: 10с, 5м, 2ч, 10h, 5m
    match = re.search(r'(\d+)\s*([сmчh])\b', txt)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        if unit == 'с':
            return num
        if unit == 'm':
            # латинская m — считаем минуты
            return num * 60
        if unit == 'ч' or unit == 'h':
            return num * 3600

    # Ищем полные слова: секунд(ы), мин(ут)(ы), час(ов)(а)
    match_words = re.search(
        r'(\d+)\s*(секунд[ау]?|сек|минут[ау]?|мин|час(ов|а)?)\b', txt
    )
    if match_words:
        num = int(match_words.group(1))
        unit_word = match_words.group(2)
        if unit_word.startswith('сек'):
            return num
        if unit_word.startswith('мин'):
            return num * 60
        if unit_word.startswith('час'):
            return num * 3600

    return None


def parse_until(text: str) -> datetime | None:
    """
    Ищет формат «до HH:MM» или «до H:MM» и возвращает ближайший datetime в будущем,
    соответствующий указанному времени.
    """
    txt = text.lower()
    match = re.search(r'до\s+(\d{1,2}):(\d{2})', txt)
    if not match:
        return None

    hh = int(match.group(1))
    mm = int(match.group(2))
    now = datetime.now()
    try:
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except ValueError:
        return None  # Неверный формат времени

    # Если указанное время уже прошло сегодня — берём завтра
    if target <= now:
        target += timedelta(days=1)
    return target
