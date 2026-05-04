from pathlib import Path
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from config import settings
from services.file_manager import get_weekly_path, read_file, count_tasks

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 <b>Obsidian Task Bot</b>\n\n"
        "Скинь текст итогов собрания или новые задачи — "
        "я извлеку изменения и обновлю файл задач в Obsidian.\n\n"
        "Команды:\n"
        "/status — текущий недельный файл\n"
        "/week — показать содержимое файла",
        parse_mode="HTML",
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    vault = settings.vault
    path = get_weekly_path(vault)

    if not path.exists():
        await message.answer(
            f"📂 Файл ещё не создан:\n<code>{path}</code>\n\n"
            "Отправь текст задач — создам автоматически.",
            parse_mode="HTML",
        )
        return

    content = read_file(path)
    open_, done = count_tasks(content)
    await message.answer(
        f"📂 <b>Текущий файл:</b> <code>{path.name}</code>\n"
        f"📍 <code>{path}</code>\n\n"
        f"✅ Выполнено: {done}\n"
        f"⏳ Открыто: {open_}",
        parse_mode="HTML",
    )


@router.message(Command("week"))
async def cmd_week(message: Message) -> None:
    vault = settings.vault
    path = get_weekly_path(vault)

    if not path.exists():
        await message.answer("Файл задач на эту неделю ещё не создан.")
        return

    content = read_file(path)
    if len(content) > 3800:
        content = content[:3800] + "\n\n…(обрезано)"

    await message.answer(
        f"<b>{path.name}</b>\n\n<pre>{content}</pre>",
        parse_mode="HTML",
    )
