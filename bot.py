import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, CHECKLIST_TIME
from database import *

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()

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
        [InlineKeyboardButton(text="🗑️ Очистить старые", callback_data="clean_old")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="users_count")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])

def channel_keyboard():
    channel = get_required_channel()
    text = channel if channel else "❌ Не установлен"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 Текущий: {text}", callback_data="noop")],
        [InlineKeyboardButton(text="✏️ Изменить канал", callback_data="change_channel")],
        [InlineKeyboardButton(text="🗑️ Удалить канал", callback_data="delete_channel")],
        [InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub_admin")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

def contests_keyboard(page, total_pages, user_id):
    buttons = []
    nav_buttons = []
    
    if total_pages > 1:
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"contests_page_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"contests_page_{page+1}"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# === КОМАНДА /START ===
@dp.message(Command("start"))
async def start(message: types.Message):
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="my_contests", description="📋 Мои конкурсы"),
        BotCommand(command="add_contest", description="➕ Добавить конкурс"),
        BotCommand(command="active", description="⏳ Активные"),
        BotCommand(command="stats", description="📊 Статистика"),
        BotCommand(command="admin", description="⚙️ Админ-панель"),
        BotCommand(command="help", description="❓ Помощь"),
    ]
    await bot.set_my_commands(commands)
    
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    
    add_user(user_id, username)
    
    channel = get_required_channel()
    if channel:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ['member', 'administrator', 'creator']:
                update_subscription(user_id, 1)
            else:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{channel.replace('@', '')}")],
                    [InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub_user")]
                ])
                await message.answer(
                    f"🔒 Подпишись на канал:\n{channel}",
                    reply_markup=keyboard
                )
                return
        except:
            pass
    
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\nВыбери действие:",
        reply_markup=main_keyboard(user_id)
    )

# === ОБРАБОТЧИКИ КОМАНД МЕНЮ ===
@dp.message(Command("my_contests"))
async def cmd_my_contests(message: types.Message):
    user_id = message.from_user.id
    contests = get_all_contests(user_id)
    
    if not contests:
        await message.answer("📭 Нет конкурсов.", reply_markup=main_keyboard(user_id))
        return
    
    text = "📋 **Все конкурсы:**\n\n"
    for i, c in enumerate(contests[:10], 1):
        status = "✅ Выполнен" if c[5] == 1 else "⏳ Активен"
        text += f"{i}. **{c[3]}**\n  {status} | До: {c[4]}\n  🔗 {c[2]}\n\n"
    
    if len(contests) > 10:
        text += f"… и ещё {len(contests) - 10}"
    
    await message.answer(text, reply_markup=main_keyboard(user_id), parse_mode="Markdown")

@dp.message(Command("add_contest"))
async def cmd_add_contest(message: types.Message, state: FSMContext):
    await message.answer("🔗 Введи ссылку на конкурс (например, t.me/durov/123):")
    await state.set_state(AddContest.waiting_for_link)

@dp.message(Command("active"))
async def cmd_active(message: types.Message):
    user_id = message.from_user.id
    contests = get_active_contests(user_id)
    
    if not contests:
        await message.answer("🎉 Нет активных конкурсов!", reply_markup=main_keyboard(user_id))
        return
    
    text = "⏳ **Активные конкурсы:**\n\n"
    for i, c in enumerate(contests[:10], 1):
        end_time = datetime.strptime(c[4], "%Y-%m-%d %H:%M")
        diff = end_time - datetime.now()
        
        if diff.total_seconds() < 3600:
            emoji = "🔴"
        elif diff.total_seconds() < 86400:
            emoji = "🟡"
        else:
            emoji = "🟢"
        
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        time_str = f"{days}д {hours}ч {minutes}м" if days > 0 else f"{hours}ч {minutes}м"
        
        text += f"{emoji} {i}. **{c[3]}**\n"
        text += f"   ⏳ Осталось: {time_str}\n"
        text += f"   📅 До: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"   🔗 {c[2]}\n\n"
    
    if len(contests) > 10:
        text += f"… и ещё {len(contests) - 10}"
    
    await message.answer(text, reply_markup=main_keyboard(user_id), parse_mode="Markdown")

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    user_id = message.from_user.id
    contests = get_all_contests(user_id)
    total = len(contests)
    active = len([c for c in contests if c[4] == 'active' and datetime.strptime(c[4], "%Y-%m-%d %H:%M") > datetime.now()])
    participated = len([c for c in contests if c[5] == 1])
    
    text = f"📊 **Статистика:**\n\n"
    text += f"📝 Всего: {total}\n"
    text += f"⏳ Активных: {active}\n"
    text += f"✅ Участвовал: {participated}\n"
    if total > 0:
        text += f"📈 Процент: {round(participated/total*100, 1)}%"
    
    await message.answer(text, reply_markup=main_keyboard(user_id), parse_mode="Markdown")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён!")
        return
    await message.answer("⚙️ **Админ-панель**", reply_markup=admin_keyboard(), parse_mode="Markdown")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "❓ **Помощь**\n\n"
        "📋 **Мои конкурсы** — список всех конкурсов\n"
        "➕ **Добавить конкурс** — добавить новый конкурс\n"
        "⏳ **Активные** — только активные конкурсы\n"
        "📊 **Статистика** — твоя статистика\n"
        "⚙️ **Админ-панель** — управление ботом\n\n"
        "📌 Все конкурсы проверяются на дубликаты.",
        parse_mode="Markdown",
        reply_markup=main_keyboard(message.from_user.id)
    )

