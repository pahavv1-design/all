import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, CHECKLIST_TIME
from database import *

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()

# === СОСТОЯНИЯ ДЛЯ FSM ===
class AddContest(StatesGroup):
    waiting_for_link = State()
    waiting_for_title = State()
    waiting_for_time = State()

class AdminStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_newsletter = State()

# === КЛАВИАТУРЫ ===
def main_keyboard(user_id):
    buttons = [
        [InlineKeyboardButton(text="📋 Мои конкурсы", callback_data="my_contests")],
        [InlineKeyboardButton(text="➕ Добавить конкурс", callback_data="add_contest")],
        [InlineKeyboardButton(text="⏳ Активные", callback_data="active_contests")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Управление каналом", callback_data="manage_channel")],
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="newsletter")],
        [InlineKeyboardButton(text="👥 Статистика пользователей", callback_data="users_count")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")]
    ])

def channel_keyboard():
    channel = get_required_channel()
    text = channel if channel else "❌ Не установлен"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 Текущий: {text}", callback_data="noop")],
        [InlineKeyboardButton(text="✏️ Изменить канал", callback_data="change_channel")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub_admin")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

# === КОМАНДА /START ===
@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    
    # Добавляем пользователя
    add_user(user_id, username)
    
    # Проверяем подписку
    channel = get_required_channel()
    if channel:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ['member', 'administrator', 'creator']:
                update_subscription(user_id, 1)
            else:
                # Создаём кнопку подписки
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{channel.replace('@', '')}")],
                    [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub_user")]
                ])
                await message.answer(
                    f"🔒 Для использования бота подпишись на канал:\n{channel}",
                    reply_markup=keyboard
                )
                return
        except:
            pass
    
    # Главное меню
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n"
        f"Я помогу тебе управлять конкурсами.\n\n"
        f"📌 Выбери действие:",
        reply_markup=main_keyboard(user_id)
    )

# === ПРОВЕРКА ПОДПИСКИ (ДЛЯ ПОЛЬЗОВАТЕЛЯ) ===
@dp.callback_query(lambda c: c.data == "check_sub_user")
async def check_sub_user(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    channel = get_required_channel()
    
    if not channel:
        await callback.message.edit_text(
            "⚠️ Канал для подписки не установлен.",
            reply_markup=main_keyboard(user_id)
        )
        await callback.answer()
        return
    
    try:
        member = await bot.get_chat_member(channel, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            update_subscription(user_id, 1)
            await callback.message.edit_text(
                "✅ Спасибо за подписку! Теперь ты можешь пользоваться ботом.",
                reply_markup=main_keyboard(user_id)
            )
        else:
            await callback.answer("❌ Ты ещё не подписан!", show_alert=True)
    except:
        await callback.answer("⚠️ Ошибка проверки", show_alert=True)

# === ПРОВЕРКА ПОДПИСКИ (ДЛЯ АДМИНА) ===
@dp.callback_query(lambda c: c.data == "check_sub_admin")
async def check_sub_admin(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    channel = get_required_channel()
    if not channel:
        await callback.answer("⚠️ Канал не установлен!", show_alert=True)
        return
    
    await callback.answer(f"✅ Текущий канал: {channel}", show_alert=True)

# === ДОБАВЛЕНИЕ КОНКУРСА ===
@dp.callback_query(lambda c: c.data == "add_contest")
async def add_contest_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "🔗 Введи ссылку на конкурс:\n"
        "Например: `t.me/durov/123`",
        parse_mode="Markdown"
    )
    await state.set_state(AddContest.waiting_for_link)
    await callback.answer()

@dp.message(AddContest.waiting_for_link)
async def add_contest_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    user_id = message.from_user.id
    
    # Проверяем дубликат
    duplicate = check_duplicate(user_id, link)
    
    if duplicate:
        contest_id, title, end_time, status = duplicate
        time_left = get_time_left(end_time)
        
        if status == 'active' and datetime.fromisoformat(end_time) > datetime.now():
            # Активный конкурс
            await message.answer(
                f"⚠️ Ты уже участвуешь в этом конкурсе!\n\n"
                f"📝 Название: {title}\n"
                f"⏳ Осталось: {time_left}\n"
                f"🔗 {link}\n\n"
                f"Нажми /start для возврата в меню."
            )
            await state.clear()
            return
        else:
            # Завершённый конкурс
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, добавить заново", callback_data=f"re_add_{contest_id}")],
                [InlineKeyboardButton(text="❌ Нет, отмена", callback_data="cancel_add")]
            ])
            await message.answer(
                f"⚠️ Этот конкурс уже был добавлен и закончился!\n\n"
                f"📝 Название: {title}\n"
                f"⏳ Закончился: {end_time}\n\n"
                f"Добавить заново?",
                reply_markup=keyboard
            )
            await state.update_data(link=link, re_add_id=contest_id)
            await state.set_state(AddContest.waiting_for_title)
            return
    
    # Если дубликатов нет, сохраняем ссылку и продолжаем
    await state.update_data(link=link)
    await message.answer("📝 Введи название конкурса:")
    await state.set_state(AddContest.waiting_for_title)

