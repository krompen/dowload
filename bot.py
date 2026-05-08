import asyncio
import aiosqlite
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "8174433113:AAGsCNLWDI_j8qIi4JI4Bqt2uLuAjO2QM30"
OWNER_ID = 8032626504
DB_NAME = "autoposter_bot.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==================== БАЗА ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance_hours REAL DEFAULT 0, is_banned INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS autoposts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, photo_file_id TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS user_chats (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER, chat_title TEXT, topic_id INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status TEXT DEFAULT 'open')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, user_id INTEGER, message TEXT, is_admin INTEGER DEFAULT 0)""")
        await db.commit()

# ==================== FSM ====================
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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Мой автопостинг", callback_data="my_autopost"),
         InlineKeyboardButton(text="➕ Добавить пост", callback_data="user_add_post")],
        [InlineKeyboardButton(text="📋 Мои чаты", callback_data="my_chats"),
         InlineKeyboardButton(text="➕ Купить часы", callback_data="buy_hours")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq"),
         InlineKeyboardButton(text="📞 Контакты", callback_data="contacts")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="support"),
         InlineKeyboardButton(text="📈 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🔧 Админ-панель", callback_data="admin_menu")] if user_id == OWNER_ID else []
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban")],
        [InlineKeyboardButton(text="➕ Добавить часы", callback_data="admin_add_hours"),
         InlineKeyboardButton(text="🗑 Управление автопостами", callback_data="admin_manage_posts")],
        [InlineKeyboardButton(text="🎟 Тикеты", callback_data="admin_tickets"),
         InlineKeyboardButton(text="👥 Активные пользователи", callback_data="admin_active_users")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_global_stats"),
         InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])

# ==================== АВТОПОСТИНГ (5 минут) ====================
async def autopost_worker():
    post_index = {}
    while True:
        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cursor = await db.execute("SELECT user_id, balance_hours FROM users WHERE balance_hours > 0 AND is_banned = 0")
                for user_id, hours in await cursor.fetchall():
                    cursor = await db.execute("SELECT id, text, photo_file_id FROM autoposts WHERE user_id = ? ORDER BY id", (user_id,))
                    posts = await cursor.fetchall()
                    if not posts: continue

                    cursor = await db.execute("SELECT chat_id, topic_id FROM user_chats WHERE user_id = ?", (user_id,))
                    chats = await cursor.fetchall()
                    if not chats: continue

                    if user_id not in post_index: post_index[user_id] = 0
                    post = posts[post_index[user_id] % len(posts)]
                    post_index[user_id] += 1

                    promo = "\n\n——————————\n🤖 Автопостинг от @teqqines_bot\nКупить: /start"

                    for chat_id, topic_id in chats:
                        try:
                            if post[2]:
                                await bot.send_photo(chat_id, photo=post[2], caption=(post[1] or "") + promo, message_thread_id=topic_id if topic_id else None)
                            else:
                                await bot.send_message(chat_id, (post[1] or "") + promo, message_thread_id=topic_id if topic_id else None)
                        except: pass

                    new_hours = max(0, round(hours - 5/60, 2))
                    await db.execute("UPDATE users SET balance_hours = ? WHERE user_id = ?", (new_hours, user_id))
                    await db.commit()
        except Exception as e:
            logger.error(f"Ошибка автопостинга: {e}")
        await asyncio.sleep(300)  # 5 минут

# ==================== ОСНОВНЫЕ ХЕНДЛЕРЫ ====================
@dp.message(CommandStart())
async def start(message: Message):
    await get_or_create_user(message.from_user.id, message.from_user.username)
    await message.answer("🚀 <b>Autoposter Bot</b>\n\nАвтоматическая рассылка каждые 5 минут.", reply_markup=main_menu(message.from_user.id))

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
        count = (await cursor.fetchone())[0]
    await callback.message.edit_text(f"📊 <b>Мой автопостинг</b>\n\nОсталось: <b>{round(hours,2)}</b> ч\nПостов: <b>{count}</b>", reply_markup=main_menu(callback.from_user.id))

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
    await message.answer("Фото (или /skip):")

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
    await callback.message.edit_text("💳 <b>Купить часы</b>\n\n1 час → http://t.me/send?start=IVaRmLsNBkDN\n3 часа → http://t.me/send?start=IVdE6YCEFTvo", reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "my_chats")
async def my_chats(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT chat_title FROM user_chats WHERE user_id = ?", (callback.from_user.id,))
        chats = await cursor.fetchall()
    text = "📋 <b>Твои чаты:</b>\n" + "\n".join([f"• {c[0]}" for c in chats]) if chats else "Чатов нет. Используй /addchat"
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

@dp.message(Command("addchat"))
async def add_chat(message: Message):
    topic_id = message.message_thread_id or 0
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO user_chats (user_id, chat_id, chat_title, topic_id) VALUES (?, ?, ?, ?)", 
                         (message.from_user.id, message.chat.id, message.chat.title or "", topic_id))
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
    await callback.message.edit_text("📢 Текст рассылки:")

