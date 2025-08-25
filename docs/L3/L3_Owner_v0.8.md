# L3 — Owner (Events & Data‑Flow) v0.8

> Слой событий и потоков данных для **владельца курса**. Синхронизировано с L1 v0.8 и L2 Owner v0.8.  
> Для каждого события фиксируем: **Intent/Action**, **Preconditions**, **Validations**, **Side‑effects (DB/Storage)**, **Notifications/Toasts**, **Logs (AuditLog)**, **Idempotency**, **Errors**.

---

## 0. Соглашения, кодирование и сущности

### 0.1. Кодирование действий (callback_data)
`r=owner;a=<action>;p=<page?>;w=<Wxx?>;t=<type?>;id=<id?>`  
- `r` — роль, `a` — код действия, `p` — пагинация/шаг мастера, `w` — неделя, `t` — тип материала/пресета и т.п., `id` — внутренний идентификатор.

### 0.2. Основные сущности (схема с ключами)
- `User { id, human_id in {OW, TA###, ST###}, role∈{owner,teacher,student}, fio, email, tg_id, active }`
- `TeacherProfile { user_id(PK/FK User), weekly_limit:int ≥0 }`
- `StudentProfile { user_id(PK/FK User), group, lms_email }`
- `Course { id, title, description?, weeks:int, tz, locale, settings_id }`
- `Week { id=Wxx, deadline:date }`
- `Settings { id, limits: { solutions: { files_per_week:int=5, bytes_per_week:int=30*MB }, materials: { max_file_mb:int=100 } }, notify: { slot_changes:bool } }`
- `Material { id, week(Wxx), type∈{prep,teacher,notes,slides,video}, visibility∈{student,teacher}, file_ref|link, size_bytes?, checksum?, state∈{active,archived}, uploaded_by, created_at, updated_at }`
- `Submission { id, student_id, week, file_ref, size_bytes, checksum, state∈{active,archived}, created_at }`
- `ArchiveEntry { id, kind∈{submission,material}, ref_id, reason∈{delete,reupload,soft_delete}, archived_at }`
- `AssignmentMatrix { week, student_id, teacher_id } // (PK: week, student_id)`
- `Slot { id, teacher_id, start_ts, end_ts, mode∈{online,offline}, location?, link?, cap:int, state∈{open,closed,cancelled} }`
- `Booking { id, week, slot_id, student_id, status∈{active,cancelled}, created_at }`
- `Grade { student_id, week, teacher_id, score:int(1..10), letter∈{A,B,C,D}, comment?, created_at } // (PK: student_id, week)`
- `Preset { id, scope∈{global,personal}, owner_id (User.id), teacher_id?(User.id), title, description?, mode∈{online,offline}, link_template?, location_template?, slot_templates:[PresetSlot] }`
- `PresetSlot { id, preset_id, pattern∈{weekday,date}, weekday∈{1..7}?, date?:date, start_time:HH:MM, duration_min|end_time, cap:int }`
- `AuditLog { ts, actor_id, event_code, payload(JSON) }`

> Примечание: **каноническое лог‑событие для оценок** — `GRADE_UPSERT` c полями: `{actor_id, student_id, week, teacher_id, old_score?, old_letter?, new_score, new_letter, origin∈{teacher,owner}, comment?}`.

---

## 1. Регистрация и инициализация

### EVT: `owner_register_start`
**Intent:** первый вход владельца.  
**Preconditions:** у текущего `tg_id` нет owner.  
**Side‑effects:** показать форму: ФИО, email, флаг «я TA», `weekly_limit` при флаге.  
**Logs:** `OWNER_REGISTER_START {tg_id}`

### EVT: `owner_register_commit`
**Intent:** сохранить профиль owner (и, опционально, TA).  
**Validations:** корректный email, уникальность owner.  
**Side‑effects:** `User{role=owner,human_id=OW,tg_id=...}`; при «я TA» → `TeacherProfile{weekly_limit}`.  
**Notifications:** `✅ Профиль владельца создан`.  
**Logs:** `OWNER_REGISTER_COMMIT {user_id}`  
**Idempotency:** повторный вызов при существующем owner → no‑op.  
**Errors:** `E_ALREADY_EXISTS`, `E_INPUT_INVALID`.

### EVT: `course_init`
**Intent:** создать курс.  
**Input:** title, description?, weeks, tz, locale.  
**Side‑effects:** `Course` + `Week[W01..Wnn]`.  
**Logs:** `OWNER_COURSE_INIT {course_id} {weeks}`

### EVT: `settings_update`
**Intent:** обновить политики/лимиты/notify.  
**Side‑effects:** апдейт `Settings`.  
**Notifications:** `✅ Настройки обновлены`.  
**Logs:** `OWNER_SETTINGS_UPDATE {settings_id}`

