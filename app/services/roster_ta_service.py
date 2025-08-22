# Создайте новый файл app/services/roster_ta_service.py

from __future__ import annotations
import os
from typing import Optional, List, Dict
import pandas as pd
from app.repositories.csv_repo import CsvTable

ROSTER_TA_COLUMNS = ["ta_id", "last_name_ru", "first_name_ru", "middle_name_ru"]

class RosterTaService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "roster_ta.csv"), ROSTER_TA_COLUMNS)
    
    def get_all_tas(self) -> List[Dict]:
        """Получить всех преподавателей из ростера"""
        df = self.table.read()
        if df.empty:
            return []
        
        tas = []
        for _, row in df.iterrows():
            ta_dict = row.to_dict()
            # Форматируем полное имя
            first_name = str(ta_dict.get("first_name_ru", "")).strip()
            last_name = str(ta_dict.get("last_name_ru", "")).strip() 
            middle_name = str(ta_dict.get("middle_name_ru", "")).strip()
            
            full_name = f"{last_name} {first_name}"
            if middle_name and middle_name != "nan":
                full_name += f" {middle_name}"
            
            ta_dict["full_name"] = full_name.strip()
            tas.append(ta_dict)
        
        return tas
    
    def get_ta_by_id(self, ta_id: str) -> Optional[Dict]:
        """Найти преподавателя по ta_id"""
        df = self.table.read()
        if df.empty:
            return None
        
        ta_data = df[df["ta_id"] == ta_id]
        if ta_data.empty:
            return None
        
        ta_dict = ta_data.iloc[0].to_dict()
        
        # Форматируем полное имя
        first_name = str(ta_dict.get("first_name_ru", "")).strip()
        last_name = str(ta_dict.get("last_name_ru", "")).strip()
        middle_name = str(ta_dict.get("middle_name_ru", "")).strip()
        
        full_name = f"{last_name} {first_name}"
        if middle_name and middle_name != "nan":
            full_name += f" {middle_name}"
        
        ta_dict["full_name"] = full_name.strip()
        return ta_dict