@dp.message(AdminBroadcast.waiting_text)
async def do_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = await cursor.fetchall()
    count = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 <b>От админа:</b>\n\n{message.text}")
            count += 1
        except: pass
    await message.answer(f"✅ Разослано {count} пользователям.")
    await state.clear()

@dp.callback_query(F.data == "admin_ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminBan.waiting_user_id)
    await callback.message.edit_text("🚫 ID пользователя:")

@dp.message(AdminBan.waiting_user_id)
async def admin_ban_action(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    try:
        uid = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT is_banned FROM users WHERE user_id = ?", (uid,))
            row = await cursor.fetchone()
            if row:
                new = 0 if row[0] == 1 else 1
                await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new, uid))
                await db.commit()
                await message.answer(f"✅ {'Разбанен' if new == 0 else 'Забанен'}.")
            else:
                await message.answer("❌ Не найден.")
    except:
        await message.answer("❌ Ошибка.")
    await state.clear()

@dp.callback_query(F.data == "admin_add_hours")
async def admin_add_hours_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminAddHours.waiting_user)
    await callback.message.edit_text("ID пользователя:")

@dp.message(AdminAddHours.waiting_user)
async def admin_add_hours_user(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    await state.update_data(user_id=int(message.text))
    await state.set_state(AdminAddHours.waiting_hours)
    await message.answer("Сколько часов?")

@dp.message(AdminAddHours.waiting_hours)
async def admin_add_hours_final(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET balance_hours = balance_hours + ? WHERE user_id = ?", (float(message.text), data["user_id"]))
        await db.commit()
    await message.answer("✅ Часы добавлены.")
    await state.clear()

@dp.callback_query(F.data == "admin_manage_posts")
async def admin_manage_posts(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, user_id, text FROM autoposts ORDER BY id DESC LIMIT 20")
        posts = await cursor.fetchall()
    if not posts:
        return await callback.message.edit_text("Постов нет.", reply_markup=admin_menu())
    text = "🗑 <b>Управление автопостами</b>\n\n"
    keyboard = []
    for pid, uid, txt in posts:
        text += f"#{pid} | User: {uid} | {txt[:30] if txt else 'Без текста'}...\n"
        keyboard.append([InlineKeyboardButton(text=f"Удалить #{pid}", callback_data=f"delete_post_{pid}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("delete_post_"))
async def delete_post(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    post_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM autoposts WHERE id = ?", (post_id,))
        await db.commit()
    await callback.message.edit_text("✅ Пост удалён.", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, user_id FROM support_tickets WHERE status = 'open' LIMIT 15")
        tickets = await cursor.fetchall()
    if not tickets:
        return await callback.message.edit_text("Тикетов нет.", reply_markup=admin_menu())
    text = "🎟 <b>Открытые тикеты</b>\n"
    for tid, uid in tickets:
        text += f"#{tid} | {uid}\n"
    await callback.message.edit_text(text, reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_active_users")
async def admin_active_users(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id, username, balance_hours FROM users WHERE balance_hours > 0 LIMIT 15")
        users = await cursor.fetchall()
    text = "👥 <b>Активные пользователи</b>\n" + "\n".join([f"@{u[1] or u[0]} — {round(u[2],1)}ч" for u in users])
    await callback.message.edit_text(text, reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_global_stats")
async def admin_global_stats(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        active = (await (await db.execute("SELECT COUNT(*) FROM users WHERE balance_hours > 0")).fetchone())[0]
        posts = (await (await db.execute("SELECT COUNT(*) FROM autoposts")).fetchone())[0]
    await callback.message.edit_text(f"📊 <b>Статистика</b>\nПользователей: {total}\nАктивных: {active}\nПостов: {posts}", reply_markup=admin_menu())

@dp.callback_query(F.data == "faq")
async def faq(callback: CallbackQuery):
    await callback.message.edit_text("❓ <b>FAQ</b>\n\n• Автопостинг каждые 5 минут\n• Правила: без скама, криминала, спама\n• Поддержка: @teqqines", reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "contacts")
async def contacts(callback: CallbackQuery):
    await callback.message.edit_text("📞 <b>Контакты</b>\n\n@teqqines — все вопросы", reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    await callback.message.edit_text("🛠 <b>Поддержка</b>\n\nНапиши своё сообщение.", reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "stats")
async def stats(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        hours = (await (await db.execute("SELECT balance_hours FROM users WHERE user_id = ?", (callback.from_user.id,))).fetchone())[0] or 0
        posts = (await (await db.execute("SELECT COUNT(*) FROM autoposts WHERE user_id = ?", (callback.from_user.id,))).fetchone())[0]
    await callback.message.edit_text(f"📈 <b>Статистика</b>\nОсталось: {round(hours,2)} ч\nПостов: {posts}", reply_markup=main_menu(callback.from_user.id))

# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    asyncio.create_task(autopost_worker())
    logger.info("🚀 Autoposter Bot запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