---

## 2. Управление ролями (импорт и поиск)

### EVT: `upload_teachers`
**Intent:** импорт преподавателей.  
**Input:** CSV/XLSX (ФИО, weekly_limit).  
**Side‑effects:** создать `User{role=teacher,human_id=TA###}` + `TeacherProfile`.  
**Logs:** `OWNER_UPLOAD_TEACHERS {count}`  
**Errors:** `E_INPUT_INVALID` (формат файла).

### EVT: `upload_students`
**Intent:** импорт студентов.  
**Input:** CSV/XLSX (ФИО, group, lms_email).  
**Side‑effects:** создать `User{role=student,human_id=ST###}` + `StudentProfile`.  
**Logs:** `OWNER_UPLOAD_STUDENTS {count}`

### EVT: `search_entity`
**Intent:** поиск по ролям/ФИО/группе.  
**Output:** список или карточка.  
**Logs:** `OWNER_SEARCH {role} {q}`

---

## 3. Материалы курса (версионирование)

### EVT: `material_list`
**Intent:** показать типы материалов по `Wxx`.  
**Output:** 📖/📘/📝/📊/🎥.  
**Logs:** `OWNER_MATERIAL_LIST {Wxx}`

### EVT: `material_upload`
**Intent:** загрузить/обновить материал.  
**Input:** `(Wxx, type, file|link)`  
**Validations:** размер ≤ `Settings.materials.max_file_mb`; ссылка для 🎥 валидна.  
**Side‑effects:** активная версия для `(Wxx,type)` архивируется; новая запись становится `active`; сохраняем `checksum`, `size_bytes`.  
**Notifications:** `✅ Материал загружен`.  
**Logs:** `OWNER_MATERIAL_UPLOAD {Wxx} {type} {material_id}`  
**Idempotency:** тот же `checksum` → no‑op.  
**Errors:** `E_SIZE_LIMIT`, `E_STORAGE_IO`, `E_INPUT_INVALID`.

### EVT: `material_history`
**Intent:** история версий для `(Wxx,type)`.  
**Output:** список версий (дата, размер, состояние).  
**Logs:** `OWNER_MATERIAL_HISTORY {Wxx} {type}`

### EVT: `material_download`
**Intent:** скачать конкретную версию.  
**Input:** `material_id`.  
**Logs:** `OWNER_MATERIAL_DOWNLOAD {material_id}`

### EVT: `material_soft_delete`
**Intent:** переместить версию в архив.  
**Side‑effects:** `state=archived`; `ArchiveEntry{reason='soft_delete'}`.  
**Notifications:** `🗄️ Материал перемещён в архив`.  
**Logs:** `OWNER_MATERIAL_SOFT_DELETE {material_id}`

### EVT: `material_hard_delete`
**Intent:** удалить навсегда (только из архива).  
**Validations:** `state=archived`.  
**Side‑effects:** удалить файл и запись.  
**Notifications:** `🗑️ Материал удалён навсегда`.  
**Logs:** `OWNER_MATERIAL_HARD_DELETE {material_id}`  
**Errors:** `E_NOT_FOUND`, `E_STATE_INVALID`.

---

## 4. Пресеты расписания (глобальные)

### EVT: `preset_list`
**Intent:** показать глобальные пресеты.  
**Logs:** `OWNER_PRESET_LIST`

### EVT: `preset_create_start`
**Intent:** открыть форму создания.  
**Logs:** `OWNER_PRESET_CREATE_START`

### EVT: `preset_create_commit`
**Intent:** сохранить пресет.  
**Input:** title, description?, `mode`, шаблоны слотов `slot_templates[]`.  
**Validations:** значения cap/duration, корректность time/weekday/date.  
**Side‑effects:** `Preset{scope='global', owner_id=OW,...}` + `PresetSlot[]`.  
**Notifications:** `✅ Пресет сохранён`.  
**Logs:** `OWNER_PRESET_CREATE {preset_id}`  
**Errors:** `E_INPUT_INVALID`

### EVT: `preset_update`
**Intent:** редактировать пресет.  
**Side‑effects:** апдейт `Preset`/`PresetSlot[]`.  
**Notifications:** `✅ Пресет обновлён`.  
**Logs:** `OWNER_PRESET_UPDATE {preset_id}`

### EVT: `preset_delete`
**Intent:** удалить пресет.  
**Preconditions:** пресет существует.  
**Side‑effects:** каскадное удаление `PresetSlot[]`.  
**Notifications:** `🗑️ Пресет удалён`.  
**Logs:** `OWNER_PRESET_DELETE {preset_id}`  
**Errors:** `E_PRESET_NOT_FOUND`

