from __future__ import annotations
import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
import pandas as pd
from app.repositories.csv_repo import CsvTable

WEEKS_COLUMNS = ["week", "title", "description"]

class WeeksService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "weeks.csv"), WEEKS_COLUMNS)
        
        # Константы для расчета дедлайнов
        self.WEEK_1_START = date(2025, 8, 27)  # 27-08-2025
        self.WEEK_1_DEADLINE = date(2025, 9, 6)  # 06-09-2025
        
    def list_all_weeks(self) -> pd.DataFrame:
        """Возвращает все недели с вычисленными дедлайнами"""
        df = self.table.read()
        if df.empty:
            return df
            
        # Добавляем вычисляемые поля
        df_enriched = df.copy()
        df_enriched["deadline_date"] = df_enriched["week"].apply(self._calculate_deadline)
        df_enriched["is_overdue"] = df_enriched["deadline_date"].apply(self._is_overdue)
        df_enriched["status_emoji"] = df_enriched["is_overdue"].apply(
            lambda overdue: "🔴" if overdue else "🟢"
        )
        
        return df_enriched.sort_values("week")
    
    def get_week(self, week_number: int) -> Optional[Dict]:
        """Получить информацию о конкретной неделе"""
        df = self.table.read()
        if df.empty:
            return None
            
        week_data = df[df["week"] == week_number]
        if week_data.empty:
            return None
            
        week_dict = week_data.iloc[0].to_dict()
        
        # Добавляем вычисляемые поля
        week_dict["deadline_date"] = self._calculate_deadline(week_number)
        week_dict["is_overdue"] = self._is_overdue(week_dict["deadline_date"])
        week_dict["status_emoji"] = "🔴" if week_dict["is_overdue"] else "🟢"
        week_dict["deadline_str"] = week_dict["deadline_date"].strftime("%d.%m.%Y")
        
        return week_dict
    
    def _calculate_deadline(self, week_number: int) -> date:
        """Вычисляет дедлайн для недели: 1 неделя = 06.09.2025, каждая следующая +7 дней"""
        days_offset = (week_number - 1) * 7
        return self.WEEK_1_DEADLINE + timedelta(days=days_offset)
    
    def _is_overdue(self, deadline_date: date) -> bool:
        """Проверяет, просрочена ли неделя"""
        today = date.today()
        return today > deadline_date
    
    def get_current_weeks(self) -> List[Dict]:
        """Возвращает 3 ближайшие актуальные недели (не просроченные)"""
        df = self.list_all_weeks()
        if df.empty:
            return []
            
        # Берем только не просроченные недели
        current_weeks = []
        for _, row in df.iterrows():
            week_dict = row.to_dict()
            if not week_dict["is_overdue"]:
                current_weeks.append(week_dict)
                # Ограничиваем до 3 недель
                if len(current_weeks) >= 3:
                    break
                    
        return current_weeks
    
    def get_all_weeks(self) -> List[Dict]:
        """Возвращает все недели"""
        df = self.list_all_weeks()
        if df.empty:
            return []
        
        all_weeks = []
        for _, row in df.iterrows():
            week_dict = row.to_dict()
            all_weeks.append(week_dict)
            
        return all_weeks
    
    def format_week_button_text(self, week_dict: Dict) -> str:
        """Форматирует текст кнопки для недели (без статус-эмодзи)"""
        week_num = week_dict["week"]
        title = week_dict["title"]
        
        # Обрезаем длинные названия для кнопок
        if len(title) > 30:
            title = title[:27] + "..."
            
        return f"{week_num}. {title}"
    
    def populate_from_csv(self, csv_path: str) -> None:
        """Заполняет weeks.csv из вашего файла Weeks_CSV_Preview.csv"""
        try:
            # Читаем ваш CSV
            source_df = pd.read_csv(csv_path)
            
            # Проверяем наличие нужных колонок
            required_cols = ["week", "title", "description"]
            if not all(col in source_df.columns for col in required_cols):
                raise ValueError(f"CSV должен содержать колонки: {required_cols}")
            
            # Берем только нужные колонки и сортируем
            weeks_df = source_df[required_cols].sort_values("week")
            
            # Записываем в weeks.csv
            with self.table.lock:
                weeks_df.to_csv(self.table.path, index=False)
                
            print(f"✅ Импортировано {len(weeks_df)} недель в weeks.csv")
            
        except Exception as e:
            print(f"❌ Ошибка импорта: {e}")
            raise