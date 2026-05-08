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
        # Пользователи + автопостинг
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance_hours REAL DEFAULT 0,
                status TEXT DEFAULT 'user',
                is_banned INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Автопосты пользователя
        await db.execute("""
            CREATE TABLE IF NOT EXISTS autoposts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                text TEXT,
                photo_file_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Активные чаты пользователя
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id INTEGER,
                chat_title TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Тикеты поддержки
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                status TEXT DEFAULT 'open',
                priority INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER,
                user_id INTEGER,
                message TEXT,
                is_admin INTEGER DEFAULT 0,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Логи
        await db.execute("""
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER,
                action TEXT,
                details TEXT
            )
        """)

        await db.commit()
        logger.info("✅ База данных готова")


async def log_action(user_id: int, action: str, details: str = ""):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO action_logs (user_id, action, details) VALUES (?, ?, ?)",
            (user_id, action, details)
        )
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


# ==================== АВТОПОСТИНГ (максимально защищённая версия) ====================
async def autopost_worker():
    post_index = {}

    while True:
        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cursor = await db.execute("""
                    SELECT user_id, balance_hours 
                    FROM users 
                    WHERE balance_hours > 0 AND is_banned = 0
                """)
                users = await cursor.fetchall()

                for user_id, hours in users:
                    try:
                        cursor = await db.execute(
                            "SELECT id, text, photo_file_id FROM autoposts WHERE user_id = ? ORDER BY id",
                            (user_id,)
                        )
                        posts = await cursor.fetchall()

                        if not posts:
                            continue

                        cursor = await db.execute(
                            "SELECT chat_id, chat_title FROM user_chats WHERE user_id = ?",
                            (user_id,)
                        )
                        chats = await cursor.fetchall()

                        if not chats:
                            continue

                        # Ротация
                        if user_id not in post_index:
                            post_index[user_id] = 0
                        idx = post_index[user_id] % len(posts)
                        post = posts[idx]
                        post_index[user_id] += 1

                        sent = 0
                        for chat_id, title in chats:
                            try:
                                if post[2]:
                                    await bot.send_photo(chat_id, photo=post[2], caption=post[1] or "")
                                else:
                                    await bot.send_message(chat_id, post[1] or "")
                                sent += 1
                            except Exception as send_err:
                                logger.warning(f"Ошибка отправки в {chat_id}: {send_err}")

                        # Вычитаем время
                        new_hours = max(0, round(hours - 5/60, 2))
                        await db.execute(
                            "UPDATE users SET balance_hours = ? WHERE user_id = ?",
                            (new_hours, user_id)
                        )
                        await db.commit()

                        if sent > 0:
                            await log_action(user_id, "autopost", f"Отправлено {sent} постов")

                        # Уведомление о низком балансе
                        if 0 < new_hours < 0.5 and hours >= 0.5:
                            try:
                                await bot.send_message(user_id, "⚠️ Осталось меньше 30 минут автопостинга!")
                            except:
                                pass

                    except Exception as user_err:
                        logger.error(f"Ошибка у пользователя {user_id}: {user_err}")

        except Exception as main_err:
            logger.critical(f"Критическая ошибка в воркере: {main_err}")

        await asyncio.sleep(300)


# ==================== ХЕНДЛЕРЫ ====================
@dp.message(CommandStart())
async def start(message: Message):
    await get_or_create_user(message.from_user.id, message.from_user.username)
    text = (
        "🚀 <b>Autoposter Bot</b>\n\n"
        "Автоматическая рассылка твоего контента в чаты каждые 5 минут.\n\n"
        "Купи часы автопостинга и добавь свои посты — бот будет работать за тебя!"
    )
    await message.answer(text, reply_markup=main_menu(message.from_user.id))


async def get_or_create_user(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username or "")
        )
        await db.commit()


@dp.callback_query(F.data == "my_autopost")
async def my_autopost(callback: CallbackQuery):
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT balance_hours FROM users WHERE user_id = ?",
                (callback.from_user.id,)
            )
            row = await cursor.fetchone()
            hours = row[0] if row else 0

            cursor = await db.execute(
                "SELECT COUNT(*) FROM autoposts WHERE user_id = ?",
                (callback.from_user.id,)
            )
            post_count = (await cursor.fetchone())[0]

        text = (
            f"📊 <b>Мой автопостинг</b>\n\n"
            f"Осталось часов: <b>{round(hours, 2)}</b>\n"
            f"Количество постов: <b>{post_count}</b>\n\n"
            f"Бот публикует твои посты каждые 5 минут в добавленные чаты."
        )
        await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))
    except Exception as e:
        logger.error(f"Ошибка в my_autopost: {e}")
        await callback.answer("❌ Произошла ошибка. Попробуй позже.", show_alert=True)


@dp.callback_query(F.data == "user_add_post")
async def user_add_post_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserAddPost.waiting_text)
    text = (
        "➕ <b>Добавить свой пост</b>\n\n"
        "Отправь текст поста (или /skip если только фото):"
    )
    await callback.message.edit_text(text)


@dp.message(UserAddPost.waiting_text)
async def user_add_post_text(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "/skip":
        await state.update_data(text="")
        await state.set_state(UserAddPost.waiting_photo)
        await message.answer("✅ Текст пропущен. Теперь отправь фото (или /skip если только текст):")
    else:
        await state.update_data(text=message.text or "")
        await state.set_state(UserAddPost.waiting_photo)
        await message.answer("Теперь отправь фото (или /skip если только текст):")


@dp.message(UserAddPost.waiting_photo, F.photo)
async def user_add_post_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id if message.photo else None
    text = data.get("text", "")

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO autoposts (user_id, text, photo_file_id) VALUES (?, ?, ?)",
            (message.from_user.id, text, photo_id)
        )
        await db.commit()

    await message.answer("✅ Пост успешно добавлен!", reply_markup=main_menu(message.from_user.id))
    await state.clear()


@dp.callback_query(F.data == "buy_hours")
async def buy_hours(callback: CallbackQuery):
    text = (
        "💳 <b>Купить часы автопостинга</b>\n\n"
        "Выбери пакет:\n\n"
        "• 1 час — <b>CryptoBot</b>\n"
        "  http://t.me/send?start=IVaRmLsNBkDN\n\n"
        "• 3 часа — <b>CryptoBot</b>\n"
        "  http://t.me/send?start=IVdE6YCEFTvo\n\n"
        "После оплаты напиши сюда скриншот или ID транзакции.\n"
        "Также можно оплатить звёздами — отправь их @teqqines"
    )
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))


@dp.callback_query(F.data == "my_chats")
async def my_chats(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT chat_id, chat_title FROM user_chats WHERE user_id = ?",
            (callback.from_user.id,)
        )
        chats = await cursor.fetchall()

    if not chats:
        text = "📋 У тебя пока нет добавленных чатов.\n\nДобавь бота в свой чат и напиши /addchat"
    else:
        text = "📋 <b>Твои чаты:</b>\n\n"
        for chat_id, title in chats:
            text += f"• {title or chat_id}\n"

    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))


@dp.message(Command("addchat"))
async def add_chat(message: Message):
    if not message.chat.type in ["group", "supergroup", "channel"]:
        return await message.answer("❌ Добавь бота в группу или канал.")

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_chats (user_id, chat_id, chat_title) VALUES (?, ?, ?)",
            (message.from_user.id, message.chat.id, message.chat.title or "")
        )
        await db.commit()

    await message.answer("✅ Чат добавлен в автопостинг!")


# ==================== АДМИН ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin_menu")
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return
    await callback.message.edit_text("🔧 <b>Админ-панель</b>", reply_markup=admin_menu())


@dp.callback_query(F.data == "admin_add_post")
async def admin_add_post_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        return
    await state.set_state(AdminAddPost.waiting_user_id)
    await callback.message.edit_text("Введите ID пользователя, которому добавить пост:")


@dp.message(AdminAddPost.waiting_user_id)
async def admin_add_post_user(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    try:
        user_id = int(message.text)
        await state.update_data(user_id=user_id)
        await state.set_state(AdminAddPost.waiting_text)
        await message.answer("Теперь отправь текст поста (или /skip если только фото):")
    except:
        await message.answer("❌ Неверный ID.")


@dp.message(AdminAddPost.waiting_text)
async def admin_add_post_text(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    data = await state.get_data()
    if message.text != "/skip":
        await state.update_data(text=message.text)
    await state.set_state(AdminAddPost.waiting_photo)
    await message.answer("Теперь отправь фото (или /skip если только текст):")


@dp.message(AdminAddPost.waiting_photo, F.photo)
async def admin_add_post_photo(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    data = await state.get_data()
    photo_id = message.photo[-1].file_id
    text = data.get("text", "")

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO autoposts (user_id, text, photo_file_id) VALUES (?, ?, ?)",
            (data["user_id"], text, photo_id)
        )
        await db.commit()

    await message.answer("✅ Пост успешно добавлен пользователю!")
    await state.clear()


# ==================== ТИКЕТЫ (из старого кода) ====================
@dp.callback_query(F.data == "faq")
async def faq(callback: CallbackQuery):
    text = (
        "❓ <b>FAQ — Частые вопросы</b>\n\n"
        "• Как работает автопостинг?\n"
        "Бот каждые 5 минут публикует твои посты в добавленные чаты.\n\n"
        "• Сколько стоит?\n"
        "1 час — через CryptoBot или звёзды @teqqines\n\n"
        "• Можно ли поставить на паузу?\n"
        "Да, скоро будет кнопка Пауза.\n\n"
        "• Что будет, если закончится время?\n"
        "Автопостинг остановится автоматически.\n\n"
        "• Как добавить несколько постов?\n"
        "Просто добавляй их по одному — они будут чередоваться."
    )
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))


@dp.callback_query(F.data == "contacts")
async def contacts(callback: CallbackQuery):
    text = (
        "📞 <b>Контакты</b>\n\n"
        "По всем вопросам:\n"
        "• Telegram: @teqqines\n"
        "• Поддержка: через бота (кнопка «Поддержка»)\n\n"
        "По вопросам оплаты и добавления постов — пиши лично @teqqines"
    )
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))


@dp.callback_query(F.data == "support")
async def support_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_message)
    await callback.message.edit_text("🛠 Напиши своё сообщение в поддержку:")


@dp.message(SupportState.waiting_message)
async def support_save(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "INSERT INTO support_tickets (user_id) VALUES (?) RETURNING id",
            (message.from_user.id,)
        )
        ticket_id = (await cursor.fetchone())[0]
        await db.execute(
            "INSERT INTO support_messages (ticket_id, user_id, message) VALUES (?, ?, ?)",
            (ticket_id, message.from_user.id, message.text)
        )
        await db.commit()

    await message.answer("✅ Тикет создан! Мы ответим скоро.")
    try:
        await bot.send_message(OWNER_ID, f"🎟 Новый тикет #{ticket_id} от @{message.from_user.username}")
    except:
        pass
    await state.clear()


@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, user_id, status FROM support_tickets WHERE status = 'open' ORDER BY id DESC LIMIT 20")
        tickets = await cursor.fetchall()

    if not tickets:
        return await callback.message.edit_text("🎟 Нет открытых тикетов.")

    text = "🎟 <b>Открытые тикеты</b>\n\n"
    keyboard = []
    for tid, uid, status in tickets:
        text += f"#{tid} | ID: {uid}\n"
        keyboard.append([InlineKeyboardButton(text=f"#{tid} — Принять", callback_data=f"ticket_take_{tid}")])

    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@dp.callback_query(F.data == "admin_active_users")
async def admin_active_users(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT u.user_id, u.username, u.balance_hours, COUNT(a.id) as post_count, COUNT(c.id) as chat_count
            FROM users u
            LEFT JOIN autoposts a ON u.user_id = a.user_id
            LEFT JOIN user_chats c ON u.user_id = c.user_id
            WHERE u.balance_hours > 0
            GROUP BY u.user_id
            ORDER BY u.balance_hours DESC
            LIMIT 15
        """)
        users = await cursor.fetchall()

    if not users:
        return await callback.message.edit_text("👥 Нет активных пользователей с автопостингом.")

    text = "👥 <b>Активные пользователи автопостинга</b>\n\n"
    for uid, username, hours, posts, chats in users:
        text += f"@{username or uid} | {round(hours,1)}ч | Постов: {posts} | Чатов: {chats}\n"

    await callback.message.edit_text(text, reply_markup=admin_menu())


