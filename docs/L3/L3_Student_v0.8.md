# L3 — Student (Events & Data‑Flow) v0.8

> Слой событий и потоков данных для **студента**. Синхронизировано с L1 v0.8 и L2 Student v0.8.  
> Функционал по пресетам на UX студента не влияет; разделы обновлены по терминологии.

---

## 0. Соглашения, кодирование и сущности

### 0.1. Кодирование действий (callback_data)
`r=student;a=<action>;w=<Wxx?>;p=<page?>;id=<id?>`

### 0.2. Сущности
Используются: `User{role=student}`, `StudentProfile{group,lms_email}`, `Week`, `Material{visibility=student}`, `Submission`, `ArchiveEntry`, `AssignmentMatrix`, `Slot`, `Booking`, `Grade`, `Settings`, `AuditLog`.

---

## 1. Регистрация студента

### EVT: `student_register_start`
**Intent:** первый вход → запрос email LMS.  
**Preconditions:** у `tg_id` нет студента.  
**Logs:** `STUDENT_REGISTER_START {tg_id}`

### EVT: `student_register_email`
**Intent:** ввести email LMS.  
**Validations:** email‑формат; наличие в загруженном списке; уникальность привязки.  
**Side‑effects:** привязать `tg_id`, `active=true`.  
**Notifications:** `✅ Регистрация завершена`.  
**Logs:** `STUDENT_REGISTER_EMAIL {email} {success}`  
**Errors:** `E_EMAIL_INVALID`, `E_EMAIL_NOT_FOUND`, `E_EMAIL_ALREADY_USED`  
**Idempotency:** повтор с теми же `tg_id/email` → no‑op.

---

## 2. WIC — Работа с неделями

### EVT: `week_open`
**Intent:** открыть меню недели `Wxx`.  
**Logs:** `STUDENT_WEEK_OPEN {Wxx}`

### EVT: `week_info`
**Intent:** показать описание и дедлайн недели.  
**Logs:** `STUDENT_WEEK_INFO {Wxx}`

### EVT: `material_list`
**Intent:** показать материалы недели для студента.  
**Output:** 📖/📝/📊/🎥.  
**Logs:** `STUDENT_MATERIAL_LIST {Wxx}`

### EVT: `material_get`
**Intent:** получить материал.  
**Input:** `(Wxx, type∈{prep,notes,slides,video})`.  
**Preconditions:** `visibility=student`, `state=active`.  
**Notifications:** `📂 Материал получен`.  
**Logs:** `STUDENT_MATERIAL_GET {Wxx} {type}`  
**Errors:** `E_NOT_FOUND`

---

## 3. Мои решения (файлы)

### EVT: `solution_list`
**Intent:** список моих файлов по неделе.  
**Logs:** `STUDENT_SOLUTION_LIST {Wxx}`

### EVT: `solution_upload`
**Intent:** загрузить/добавить файл.  
**Validations:** тип ∈ {PNG,JPG,JPEG,PDF}; активных файлов <5; суммарно ≤30 МБ.  
**Side‑effects:** сохранить файл; `Submission{state=active}`.  
**Notifications:** `📤 Файл загружен`.  
**Logs:** `STUDENT_UPLOAD {id} {size}`  
**Idempotency:** по `checksum`.  
**Errors:** `E_FILE_TYPE`, `E_FILES_COUNT_LIMIT`, `E_BYTES_LIMIT`, `E_STORAGE_IO`

### EVT: `solution_reupload`
**Intent:** перезагрузить файл.  
**Side‑effects:** старая версия → `archived` + `ArchiveEntry{reason='reupload'}`; новая — активна.  
**Notifications:** `🔁 Решение обновлено`.  
**Logs:** `STUDENT_REUPLOAD {old}->{new}`