# === ПРОВЕРКА ПОДПИСКИ ===
@dp.callback_query(lambda c: c.data == "check_sub_user")
async def check_sub_user(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    channel = get_required_channel()
    
    if not channel:
        await callback.message.edit_text("⚠️ Канал не установлен.", reply_markup=main_keyboard(user_id))
        await callback.answer()
        return
    
    try:
        member = await bot.get_chat_member(channel, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            update_subscription(user_id, 1)
            await callback.message.edit_text("✅ Подписка подтверждена!", reply_markup=main_keyboard(user_id))
        else:
            await callback.answer("❌ Ты не подписан!", show_alert=True)
    except:
        await callback.answer("⚠️ Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data == "check_sub_admin")
async def check_sub_admin(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    channel = get_required_channel()
    await callback.answer(f"✅ Канал: {channel}" if channel else "⚠️ Не установлен", show_alert=True)

@dp.callback_query(lambda c: c.data == "delete_channel")
async def delete_channel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    set_required_channel("")
    await callback.message.edit_text(
        "🗑️ Канал удалён! Подписка больше не обязательна.",
        reply_markup=channel_keyboard()
    )
    await callback.answer("✅ Канал удалён!", show_alert=True)

# === ДОБАВЛЕНИЕ КОНКУРСА ===
@dp.callback_query(lambda c: c.data == "add_contest")
async def add_contest_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🔗 Введи ссылку на конкурс (например, t.me/durov/123):")
    await state.set_state(AddContest.waiting_for_link)
    await callback.answer()

@dp.message(AddContest.waiting_for_link)
async def add_contest_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    user_id = message.from_user.id
    
    duplicate = check_duplicate(user_id, link)
    if duplicate:
        contest_id, title, end_time, status = duplicate
        if status == 'active' and datetime.strptime(end_time, "%Y-%m-%d %H:%M") > datetime.now():
            await message.answer(f"⚠️ Ты уже участвуешь в этом конкурсе!\n📝 {title}\n⏳ Осталось: {get_time_left(end_time)}")
            await state.clear()
            return
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да", callback_data=f"re_add_{contest_id}")],
                [InlineKeyboardButton(text="❌ Нет", callback_data="cancel_add")]
            ])
            await message.answer(f"⚠️ Конкурс уже был и закончился. Добавить заново?", reply_markup=keyboard)
            await state.update_data(link=link, re_add_id=contest_id)
            await state.set_state(AddContest.waiting_for_title)
            return
    
    await state.update_data(link=link)
    await message.answer("📝 Введи название конкурса:")
    await state.set_state(AddContest.waiting_for_title)

@dp.callback_query(lambda c: c.data.startswith("re_add_"))
async def re_add_contest(callback: types.CallbackQuery, state: FSMContext):
    contest_id = int(callback.data.split("_")[2])
    await state.update_data(re_add_id=contest_id)
    await callback.message.answer("📝 Введи название:")
    await state.set_state(AddContest.waiting_for_title)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_add")
async def cancel_add(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено.", reply_markup=main_keyboard(callback.from_user.id))
    await callback.answer()

@dp.message(AddContest.waiting_for_title)
async def add_contest_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if 're_add_id' in data:
        delete_contest(data['re_add_id'])
        await state.update_data(re_add_id=None)
    
    await state.update_data(title=message.text.strip())
    await message.answer("⏳ Введи время (2026-08-25 18:00 или 72):")
    await state.set_state(AddContest.waiting_for_time)

@dp.message(AddContest.waiting_for_time)
async def add_contest_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    time_input = message.text.strip()
    
    try:
        hours = int(time_input)
        end_time = datetime.now() + timedelta(hours=hours)
        end_time_str = end_time.strftime("%Y-%m-%d %H:%M")
    except:
        try:
            end_time = datetime.strptime(time_input, "%Y-%m-%d %H:%M")
            end_time = end_time.replace(tzinfo=None)
            if end_time < datetime.now():
                await message.answer("❌ Дата должна быть в будущем!")
                return
            end_time_str = time_input
        except:
            await message.answer("❌ Неверный формат! Используй: 2026-08-25 18:00 или 72")
            return
    
    add_contest(user_id, data['link'], data['title'], end_time_str)
    await message.answer(f"✅ Конкурс добавлен!\n📝 {data['title']}\n⏳ До: {end_time_str}", reply_markup=main_keyboard(user_id))
    await state.clear()

# === АКТИВНЫЕ КОНКУРСЫ ===
@dp.callback_query(lambda c: c.data == "active_contests")
async def show_active(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    contests = get_active_contests(user_id)
    
    if not contests:
        await callback.message.edit_text("🎉 Нет активных конкурсов!", reply_markup=main_keyboard(user_id))
        await callback.answer()
        return
    
    text = "⏳ **Активные конкурсы:**\n\n"
    for i, c in enumerate(contests[:10], 1):
        end_time = datetime.strptime(c[4], "%Y-%m-%d %H:%M")
        diff = end_time - datetime.now()
        
        if diff.total_seconds() < 3600:
            emoji = "🔴"
        elif diff.total_seconds() < 86400:
            emoji = "🟡"
        else:
            emoji = "🟢"
        
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        time_str = f"{days}д {hours}ч {minutes}м" if days > 0 else f"{hours}ч {minutes}м"
        
        text += f"{emoji} {i}. **{c[3]}**\n"
        text += f"   ⏳ Осталось: {time_str}\n"
        text += f"   📅 До: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"   🔗 {c[2]}\n\n"
    
    if len(contests) > 10:
        text += f"… и ещё {len(contests) - 10}\n"
        text += "\n📌 Нажми кнопку ниже для просмотра всех"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все конкурсы", callback_data="my_contests")],
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
        await callback.message.edit_text("📭 Нет конкурсов.", reply_markup=main_keyboard(user_id))
        await callback.answer()
        return
    
    text = "📋 **Все конкурсы:**\n\n"
    for i, c in enumerate(contests[:10], 1):
        status = "✅ Выполнен" if c[5] == 1 else "⏳ Активен"
        text += f"{i}. **{c[3]}**\n  {status} | До: {c[4]}\n  🔗 {c[2]}\n\n"
    
    if len(contests) > 10:
        text += f"… и ещё {len(contests) - 10}\n"
        text += "\n📌 Нажми кнопку ниже для просмотра активных"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Активные конкурсы", callback_data="active_contests")],
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
    active = len([c for c in contests if c[4] == 'active' and datetime.strptime(c[4], "%Y-%m-%d %H:%M") > datetime.now()])
    participated = len([c for c in contests if c[5] == 1])
    
    text = f"📊 **Статистика:**\n\n"
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
    await callback.answer("✅ Отмечено!", show_alert=True)
    await callback.message.edit_text("✅ Выполнено!", reply_markup=main_keyboard(callback.from_user.id))

# === УДАЛЕНИЕ КОНКУРСА ===
@dp.callback_query(lambda c: c.data and c.data.startswith("delete_"))
async def delete_contest_cmd(callback: types.CallbackQuery):
    contest_id = int(callback.data.split("_")[1])
    delete_contest(contest_id)
    await callback.answer("🗑️ Удалено!", show_alert=True)
    await callback.message.edit_text("🗑️ Удалено.", reply_markup=main_keyboard(callback.from_user.id))

# === ОЧИСТКА СТАРЫХ КОНКУРСОВ ===
@dp.callback_query(lambda c: c.data == "clean_old")
async def clean_old_contests(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    deleted = clean_expired_contests()
    await callback.message.edit_text(
        f"🗑️ Удалено старых конкурсов: {deleted}",
        reply_markup=admin_keyboard()
    )
    await callback.answer(f"✅ Удалено {deleted} конкурсов!", show_alert=True)

# === АДМИН-ПАНЕЛЬ ===
@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    await callback.message.edit_text(
        "⚙️ **Админ-панель**",
        reply_markup=admin_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "manage_channel")
async def manage_channel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    await callback.message.edit_text(
        "📢 **Управление канал
