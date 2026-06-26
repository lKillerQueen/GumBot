#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Бот для контроля питания и тренировок
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from config import BOT_TOKEN, PROXY_URL, PROGRESSION_STEP
from storage import (
    load_data, save_data, get_meals_schedule,
    get_last_workout, check_veggies, calculate_calories
)
from constants import (
    MEALS_ORDER, MEALS_NAMES, MEALS_EMOJI,
    FOOD_DB,
    BREAKFAST_TRAIN, BREAKFAST_REST,
    LUNCH_MEALS, DINNER_MEALS,
    SNACK_MEALS, BEFORE_BED_MEALS, SALAD_MEALS,
    WORKOUT_SCHEDULE, DAYS_RU,
    DEFAULT_HEIGHT, DEFAULT_AGE, DEFAULT_ACTIVITY, ACTIVITY_LEVELS
)


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def calc_kcal(items: list) -> tuple:
    """Рассчитывает КБЖУ по списку ингредиентов"""
    total_p = total_f = total_c = total_kcal = 0
    for key, count in items:
        if key in FOOD_DB:
            p, f, c, kcal = FOOD_DB[key]
            total_p += p * count
            total_f += f * count
            total_c += c * count
            total_kcal += kcal * count
    return round(total_kcal, 1), round(total_p, 1), round(total_f, 1), round(total_c, 1)


def is_training_day() -> bool:
    """Проверяет, тренировочный ли сегодня день"""
    settings = load_data("settings.json")
    training_days = settings.get("training_days", [0, 2, 4])
    today = datetime.now().weekday()
    return today in training_days


def get_day_calories() -> int:
    """Возвращает норму калорий на сегодня"""
    settings = load_data("settings.json")
    if is_training_day():
        return settings.get("daily_calories_train", 2540)
    return settings.get("daily_calories_rest", 2340)


def get_today_workout() -> Optional[Dict]:
    """Возвращает тренировку на сегодня или None"""
    today = datetime.now().weekday()
    return WORKOUT_SCHEDULE.get(today)


def get_progression_message(workout_type: str) -> str:
    """Возвращает сообщение с рекомендациями по прогрессии"""
    last = get_last_workout(workout_type)
    if not last:
        return ""

    msg = "🔔 ПРОГРЕССИЯ:\n\n"
    msg += f"В прошлый раз ({last['date']}):\n"

    for ex_name, ex_data in last['data'].get('exercises', {}).items():
        if ex_data.get('is_base'):
            sets_str = ", ".join([f"{s['weight']}кг x {s['reps']}" for s in ex_data.get('sets', [])])
            msg += f"⭐ {ex_name}: {sets_str}\n"

    msg += f"\n📈 Добавь +{PROGRESSION_STEP}кг к базовым упражнениям!"
    msg += "\nБудет тяжело — это нормально! 💪"

    return msg


def format_stats(day_data: Dict) -> str:
    """Формирует красивую таблицу со статистикой"""
    settings = load_data("settings.json")
    daily_cal = get_day_calories()
    meals_data = day_data.get("meals", {})
    total_p = total_f = total_c = total_kcal = 0
    lines = []

    for meal in MEALS_ORDER:
        m = meals_data.get(meal, {})
        emoji = MEALS_EMOJI.get(meal, "")
        name = MEALS_NAMES.get(meal, meal.upper())
        if m.get("eaten"):
            dish = m.get("dish", "Блюдо")
            if m.get("is_custom"):
                dish += " ✏️"
            kcal = m.get("kcal", 0)
            p = m.get("protein", 0)
            c = m.get("carbs", 0)
            f = m.get("fat", 0)
            total_p += p
            total_f += f
            total_c += c
            total_kcal += kcal
            lines.append(f"✅ {emoji} {name}: {dish}")
            lines.append(f"   🔥 {kcal} ккал | 🥩 {p}г | 🍞 {c}г | 🥑 {f}г")
        else:
            lines.append(f"⏳ {emoji} {name}: ЕЩЕ НЕ ЕЛ")

    # Добавляем дополнительные приемы (кастомные)
    for extra in day_data.get("extra_meals", []):
        if extra.get("eaten"):
            lines.append(f"✅ ✏️ ДОПОЛНИТЕЛЬНО: {extra.get('dish')}")
            lines.append(
                f"   🔥 {extra.get('kcal')} ккал | 🥩 {extra.get('protein')}г | 🍞 {extra.get('carbs')}г | 🥑 {extra.get('fat')}г")
            total_kcal += extra.get('kcal', 0)
            total_p += extra.get('protein', 0)
            total_f += extra.get('fat', 0)
            total_c += extra.get('carbs', 0)

    lines.append("\n═══════════════════════════════════════════")
    remaining = daily_cal - total_kcal
    lines.append(f"ИТОГО ЗА СЕГОДНЯ (цель: {daily_cal} ккал):")
    lines.append(f"🔥 Калории: {total_kcal:.1f} / {daily_cal} (осталось {remaining:.1f})")
    lines.append(f"🥩 Белки: {total_p:.1f} / {settings.get('daily_protein', 170)} г")
    lines.append(f"🍞 Углеводы: {total_c:.1f} / {settings.get('daily_carbs', 300)} г")
    lines.append(f"🥑 Жиры: {total_f:.1f} / {settings.get('daily_fat', 85)} г")

    return "\n".join(lines)


