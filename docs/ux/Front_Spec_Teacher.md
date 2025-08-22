# Мини‑спецификация фронта — Преподаватель

## Общее
- Inline‑клавиатуры, короткие подтверждения (toast‑стиль), пагинация `‹ ›` + «Стр. X/Y».
- Единый формат `callback_data` (≤64 байт):
```
r=<role>;a=<action>;w=<week>;d=<yyyymmdd>;s=<slotId>;u=<userId>;p=<page>;f=<filter>
```
Пример: `r=t;a=slot_list;d=20250901;p=2`

## Actions (коды)
### Расписание
- `sched_create_start` → `sched_create_dates` → `sched_create_time` → `sched_create_len` → `sched_create_cap` → `sched_create_confirm`
- `sched_manage_dates` → `slot_list` → `slot_card` → `slot_actions`

### Слот
- `slot_open`, `slot_close`, `slot_delete`, `slot_edit`
- `slot_students` → `slot_student_view`

### Материалы
- `syllabus_view`
- `material_upload_pick_week` → `material_upload_wait_file`

### Сдачи
- `sub_act_dates` → `sub_act_slots` → `sub_act_students` → `sub_action_[download|grade]`
- `sub_past_pick_mode` ∈ {`by_slot`, `by_week`, `by_group`, `by_student`}

## Экранные шаблоны
### Карточка слота
```
⏰ 10:00–10:30 | 2025‑09‑01
👥 1/3 | Статус: 🟡 Частично свободен
[👨‍🎓 Студенты] [✏️ Изменить параметры] [🟢 Открыть/🚫 Закрыть] [❌ Удалить] [⬅️ Назад]
```
### Выставление оценки
- Кнопки: `5`, `4`, `3`, `2`, `1`, `Отмена`
- Toast: `✅ Оценка 5 для Иванов И.И. сохранена`
### Загрузка материалов
- Шаг 1: кнопки `W01..Wnn`
- Шаг 2: ожидание файла → `✅ Материалы для Wxx загружены`

## Фильтры и пагинация
- В списке слотов: фильтры `🟢`, `🟡`, `🔴`, `⚪`, `⚫` + «Сброс»
- Пагинация: `‹`, `›` + «Стр. X/Y»

## Логи (минимум)
- `TEACHER_SCHED_CREATE {teacher_id} {from_date} {to_date} {len} {cap} -> {n_slots}`
- `TEACHER_SLOT_ACTION {teacher_id} {slot_id} {action}`
- `TEACHER_MATERIAL_UPLOAD {teacher_id} {week} {file_id}`
- `TEACHER_GRADE_SET {teacher_id} {student_id} {week|slot_id} {grade}`

## Справочник статусов слотов
- 🟢 Свободен | 🟡 Частично свободен | 🔴 Занят | ⚪ Закрыт | ⚫ Прошёл
