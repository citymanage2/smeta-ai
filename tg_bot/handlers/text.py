import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import settings
from services.claude import extract_changes
from services.file_manager import get_weekly_path, ensure_template, write_file

router = Router()


class ConfirmState(StatesGroup):
    waiting = State()


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Записать", callback_data="confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    ]])


@router.message(F.text & ~F.text.startswith("/"))
async def handle_meeting_notes(message: Message, state: FSMContext) -> None:
    vault = settings.vault
    weekly_path = get_weekly_path(vault)
    current_content = ensure_template(weekly_path)

    wait_msg = await message.answer("⏳ Обрабатываю через Claude...")

    try:
        result = await extract_changes(current_content, message.text)
    except Exception as e:
        await wait_msg.delete()
        await message.answer(f"❌ Ошибка Claude: {e}")
        return

    await wait_msg.delete()

    if not result.changes:
        await message.answer("Изменений не обнаружено.")
        return

    changes_text = "\n".join(f"• {c}" for c in result.changes)
    preview = (
        f"📋 <b>Обнаруженные изменения:</b>\n\n"
        f"{changes_text}\n\n"
        f"Записать в файл <code>{weekly_path.name}</code>?"
    )

    await state.set_state(ConfirmState.waiting)
    await state.update_data(updated_content=result.updated_content, file_path=str(weekly_path))

    await message.answer(preview, parse_mode="HTML", reply_markup=_confirm_kb())


@router.callback_query(ConfirmState.waiting, F.data == "confirm")
async def on_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()

    from pathlib import Path
    file_path = Path(data["file_path"])
    content = data["updated_content"]

    try:
        await write_file(file_path, content)
        await callback.message.edit_text(f"✅ Файл обновлён: <code>{file_path.name}</code>", parse_mode="HTML")
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка записи: {e}")

    await callback.answer()


@router.callback_query(ConfirmState.waiting, F.data == "cancel")
async def on_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Отменено. Файл не изменён.")
    await callback.answer()
