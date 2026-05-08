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

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8174433113:AAGsCNLWDI_j8qIi4JI4Bqt2uLuAjO2QM30"
OWNER_ID = 8592184380
DB_NAME = "autoposter_bot.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, balance_hours REAL DEFAULT 0, is_banned INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS autoposts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, photo_file_id TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS user_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER, chat_title TEXT, topic_id INTEGER DEFAULT 0, is_system INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status TEXT DEFAULT 'open')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, user_id INTEGER, message TEXT, is_admin INTEGER DEFAULT 0)""")
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

class AdminSpecialBroadcast(StatesGroup):
    waiting_text = State()

# ==================== МЕНЮ ====================
def main_menu(user_id: int):
    buttons = [
        [InlineKeyboardButton(text="📊 Мой автопостинг", callback_data="my_autopost"),
         InlineKeyboardButton(text="➕ Добавить пост", callback_data="user_add_post")],
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
        [InlineKeyboardButton(text="➕ Добавить часы", callback_data="admin_add_hours"),
         InlineKeyboardButton(text="📢 Особая рассылка", callback_data="admin_special_broadcast")],
        [InlineKeyboardButton(text="🗑 Управление постами", callback_data="admin_manage_posts"),
         InlineKeyboardButton(text="🎟 Тикеты", callback_data="admin_tickets")],
        [InlineKeyboardButton(text="👥 Активные пользователи", callback_data="admin_active_users"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="admin_global_stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])

# ==================== АВТОПОСТИНГ (30 минут) ====================
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

                    cursor = await db.execute("SELECT chat_id, topic_id, is_system FROM user_chats WHERE user_id = ?", (user_id,))
                    chats = await cursor.fetchall()
                    if not chats: continue

                    if user_id not in post_index: post_index[user_id] = 0
                    post = posts[post_index[user_id] % len(posts)]
                    post_index[user_id] += 1

                    for chat_id, topic_id, is_system in chats:
                        try:
                            text = post[1] or ""
                            if is_system:
                                text += "\n\n🔥 <b>СПЕЦИАЛЬНЫЙ ПИАР ОТ АДМИНА</b> 🔥"

                            promo = "\n\n——————————\n🤖 <b>Teqqines Piar Bot</b>\nКупить часы: /start"

                            if post[2]:
                                await bot.send_photo(chat_id, photo=post[2], caption=text + promo, message_thread_id=topic_id if topic_id else None)
                            else:
                                await bot.send_message(chat_id, text + promo, message_thread_id=topic_id if topic_id else None)
                        except: pass

                    new_hours = max(0, round(hours - 30/60, 2))
                    await db.execute("UPDATE users SET balance_hours = ? WHERE user_id = ?", (new_hours, user_id))
                    await db.commit()
        except Exception as e:
            logger.error(f"Ошибка автопостинга: {e}")
        await asyncio.sleep(1800)

# ==================== ХЕНДЛЕРЫ ====================
@dp.message(CommandStart())
async def start(message: Message):
    await get_or_create_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "🚀 <b>Teqqines Piar Bot</b>\n\n"
        "Автоматическая рассылка твоего контента каждые 30 минут.\n\n"
        "Купи часы и добавь пост — бот будет работать за тебя!",
        reply_markup=main_menu(message.from_user.id)
    )

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
        posts = (await cursor.fetchone())[0]
    await callback.message.edit_text(
        f"📊 <b>Мой автопостинг</b>\n\n"
        f"Осталось часов: <b>{round(hours, 2)}</b>\n"
        f"Количество постов: <b>{posts}</b>\n\n"
        f"Бот публикует твои посты каждые 30 минут.",
        reply_markup=main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "user_add_post")
async def user_add_post_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM autoposts WHERE user_id = ?", (callback.from_user.id,))
            if (await cursor.fetchone())[0] >= 1:
                return await callback.message.edit_text("❌ У тебя уже есть пост. Удали старый перед добавлением нового.", reply_markup=main_menu(callback.from_user.id))
    
    await state.set_state(UserAddPost.waiting_text)
    await callback.message.edit_text("➕ <b>Добавить пост</b>\n\nОтправь текст (или /skip если только фото):")

@dp.message(UserAddPost.waiting_text)
async def user_add_post_text(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "/skip":
        await state.update_data(text="")
    else:
        await state.update_data(text=message.text or "")
    await state.set_state(UserAddPost.waiting_photo)
    await message.answer("Теперь отправь фото (или /skip если только текст):")

@dp.message(UserAddPost.waiting_photo)
async def user_add_post_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id if message.photo else None
    text = data.get("text", "")

    if not text and not photo_id:
        await message.answer("❌ Нужно хотя бы текст или фото!")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO autoposts (user_id, text, photo_file_id) VALUES (?, ?, ?)", (message.from_user.id, text, photo_id))
        await db.commit()

    await message.answer("✅ Пост успешно добавлен!", reply_markup=main_menu(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "buy_hours")
async def buy_hours(callback: CallbackQuery):
    await callback.message.edit_text(
        "💳 <b>Купить часы автопостинга</b>\n\n"
        "• 1 час — http://t.me/send?start=IVaRmLsNBkDN\n"
        "• 3 часа — http://t.me/send?start=IVdE6YCEFTvo\n\n"
        "После оплаты напиши сюда скриншот или ID транзакции.\n"
        "Также можно оплатить звёздами — отправь @teqqines",
        reply_markup=main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "my_chats")
async def my_chats(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT chat_title, is_system FROM user_chats WHERE user_id = ?", (callback.from_user.id,))
        chats = await cursor.fetchall()

    text = "📋 <b>Системные чаты</b> (добавлены админом)\n"
    system_chats = [c[0] for c in chats if c[1] == 1]
    personal_chats = [c[0] for c in chats if c[1] == 0]

    if system_chats:
        text += "\n".join([f"• {c}" for c in system_chats])
    else:
        text += "Пока нет системных чатов\n"

    text += "\n📋 <b>Мои чаты</b> (добавлены тобой)\n"
    if personal_chats:
        text += "\n".join([f"• {c}" for c in personal_chats])
    else:
        text += "Пока нет личных чатов\n"

    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

@dp.message(Command("addchat"))
async def add_chat(message: Message):
    topic_id = message.message_thread_id or 0
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO user_chats (user_id, chat_id, chat_title, topic_id, is_system) VALUES (?, ?, ?, ?, 0)", 
                         (message.from_user.id, message.chat.id, message.chat.title or "", topic_id))
        await db.commit()
    await message.answer("✅ Чат добавлен в твои личные чаты!")

# ==================== АДМИН ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin_menu")
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    await callback.message.edit_text("🔧 <b>Админ-панель — Teqqines Piar Bot</b>", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminBroadcast.waiting_text)
    await callback.message.edit_text("📢 Введи текст для обычной рассылки:")

@dp.message(AdminBroadcast.waiting_text)
async def do_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = await cursor.fetchall()
        cursor = await db.execute("SELECT DISTINCT chat_id, topic_id FROM user_chats")
        chats = await cursor.fetchall()

    count = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 <b>Сообщение от админа:</b>\n\n{message.text}")
            count += 1
        except: pass

    for chat_id, topic_id in chats:
        try:
            await bot.send_message(chat_id, f"📢 <b>Сообщение от админа:</b>\n\n{message.text}", message_thread_id=topic_id if topic_id else None)
            count += 1
        except: pass

    await message.answer(f"✅ Разослано {count} получателям.")
    await state.clear()

@dp.callback_query(F.data == "admin_special_broadcast")
async def admin_special_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    await state.set_state(AdminSpecialBroadcast.waiting_text)
    await callback.message.edit_text("🔥 Введи текст для <b>особой</b> рассылки (будет с другим оформлением):")

@dp.message(AdminSpecialBroadcast.waiting_text)
async def do_special_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = await cursor.fetchall()

    count = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"🔥 <b>СПЕЦИАЛЬНОЕ ПРЕДЛОЖЕНИЕ ОТ АДМИНА</b> 🔥\n\n{message.text}\n\n@teqqines_bot")
            count += 1
        except: pass

    await message.answer(f"✅ Особая рассылка отправлена {count} пользователям.")
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
                new = 0 if row[0] == 1 else 1
                await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new, uid))
                await db.commit()
                await message.answer(f"✅ Пользователь {uid} {'разбанен' if new == 0 else 'забанен'}.")
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
    await state.update_data(user_id=int(message.text))
    await state.set_state(AdminAddHours.waiting_hours)
    await message.answer("Сколько часов добавить?")

@dp.message(AdminAddHours.waiting_hours)
async def admin_add_hours_final(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    data = await state.get_data()
    try:
        hours = float(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET balance_hours = balance_hours + ? WHERE user_id = ?", (hours, data["user_id"]))
            await db.commit()
        
        # Красивое уведомление
        try:
            await bot.send_message(
                data["user_id"],
                f"🎉 <b>Поздравляем!</b>\n\n"
                f"Вам начислено <b>{hours} часов</b> автопостинга!\n\n"
                f"Теперь вы можете добавлять посты — они будут публиковаться автоматически каждые 30 минут.\n\n"
                f"Спасибо за сотрудничество! 🚀"
            )
        except: pass
        
        await message.answer(f"✅ Добавлено {hours} часов пользователю {data['user_id']}.")
    except:
        await message.answer("❌ Неверное число.")
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
        text += f"#{pid} | User: {uid} | {txt[:40] if txt else 'Без текста'}...\n"
        keyboard.append([InlineKeyboardButton(text=f"🗑 Удалить #{pid}", callback_data=f"delete_post_{pid}")])
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
        cursor = await db.execute("SELECT id, user_id FROM support_tickets WHERE status = 'open' ORDER BY id DESC LIMIT 15")
        tickets = await cursor.fetchall()
    if not tickets:
        return await callback.message.edit_text("🎟 Нет открытых тикетов.", reply_markup=admin_menu())
    text = "🎟 <b>Открытые тикеты</b>\n\n"
    keyboard = []
    for tid, uid in tickets:
        text += f"#{tid} | ID: {uid}\n"
        keyboard.append([InlineKeyboardButton(text=f"✅ Принять #{tid}", callback_data=f"ticket_take_{tid}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("ticket_take_"))
async def ticket_take(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID: return
    ticket_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM support_tickets WHERE id = ?", (ticket_id,))
        user_id = (await cursor.fetchone())[0]
        await db.execute("UPDATE support_tickets SET status = 'in_progress' WHERE id = ?", (ticket_id,))
        await db.commit()
    try:
        await bot.send_message(user_id, f"✅ Ваш тикет #{ticket_id} взят в работу!")
    except: pass
    await state.set_state("admin_ticket_reply")
    await state.update_data(ticket_id=ticket_id)
    await callback.message.edit_text("✍️ Напиши ответ пользователю:")

@dp.message(lambda m: True)
async def ticket_reply(message: Message, state: FSMContext):
    current = await state.get_state()
    if current != "admin_ticket_reply": return
    if message.from_user.id != OWNER_ID: return
    
    data = await state.get_data()
    ticket_id = data["ticket_id"]
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM support_tickets WHERE id = ?", (ticket_id,))
        user_id = (await cursor.fetchone())[0]
        await db.execute("INSERT INTO support_messages (ticket_id, user_id, message, is_admin) VALUES (?, ?, ?, 1)", (ticket_id, message.from_user.id, message.text))
        await db.execute("UPDATE support_tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
        await db.commit()
    
    try:
        await bot.send_message(user_id, f"📩 <b>Ответ от поддержки:</b>\n\n{message.text}\n\nТикет закрыт. Спасибо!")
    except: pass
    
    await message.answer("✅ Ответ отправлен, тикет закрыт.")
    await state.clear()

@dp.callback_query(F.data == "admin_active_users")
async def admin_active_users(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id, username, balance_hours FROM users WHERE balance_hours > 0 LIMIT 20")
        users = await cursor.fetchall()
    if not users:
        text = "👥 <b>Активные пользователи</b>\n\nПока нет пользователей с активным автопостингом."
    else:
        text = "👥 <b>Активные пользователи автопостинга</b>\n\n"
        for uid, username, hours in users:
            text += f"• @{username or uid} — {round(hours,1)} ч\n"
    await callback.message.edit_text(text, reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_global_stats")
async def admin_global_stats(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        active = (await (await db.execute("SELECT COUNT(*) FROM users WHERE balance_hours > 0")).fetchone())[0]
        posts = (await (await db.execute("SELECT COUNT(*) FROM autoposts")).fetchone())[0]
    await callback.message.edit_text(
        f"📊 <b>Общая статистика</b>\n\n"
        f"Всего пользователей: <b>{total}</b>\n"
        f"С активным автопостингом: <b>{active}</b>\n"
        f"Всего постов в базе: <b>{posts}</b>",
        reply_markup=admin_menu()
    )

@dp.callback_query(F.data == "faq")
async def faq(callback: CallbackQuery):
    text = (
        "❓ <b>FAQ — Частые вопросы</b>\n\n"
        "• Как работает автопостинг?\n"
        "Бот публикует твои посты каждые 30 минут во все добавленные чаты.\n\n"
        "• Сколько стоит?\n"
        "1 час — через CryptoBot или звёзды @teqqines\n\n"
        "• Правила:\n"
        "❌ Без скама, криминала, тяжёлого контента, спама\n"
        "✅ Только качественный контент\n\n"
        "• Что будет, если закончится время?\n"
        "Автопостинг остановится автоматически.\n\n"
        "• Можно ли добавить несколько постов?\n"
        "Нет, только 1 пост на пользователя (кроме админа)."
    )
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "contacts")
async def contacts(callback: CallbackQuery):
    text = (
        "📞 <b>Контакты</b>\n\n"
        "Системные администраторы:\n"
        "• @teqqines (Главный администратор)\n"
        "• Системный администратор\n\n"
        "По всем вопросам бота — пиши @teqqines"
    )
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await state.set_state("support_waiting")
    await callback.message.edit_text("🛠 <b>Поддержка</b>\n\nНапиши своё сообщение. Мы ответим в ближайшее время.")

@dp.message(lambda m: True)
async def support_message(message: Message, state: FSMContext):
    current = await state.get_state()
    if current != "support_waiting": return

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("INSERT INTO support_tickets (user_id) VALUES (?) RETURNING id", (message.from_user.id,))
        ticket_id = (await cursor.fetchone())[0]
        await db.execute("INSERT INTO support_messages (ticket_id, user_id, message) VALUES (?, ?, ?)", (ticket_id, message.from_user.id, message.text))
        await db.commit()

    await message.answer("✅ Тикет создан! Мы ответим в ближайшее время.")
    try:
        await bot.send_message(OWNER_ID, f"🎟 Новый тикет #{ticket_id} от @{message.from_user.username}")
    except: pass
    await state.clear()

@dp.callback_query(F.data == "stats")
async def stats(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance_hours FROM users WHERE user_id = ?", (callback.from_user.id,))
        hours = (await cursor.fetchone())[0] or 0
        cursor = await db.execute("SELECT COUNT(*) FROM autoposts WHERE user_id = ?", (callback.from_user.id,))
        posts = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM user_chats WHERE user_id = ?", (callback.from_user.id,))
        chats = (await cursor.fetchone())[0]

    text = (
        f"📊 <b>СТАТИСТИКА ПОСТАВЩИКА</b>\n\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"💰 Осталось часов: <b>{round(hours, 2)}</b>\n"
        f"📝 Всего постов: <b>{posts}</b>\n"
        f"📋 Добавлено чатов: <b>{chats}</b>\n\n"
        f"Бот публикует твои посты каждые 30 минут."
    )
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))

# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    asyncio.create_task(autopost_worker())
    logger.info("🚀 Teqqines Piar Bot запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