### EVT: `solution_delete`
**Intent:** мягко удалить файл (в архив).  
**Side‑effects:** `state=archived` + `ArchiveEntry{reason='delete'}`.  
**Notifications:** `🗑️ Решение удалено (в архив)`.  
**Logs:** `STUDENT_DELETE_SOFT {id}`  
**Idempotency:** повторное удаление → no‑op.

### EVT: `solution_download`
**Intent:** скачать свой файл.  
**Preconditions:** принадлежит студенту, `state=active`.  
**Logs:** `STUDENT_DOWNLOAD {id}`

---

## 4. Запись на сдачу

### EVT: `booking_open`
**Intent:** показать доступные слоты назначенного преподавателя для `Wxx`.  
**Preconditions:** запись в `AssignmentMatrix` существует.  
**Side‑effects:** фильтр слотов: только назначенный преподаватель, статусы 🟢/🟡, дата ≥ сегодня.  
**Logs:** `STUDENT_BOOKING_OPEN {Wxx} {teacher_id}`

### EVT: `booking_create`
**Intent:** записаться в слот.  
**Validations:** нет другой активной записи на эту неделю; слот `open` и есть места; принадлежит назначенному преподавателю.  
**Side‑effects:** `Booking{status=active}`.  
**Notifications:** `✅ Запись создана`.  
**Logs:** `STUDENT_BOOKING_CREATE {slot_id} {Wxx}`  
**Idempotency:** ключ `(student,week)`; повтор → no‑op.  
**Errors:** `E_ALREADY_BOOKED`, `E_NOT_FOUND`

### EVT: `booking_cancel`
**Intent:** отменить запись.  
**Side‑effects:** `status=cancelled`.  
**Notifications:** `❌ Запись отменена`.  
**Logs:** `STUDENT_BOOKING_CANCEL {id}`

### EVT: `booking_reschedule`
**Intent:** перезаписаться.  
**Side‑effects:** открыть выбор слотов; старую запись отменяем после подтверждения новой.  
**Logs:** `STUDENT_BOOKING_RESCHEDULE {id}`

---

## 5. Оценки и история

### EVT: `grade_get`
**Intent:** узнать оценку за неделю.  
**Output:** `score (1..10)`, `letter (A..D)`, `comment`.  
**Logs:** `STUDENT_GRADE_GET {Wxx}`

### EVT: `grades_overview`
**Intent:** сводка по оценкам.  
**Logs:** `STUDENT_GRADES_OVERVIEW {student_id}`

### EVT: `history_list`
**Intent:** история сдач.  
**Output:** прошедшие записи/оценки; фильтры по преподавателю/статусу.  
**Logs:** `STUDENT_HISTORY_LIST {student_id}`

---

## 6. Нотификации / Тосты
- `📤 Файл загружен`, `🔁 Решение обновлено`, `🗑️ Решение удалено (в архив)`  
- `📂 Материал получен`  
- `✅ Запись создана`, `❌ Запись отменена`

---

## 7. Ошибки/коды
`E_EMAIL_INVALID`, `E_EMAIL_NOT_FOUND`, `E_EMAIL_ALREADY_USED`, `E_FILE_TYPE`, `E_FILES_COUNT_LIMIT`, `E_BYTES_LIMIT`, `E_STORAGE_IO`, `E_ALREADY_BOOKED`, `E_NOT_FOUND`.

---

## 8. Идемпотентность и журналирование
- Идемпотентны: регистрация (по email), загрузка/перезагрузка (по checksum), запись на неделю (по `(student,week)`).  
- Все действия логируются в `AuditLog` с ключевыми идентификаторами и полезной нагрузкой (`payload`).

---

## 9. Каркас модулей (Python)
- `bot/routers/student/main.py` (+ `weeks.py`, `materials.py`, `solutions.py`, `booking.py`, `grades.py`)  
- `services/student/*` — бизнес‑логика для соответствующих доменов  
- `utils/*` — `validators.py`, `logs.py`, `checksums.py`, `dates.py`
