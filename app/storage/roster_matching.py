"""
Система поиска и сопоставления студентов с ростером
"""
import re
from typing import List, Dict, Optional, Tuple
from difflib import SequenceMatcher
from dataclasses import dataclass

from app.storage import roster


@dataclass
class MatchResult:
    student_code: str
    external_email: str
    display_name: str  # для показа пользователю
    match_type: str    # "email", "name_group", "name_only"
    confidence: float  # 0.0 - 1.0
    roster_data: dict  # полные данные из ростера


def normalize_name(name: str) -> str:
    """Нормализация имени для поиска"""
    if not name:
        return ""
    # Убираем лишние пробелы, приводим к нижнему регистру
    normalized = re.sub(r'\s+', ' ', name.strip().lower())
    # Убираем дефисы и точки
    normalized = re.sub(r'[-.]', '', normalized)
    return normalized


def fuzzy_match_score(s1: str, s2: str) -> float:
    """Вычисляет схожесть двух строк (0.0 - 1.0)"""
    if not s1 or not s2:
        return 0.0
    return SequenceMatcher(None, normalize_name(s1), normalize_name(s2)).ratio()


def extract_lastname_from_full_name(full_name: str) -> str:
    """Извлекает фамилию из полного имени (последнее слово)"""
    if not full_name:
        return ""
    parts = full_name.strip().split()
    return parts[-1] if parts else ""


def build_display_name(roster_row: dict) -> str:
    """Строит отображаемое имя из данных ростера"""
    # Приоритет русским именам
    if roster_row.get('last_name_ru') and roster_row.get('first_name_ru'):
        name = f"{roster_row['last_name_ru']} {roster_row['first_name_ru']}"
        if roster_row.get('middle_name_ru'):
            name += f" {roster_row['middle_name_ru']}"
    elif roster_row.get('last_name_en') and roster_row.get('first_name_en'):
        name = f"{roster_row['last_name_en']} {roster_row['first_name_en']}"
        if roster_row.get('middle_name_en'):
            name += f" {roster_row['middle_name_en']}"
    else:
        name = "Unknown Name"
    
    group = roster_row.get('group', 'Unknown Group')
    return f"{name} ({group})"


def find_student_matches(
    full_name: str, 
    group: str, 
    email: str
) -> List[MatchResult]:
    """
    Основная функция поиска с приоритетами
    
    Приоритеты:
    1. Точное совпадение по email
    2. Фамилия + группа (fuzzy)
    3. Только фамилия (fuzzy)
    """
    all_roster_data = roster.load_roster()  # Используем существующую функцию
    if not all_roster_data:
        return []
    
    matches = []
    student_lastname = extract_lastname_from_full_name(full_name)
    
    # Приоритет 1: Точное совпадение по email
    for row in all_roster_data:
        if row.get('external_email', '').lower() == email.lower():
            matches.append(MatchResult(
                student_code=row['student_code'],
                external_email=row['external_email'],
                display_name=build_display_name(row),
                match_type="email",
                confidence=1.0,
                roster_data=row
            ))
    
    # Если нашли точное совпадение по email, возвращаем только его
    if matches:
        return matches
    
    # Приоритет 2: Фамилия + группа (fuzzy matching)
    for row in all_roster_data:
        # Проверяем русскую фамилию
        ru_lastname = row.get('last_name_ru', '')
        en_lastname = row.get('last_name_en', '')
        row_group = row.get('group', '')
        
        # Fuzzy match по фамилии
        ru_score = fuzzy_match_score(student_lastname, ru_lastname)
        en_score = fuzzy_match_score(student_lastname, en_lastname)
        name_score = max(ru_score, en_score)
        
        # Точное совпадение группы (с небольшой толерантностью к регистру)
        group_match = group.strip().lower() == row_group.strip().lower() if group and row_group else False
        
        # Если фамилия похожа (>0.7) И группа совпадает
        if name_score > 0.7 and group_match:
            matches.append(MatchResult(
                student_code=row['student_code'],
                external_email=row['external_email'],
                display_name=build_display_name(row),
                match_type="name_group",
                confidence=name_score * 0.9,  # немного снижаем за неточность
                roster_data=row
            ))
    
    # Если нашли совпадения по фамилии+группе, возвращаем их
    if matches:
        return sorted(matches, key=lambda x: x.confidence, reverse=True)
    
    # Приоритет 3: Только фамилия (fuzzy matching)
    for row in all_roster_data:
        ru_lastname = row.get('last_name_ru', '')
        en_lastname = row.get('last_name_en', '')
        
        ru_score = fuzzy_match_score(student_lastname, ru_lastname)
        en_score = fuzzy_match_score(student_lastname, en_lastname)
        name_score = max(ru_score, en_score)
        
        # Если фамилия достаточно похожа (>0.8 для более строгого отбора)
        if name_score > 0.8:
            matches.append(MatchResult(
                student_code=row['student_code'],
                external_email=row['external_email'],
                display_name=build_display_name(row),
                match_type="name_only",
                confidence=name_score * 0.7,  # значительно снижаем за отсутствие группы
                roster_data=row
            ))
    
    # Возвращаем топ-3 по уверенности
    return sorted(matches, key=lambda x: x.confidence, reverse=True)[:3]


def validate_match_quality(matches: List[MatchResult]) -> Tuple[str, List[MatchResult]]:
    """
    Анализирует качество найденных совпадений
    
    Returns:
        status: "exact", "good", "uncertain", "none"
        filtered_matches: отфильтрованные совпадения
    """
    if not matches:
        return "none", []
    
    # Если есть точное совпадение по email
    email_matches = [m for m in matches if m.match_type == "email"]
    if email_matches:
        return "exact", email_matches[:1]
    
    # Если есть хорошие совпадения по фамилии+группе
    name_group_matches = [m for m in matches if m.match_type == "name_group" and m.confidence > 0.8]
    if len(name_group_matches) == 1:
        return "good", name_group_matches
    elif len(name_group_matches) <= 3:
        return "uncertain", name_group_matches
    
    # Если есть только совпадения по фамилии
    name_only_matches = [m for m in matches if m.match_type == "name_only" and m.confidence > 0.85]
    if len(name_only_matches) <= 3:
        return "uncertain", name_only_matches
    
    return "none", []