def get_nearest_meal(wake_time: datetime, current_time: datetime) -> str:
    """Определяет, какой прием пищи сейчас ближе всего"""
    schedule = get_meals_schedule(wake_time)
    nearest = None
    min_diff = float('inf')

    for meal, meal_time in schedule.items():
        diff = (current_time - meal_time).total_seconds()
        if 0 <= diff < min_diff:
            min_diff = diff
            nearest = meal

    return nearest


# ==================== КЛАВИАТУРЫ ====================

def get_main_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🍽️ Поесть", callback_data="menu_eat")],
        [InlineKeyboardButton("🏋️ Тренировка", callback_data="menu_train")],
        [InlineKeyboardButton("📊 Рацион", callback_data="menu_stats")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings")],
        [InlineKeyboardButton("➕ Добавить свое блюдо", callback_data="menu_custom_meal")],
    ]
    return InlineKeyboardMarkup(kb)


def get_meals_menu_kb() -> InlineKeyboardMarkup:
    kb = []
    for meal in MEALS_ORDER:
        kb.append([InlineKeyboardButton(
            f"{MEALS_EMOJI.get(meal, '')} {MEALS_NAMES.get(meal, '')}",
            callback_data=f"meal_{meal}"
        )])
    kb.append([InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(kb)


def get_meal_kb(meal: str, is_train: bool) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру с вариантами блюд для конкретного приема"""
    if meal == "breakfast":
        options = BREAKFAST_TRAIN if is_train else BREAKFAST_REST
    elif meal == "lunch":
        options = LUNCH_MEALS
    elif meal == "dinner":
        options = DINNER_MEALS
    elif meal == "snack":
        options = SNACK_MEALS
    elif meal == "before_bed":
        options = BEFORE_BED_MEALS
    else:
        options = []

    kb = []
    for i, opt in enumerate(options):
        kb.append([InlineKeyboardButton(
            opt["name"],
            callback_data=f"eat_{meal}_{i}"
        )])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_meals")])
    return InlineKeyboardMarkup(kb)


def get_salad_kb() -> InlineKeyboardMarkup:
    kb = []
    for i, salad in enumerate(SALAD_MEALS):
        kb.append([InlineKeyboardButton(
            f"{salad['name']} — {salad['kcal']} ккал",
            callback_data=f"salad_{i}"
        )])
    kb.append([InlineKeyboardButton("⏭️ Пропустить", callback_data="salad_skip")])
    return InlineKeyboardMarkup(kb)


# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_data("users.json")
    chat = update.effective_chat

    if chat.type in ["group", "supergroup"]:
        if not users.get("group_id"):
            users["group_id"] = chat.id
            save_data("users.json", users)
            await update.message.reply_text(
                "👋 Привет! Я бот для контроля питания и тренировок.\n\n"
                "Напиши /setadmin, чтобы назначить себя администратором.\n"
                "После этого я буду работать в этой группе."
            )
        else:
            await update.message.reply_text(
                "Бот уже настроен. Используй кнопки ниже.",
                reply_markup=get_main_kb()
            )
    else:
        await update.message.reply_text(
            "👋 Привет! Я работаю только в групповых чатах.\n"
            "Создай группу, добавь меня туда и дай права администратора."
        )


async def setadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_data("users.json")
    if users.get("admin_id"):
        await update.message.reply_text("⚠️ Администратор уже назначен.")
        return

    users["admin_id"] = update.effective_user.id
    save_data("users.json", users)

    await update.message.reply_text(
        f"✅ {update.effective_user.first_name}, ты назначен администратором бота!\n"
        "Теперь ты можешь:\n• Выбирать блюда\n• Записывать тренировки\n• Менять настройки\n• Добавлять свои блюда\n\n"
        "Остальные участники группы могут только просматривать рацион."
    )


async def start_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_data("users.json")
    if update.effective_user.id != users.get("admin_id"):
        await update.message.reply_text("⛔ Только администратор может начать день.")
        return

    now = datetime.now()
    day_data = load_data("day_data.json")
    day_data["wake_time"] = now.isoformat()
    day_data["extra_meals"] = []

    for meal in MEALS_ORDER:
        day_data["meals"][meal] = {
            "eaten": False,
            "dish": None,
            "kcal": 0,
            "protein": 0,
            "fat": 0,
            "carbs": 0,
            "has_veggies": False,
            "is_custom": False
        }

    day_data["veggies_eaten_today"] = False
    day_data["salad_offered"] = False
    day_data["salad_eaten"] = None

    save_data("day_data.json", day_data)

    schedule = get_meals_schedule(now)
    msg = f"🌅 День начат в {now.strftime('%H:%M')}\n\n📅 РАСПИСАНИЕ ПРИЕМОВ ПИЩИ:\n"
    for meal in MEALS_ORDER:
        meal_time = schedule.get(meal)
        if meal_time:
            msg += f"{MEALS_EMOJI.get(meal, '')} {MEALS_NAMES.get(meal, '')}: {meal_time.strftime('%H:%M')}\n"

    msg += f"\n🔥 Калорийность сегодня: {get_day_calories()} ккал"
    if is_training_day():
        msg += "\n🏋️ ТРЕНИРОВОЧНЫЙ"
        workout = get_today_workout()
        if workout:
            msg += f"\n📋 {workout['name']}"
    else:
        msg += "\n😴 ДЕНЬ ОТДЫХА"

    await update.message.reply_text(msg, reply_markup=get_main_kb())

    for obs_id in users.get("observers", []):
        try:
            await context.bot.send_message(
                obs_id,
                f"🌅 {update.effective_user.first_name} начал день в {now.strftime('%H:%M')}"
            )
        except:
            pass


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Твой ID: <code>{update.effective_user.id}</code>")


async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_data("users.json")
    admin_id = users.get("admin_id")

    if not admin_id:
        await update.message.reply_text("⚠️ Администратор еще не назначен. Напиши /setadmin")
        return

    if update.effective_user.id == admin_id:
        await update.message.reply_text("Ты уже администратор.")
        return

    if update.effective_user.id in users.get("observers", []):
        await update.message.reply_text("Ты уже привязан как наблюдатель.")
        return

    users["observers"].append(update.effective_user.id)
    save_data("users.json", users)
    await update.message.reply_text("✅ Ты привязан к администратору как наблюдатель!")


# ==================== ОБРАБОТЧИКИ КНОПОК ====================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    users = load_data("users.json")
    is_admin = (user_id == users.get("admin_id"))

    # ====== НАЗАД ======
    if data == "back_to_meals":
        await query.edit_message_text(
            "🍽️ Выбери прием пищи:",
            reply_markup=get_meals_menu_kb()
        )
        return

    if data == "main_menu":
        await query.edit_message_text(
            "🏠 Главное меню:",
            reply_markup=get_main_kb()
        )
        return

    # ====== МЕНЮ ======
    if data == "menu_eat":
        if not is_admin:
            await query.answer("⛔ Только администратор может выбирать еду.", show_alert=True)
            return
        await query.edit_message_text(
            "🍽️ Выбери прием пищи:",
            reply_markup=get_meals_menu_kb()
        )
        return

    if data == "menu_stats":
        day_data = load_data("day_data.json")
        await query.edit_message_text(
            format_stats(day_data),
            reply_markup=get_main_kb()
        )
        return

    if data == "menu_settings":
        if not is_admin:
            await query.answer("⛔ Только администратор может менять настройки.", show_alert=True)
            return
        settings = load_data("settings.json")
        weight = settings.get('weight', 63)
        height = settings.get('height', DEFAULT_HEIGHT)
        age = settings.get('age', DEFAULT_AGE)
        activity = settings.get('activity', DEFAULT_ACTIVITY)
        rest_cal = settings.get('daily_calories_rest', 2340)
        train_cal = settings.get('daily_calories_train', 2540)

        activity_name = ACTIVITY_LEVELS.get(activity, "Неизвестно")

        msg = "⚙️ НАСТРОЙКИ\n\n"
        msg += f"📏 Рост: {height} см\n"
        msg += f"⚖️ Вес: {weight} кг\n"
        msg += f"🎂 Возраст: {age} лет\n"
        msg += f"🏃 Активность: {activity} ({activity_name})\n\n"
        msg += f"🔥 Калории (отдых): {rest_cal} ккал\n"
        msg += f"🔥 Калории (тренировка): {train_cal} ккал\n"

        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Изменить вес", callback_data="set_weight")],
                [InlineKeyboardButton("📏 Изменить рост", callback_data="set_height")],
                [InlineKeyboardButton("🎂 Изменить возраст", callback_data="set_age")],
                [InlineKeyboardButton("🏃 Изменить активность", callback_data="set_activity")],
                [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
            ])
        )
        return

    if data == "menu_custom_meal":
        if not is_admin:
            await query.answer("⛔ Только администратор может добавлять блюда.", show_alert=True)
            return
        temp = load_data("temp.json")
        temp["custom_state"] = "waiting_name"
        save_data("temp.json", temp)
        await query.edit_message_text(
            "🍽️ Введи название блюда:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
            ])
        )
        return

    # ====== ТРЕНИРОВКИ ======
    if data == "menu_train":
        if not is_admin:
            await query.answer("⛔ Только администратор может записывать тренировки.", show_alert=True)
            return

        workout = get_today_workout()
        if not workout:
            await query.edit_message_text(
                "😴 Сегодня день отдыха!\n"
                f"Следующая тренировка: {DAYS_RU.get(datetime.now().weekday() + 1, '')}",
                reply_markup=get_main_kb()
            )
            return

        # Прогрессия
        prog_msg = get_progression_message(workout["type"])

        msg = f"🏋️ ТРЕНИРОВКА {workout['type']}: {workout['name']}\n\n"
        if prog_msg:
            msg += prog_msg + "\n\n"

        msg += "📋 Упражнения:\n"
        for i, ex in enumerate(workout["exercises"], 1):
            base_tag = " (базовое)" if ex.get("is_base") else ""
            msg += f"{i}. {ex['name']}{base_tag} — {ex['sets']} подходов x {ex['reps']} повторений\n"
            msg += f"   💡 {ex['note']}\n"

        msg += "\nВыбери упражнение:"

        kb = []
        for ex in workout["exercises"]:
            kb.append([InlineKeyboardButton(ex["name"], callback_data=f"train_ex_{workout['exercises'].index(ex)}")])
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])

        # Сохраняем состояние тренировки
        temp = load_data("temp.json")
        temp["train_state"] = "selecting_exercise"
        temp["workout_type"] = workout["type"]
        temp["workout_name"] = workout["name"]
        temp["exercises"] = workout["exercises"]
        temp["current_exercise_index"] = 0
        temp["current_exercise"] = None
        temp["total_sets"] = 0
        temp["current_set"] = 0
        temp["sets_log"] = []
        temp["all_exercises_log"] = {}
        save_data("temp.json", temp)

        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("train_ex_"):
        if not is_admin:
            await query.answer("⛔ Только администратор может записывать тренировки.", show_alert=True)
            return

        idx = int(data.replace("train_ex_", ""))
        temp = load_data("temp.json")
        exercises = temp.get("exercises", [])

        if idx >= len(exercises):
            await query.answer("Упражнение не найдено.")
            return

        ex = exercises[idx]
        temp["current_exercise"] = ex["name"]
        temp["current_exercise_index"] = idx
        temp["current_set"] = 0
        temp["sets_log"] = []
        temp["train_state"] = "selecting_sets"
        save_data("temp.json", temp)

        # Проверяем прогрессию для этого упражнения
        prog_msg = ""
        if ex.get("is_base"):
            last = get_last_workout(temp["workout_type"])
            if last:
                ex_data = last["data"].get("exercises", {}).get(ex["name"])
                if ex_data:
                    last_weight = ex_data["sets"][-1]["weight"] if ex_data["sets"] else 0
                    prog_msg = f"\n📈 Рекомендуемый вес: {last_weight + PROGRESSION_STEP}кг (+{PROGRESSION_STEP}кг к прошлому)"

        await query.edit_message_text(
            f"🏋️ {ex['name']}\n"
            f"По плану: {ex['sets']} подходов x {ex['reps']} повторений\n"
            f"💡 {ex['note']}{prog_msg}\n\n"
            "Сколько подходов ты хочешь сделать?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("3", callback_data=f"sets_3")],
                [InlineKeyboardButton("4", callback_data=f"sets_4")],
                [InlineKeyboardButton("5", callback_data=f"sets_5")],
                [InlineKeyboardButton("🔙 Назад", callback_data="menu_train")]
            ])
        )
        return

    if data.startswith("sets_"):
        if not is_admin:
            await query.answer()
            return

        sets = int(data.replace("sets_", ""))
        temp = load_data("temp.json")
        temp["total_sets"] = sets
        temp["current_set"] = 1
        temp["train_state"] = "entering_sets"
        save_data("temp.json", temp)

        ex_name = temp.get("current_exercise", "Упражнение")
        await query.edit_message_text(
            f"🏋️ {ex_name}\n"
            f"Подход 1 из {sets}\n\n"
            "Введи вес и количество повторений через пробел:\n"
            "<code>вес повторения</code>\n"
            "Пример: 80 8",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="menu_train")]
            ])
        )
        return

    # ====== ВЫБОР ПРИЕМА ПИЩИ ======
    if data.startswith("meal_"):
        if not is_admin:
            await query.answer("⛔ Только администратор может выбирать еду.", show_alert=True)
            return
        meal = data.replace("meal_", "")
        is_train = is_training_day()
        await query.edit_message_text(
            f"{MEALS_EMOJI.get(meal, '')} {MEALS_NAMES.get(meal, '')}\n"
            f"{'🏋️ ТРЕНИРОВОЧНЫЙ' if is_train else '😴 ДЕНЬ ОТДЫХА'}\n\nВыбери блюдо:",
            reply_markup=get_meal_kb(meal, is_train)
        )
        return

    # ====== ВЫБОР БЛЮДА ======
    if data.startswith("eat_"):
        if not is_admin:
            await query.answer("⛔ Только администратор может выбирать еду.", show_alert=True)
            return

        parts = data.split("_")
        meal = parts[1]
        idx = int(parts[2])

        # Определяем список блюд
        if meal == "breakfast":
            options = BREAKFAST_TRAIN if is_training_day() else BREAKFAST_REST
        elif meal == "lunch":
            options = LUNCH_MEALS
        elif meal == "dinner":
            options = DINNER_MEALS
        elif meal == "snack":
            options = SNACK_MEALS
        elif meal == "before_bed":
            options = BEFORE_BED_MEALS
        else:
            await query.answer("Неизвестный прием пищи.")
            return

        if idx >= len(options):
            await query.answer("Блюдо не найдено.")
            return

        opt = options[idx]
        kcal, protein, fat, carbs = calc_kcal(opt.get("items", []))

        day_data = load_data("day_data.json")
        day_data["meals"][meal] = {
            "eaten": True,
            "dish": opt["name"],
            "kcal": kcal,
            "protein": protein,
            "fat": fat,
            "carbs": carbs,
            "has_veggies": opt.get("has_veggies", False),
            "is_custom": False
        }

        # Обновляем статус овощей
        if opt.get("has_veggies", False):
            day_data["veggies_eaten_today"] = True

        save_data("day_data.json", day_data)

        await query.edit_message_text(
            f"✅ {MEALS_NAMES.get(meal, '')} записан!\n🍽️ {opt['name']}\n"
            f"🔥 {kcal} ккал | 🥩 {protein}г | 🍞 {carbs}г | 🥑 {fat}г\n\n"
            f"📊 Статистика обновлена.",
            reply_markup=get_main_kb()
        )

        # Уведомление наблюдателей
        for obs_id in users.get("observers", []):
            try:
                await context.bot.send_message(
                    obs_id,
                    f"🍽️ {query.from_user.first_name} {MEALS_NAMES.get(meal, '').lower()}:\n{opt['name']}\n🔥 {kcal} ккал"
                )
            except:
                pass

        # Проверка овощей (в 22:00 или позже)
        now = datetime.now()
        if now.hour >= 22:
            day_data = load_data("day_data.json")
            if not day_data.get("veggies_eaten_today") and not day_data.get("salad_offered"):
                day_data["salad_offered"] = True
                save_data("day_data.json", day_data)
                await query.message.reply_text(
                    "🥗 ВНИМАНИЕ! Сегодня ты не ел овощи!\n\n"
                    "Овощи необходимы для пищеварения и витаминов.\n"
                    "Выбери салат на перекус:",
                    reply_markup=get_salad_kb()
                )

        return

    # ====== САЛАТЫ ======
    if data.startswith("salad_"):
        if data == "salad_skip":
            day_data = load_data("day_data.json")
            day_data["salad_offered"] = True
            save_data("day_data.json", day_data)
            await query.edit_message_text(
                "⏭️ Хорошо, в следующий раз не забывай про овощи! 🥗",
                reply_markup=get_main_kb()
            )
            return

        idx = int(data.replace("salad_", ""))
        if idx >= len(SALAD_MEALS):
            await query.answer("Салат не найден.")
            return

        salad = SALAD_MEALS[idx]
        day_data = load_data("day_data.json")
        day_data["salad_eaten"] = salad["name"]
        day_data["veggies_eaten_today"] = True
        day_data["extra_meals"].append({
            "eaten": True,
            "dish": salad["name"] + " (салат)",
            "kcal": salad["kcal"],
            "protein": salad["protein"],
            "fat": salad["fat"],
            "carbs": salad["carbs"],
            "is_custom": False,
            "has_veggies": True
        })
        save_data("day_data.json", day_data)

        await query.edit_message_text(
            f"✅ Салат '{salad['name']}' добавлен в рацион!\n"
            f"🔥 {salad['kcal']} ккал | 🥩 {salad['protein']}г | 🍞 {salad['carbs']}г | 🥑 {salad['fat']}г\n\n"
            f"📊 Статистика обновлена.",
            reply_markup=get_main_kb()
        )
        return

    # ====== ИЗМЕНЕНИЕ НАСТРОЕК ======
    if data == "set_weight":
        if not is_admin:
            await query.answer("⛔ Только администратор может менять настройки.", show_alert=True)
            return
        temp = load_data("temp.json")
        temp["waiting_setting"] = "weight"
        save_data("temp.json", temp)
        await query.edit_message_text(
            "📝 Введи новый вес в килограммах.\nНапример: <code>65</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="menu_settings")]
            ])
        )
        return

    if data == "set_height":
        if not is_admin:
            await query.answer("⛔ Только администратор может менять настройки.", show_alert=True)
            return
        temp = load_data("temp.json")
        temp["waiting_setting"] = "height"
        save_data("temp.json", temp)
        await query.edit_message_text(
            "📏 Введи свой рост в сантиметрах.\nНапример: <code>177</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="menu_settings")]
            ])
        )
        return

    if data == "set_age":
        if not is_admin:
            await query.answer("⛔ Только администратор может менять настройки.", show_alert=True)
            return
        temp = load_data("temp.json")
        temp["waiting_setting"] = "age"
        save_data("temp.json", temp)
        await query.edit_message_text(
            "🎂 Введи свой возраст.\nНапример: <code>22</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="menu_settings")]
            ])
        )
        return

    if data == "set_activity":
        if not is_admin:
            await query.answer("⛔ Только администратор может менять настройки.", show_alert=True)
            return

        kb = []
        for val, name in ACTIVITY_LEVELS.items():
            kb.append([InlineKeyboardButton(
                f"{val} — {name}",
                callback_data=f"activity_{val}"
            )])
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data="menu_settings")])

        await query.edit_message_text(
            "🏃 Выбери свой уровень активности:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if data.startswith("activity_"):
        if not is_admin:
            await query.answer()
            return

        activity = float(data.replace("activity_", ""))
        settings = load_data("settings.json")
        settings["activity"] = activity

        # Пересчитываем калории
        weight = settings.get("weight", 63)
        height = settings.get("height", DEFAULT_HEIGHT)
        age = settings.get("age", DEFAULT_AGE)

        rest_cal, train_cal = calculate_calories(weight, height, age, activity)
        settings["daily_calories_rest"] = rest_cal
        settings["daily_calories_train"] = train_cal

        save_data("settings.json", settings)

        await query.edit_message_text(
            f"✅ Активность обновлена: {activity}\n"
            f"🔥 Калории пересчитаны:\n"
            f"   Отдых: {rest_cal} ккал\n"
            f"   Тренировка: {train_cal} ккал",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Настройки", callback_data="menu_settings")]
            ])
        )
        return


# ==================== ОБРАБОТЧИК ТЕКСТА ====================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.startswith("/"):
        return

    temp = load_data("temp.json")
    users = load_data("users.json")

    # Проверяем, что пользователь — админ
    if update.effective_user.id != users.get("admin_id"):
        return

    # ====== ИЗМЕНЕНИЕ НАСТРОЕК ======
    if temp.get("waiting_setting"):
        try:
            value = float(update.message.text.strip())
            if value <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ Введи положительное число!")
            return

        setting = temp.get("waiting_setting")
        settings = load_data("settings.json")
        settings[setting] = value

        # Если изменился вес, рост или возраст — пересчитываем калории
        if setting in ["weight", "height", "age"]:
            weight = settings.get("weight", 63)
            height = settings.get("height", DEFAULT_HEIGHT)
            age = settings.get("age", DEFAULT_AGE)
            activity = settings.get("activity", DEFAULT_ACTIVITY)

            rest_cal, train_cal = calculate_calories(weight, height, age, activity)
            settings["daily_calories_rest"] = rest_cal
            settings["daily_calories_train"] = train_cal

            msg = f"✅ {setting.capitalize()} обновлен: {value}\n"
            msg += f"🔥 Калории пересчитаны:\n"
            msg += f"   Отдых: {rest_cal} ккал\n"
            msg += f"   Тренировка: {train_cal} ккал"
        else:
            msg = f"✅ {setting.capitalize()} обновлен: {value}"

        save_data("settings.json", settings)

        temp["waiting_setting"] = None
        save_data("temp.json", temp)

        await update.message.reply_text(msg, reply_markup=get_main_kb())
        return

    # ====== ДОБАВЛЕНИЕ КАСТОМНОГО БЛЮДА ======
    if temp.get("custom_state") == "waiting_name":
        name = update.message.text.strip()
        if not name:
            await update.message.reply_text("⚠️ Название не может быть пустым.")
            return

        temp["custom_name"] = name
        temp["custom_state"] = "waiting_kbju"
        save_data("temp.json", temp)

        await update.message.reply_text(
            f"📊 Введи КБЖУ для '{name}' через пробел:\n"
            "<code>калории белки жиры углеводы</code>\n"
            "Пример: 250 25 5 20"
        )
        return

    if temp.get("custom_state") == "waiting_kbju":
        parts = update.message.text.split()
        if len(parts) != 4:
            await update.message.reply_text("⚠️ Нужно 4 числа: калории белки жиры углеводы\nПример: 250 25 5 20")
            return

        try:
            kcal = float(parts[0])
            protein = float(parts[1])
            fat = float(parts[2])
            carbs = float(parts[3])
        except ValueError:
            await update.message.reply_text("⚠️ Введи числа! Пример: 250 25 5 20")
            return

        name = temp.get("custom_name", "Блюдо")
        day_data = load_data("day_data.json")

        # Добавляем в extra_meals
        day_data["extra_meals"].append({
            "eaten": True,
            "dish": name + " (кастомное)",
            "kcal": kcal,
            "protein": protein,
            "fat": fat,
            "carbs": carbs,
            "has_veggies": False,
            "is_custom": True
        })
        save_data("day_data.json", day_data)

        # Сохраняем в custom_meals.json
        custom_meals = load_data("custom_meals.json")
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in custom_meals:
            custom_meals[today] = []
        custom_meals[today].append({
            "name": name,
            "kcal": kcal,
            "protein": protein,
            "fat": fat,
            "carbs": carbs,
            "added_at": datetime.now().isoformat()
        })
        save_data("custom_meals.json", custom_meals)

        temp["custom_state"] = None
        temp["custom_name"] = None
        save_data("temp.json", temp)

        await update.message.reply_text(
            f"✅ Блюдо '{name}' добавлено в рацион!\n"
            f"🔥 {kcal} ккал | 🥩 {protein}г | 🍞 {carbs}г | 🥑 {fat}г\n\n"
            f"📊 Статистика обновлена.",
            reply_markup=get_main_kb()
        )
        return

    # ====== ТРЕНИРОВКИ (ВВОД ПОДХОДОВ) ======
    if temp.get("train_state") == "entering_sets":
        parts = update.message.text.split()
        if len(parts) != 2:
            await update.message.reply_text("⚠️ Нужно 2 числа: вес повторения\nПример: 80 8")
            return

        try:
            weight = float(parts[0])
            reps = int(parts[1])
        except ValueError:
            await update.message.reply_text("⚠️ Введи числа! Пример: 80 8")
            return

        ex_name = temp.get("current_exercise", "Упражнение")
        total_sets = temp.get("total_sets", 0)
        current_set = temp.get("current_set", 1)
        sets_log = temp.get("sets_log", [])

        sets_log.append({"weight": weight, "reps": reps})
        temp["sets_log"] = sets_log
        temp["current_set"] = current_set + 1

        if current_set < total_sets:
            save_data("temp.json", temp)
            await update.message.reply_text(
                f"✅ Подход {current_set}: {weight}кг x {reps} повторений\n\n"
                f"🏋️ {ex_name}\n"
                f"Подход {current_set + 1} из {total_sets}\n\n"
                "Введи вес и количество повторений:"
            )
        else:
            # Все подходы записаны
            # Сохраняем в тренировочный лог
            training_log = load_data("training_log.json")
            today = datetime.now().strftime("%Y-%m-%d")
            if today not in training_log:
                training_log[today] = {
                    "day_name": DAYS_RU.get(datetime.now().weekday()),
                    "workout_name": temp.get("workout_name", ""),
                    "workout_type": temp.get("workout_type", ""),
                    "exercises": {}
                }

            # Находим все записанные упражнения
            all_logs = temp.get("all_exercises_log", {})
            all_logs[ex_name] = {
                "is_base": temp.get("exercises", [])[temp.get("current_exercise_index", 0)].get("is_base", False),
                "sets": sets_log
            }
            temp["all_exercises_log"] = all_logs

            # Сохраняем в training_log
            training_log[today]["exercises"] = all_logs
            save_data("training_log.json", training_log)

            # Показываем итог по упражнению
            sets_str = "\n".join([f"  {i + 1}) {s['weight']}кг x {s['reps']}" for i, s in enumerate(sets_log)])
            msg = f"✅ {ex_name}: {total_sets} подходов\n{sets_str}\n\n"

            # Предлагаем следующее упражнение или завершение
            exercises = temp.get("exercises", [])
            current_idx = temp.get("current_exercise_index", 0)

            if current_idx + 1 < len(exercises):
                temp["train_state"] = "selecting_exercise"
                temp["current_exercise_index"] = current_idx + 1
                temp["current_exercise"] = None
                temp["total_sets"] = 0
                temp["current_set"] = 0
                temp["sets_log"] = []
                save_data("temp.json", temp)

                kb = []
                for i, ex in enumerate(exercises[current_idx + 1:], start=current_idx + 1):
                    kb.append([InlineKeyboardButton(ex["name"], callback_data=f"train_ex_{i}")])
                kb.append([InlineKeyboardButton("✅ Завершить тренировку", callback_data="finish_workout")])

                msg += "Выбери следующее упражнение или заверши тренировку:"
                await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
            else:
                # Все упражнения завершены
                temp["train_state"] = "done"
                save_data("temp.json", temp)

                # Формируем полный отчет
                report = f"🏋️ ТРЕНИРОВКА {temp.get('workout_type', '')} ЗАВЕРШЕНА!\n\n"
                report += f"📅 {today} ({DAYS_RU.get(datetime.now().weekday())})\n"
                report += f"🏷️ {temp.get('workout_name', '')}\n\n"

                for ex_name, ex_data in all_logs.items():
                    sets_str = ", ".join([f"{s['weight']}кг x {s['reps']}" for s in ex_data["sets"]])
                    report += f"📋 {ex_name}:\n"
                    report += f"  {sets_str}\n\n"

                report += "✅ Все данные сохранены! 💪"
                await update.message.reply_text(report, reply_markup=get_main_kb())

        return


# ==================== ЗАВЕРШЕНИЕ ТРЕНИРОВКИ (ОТДЕЛЬНЫЙ ОБРАБОТЧИК) ====================

async def finish_workout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data != "finish_workout":
        return

    temp = load_data("temp.json")
    users = load_data("users.json")

    if query.from_user.id != users.get("admin_id"):
        await query.answer("⛔ Только администратор может завершать тренировку.", show_alert=True)
        return

    today = datetime.now().strftime("%Y-%m-%d")
    all_logs = temp.get("all_exercises_log", {})

    if not all_logs:
        await query.edit_message_text("⚠️ Нет записанных упражнений для завершения.", reply_markup=get_main_kb())
        return

    # Сохраняем в тренировочный лог
    training_log = load_data("training_log.json")
    training_log[today] = {
        "day_name": DAYS_RU.get(datetime.now().weekday()),
        "workout_name": temp.get("workout_name", ""),
        "workout_type": temp.get("workout_type", ""),
        "exercises": all_logs
    }
    save_data("training_log.json", training_log)

    temp["train_state"] = "done"
    save_data("temp.json", temp)

    # Формируем отчет
    report = f"🏋️ ТРЕНИРОВКА {temp.get('workout_type', '')} ЗАВЕРШЕНА!\n\n"
    report += f"📅 {today} ({DAYS_RU.get(datetime.now().weekday())})\n"
    report += f"🏷️ {temp.get('workout_name', '')}\n\n"

    for ex_name, ex_data in all_logs.items():
        sets_str = ", ".join([f"{s['weight']}кг x {s['reps']}" for s in ex_data["sets"]])
        report += f"📋 {ex_name}:\n"
        report += f"  {sets_str}\n\n"

    report += "✅ Все данные сохранены! 💪"
    await query.edit_message_text(report, reply_markup=get_main_kb())


# ==================== ЗАПУСК ====================

def main():
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN)

    if PROXY_URL:
        application = application.proxy(PROXY_URL)

    application = application.build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setadmin", setadmin))
    application.add_handler(CommandHandler("start_day", start_day))
    application.add_handler(CommandHandler("myid", myid))
    application.add_handler(CommandHandler("link", link))

    # Кнопки
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CallbackQueryHandler(finish_workout_callback, pattern="finish_workout"))

    # Текст
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 Бот запущен на python-telegram-bot!")
    application.run_polling()


if __name__ == "__main__":
    main()