### EVT: `preset_preview`
**Intent:** предпросмотр порождаемых слотов (на заданный период).  
**Input:** период (дата‑от/до), опц. фильтры.  
**Output:** список потенциальных слотов (без фактического создания).  
**Logs:** `OWNER_PRESET_PREVIEW {preset_id}`

> Примечание: применение глобальных пресетов выполняется преподавателями в их мастере. Owner управляет только CRUD и предпросмотром.

---

## 5. Автоназначение преподавателей (по неделям)

### EVT: `assign_preview`
**Intent:** сформировать предпросмотр матрицы распределения (round‑robin со сдвигом).  
**Preconditions:** есть `Student` и `Teacher` с `weekly_limit`, есть `Week`.  
**Side‑effects:** временное хранилище черновика предпросмотра.  
**Logs:** `OWNER_ASSIGN_PREVIEW {students} {teachers} {weeks}`

### EVT: `assign_commit`
**Intent:** зафиксировать распределение.  
**Side‑effects:** заполнить `AssignmentMatrix`, исключая TA с нулевым лимитом.  
**Notifications:** `✅ Автоназначение выполнено`.  
**Logs:** `OWNER_ASSIGN_AUTO {student_count} {teacher_count}`  
**Idempotency:** дубль по `(student,week)` игнорируется.

### EVT: `assign_export`
**Intent:** выгрузка CSV/XLSX.  
**Logs:** `OWNER_ASSIGN_EXPORT`

---

## 6. Архив решений (owner‑only)

### EVT: `archive_list`
**Intent:** список архивных решений с фильтрами.  
**Logs:** `OWNER_ARCHIVE_LIST {filters}`

### EVT: `archive_delete_hard`
**Intent:** удалить навсегда архивный файл.  
**Logs:** `OWNER_DELETE_ARCHIVE {submission_id}`  
**Errors:** `E_NOT_FOUND`

---

## 7. Оценки: override владельцем

### EVT: `grade_override_open`
**Intent:** открыть список оценок студента по неделям.  
**Input:** `student_id`.  
**Logs:** `OWNER_GRADE_OVERRIDE_OPEN {student_id}`

### EVT: `grade_override_commit`
**Intent:** добавить/изменить оценку (override).  
**Input:** `student_id, week, score(1..10), letter(A..D), comment?`.  
**Validations:** согласованность `score↔letter` (автоподбор буквы из score).  
**Side‑effects:** UPSERT в `Grade` (по ключу `student_id+week`).  
**Notifications:** `✅ Оценка обновлена`.  
**Logs (канонические):**  
- `GRADE_UPSERT` с `origin='owner'` и полями `old_*`/`new_*`.  
- (опц.) Технический алиас: `OWNER_GRADE_OVERRIDE {student_id} {week}`.  
**Idempotency:** повтор с теми же `score/letter/comment` → no‑op.

---

## 8. Отчёты и аналитика

### EVT: `report_open`
**Intent:** выбор отчёта (студенты/преподаватели/недели).  
**Logs:** `OWNER_REPORT_OPEN`

### EVT: `report_export`
**Intent:** экспорт отчёта CSV/XLSX.  
**Logs:** `OWNER_REPORT_EXPORT {kind}`

---

## 9. Ошибки (коды)
`E_ALREADY_EXISTS`, `E_INPUT_INVALID`, `E_SIZE_LIMIT`, `E_STORAGE_IO`, `E_NOT_FOUND`, `E_STATE_INVALID`, `E_PRESET_NOT_FOUND`.

---

## 10. Идемпотентность и журналирование
- Идемпотентны: регистрация owner, загрузка материала (по `checksum`), коммит автоназначения (по `(student,week)`), override оценок (с сравнением старых/новых значений).
- **AuditLog** — единый реестр событий; для оценок используется канон `GRADE_UPSERT`.
- Каждое мутационное событие фиксирует `actor_id`, `payload` с ключевыми идентификаторами.

---

## 11. Каркас модулей (Python)
- `bot/routers/owner/main.py` — маршрутизация меню.
- `bot/routers/owner/materials.py` — list/upload/history/download/soft/hard.
- `bot/routers/owner/presets.py` — CRUD + preview глобальных пресетов.
- `bot/routers/owner/assignments.py` — preview/commit/export автоназначений.
- `bot/routers/owner/archive.py` — list/delete_hard.
- `bot/routers/owner/grades.py` — override оценок.
- `bot/routers/owner/reports.py` — open/export.
- `services/owner/*`: `materials_service.py`, `presets_service.py`, `assignments_service.py`, `grades_service.py`, `reports_service.py`.
- `repositories/*`: `materials_repo.py`, `presets_repo.py`, `assignments_repo.py`, `archive_repo.py`, `grades_repo.py`.
- `utils/*`: `validators.py`, `checksums.py`, `logs.py`, `dates.py`.
