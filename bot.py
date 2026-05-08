import asyncio
import aiosqlite
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8174433113:AAGsCNLWDI_j8qIi4JI4Bqt2uLuAjO2QM30"
OWNER_ID = 8032626504
DB_NAME = "autoposter_bot.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==================== БАЗА ДАННЫЕ ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, balance_hours REAL DEFAULT 0,
            status TEXT DEFAULT 'user', is_banned INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS autoposts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, photo_file_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS user_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER, chat_title TEXT, added_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status TEXT DEFAULT 'open', priority INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, user_id INTEGER, message TEXT, is_admin INTEGER DEFAULT 0, sent_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, user_id INTEGER, action TEXT, details TEXT)""")
        await db.commit()

async def log_action(user_id: int, action: str, details: str = ""):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO action_logs (user_id, action, details) VALUES (?, ?, ?)", (user_id, action, details))
        await db.commit()

# ==================== FSM ====================
class SupportState(StatesGroup):
    waiting_message = State()

class AdminTicketReply(StatesGroup):
    waiting_reply = State()
    ticket_id = State()

class AdminAddPost(StatesGroup):
    waiting_user_id = State()
    waiting_text = State()
    waiting_photo = State()

class UserAddPost(StatesGroup):
    waiting_text = State()
    waiting_photo = State()

class AdminAddHours(StatesGroup):
    waiting_user = State()
    waiting_hours = State()

class AdminBroadcast(StatesGroup):
    waiting_text = State()

class AdminBan(StatesGroup):
    waiting_user_id = State()

# ==================== МЕНЮ ====================
def main_menu(user_id: int):
    buttons = [
        [InlineKeyboardButton(text="📊 Мой автопостинг", callback_data="my_autopost"),
         InlineKeyboardButton(text="➕ Добавить свой пост", callback_data="user_add_post")],
        [InlineKeyboardButton(text="📋 Мои чаты", callback_data="my_chats"),
         InlineKeyboardButton(text="➕ Купить часы", callback_data="buy_hours")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq"),
         InlineKeyboardButton(text="📞 Контакты", callback_data="contacts")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="support"),
         InlineKeyboardButton(text="📈 Статистика", callback_data="stats")]
    ]
    if user_id == OWNER_ID:
        buttons.append([InlineKeyboardButton(text="🔧 Админ-панель", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban")],
        [InlineKeyboardButton(text="➕ Добавить часы пользователю", callback_data="admin_add_hours"),
         InlineKeyboardButton(text="➕ Добавить автопост", callback_data="admin_add_post")],
        [InlineKeyboardButton(text="🎟 Открытые тикеты", callback_data="admin_tickets"),
         InlineKeyboardButton(text="👥 Активные пользователи", callback_data="admin_active_users")],
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_global_stats"),
         InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])

# ==================== АВТОПОСТИНГ ====================
async def autopost_worker():
    post_index = {}
    while True:
        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cursor = await db.execute("SELECT user_id, balance_hours FROM users WHERE balance_hours > 0 AND is_banned = 0")
                users = await cursor.fetchall()
                for user_id, hours in users:
                    try:
                        cursor = await db.execute("SELECT id, text, photo_file_id FROM autoposts WHERE user_id = ? ORDER BY id", (user_id,))
                        posts = await cursor.fetchall()
                        if not posts: continue
                        cursor = await db.execute("SELECT chat_id, chat_title FROM user_chats WHERE user_id = ?", (user_id,))
                        chats = await cursor.fetchall()
                        if not chats: continue
                        if user_id not in post_index: post_index[user_id] = 0
                        post = posts[post_index[user_id] % len(posts)]
                        post_index[user_id] += 1
                        sent = 0
                        for chat_id, title in chats:
                            try:
                                if post[2]:
                                    await bot.send_photo(chat_id, photo=post[2], caption=post[1] or "")
                                else:
                                    await bot.send_message(chat_id, post[1] or "")
                                sent += 1
                            except: pass
                        new_hours = max(0, round(hours - 5/60, 2))
                        await db.execute("UPDATE users SET balance_hours = ? WHERE user_id = ?", (new_hours, user_id))
                        await db.commit()
                        if 0 < new_hours < 0.5 and hours >= 0.5:
                            try: await bot.send_message(user_id, "⚠️ Осталось меньше 30 минут!")
                            except: pass
                    except Exception as e: logger.error(f"Ошибка у {user_id}: {e}")
        except Exception as e: logger.critical(f"Ошибка в воркере: {e}")
        await asyncio.sleep(300)

# ==================== ХЕНДЛЕРЫ ====================
@dp.message(CommandStart())
async def start(message: Message):
    await get_or_create_user(message.from_user.id, message.from_user.username)
    await message.answer("🚀 <b>Autoposter Bot</b>\n\nАвтоматическая рассылка контента каждые 5 минут.", reply_markup=main_menu(message.from_user.id))

async def get_or_create_user(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username or ""))
        await db.commit()

@dp.callback_query(F.data == "my_autopost")
async def my_autopost(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance_hours FROM users WHERE user_id = ?", (callback.from_user.id,))
        hours = (await cursor.fetchone())[0] or 0
        cursor = await db.execute("SELECT COUNT(*) FROM autoposts WHERE user_id = ?", (callback.from_user.id,))
        post_count = (await cursor.fetchone())[0]
    await callback.message.edit_text(f"📊 <b>Мой автопостинг</b>\n\nОсталось: <b>{round(hours,2)}</b> ч\nПостов: <b>{post_count}</b>", reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "user_add_post")
async def user_add_post_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserAddPost.waiting_text)
    await callback.message.edit_text("➕ <b>Добавить пост</b>\n\nТекст (или /skip):")

@dp.message(UserAddPost.waiting_text)
async def user_add_post_text(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "/skip":
        await state.update_data(text="")
    else:
        await state.update_data(text=message.text or "")
    await state.set_state(UserAddPost.waiting_photo)
    await message.answer("Теперь фото (или /skip):")

@dp.message(UserAddPost.waiting_photo, F.photo)
async def user_add_post_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id if message.photo else None
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO autoposts (user_id, text, photo_file_id) VALUES (?, ?, ?)", (message.from_user.id, data.get("text", ""), photo_id))
        await db.commit()
    await message.answer("✅ Пост добавлен!", reply_markup=main_menu(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "buy_hours")
async def buy_hours(callback: CallbackQuery):
    await callback.message.edit_text("💳 <b>Купить часы</b>\n\n1 час: http://t.me/send?start=IVaRmLsNBkDN\n3 часа: http://t.me/send?start=IVdE6YCEFTvo", reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "my_chats")
async def my_chats(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT chat_title FROM user_chats WHERE user_id = ?", (callback.from_user.id,))
        chats = await cursor.fetchall()
    text = "📋 <b>Твои чаты:</b>\n" + "\n".join([f"• {c[0] or 'Без названия'}" for c in chats]) if chats else "Чатов нет. Добавь командой /addchat"
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

@dp.message(Command("addchat"))
async def add_chat(message: Message):
    if message.chat.type not in ["group", "supergroup", "channel"]:
        return await message.answer("❌ Только в группах/каналах.")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO user_chats (user_id, chat_id, chat_title) VALUES (?, ?, ?)", (message.from_user.id, message.chat.id, message.chat.title or ""))
        await db.commit()
    await message.answer("✅ Чат добавлен!")

# ==================== АДМИН ====================
@dp.callback_query(F.data == "admin_menu")
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    await callback.message.edit_text("🔧 <b>Админ-панель</b>", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminBroadcast.waiting_text)
    await callback.message.edit_text("📢 Введи текст рассылки:")

@dp.message(AdminBroadcast.waiting_text)
async def do_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = await cursor.fetchall()
    count = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 <b>Сообщение от админа:</b>\n\n{message.text}")
            count += 1
        except: pass
    await message.answer(f"✅ Разослано {count} пользователям.")
    await state.clear()

@dp.callback_query(F.data == "admin_ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminBan.waiting_user_id)
    await callback.message.edit_text("🚫 Введи ID пользователя для бана/разбана:")

@dp.message(AdminBan.waiting_user_id)
async def admin_ban_action(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        uid = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT is_banned FROM users WHERE user_id = ?", (uid,))
            row = await cursor.fetchone()
            if row:
                new_status = 0 if row[0] == 1 else 1
                await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_status, uid))
                await db.commit()
                await message.answer(f"✅ Пользователь {uid} {'разбанен' if new_status == 0 else 'забанен'}.")
            else:
                await message.answer("❌ Пользователь не найден.")
    except:
        await message.answer("❌ Ошибка.")
    await state.clear()

@dp.callback_query(F.data == "admin_add_hours")
async def admin_add_hours_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminAddHours.waiting_user)
    await callback.message.edit_text("Введите ID пользователя:")

@dp.message(AdminAddHours.waiting_user)
async def admin_add_hours_user(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        await state.update_data(user_id=int(message.text))
        await state.set_state(AdminAddHours.waiting_hours)
        await message.answer("Сколько часов добавить?")
    except:
        await message.answer("❌ Неверный ID.")

@dp.message(AdminAddHours.waiting_hours)
async def admin_add_hours_final(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    data = await state.get_data()
    try:
        hours = float(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET balance_hours = balance_hours + ? WHERE user_id = ?", (hours, data["user_id"]))
            await db.commit()
        await message.answer(f"✅ Добавлено {hours} часов пользователю {data['user_id']}.")
    except:
        await message.answer("❌ Неверное число.")
    await state.clear()

@dp.callback_query(F.data == "stats")
async def user_stats(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance_hours FROM users WHERE user_id = ?", (callback.from_user.id,))
        hours = (await cursor.fetchone())[0] or 0
        cursor = await db.execute("SELECT COUNT(*) FROM autoposts WHERE user_id = ?", (callback.from_user.id,))
        posts = (await cursor.fetchone())[0]
    await callback.message.edit_text(f"📈 <b>Статистика</b>\n\nОсталось: <b>{round(hours,2)}</b> ч\nПостов: <b>{posts}</b>", reply_markup=main_menu(callback.from_user.id))

# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    asyncio.create_task(autopost_worker())
    logger.info("🚀 Autoposter Bot запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
