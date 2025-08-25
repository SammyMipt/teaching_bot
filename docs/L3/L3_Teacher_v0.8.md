# L3 — Teacher (Events & Data‑Flow) v0.8

> Слой событий и потоков данных для **преподавателя**. Синхронизировано с L1 v0.8 и L2 Teacher v0.8.  
> Добавлены **личные пресеты расписания** и использование пресетов в мастере создания расписания.

---

## 0. Соглашения, кодирование и сущности

### 0.1. Кодирование действий (callback_data)
`r=teacher;a=<action>;p=<page?>;id=<id?>;date=<YYYY-MM-DD?>;preset=<id?>`

### 0.2. Сущности
Помимо общих (User/TeacherProfile/Slot/Booking/Material/Submission/Grade/AuditLog) используются:  
- `Preset { id, scope='personal', owner_id, teacher_id, ... }`
- `PresetSlot[]` (см. Owner L3).

---

## 1. Регистрация преподавателя (первый вход)

### EVT: `teacher_register_start`
**Intent:** первый вход → «Зарегистрироваться как преподаватель».  
**Preconditions:** у `tg_id` нет привязки к teacher.  
**Logs:** `TEACHER_REGISTER_START {tg_id}`

### EVT: `teacher_register_code`
**Intent:** ввод секретного кода (ENV: `TEACHER_SECRET`).  
**Validations:** сравнить с ENV.  
**Side‑effects:** при успехе — список TA без `tg_id`.  
**Logs:** `TEACHER_REGISTER_CODE {success}`  
**Errors:** `E_CODE_INVALID`

### EVT: `teacher_register_select`
**Intent:** выбрать себя из списка.  
**Validations:** выбранный `user_id` не привязан к другому `tg_id`.  
**Side‑effects:** `User.tg_id = current`, `active=true`.  
**Notifications:** `✅ Регистрация завершена`.  
**Logs:** `TEACHER_REGISTER_SELECT {user_id}`  
**Idempotency:** повторный выбор того же id → no‑op.

---

## 2. Пресеты расписания (личные)

### EVT: `preset_list`
**Intent:** список личных + чтение глобальных.  
**Logs:** `TEACHER_PRESET_LIST {teacher_id}`

### EVT: `preset_create_start`
**Intent:** форма создания.  
**Logs:** `TEACHER_PRESET_CREATE_START {teacher_id}`

### EVT: `preset_create_commit`
**Intent:** сохранить личный пресет.  
**Input:** title, description?, `mode`, `slot_templates[]`.  
**Validations:** cap/duration; time/weekday/date; коллизии с физически невозможными интервалами.  
**Side‑effects:** `Preset{scope='personal', teacher_id=...}` + `PresetSlot[]`.  
**Notifications:** `✅ Пресет сохранён`.  
**Logs:** `TEACHER_PRESET_CREATE {preset_id}`  
**Errors:** `E_INPUT_INVALID`

### EVT: `preset_update`
**Intent:** отредактировать личный пресет.  
**Side‑effects:** update `Preset`/`PresetSlot[]`.  
**Notifications:** `✅ Пресет обновлён`.  
**Logs:** `TEACHER_PRESET_UPDATE {preset_id}`

### EVT: `preset_delete`
**Intent:** удалить личный пресет.  
**Side‑effects:** каскадное удаление слотов пресета.  
**Notifications:** `🗑️ Пресет удалён`.  
**Logs:** `TEACHER_PRESET_DELETE {preset_id}`  
**Errors:** `E_PRESET_NOT_FOUND`

### EVT: `preset_preview`
**Intent:** предпросмотр создаваемых слотов на период.  
**Output:** список потенциальных слотов без записи в БД.  
**Logs:** `TEACHER_PRESET_PREVIEW {preset_id}`

---

## 3. Создание расписания (мастер)

### EVT: `sched_create_start`
**Intent:** запуск мастера.  
**Logs:** `TEACHER_SCHED_CREATE_START {teacher_id}`

### EVT: `sched_create_choose_mode`
**Intent:** выбор: **Быстрый** (по пресету) / **Ручной**.  
**Logs:** `TEACHER_SCHED_CREATE_CHOOSE_MODE {mode}`

### EVT: `sched_create_quick_select`
**Intent:** выбрать пресет → личные, затем глобальные.  
**Preconditions:** наличие хотя бы одного пресета.  
**Side‑effects:** загрузка пресета, подготовка предпросмотра.  
**Logs:** `TEACHER_SCHED_CREATE_QUICK_SELECT {preset_id}`

### EVT: `sched_create_quick_preview`
**Intent:** предпросмотр слотов, которые будут созданы заданным пресетом (для периода).  
**Validations:** базовые лимиты (онлайн ≤3, очно ≤50, ≤6 ч/сутки).  
**Side‑effects:** временный список кандидатов.  
**Logs:** `TEACHER_SCHED_CREATE_QUICK_PREVIEW {preset_id}`