# === ОБРАБОТКА ПОВТОРНОГО ДОБАВЛЕНИЯ ===
@dp.callback_query(lambda c: c.data.startswith("re_add_"))
async def re_add_contest(callback: types.CallbackQuery, state: FSMContext):
    contest_id = int(callback.data.split("_")[2])
    await state.update_data(re_add_id=contest_id)
    await callback.message.answer("📝 Введи новое название конкурса (или отправь текущее):")
    await state.set_state(AddContest.waiting_for_title)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_add")
async def cancel_add(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Добавление отменено.",
        reply_markup=main_keyboard(callback.from_user.id)
    )
    await callback.answer()

# === ПОЛУЧЕНИЕ НАЗВАНИЯ ===
@dp.message(AddContest.waiting_for_title)
async def add_contest_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = message.text.strip()
    
    # Если это повторное добавление, удаляем старый конкурс
    if 're_add_id' in data:
        delete_contest(data['re_add_id'])
        await state.update_data(re_add_id=None)
    
    await state.update_data(title=title)
    await message.answer(
        "⏳ Введи время окончания:\n\n"
        "📅 Формат даты: `2026-08-20 18:00`\n"
        "⏰ Или количество часов: `72`",
        parse_mode="Markdown"
    )
    await state.set_state(AddContest.waiting_for_time)

@dp.message(AddContest.waiting_for_time)
async def add_contest_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    time_input = message.text.strip()
    
    # Пробуем парсить часы
    try:
        hours = int(time_input)
        end_time = datetime.now() + timedelta(hours=hours)
        end_time_str = end_time.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        # Пробуем парсить дату
        try:
            end_time = datetime.strptime(time_input, "%Y-%m-%d %H:%M")
            if end_time < datetime.now():
                await message.answer("❌ Дата должна быть в будущем! Попробуй снова.")
                return
            end_time_str = time_input
        except:
            await message.answer(
                "❌ Неверный формат!\n"
                "Используй: `2026-08-20 18:00` или `72`",
                parse_mode="Markdown"
            )
            return
    
    # Сохраняем конкурс
    add_contest(user_id, data['link'], data['title'], end_time_str)
    
    await message.answer(
        f"✅ Конкурс добавлен!\n\n"
        f"📝 Название: {data['title']}\n"
        f"🔗 Ссылка: {data['link']}\n"
        f"⏳ Окончание: {end_time_str}",
        reply_markup=main_keyboard(user_id)
    )
    await state.clear()

# === АКТИВНЫЕ КОНКУРСЫ ===
@dp.callback_query(lambda c: c.data == "active_contests")
async def show_active(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    contests = get_active_contests(user_id)
    
    if not contests:
        await callback.message.edit_text(
            "🎉 У тебя нет активных конкурсов!",
            reply_markup=main_keyboard(user_id)
        )
        await callback.answer()
        return
    
    text = "⏳ **Активные конкурсы:**\n\n"
    for c in contests:
        end_time = datetime.fromisoformat(c[4])
        now = datetime.now()
        diff = end_time - now
        
        # Цветовая индикация
        if diff.total_seconds() < 3600:
            emoji = "🔴"
        elif diff.total_seconds() < 86400:
            emoji = "🟡"
        else:
            emoji = "🟢"
        
        # Форматируем оставшееся время
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        
        time_str = ""
        if days > 0:
            time_str += f"{days}д "
        if hours > 0:
            time_str += f"{hours}ч "
        if minutes > 0:
            time_str += f"{minutes}м"
        if not time_str:
            time_str = "менее минуты"
        
        text += f"{emoji} **{c[3]}**\n"
        text += f"   ⏳ Осталось: {time_str}\n"
        text += f"   📅 До: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"   🔗 {c[2]}\n\n"
    
    # Добавляем кнопки действий
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="active_contests")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

