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

@dp.message(Command("start"))
async def start(message: types.Message):
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
                    [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub_user")]
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
        if status == 'active' and datetime.fromisoformat(end_time) > datetime.now():
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
    await message.answer("⏳ Введи время (2026-08-20 18:00 или 72):")
    await state.set_state(AddContest.waiting_for_time)

@dp.message(AddContest.waiting_for_time)
async def add_contest_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    time_input = message.text.strip()
    
    try:
        hours = int(time_input)
        end_time_str = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    except:
        try:
            end_time = datetime.strptime(time_input, "%Y-%m-%d %H:%M")
            if end_time < datetime.now():
                await message.answer("❌ Дата должна быть в будущем!")
                return
            end_time_str = time_input
        except:
            await message.answer("❌ Неверный формат! Используй: 2026-08-20 18:00 или 72")
            return
    
    add_contest(user_id, data['link'], data['title'], end_time_str)
    await message.answer(f"✅ Конкурс добавлен!\n📝 {data['title']}\n⏳ До: {end_time_str}", reply_markup=main_keyboard(user_id))
    await state.clear()

@dp.callback_query(lambda c: c.data == "active_contests")
async def show_active(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    contests = get_active_contests(user_id)
    
    if not contests:
        await callback.message.edit_text("🎉 Нет активных конкурсов!", reply_markup=main_keyboard(user_id))
        await callback.answer()
        return
    
    text = "⏳ **Активные конкурсы:**\n\n"
    for c in contests:
        end_time = datetime.fromisoformat(c[4])
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
        
        text += f"{emoji} **{c[3]}**\n"
        text += f"   ⏳ Осталось: {time_str}\n"
        text += f"   📅 До: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"   🔗 {c[2]}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="active_contests")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "my_contests")
async def show_all(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    contests = get_all_contests(user_id)
    
    if not contests:
        await callback.message.edit_text("📭 Нет конкурсов.", reply_markup=main_keyboard(user_id))
        await callback.answer()
        return
    
    text = "📋 **Все конкурсы:**\n\n"
    for c in contests[:10]:
        status = "✅ Выполнен" if c[5] == 1 else "⏳ Активен"
        text += f"• **{c[3]}**\n  {status} | До: {c[4]}\n  🔗 {c[2]}\n\n"
    
    if len(contests) > 10:
        text += f"… и ещё {len(contests) - 10}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "stats")
async def show_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    contests = get_all_contests(user_id)
    total = len(contests)
    active = len([c for c in contests if c[4] == 'active' and datetime.fromisoformat(c[4]) > datetime.now()])
    participated = len([c for c in contests if c[5] == 1])
    
    text = f"📊 **Статистика:**\n\n📝 Всего: {total}\n⏳ Активных: {active}\n✅ Участвовал: {participated}"
    if total > 0:
        text += f"\n📈 Процент: {round(participated/total*100, 1)}%"
    
    await callback.message.edit_text(text, reply_markup=main_keyboard(user_id), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("participate_"))
async def participate(callback: types.CallbackQuery):
    contest_id = int(callback.data.split("_")[1])
    mark_participated(contest_id)
    await callback.answer("✅ Отмечено!", show_alert=True)
    await callback.message.edit_text("✅ Выполнено!", reply_markup=main_keyboard(callback.from_user.id))

@dp.callback_query(lambda c: c.data and c.data.startswith("delete_"))
async def delete_contest_cmd(callback: types.CallbackQuery):
    contest_id = int(callback.data.split("_")[1])
    delete_contest(contest_id)
    await callback.answer("🗑️ Удалено!", show_alert=True)
    await callback.message.edit_text("🗑️ Удалено.", reply_markup=main_keyboard(callback.from_user.id))

@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    await callback.message.edit_text("⚙️ **Админ-панель**", reply_markup=admin_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "manage_channel")
async def manage_channel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    await callback.message.edit_text("📢 **Управление каналом**", reply_markup=channel_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "change_channel")
async def change_channel(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    await callback.message.answer("📢 Отправь новый канал (например, @durov):")
    await state.set_state(AdminStates.waiting_for_channel)
    await callback.answer()

@dp.message(AdminStates.waiting_for_channel)
async def save_channel(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    channel = message.text.strip()
    if 't.me/' in channel:
        channel = '@' + channel.split('t.me/')[-1]
    try:
        await bot.get_chat(channel)
    except:
        await message.answer("❌ Канал не найден!")
        return
    set_required_channel(channel)
    await message.answer(f"✅ Канал изменён на {channel}")
    await state.clear()
    await message.answer("⚙️ Админ-панель:", reply_markup=admin_keyboard())

@dp.callback_query(lambda c: c.data == "newsletter")
async def start_newsletter(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    await callback.message.answer("📨 Напиши текст для рассылки:")
    await state.set_state(AdminStates.waiting_for_newsletter)
    await callback.answer()

@dp.message(AdminStates.waiting_for_newsletter)
async def send_newsletter(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    users = get_all_users()
    if not users:
        await message.answer("❌ Нет пользователей.")
        await state.clear()
        return
    await message.answer(f"📨 Начинаю рассылку для {len(users)} пользователей...")
    sent = 0
    for user_id in users:
        try:
            await bot.send_message(user_id, message.text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    set_last_newsletter(datetime.now().isoformat())
    await message.answer(f"✅ Отправлено: {sent} из {len(users)}")
    await state.clear()

@dp.callback_query(lambda c: c.data == "users_count")
async def users_count(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    count = get_users_count()
    last_newsletter = get_last_newsletter()
    text = f"👥 **Пользователи:**\n\n📊 Всего: {count}\n"
    if last_newsletter:
        text += f"📨 Последняя рассылка: {datetime.fromisoformat(last_newsletter).strftime('%d.%m.%Y')}"
    else:
        text += "📨 Рассылок не было"
    await callback.message.edit_text(text, reply_markup=admin_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_main")
async def back_main(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👋 Главное меню:",
        reply_markup=main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()

async def send_daily_checklist():
    users = get_all_users()
    for user_id in users:
        contests = get_todays_contests(user_id)
        if not contests:
            continue
        text = "📅 **Чек-лист на сегодня**\n\n"
        for i, c in enumerate(contests, 1):
            text += f"{i}. **{c[3]}**\n   ⏳ До {datetime.fromisoformat(c[4]).strftime('%H:%M')}\n   🔗 {c[2]}\n\n"
        text += f"📌 Всего: {len(contests)} конкурсов\nУдачи! 🍀"
        try:
            await bot.send_message(user_id, text, parse_mode="Markdown")
        except:
            pass

def schedule_checklist():
    hour, minute = map(int, CHECKLIST_TIME.split(':'))
    scheduler.add_job(send_daily_checklist, 'cron', hour=hour, minute=minute, timezone='Europe/Moscow')
    scheduler.start()

async def main():
    init_db()
    schedule_checklist()
    print("🤖 Бот запущен!")
    print(f"👑 Админ: {ADMIN_ID}")
    print(f"⏰ Чек-лист в: {CHECKLIST_TIME}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