### EVT: `sched_create_quick_commit`
**Intent:** создать слоты из пресета.  
**Validations:** повторная проверка лимитов; **дедупликация** по ключу `(teacher_id, start_ts, end_ts, location|link)` чтобы не плодить дубликаты при повторном применении.  
**Side‑effects:** вставка `Slot[]` (state=`open`).  
**Notifications:** `✅ Слоты созданы`.  
**Logs:** `TEACHER_SCHED_CREATE_QUICK_COMMIT {count}`  
**Errors:** `E_DURATION_EXCEEDED`, `E_CAP_EXCEEDED`, `E_CONFLICT_DUPLICATE`

### EVT: `sched_create_manual`
**Intent:** ручное создание: дата/время/аудитория/cap или online‑ссылка.  
**Validations:** как выше.  
**Side‑effects:** создание `Slot`.  
**Notifications:** `✅ Слот создан`.  
**Logs:** `TEACHER_SCHED_CREATE_MANUAL {slot_id}`

---

## 4. Управление расписанием

### EVT: `sched_list`
**Intent:** список слотов по дате/периоду.  
**Logs:** `TEACHER_SCHED_LIST {date_from,date_to}`

### EVT: `sched_toggle`
**Intent:** открыть/закрыть слот.  
**Side‑effects:** `state=open|closed`.  
**Notifications:** `✅ Состояние слота обновлено`.  
**Logs:** `TEACHER_SCHED_TOGGLE {slot_id} {new_state}`

### EVT: `sched_edit`
**Intent:** изменить дату/время/cap/локацию/ссылку.  
**Side‑effects:** update `Slot`.  
**Notifications:** рассылка студентам, если включено `Settings.notify.slot_changes`.  
**Logs:** `TEACHER_SCHED_EDIT {slot_id}`

### EVT: `sched_delete`
**Intent:** отменить/удалить слот.  
**Side‑effects:** `state=cancelled`; уведомления студентам.  
**Logs:** `TEACHER_SCHED_DELETE {slot_id}`

### EVT: `sched_students`
**Intent:** посмотреть записавшихся.  
**Output:** список `Booking`.  
**Logs:** `TEACHER_SCHED_VIEW_STUDENTS {slot_id}`

---

## 5. Методические материалы

### EVT: `material_list`
**Intent:** список доступных типов (📖/📘/📝/📊/🎥).  
**Logs:** `TEACHER_MATERIAL_LIST {teacher_id}`

### EVT: `material_get`
**Intent:** получить активную версию.  
**Input:** `(week, type)`.  
**Notifications:** `📂 Материал отправлен`.  
**Logs:** `TEACHER_MATERIAL_GET {week} {type}`  
**Errors:** `E_NOT_FOUND`

---

## 6. Сдачи студентов и оценки

### EVT: `submissions_upcoming`
**Intent:** ближайшие сдачи (сегодня + 2 дня).  
**Output:** если >10 записей — **адаптивная группировка по фамилии**.  
**Logs:** `TEACHER_SUBMISSIONS_UPCOMING {teacher_id}`

### EVT: `submission_view`
**Intent:** карточка сдачи студента (на неделю).  
**Output:** `📂 Скачать решения` · `✅ Поставить оценку`.  
**Logs:** `TEACHER_SUBMISSION_VIEW {student_id} {week}`

### EVT: `submission_download`
**Intent:** скачать решения.  
**Logs:** `TEACHER_SUBMISSION_DOWNLOAD {submission_id}`

### EVT: `submission_grade`
**Intent:** выставить оценку.  
**Validations:** `score∈1..10`; `letter` по маппингу (10–8=A; 7–5=B; 4–3=C; 2–1=D).  
**Side‑effects:** UPSERT `Grade`.  
**Notifications:** `✅ Оценка выставлена`.  
**Logs (канонические):** `GRADE_UPSERT` с `origin='teacher'`.  
**Errors:** `E_INPUT_INVALID`

---

## 7. Ошибки/коды
`E_CODE_INVALID`, `E_INPUT_INVALID`, `E_PRESET_NOT_FOUND`, `E_DURATION_EXCEEDED`, `E_CAP_EXCEEDED`, `E_CONFLICT_DUPLICATE`, `E_NOT_FOUND`.

---

## 8. Идемпотентность и журналирование
- Идемпотентны: регистрация, `sched_create_quick_commit` с дедупликацией, UPSERT оценок.  
- Все действия логируются в `AuditLog` с каноническими событиями (в т.ч. `GRADE_UPSERT`).

---

## 9. Каркас модулей (Python)
- `bot/routers/teachers/main.py`
- `bot/routers/teachers/presets.py` (CRUD + preview для личных)
- `bot/routers/teachers/schedule.py` (quick/manual create, list/toggle/edit/delete)
- `bot/routers/teachers/submissions.py` (upcoming/view/download/grade)
- `bot/routers/teachers/materials.py`
- `services/teacher/*`: `presets_service.py`, `schedule_service.py`, `submissions_service.py`, `materials_service.py`
- `utils/*`: `validators.py`, `logs.py`, `dates.py`
