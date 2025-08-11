```mermaid
@startuml
left to right direction
skinparam packageStyle rectangle

' Акторы (роли)
actor "Студент" as Student
actor "Преподаватель" as Instructor
actor "Владелец курса" as Owner

' Владелец курса наследует права преподавателя
Owner --|> Instructor

' Системная граница как пакет
package "Учебный ассистент (Telegram + Хранилище)" {
  ' --- Use cases студента ---
  usecase (Посмотреть задания и дедлайны\nпо неделе) as UC1
  usecase (Узнать своего преподавателя\nна выбранную неделю) as UC2
  usecase (Записаться на приём\nк преподавателю) as UC3
  usecase (Показать свободные слоты\nрасписания) as UC3a
  usecase (Сдать решения за неделю) as UC4
  usecase (Посмотреть оценку и\nкомментарий за неделю) as UC5
  usecase (Отправить обратную связь\nпо материалам недели) as UC6

  ' --- Use cases преподавателя ---
  usecase (Кто сдаёт мне\nв выбранную неделю) as UC7
  usecase (Получить сдачи студента\nза неделю) as UC8
  usecase (Выставить/изменить\nоценку за неделю) as UC9
  usecase (Комментарий к сдаче\nза неделю) as UC10
  usecase (Управление расписанием\nприёмов) as UC11
  usecase (Напоминания о расписании\n(заполнить/отметить формат)) as UC12

  ' --- Use cases владельца курса ---
  usecase (Управление пользователями\nи ролями) as UC13
  usecase (Управление неделями,\nтемами, дедлайнами) as UC14
  usecase (Просмотр/редактирование\nрасписаний преподавателей) as UC15
  usecase (Экспорт логов сдач\nи оценок) as UC16
}

' Ассоциации акторов с вариантами использования
Student -- UC1
Student -- UC2
Student -- UC3
Student -- UC4
Student -- UC5
Student -- UC6

Instructor -- UC7
Instructor -- UC8
Instructor -- UC9
Instructor -- UC10
Instructor -- UC11
Instructor -- UC12

Owner -- UC13
Owner -- UC14
Owner -- UC15
Owner -- UC16

' Взаимосвязи use case'ов (семантика include)
UC3 .> UC3a : <<include>>

@enduml
```