@dp.callback_query(F.data == "admin_global_stats")
async def admin_global_stats(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE balance_hours > 0")
        active_users = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT SUM(balance_hours) FROM users")
        total_hours = (await cursor.fetchone())[0] or 0

        cursor = await db.execute("SELECT COUNT(*) FROM autoposts")
        total_posts = (await cursor.fetchone())[0]

    text = (
        f"📊 <b>Общая статистика бота</b>\n\n"
        f"Всего пользователей: <b>{total_users}</b>\n"
        f"С активным автопостингом: <b>{active_users}</b>\n"
        f"Всего часов в обороте: <b>{round(total_hours, 1)}</b>\n"
        f"Всего постов в базе: <b>{total_posts}</b>"
    )
    await callback.message.edit_text(text, reply_markup=admin_menu())


@dp.callback_query(F.data == "admin_add_hours")
async def admin_add_hours_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        return
    await state.set_state(AdminAddHours.waiting_user)
    await callback.message.edit_text("Введите ID пользователя, которому добавить часы:")


@dp.callback_query(F.data.startswith("ticket_take_"))
async def ticket_take(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        return
    ticket_id = int(callback.data.split("_")[2])

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM support_tickets WHERE id = ?", (ticket_id,))
        user_id = (await cursor.fetchone())[0]
        await db.execute("UPDATE support_tickets SET status = 'in_progress' WHERE id = ?", (ticket_id,))
        await db.commit()

    try:
        await bot.send_message(user_id, f"✅ Ваш тикет #{ticket_id} взят в работу!")
    except:
        pass

    await state.set_state(AdminTicketReply.waiting_reply)
    await state.update_data(ticket_id=ticket_id)
    await callback.message.edit_text("✍️ Напиши ответ пользователю:")


@dp.message(AdminTicketReply.waiting_reply)
async def ticket_reply(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    data = await state.get_data()
    ticket_id = data["ticket_id"]

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM support_tickets WHERE id = ?", (ticket_id,))
        user_id = (await cursor.fetchone())[0]
        await db.execute(
            "INSERT INTO support_messages (ticket_id, user_id, message, is_admin) VALUES (?, ?, ?, 1)",
            (ticket_id, message.from_user.id, message.text)
        )
        await db.execute("UPDATE support_tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
        await db.commit()

    try:
        await bot.send_message(user_id, f"📩 Ответ от поддержки:\n\n{message.text}\n\nТикет закрыт.")
    except:
        pass

    await message.answer("✅ Ответ отправлен, тикет закрыт.")
    await state.clear()


# ==================== ГЛОБАЛЬНАЯ ЗАЩИТА ОТ ОШИБОК ====================
@dp.errors()
async def error_handler(update, exception):
    logger.error(f"Ошибка: {exception}")
    return True  # Не даём боту упасть


# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    asyncio.create_task(autopost_worker())
    logger.info("🚀 Autoposter Bot запущен (максимальная защита)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

