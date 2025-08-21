# Teaching Assistant Bot (Telegram, Python, aiogram v3)

Минимальный, модульный сервис для курса физики: сдача недель, запись на приём, роли (owner/TA/student), хранение данных в Excel на диске, заготовка интеграции с Яндекс.Диском, максимальное логирование.

## Быстрый старт (Poetry)


## Быстрый старт (Poetry)

1) Установите зависимости и создайте виртуальную среду:
```
poetry install
```

2) Скопируйте и заполните `.env`:
```
cp .env.example .env
# заполните BOT_TOKEN и OWNER_TG_ID
```

3) Запуск бота:
```
poetry run python -m app.main
```

4) Тесты:
```
poetry run pytest -q
```


## Быстрый старт

1) Создайте `.env` на основе шаблона:
```
cp .env.example .env
```
Заполните `BOT_TOKEN`, `OWNER_TG_ID`. Другие параметры — по желанию.

2) Установите зависимости (Python 3.11+):
```
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

3) Запустите бота:
```
python -m app.main
```

4) Данные (CSV) лежат в `./data`. Файлы будут созданы автоматически с нужными колонками.

## Основные команды (MVP)

**Общие**
- `/start` — приветствие и краткая помощь
- `/whoami` — текущая роль и профиль
- `/help` — список команд

**Студент**
- `/register <student_code>` — привязать себя к ростеру
- `/tasks` — список заданий и дедлайнов
- `/submit <task_id>` — отправить решение (дальше пришлите файл документом)
- `/grades` — мои оценки
- `/slots` — свободные слоты преподавателей
- `/book <slot_id>` — записаться на слот
- `/feedback` — оставить отзыв (бот попросит текст)

**Преподаватель**
- `/addslot YYYY-MM-DD HH:MM-HH:MM [online|offline] [location]` — добавить слот приёма
- `/myslots` — мои слоты
- `/mysubmissions` — последние сдачи по моим заданиям (черновик)

**Владелец (owner)**
- `/addtask <week> | <title> | <deadline ISO> | <max_points>` — создать задание
- `/setrole <tg_id> <role>` — выставить роль (owner/ta/student)

## Хранилище
- CSV (.csv) через pandas/— + filelock для безопасной записи
- Файлы сдач — локально в `./data/storage` через `LocalDiskStorage`
- Заглушка для Яндекс.Диска `YandexDiskStorageStub` (логирует, как будет работать реальная интеграция)

## Структура каталогов (сокращённо)
```
app/
  main.py
  config.py
  logger.py
  bot/
    routers/
      common.py, students.py, teachers.py, owner.py
    middlewares/role_middleware.py
    keyboards/common.py
  domain/
    roles.py, models.py
  services/
    roster_service.py, task_service.py, submission_service.py,
    grade_service.py, slot_service.py, feedback_service.py,
    storage_service.py
  repositories/excel_repo.py
  integrations/storage/{base.py, local_storage.py, yandex_disk_stub.py}
  utils/{ids.py, time.py}
```

## Excel схемы
- `data/roster.csv`: `student_code,external_email,last_name_ru,first_name_ru,middle_name_ru,last_name_en,first_name_en,middle_name_en,group,tg_id,role`
- `data/tasks.csv`: `task_id,week,title,deadline_iso,max_points,description`
- `data/submissions.csv`: `submission_id,task_id,student_code,tg_id,submitted_at,file_path,comment`
- `data/grades.csv`: `grade_id,task_id,student_code,points,comment,graded_by,graded_at`
- `data/slots.csv`: `slot_id,teacher_tg_id,date,time_from,time_to,mode,location,booked_by,status`
- `data/feedback.csv`: `feedback_id,student_tg_id,text,created_at,category`

## Логи
- Пишутся в stdout и `./logs/bot.log` (ротация). Уровень через `LOG_LEVEL`.

## Тестовые данные
Пустые Excel создаются автоматически. При желании заполните `data/roster.csv` и `data/tasks.csv`.