# === МОИ КОНКУРСЫ ===
@dp.callback_query(lambda c: c.data == "my_contests")
async def show_all(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    contests = get_all_contests(user_id)
    
    if not contests:
        await callback.message.edit_text(
            "📭 У тебя пока нет конкурсов.",
            reply_markup=main_keyboard(user_id)
        )
        await callback.answer()
        return
    
    text = "📋 **Все конкурсы:**\n\n"
    for c in contests[:10]:
        status = "✅ Выполнен" if c[5] == 1 else "⏳ Активен"
        text += f"• **{c[3]}**\n"
        text += f"  {status} | До: {c[4]}\n"
        text += f"  🔗 {c[2]}\n\n"
    
    if len(contests) > 10:
        text += f"… и ещё {len(contests) - 10} конкурсов"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Показать активные", callback_data="active_contests")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

# === СТАТИСТИКА ===
@dp.callback_query(lambda c: c.data == "stats")
async def show_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    contests = get_all_contests(user_id)
    
    total = len(contests)
    active = len([c for c in contests if c[4] == 'active' and datetime.fromisoformat(c[4]) > datetime.now()])
    participated = len([c for c in contests if c[5] == 1])
    
    text = f"📊 **Твоя статистика:**\n\n"
    text += f"📝 Всего конкурсов: {total}\n"
    text += f"⏳ Активных: {active}\n"
    text += f"✅ Участвовал: {participated}\n"
    if total > 0:
        text += f"📈 Процент участия: {round(participated/total*100, 1)}%"
    
    await callback.message.edit_text(text, reply_markup=main_keyboard(user_id), parse_mode="Markdown")
    await callback.answer()

# === ОТМЕТКА УЧАСТИЯ ===
@dp.callback_query(lambda c: c.data and c.data.startswith("participate_"))
async def participate(callback: types.CallbackQuery):
    contest_id = int(callback.data.split("_")[1])
    mark_participated(contest_id)
    await callback.answer("✅ Отмечено! Ты участвовал в этом конкурсе.", show_alert=True)
    await callback.message.edit_text(
        "✅ Конкурс отмечен как выполненный!",
        reply_markup=main_keyboard(callback.from_user.id)
    )

# === УДАЛЕНИЕ КОНКУРСА ===
@dp.callback_query(lambda c: c.data and c.data.startswith("delete_"))
async def delete_contest_cmd(callback: types.CallbackQuery):
    contest_id = int(callback.data.split("_")[1])
    delete_contest(contest_id)
    await callback.answer("🗑️ Конкурс удалён!", show_alert=True)
    await callback.message.edit_text(
        "🗑️ Конкурс удалён.",
        reply_markup=main_keyboard(callback.from_user.id)
    )

# === АДМИН-ПАНЕЛЬ ===
@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "⚙️ **Админ-панель**\n\n"
        "Выбери действие:",
        reply_markup=admin_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

# === УПРАВЛЕНИЕ КАНАЛОМ ===
@dp.callback_query(lambda c: c.data == "manage_channel")
async def manage_channel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📢 **Управление каналом подписки**\n\n"
        "Здесь можно установить канал, на который должны подписываться пользователи.",
        reply_markup=channel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "change_channel")
async def change_channel(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.answer(
        "📢 Отправь новый канал:\n\n"
        "Например: `@durov` или `t.me/durov`",
        parse_mode="Markdown"
    )
    await state.set_state(AdminStates.waiting_for_channel)
    await callback.answer()

@dp.message(AdminStates.waiting_for_channel)
async def save_channel(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён!")
        return
    
    channel = message.text.strip()
    
    # Обработка ссылки
    if 't.me/' in channel:
        channel = '@' + channel.split('t.me/')[-1]
    
    # Проверка существования канала
    try:
        await bot.get_chat(channel)
    except:
        await message.answer("❌ Канал не найден! Проверь правильность ввода.")
        return
    
    set_required_channel(channel)
    await message.answer(f"✅ Канал подписки изменён на {channel}")
    await state.clear()
    
    # Возврат в админку
    await message.answer(
        "⚙️ Админ-панель:",
        reply_markup=admin_keyboard()
    )

# === РАССЫЛКА ===
@dp.callback_query(lambda c: c.data == "newsletter")
async def start_newsletter(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.answer(
        "📨 **Создание рассылки**\n\n"
        "Отправь текст сообщения.\n\n"
        "💡 Чтобы добавить кнопку, напиши:\n"
        "`Текст кнопки|https://ссылка`\n\n"
        "Пример:\n"
        "`Перейти в канал|https://t.me/my_channel`",
        parse_mode="Markdown"
    )
    await state.set_state(AdminStates.waiting_for_newsletter)
    await callback.answer()

@dp.message(AdminStates.waiting_for_newsletter)
async def send_newsletter(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    users = get_all_users()
    text = message.text
    
    # Парсим кнопку
    button_text = None
    button_url = None
    if '|' in text and 'http' in text:
        parts = text.split('|')
        button_text = parts[0].strip()
        button_url = parts[1].strip()
        text = text.replace(f"{button_text}|{button_url}", "").strip()
    
    if not users:
        await message.answer("❌ Нет пользователей для рассылки.")
        await state.clear()
        return
    
    await message.answer(f"📨 Начинаю рассылку для {len(users)} пользователей...")
    
    sent = 0
    for user_id in users:
        try:
            if button_text and button_url:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=button_text, url=button_url)]
                ])
                await bot.send_message(user_id, text, reply_markup=keyboard)
            else:
                await bot.send_message(user_id, text)
            sent += 1
            await asyncio.sleep(0.05)  # Защита от бана
        except:
            pass
    
    set_last_newsletter(datetime.now().isoformat())
    await message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"📤 Отправлено: {sent} из {len(users)}"
    )
    await state.clear()

# === СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ ===
@dp.callback_query(lambda c: c.data == "users_count")
async def users_count(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    count = get_users_count()
    last_newsletter = get_last_newsletter()
    
    text = f"👥 **Статистика пользователей**\n\n"
    text += f"📊 Всего: {count}\n"
    if last
