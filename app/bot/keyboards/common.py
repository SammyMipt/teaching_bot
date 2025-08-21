from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

def slots_keyboard(slots_df):
    kb = InlineKeyboardBuilder()
    for _, row in slots_df.iterrows():
        text = f"{row['slot_id']} | {row['date']} {row['time_from']}-{row['time_to']} ({row['mode']})"
        kb.row(InlineKeyboardButton(text=text, callback_data=f"book:{row['slot_id']}"))
    return kb.as_markup()
