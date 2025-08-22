from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from app.services.weeks_service import WeeksService
from datetime import timedelta

router = Router(name="owner_weeks_admin")

@router.message(F.text.startswith("/weeks_import"))
async def weeks_import(message: Message, weeks: WeeksService, owner_id: int):
    """
    Импортировать недели из CSV файла
    /weeks_import [путь_к_файлу]
    """
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Формат: /weeks_import [путь_к_файлу]\n\n"
            "Например: /weeks_import data/Weeks_CSV_Preview.csv"
        )
        return
    
    file_path = parts[1].strip()
    
    try:
        weeks.populate_from_csv(file_path)
        await message.answer(f"✅ Недели успешно импортированы из {file_path}")
        
        # Показываем что получилось
        weeks_list = weeks.list_all_weeks()
        if not weeks_list.empty:
            lines = ["📚 Импортированные недели:"]
            for _, row in weeks_list.head(5).iterrows():  # Показываем первые 5
                status = row["status_emoji"]
                deadline_str = row["deadline_date"].strftime('%d.%m.%Y')
                lines.append(f"{status} <b>{row['week']}. {row['title']}</b> (до {deadline_str})")
            
            if len(weeks_list) > 5:
                lines.append(f"... и еще {len(weeks_list) - 5} недель")
                
            await message.answer("\n".join(lines), parse_mode="HTML")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка импорта: {str(e)}")

@router.message(F.text == "/weeks_list")
async def weeks_list(message: Message, weeks: WeeksService, owner_id: int):
    """Показать список всех недель"""
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
    
    weeks_df = weeks.list_all_weeks()
    if weeks_df.empty:
        await message.answer("📚 Недели не загружены. Используйте /weeks_import")
        return
    
    lines = ["📚 <b>Все недели курса:</b>"]
    for _, row in weeks_df.iterrows():
        status = row["status_emoji"]
        deadline_str = row["deadline_date"].strftime('%d.%m.%Y')
        lines.append(f"<b>{row['week']}. {row['title']}</b>")
        lines.append(f"   📅 Дедлайн: {deadline_str} {status}")
        lines.append("")  # Пустая строка для разделения
    
    # Разбиваем на части если слишком длинное сообщение
    full_text = "\n".join(lines)
    if len(full_text) > 4000:
        # Отправляем по частям
        current_message = lines[0] + "\n"  # Заголовок
        for line in lines[1:]:
            if len(current_message + line + "\n") > 4000:
                await message.answer(current_message, parse_mode="HTML")
                current_message = line + "\n"
            else:
                current_message += line + "\n"
        
        if current_message.strip():
            await message.answer(current_message, parse_mode="HTML")
    else:
        await message.answer(full_text, parse_mode="HTML")

@router.message(F.text.startswith("/week_info"))
async def week_info(message: Message, weeks: WeeksService, owner_id: int):
    """Показать подробную информацию о конкретной недели"""
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /week_info [номер_недели]")
        return
    
    try:
        week_number = int(parts[1])
    except ValueError:
        await message.answer("Номер недели должен быть числом")
        return
    
    week_info = weeks.get_week(week_number)
    if not week_info:
        await message.answer(f"Неделя {week_number} не найдена")
        return
    
    status_emoji = "🔴" if week_info["is_overdue"] else "🟢"
    
    text = f"📋 <b>Неделя {week_info['week']}: {week_info['title']}</b>\n\n" \
           f"📝 <b>Описание:</b>\n{week_info['description']}\n\n" \
           f"📅 <b>Дедлайн:</b> {week_info['deadline_str']} {status_emoji}\n\n" \
           f"🔧 <b>Технические детали:</b>\n" \
           f"• Статус: {'Просрочено' if week_info['is_overdue'] else 'Актуально'}\n" \
           f"• Дедлайн: {week_info['deadline_date']}"
    
    await message.answer(text, parse_mode="HTML")