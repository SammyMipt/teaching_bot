from __future__ import annotations
import os
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import pandas as pd
from app.repositories.csv_repo import CsvTable
from app.utils.ids import new_id
from app.utils.time import now_iso

SLOTS_COLUMNS = [
    "slot_id", "ta_id", "date", "time_from", "time_to", 
    "mode", "location", "meeting_link", "duration_min", 
    "capacity", "status", "created_at", "canceled_by", 
    "canceled_at", "cancel_reason"
]

class SlotService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "slots.csv"), SLOTS_COLUMNS)

    def _read_df(self) -> pd.DataFrame:
        return self.table.read()

    def add_slot(self, ta_id: str, date: str, time_from: str, time_to: str,
                 mode: str = "online", location: str = "", meeting_link: str = "",
                 duration_min: int = 15, capacity: int = 1) -> dict:
        row = {
            "slot_id": new_id("slt"),
            "ta_id": ta_id,
            "date": date,
            "time_from": time_from,
            "time_to": time_to,
            "mode": mode,
            "location": location,
            "meeting_link": meeting_link,
            "duration_min": duration_min,
            "capacity": capacity,
            "status": "free",
            "created_at": now_iso(),
            "canceled_by": "",
            "canceled_at": "",
            "cancel_reason": ""
        }
        self.table.append_row(row)
        return row

    def list_for_teacher(self, ta_id: str) -> pd.DataFrame:
        df = self._read_df()
        if df.empty or "ta_id" not in df.columns:
            return pd.DataFrame()
        return df[df["ta_id"] == ta_id].copy()

    # def list_free_with_bookings(self, bookings_service) -> pd.DataFrame:
    #     """Возвращает только свободные слоты с информацией о бронированиях"""
    #     df = self._read_df()
    #     if df.empty:
    #         return pd.DataFrame()
        
    #     # Фильтруем только доступные для записи слоты
    #     available_df = df[
    #         (df["status"].str.lower() != "canceled") & 
    #         (~self._is_past_vectorized(df))
    #     ].copy()
        
    #     if available_df.empty:
    #         return pd.DataFrame()
            
    #     # Добавляем информацию о бронированиях
    #     booking_counts = self._get_booking_counts(bookings_service, available_df["slot_id"].tolist())
    #     available_df["booked_count"] = available_df["slot_id"].map(booking_counts).fillna(0).astype(int)
        
    #     # Фильтруем только те, где есть свободные места или статус не closed
    #     result_df = available_df[
    #         (available_df["status"].str.lower() != "closed") &
    #         (available_df["booked_count"] < available_df["capacity"].astype(int))
    #     ].copy()
        
    #     return result_df

    def list_free_with_bookings(self, bookings_service) -> pd.DataFrame:
        """Возвращает только свободные слоты с информацией о бронированиях"""
        df = self._read_df()
        print(f"DEBUG: SlotService.list_free_with_bookings called")
        print(f"DEBUG: Total slots in CSV: {len(df)}")
        if df.empty:
            return pd.DataFrame()
        
        # Показываем какие слоты есть
        print(f"DEBUG: Slots by TA:")
        if "ta_id" in df.columns:
            ta_counts = df["ta_id"].value_counts()
            for ta_id, count in ta_counts.items():
                print(f"  - TA {ta_id}: {count} slots")
        
        # Фильтруем только доступные для записи слоты
        available_df = df[
            (df["status"].str.lower() != "canceled") & 
            (~self._is_past_vectorized(df))
        ].copy()
        
        print(f"DEBUG: Available slots (not canceled/past): {len(available_df)}")
        
        if available_df.empty:
            return pd.DataFrame()
            
        # Добавляем информацию о бронированиях
        booking_counts = self._get_booking_counts(bookings_service, available_df["slot_id"].tolist())
        available_df["booked_count"] = available_df["slot_id"].map(booking_counts).fillna(0).astype(int)
        
        # Фильтруем только те, где есть свободные места или статус не closed
        result_df = available_df[
            (available_df["status"].str.lower() != "closed") &
            (available_df["booked_count"] < available_df["capacity"].astype(int))
        ].copy()
        
        print(f"DEBUG: Final result slots: {len(result_df)}")
        
        return result_df

    def get_slot_by_id(self, slot_id: str) -> tuple[bool, dict]:
        """Возвращает (found, slot_dict)"""
        df = self._read_df()
        if df.empty or "slot_id" not in df.columns:
            return False, {}
        row = df.loc[df["slot_id"] == slot_id]
        if row.empty:
            return False, {}
        return True, row.iloc[0].to_dict()

    def set_open(self, slot_id: str, is_open: bool) -> bool:
        """Переключает доступность записи (открыт/закрыт)"""
        df = self._read_df()
        if df.empty or "slot_id" not in df.columns:
            return False
        mask = df["slot_id"] == slot_id
        if not mask.any():
            return False
        
        # Меняем статус между free и closed
        new_status = "free" if is_open else "closed"
        df.loc[mask, "status"] = new_status
        self.table.write(df)
        return True

    def cancel_slot(self, slot_id: str, canceled_by: str = "", reason: str = "") -> bool:
        """Помечает слот отменённым"""
        df = self._read_df()
        if df.empty or "slot_id" not in df.columns:
            return False
        mask = df["slot_id"] == slot_id
        if not mask.any():
            return False
        
        df.loc[mask, "status"] = "canceled"
        df.loc[mask, "canceled_by"] = canceled_by
        df.loc[mask, "canceled_at"] = now_iso()
        df.loc[mask, "cancel_reason"] = reason
        self.table.write(df)
        return True

    # =================== НОВЫЕ МЕТОДЫ ДЛЯ ВЫЧИСЛЯЕМЫХ СТАТУСОВ ===================

    def get_computed_status(self, slot_dict: Dict[str, Any], current_bookings: int = None) -> str:
        """
        Вычисляет актуальный статус слота на основе базового статуса, времени и бронирований.
        
        Возвращает один из: 'free_full', 'free_partial', 'busy', 'closed', 'canceled', 'pasted'
        """
        base_status = str(slot_dict.get('status', 'free')).lower()
        
        # Неизменяемые статусы
        if base_status == 'canceled':
            return 'canceled'
        
        # Проверка на прошедшее время
        if self._is_slot_in_past(slot_dict):
            return 'pasted'
        
        # Закрытые слоты
        if base_status == 'closed':
            return 'closed'
        
        # Для свободных слотов проверяем заполненность
        if base_status == 'free':
            capacity = int(slot_dict.get('capacity', 1))
            if current_bookings is None:
                current_bookings = 0  # Если не передано, считаем пустым
            
            free_spots = capacity - current_bookings
            
            if free_spots <= 0:
                return 'busy'
            elif free_spots == capacity:
                return 'free_full'
            else:
                return 'free_partial'
        
        return base_status

    def get_display_color(self, computed_status: str) -> str:
        """Возвращает цветовой индикатор для статуса"""
        color_map = {
            'free_full': '🟢',      # полностью свободен
            'free_partial': '🟡',   # частично свободен  
            'busy': '🔴',           # полностью занят
            'closed': '⚫',         # закрыт преподавателем
            'canceled': '',         # не показываем
            'pasted': '🔘',         # прошедший
        }
        return color_map.get(computed_status, '❓')

    def get_status_description(self, computed_status: str) -> str:
        """Возвращает текстовое описание статуса"""
        descriptions = {
            'free_full': '',
            'free_partial': '',
            'busy': '',
            'closed': ' • закрыт для записи',
            'canceled': ' • отменён',
            'pasted': ' • завершён',
        }
        return descriptions.get(computed_status, '')

    def _is_slot_in_past(self, slot_dict: Dict[str, Any]) -> bool:
        """Проверяет, находится ли слот в прошлом"""
        try:
            date_str = slot_dict.get('date', '')
            time_to_str = slot_dict.get('time_to', '')
            
            if not date_str or not time_to_str:
                return False
                
            # Парсим дату и время окончания слота
            year, month, day = map(int, date_str.split('-'))
            hour, minute = map(int, time_to_str.split(':'))
            
            slot_end = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            
            return slot_end <= now
        except (ValueError, AttributeError):
            return False

    def _is_past_vectorized(self, df: pd.DataFrame) -> pd.Series:
        """Векторизованная проверка прошедших слотов для DataFrame"""
        if df.empty:
            return pd.Series([], dtype=bool)
            
        now = datetime.now(timezone.utc)
        
        def check_past(row):
            try:
                date_str = row.get('date', '')
                time_to_str = row.get('time_to', '')
                
                if not date_str or not time_to_str:
                    return False
                    
                year, month, day = map(int, str(date_str).split('-'))
                hour, minute = map(int, str(time_to_str).split(':'))
                
                slot_end = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
                return slot_end <= now
            except (ValueError, AttributeError):
                return False
        
        return df.apply(check_past, axis=1)

    def _get_booking_counts(self, bookings_service, slot_ids: list) -> dict:
        """Получает количество активных бронирований для списка слотов"""
        if not slot_ids:
            return {}
            
        try:
            booking_counts = {}
            for slot_id in slot_ids:
                try:
                    bookings_df = bookings_service.list_for_slot(slot_id)
                    if not bookings_df.empty and 'status' in bookings_df.columns:
                        # Считаем только активные бронирования
                        active_bookings = bookings_df[
                            bookings_df['status'].str.lower().isin(['active', 'confirmed'])
                        ]
                        booking_counts[slot_id] = len(active_bookings)
                    else:
                        booking_counts[slot_id] = len(bookings_df) if not bookings_df.empty else 0
                except Exception:
                    booking_counts[slot_id] = 0
            return booking_counts
        except Exception:
            return {slot_id: 0 for slot_id in slot_ids}

    def get_enriched_slots_for_teacher(self, ta_id: str, bookings_service) -> pd.DataFrame:
        """
        Возвращает слоты преподавателя с вычисленными статусами и цветами.
        Исключает отмененные слоты.
        """
        df = self.list_for_teacher(ta_id)
        if df.empty:
            return pd.DataFrame()
        
        # Исключаем отмененные слоты
        df = df[df["status"].str.lower() != "canceled"].copy()
        if df.empty:
            return df
            
        # Получаем количество бронирований
        booking_counts = self._get_booking_counts(bookings_service, df["slot_id"].tolist())
        df["booked_count"] = df["slot_id"].map(booking_counts).fillna(0).astype(int)
        
        # Вычисляем статусы и цвета
        computed_statuses = []
        display_colors = []
        status_descriptions = []
        
        for _, row in df.iterrows():
            slot_dict = row.to_dict()
            current_bookings = slot_dict.get('booked_count', 0)
            
            computed_status = self.get_computed_status(slot_dict, current_bookings)
            computed_statuses.append(computed_status)
            display_colors.append(self.get_display_color(computed_status))
            status_descriptions.append(self.get_status_description(computed_status))
        
        df["computed_status"] = computed_statuses
        df["display_color"] = display_colors
        df["status_description"] = status_descriptions
        
        return df
    
    def add_window(self, ta_id: str, date: str, start_time: str, end_time: str,
               duration_min: int, capacity: int = 1, mode: str = "online",
               location: str = "", meeting_link: str = "") -> Dict[str, Any]:
        """
        Создает множество слотов в указанном временном окне.
        Разбивает окно на слоты по duration_min минут.
        
        Возвращает:
        {
            "ok": True/False,
            "error": "описание ошибки" (если ok=False),
            "created": [список созданных слотов],
            "skipped": [список пропущенных слотов с причинами]
        }
        """
        try:
            # Валидация времени
            start_h, start_m = map(int, start_time.split(":"))
            end_h, end_m = map(int, end_time.split(":"))
            
            if not (0 <= start_h < 24 and 0 <= start_m < 60):
                return {"ok": False, "error": "Неверное время начала"}
            if not (0 <= end_h < 24 and 0 <= end_m < 60):
                return {"ok": False, "error": "Неверное время окончания"}
            
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m
            
            if start_minutes >= end_minutes:
                return {"ok": False, "error": "Время начала должно быть раньше времени окончания"}
            
            total_minutes = end_minutes - start_minutes
            if total_minutes > 6 * 60:  # Максимум 6 часов
                return {"ok": False, "error": "Окно не может быть больше 6 часов"}
            
            if duration_min <= 0 or duration_min > 120:
                return {"ok": False, "error": "Длительность слота должна быть от 1 до 120 минут"}
            
            if capacity <= 0 or capacity > 20:
                return {"ok": False, "error": "Ёмкость слота должна быть от 1 до 20"}
            
            # Генерируем слоты
            created = []
            skipped = []
            current_minutes = start_minutes
            
            while current_minutes + duration_min <= end_minutes:
                # Формируем время слота
                slot_start_h = current_minutes // 60
                slot_start_m = current_minutes % 60
                slot_end_minutes = current_minutes + duration_min
                slot_end_h = slot_end_minutes // 60
                slot_end_m = slot_end_minutes % 60
                
                slot_start_time = f"{slot_start_h:02d}:{slot_start_m:02d}"
                slot_end_time = f"{slot_end_h:02d}:{slot_end_m:02d}"
                
                # Проверяем конфликты (опционально - пока пропустим)
                
                # Создаем слот
                try:
                    slot = self.add_slot(
                        ta_id=ta_id,
                        date=date,
                        time_from=slot_start_time,
                        time_to=slot_end_time,
                        mode=mode,
                        location=location,
                        meeting_link=meeting_link,
                        duration_min=duration_min,
                        capacity=capacity
                    )
                    created.append(slot)
                except Exception as e:
                    skipped.append({
                        "time": f"{slot_start_time}-{slot_end_time}",
                        "reason": str(e)
                    })
                
                current_minutes += duration_min
            
            if not created:
                return {"ok": False, "error": "Не удалось создать ни одного слота"}
            
            return {
                "ok": True,
                "created": created,
                "skipped": skipped
            }
            
        except Exception as e:
            return {"ok": False, "error": f"Ошибка создания окна: {str(e)}"}