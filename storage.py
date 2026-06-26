#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Модуль для работы с JSON-хранилищем
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

DATA_DIR = "data"


def ensure_data_dir():
    """Создает папку data, если её нет"""
    os.makedirs(DATA_DIR, exist_ok=True)


def load_data(filename: str) -> Dict[str, Any]:
    """Загружает данные из JSON файла"""
    ensure_data_dir()
    filepath = os.path.join(DATA_DIR, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data(filename: str, data: Dict[str, Any]) -> None:
    """Сохраняет данные в JSON файл"""
    ensure_data_dir()
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def init_default_files():
    """Создает файлы с данными по умолчанию при первом запуске"""
    default_files = {
        "users.json": {
            "admin_id": None,
            "observers": [],
            "group_id": None
        },
        "settings.json": {
            "weight": 63,
            "activity": 1.4,
            "training_days": [0, 2, 4],
            "daily_calories_rest": 2340,
            "daily_calories_train": 2540,
            "daily_protein": 170,
            "daily_fat": 85,
            "daily_carbs": 300
        },
        "day_data.json": {
            "wake_time": None,
            "meals": {
                "breakfast": {"eaten": False, "dish": None, "kcal": 0, "protein": 0, "fat": 0, "carbs": 0,
                              "has_veggies": False, "is_custom": False},
                "lunch": {"eaten": False, "dish": None, "kcal": 0, "protein": 0, "fat": 0, "carbs": 0,
                          "has_veggies": False, "is_custom": False},
                "snack": {"eaten": False, "dish": None, "kcal": 0, "protein": 0, "fat": 0, "carbs": 0,
                          "has_veggies": False, "is_custom": False},
                "dinner": {"eaten": False, "dish": None, "kcal": 0, "protein": 0, "fat": 0, "carbs": 0,
                           "has_veggies": False, "is_custom": False},
                "before_bed": {"eaten": False, "dish": None, "kcal": 0, "protein": 0, "fat": 0, "carbs": 0,
                               "has_veggies": False, "is_custom": False}
            },
            "veggies_eaten_today": False,
            "salad_offered": False,
            "salad_eaten": None,
            "extra_meals": []
        },
        "training_log.json": {},
        "custom_meals.json": {},
        "temp.json": {}
    }

    for filename, default_data in default_files.items():
        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(default_data, f, indent=2, ensure_ascii=False)


def get_meals_schedule(wake_time: datetime) -> Dict[str, datetime]:
    """Рассчитывает время приемов пищи от времени пробуждения"""
    return {
        "breakfast": wake_time + timedelta(hours=1),
        "lunch": wake_time + timedelta(hours=5),
        "snack": wake_time + timedelta(hours=9),
        "dinner": wake_time + timedelta(hours=12, minutes=30),
        "before_bed": wake_time + timedelta(hours=15),
    }


def get_last_workout(workout_type: str) -> Optional[Dict]:
    """Возвращает последнюю тренировку указанного типа (A, B или C)"""
    training_log = load_data("training_log.json")

    for date in sorted(training_log.keys(), reverse=True):
        workout = training_log[date]
        if workout.get("workout_type") == workout_type:
            return {"date": date, "data": workout}

    return None


def check_veggies(day_data: Dict) -> bool:
    """Проверяет, были ли овощи в течение дня"""
    meals = day_data.get("meals", {})
    for meal in MEALS_ORDER:
        if meals.get(meal, {}).get("has_veggies", False):
            return True
    return False


def calculate_calories(weight: float, height: int, age: int, activity: float) -> tuple:
    """
    Рассчитывает калории по формуле Миффлина-Сан Жеора
    Возвращает: (калории_в_день_отдыха, калории_в_тренировочный_день)
    """
    # BMR = 10 × вес(кг) + 6.25 × рост(см) − 5 × возраст(лет) + 5
    bmr = 10 * weight + 6.25 * height - 5 * age + 5

    # Поддержание веса
    maintenance = bmr * activity

    # Набор массы (+200 ккал в дни отдыха, +400 в тренировочные дни)
    rest_calories = maintenance + 200
    train_calories = maintenance + 400

    return round(rest_calories, 0), round(train_calories, 0)


# Импорт для check_veggies
from constants import MEALS_ORDER

# Инициализация при импорте
init_default_files()