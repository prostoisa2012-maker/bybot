import asyncio
import logging
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, Message
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import sqlite3
import os

# ---------- НАСТРОЙКИ ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8520742550:AAE-8fxrY7Fr6o2xSv18GCSMtk_2aQviCGs")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 7762090976))
PRIVATE_CHANNEL_LINK = os.environ.get("PRIVATE_CHANNEL_LINK", "https://t.me/+ukyC6cdndyhkZjIy")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@sander_stark")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "sanderstark_bot")
PRICE_STARS_PROJECT = int(os.environ.get("PRICE_STARS_PROJECT", 50))
PRICE_STARS_5_REFS = int(os.environ.get("PRICE_STARS_5_REFS", 15))
PRICE_STARS_10_REFS = int(os.environ.get("PRICE_STARS_10_REFS", 30))
REFERRAL_COST = int(os.environ.get("REFERRAL_COST", 10))

# ---------- БАЗА ДАННЫХ ----------
conn = sqlite3.connect("sander_stark.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    referrer_id INTEGER DEFAULT 0,
    referrals_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'Пользователь',
    balance_ref REAL DEFAULT 0,
    last_self_ref_date TEXT DEFAULT ''
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER,
    referred_id INTEGER,
    date TEXT,
    is_self_ref INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    project_name TEXT,
    payment_method TEXT,
    payment_status TEXT DEFAULT 'ожидает',
    admin_approved INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bot_stats (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    total_uses INTEGER DEFAULT 0,
    orders_completed INTEGER DEFAULT 0,
    orders_pending INTEGER DEFAULT 0
)
""")
cursor.execute("INSERT OR IGNORE INTO bot_stats (id) VALUES (1)")
conn.commit()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

class ProjectCreation(StatesGroup):
    entering_name = State()

class AdminGiveRef(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

class ReferralInput(StatesGroup):
    waiting_for_ref_link = State()

class SupportMessage(StatesGroup):
    waiting_for_text = State()

def get_user(user_id: int):
    try:
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()
    except Exception as e:
        logger.error(f"Ошибка get_user: {e}")
        return None

def can_use_self_ref(user_id: int) -> bool:
    try:
        user = get_user(user_id)
        if not user:
            return False
        if len(user) < 7:
            return True
        last_date = user[6]
        if not last_date or last_date == '':
            return True
        today = date.today().isoformat()
        return last_date != today
    except Exception as e:
        logger.error(f"Ошибка can_use_self_ref: {e}")
        return True

def add_user(user_id: int, username: str = '', referrer_id: int = None):
    try:
        existing = get_user(user_id)
        if existing is None:
            status = "Администратор" if user_id == ADMIN_ID else "Пользователь"
            cursor.execute(
                "INSERT INTO users (user_id, username, referrer_id, status) VALUES (?, ?, ?, ?)",
                (user_id, username or '', referrer_id or 0, status)
            )
            conn.commit()
            
            if referrer_id and referrer_id != user_id and referrer_id > 0:
                add_referral(referrer_id, user_id, is_self_ref=False)
            
            cursor.execute("UPDATE bot_stats SET total_uses = total_uses + 1")
            conn.commit()
            logger.info(f"Добавлен новый пользователь: {user_id}")
    except Exception as e:
        logger.error(f"Ошибка add_user: {e}")

def add_referral(referrer_id: int, referred_id: int, is_self_ref: bool = False):
    try:
        today = date.today().isoformat()
        referrer = get_user(referrer_id)
        if not referrer:
            logger.warning(f"Реферер {referrer_id} не найден")
            return False
        
        cursor.execute(
            "INSERT INTO referrals (referrer_id, referred_id, date, is_self_ref) VALUES (?, ?, ?, ?)",
            (referrer_id, referred_id, today, 1 if is_self_ref else 0)
        )
        
        cursor.execute(
            "UPDATE users SET referrals_count = referrals_count + 1, balance_ref = balance_ref + 1 WHERE user_id = ?",
            (referrer_id,)
        )
        conn.commit()
        logger.info(f"Реферал: {referrer_id} <- {referred_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка add_referral: {e}")
        return False

def get_user_stats(user_id: int):
    try:
        user = get_user(user_id)
        if user:
            return {
                "user_id": user[0],
                "username": user[1],
                "referrals": user[3] if user[3] else 0,
                "status": user[4],
                "balance_ref": user[5]
            }
    except Exception as e:
        logger.error(f"Ошибка get_user_stats: {e}")
    return None

def increment_orders(status="pending"):
    try:
        if status == "completed":
            cursor.execute("UPDATE bot_stats SET orders_completed = orders_completed + 1, orders_pending = MAX(orders_pending - 1, 0)")
        else:
            cursor.execute("UPDATE bot_stats SET orders_pending = orders_pending + 1")
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка increment_orders: {e}")

def get_bot_stats():
    try:
        cursor.execute("SELECT * FROM bot_stats WHERE id = 1")
        row = cursor.fetchone()
        if row:
            return {
                "total_uses": row[1] or 0,
                "orders_completed": row[2] or 0,
                "orders_pending": row[3] or 0
            }
    except Exception as e:
        logger.error(f"Ошибка get_bot_stats: {e}")
    return {"total_uses": 0, "orders_completed": 0, "orders_pending": 0}

async def notify_admin(text: str, reply_markup=None):
    try:
        await bot.send_message(ADMIN_ID, text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка notify_admin: {e}")

def get_pending_orders():
    try:
        cursor.execute("""
            SELECT p.id, p.user_id, p.project_name, p.payment_method, p.payment_status, p.created_at, u.username 
            FROM projects p 
            LEFT JOIN users u ON p.user_id = u.user_id 
            WHERE p.admin_approved = 0 AND p.payment_status = 'оплачено'
        """)
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"Ошибка get_pending_orders: {e}")
        return []

def approve_order(order_id: int):
    try:
        cursor.execute("UPDATE projects SET admin_approved = 1 WHERE id = ?", (order_id,))
        increment_orders("completed")
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка approve_order: {e}")
        return False

def main_menu(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🛍 Товары", callback_data="menu_goods"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile")
    )
    builder.row(
        InlineKeyboardButton(text="👥 Рефералы", callback_data="menu_referrals"),
        InlineKeyboardButton(text="📞 Поддержка", callback_data="menu_support")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статус бота", callback_data="menu_status")
    )
    builder.row(
        InlineKeyboardButton(text="📚 Туториал", callback_data="menu_tutorial")
    )
    if user_id == ADMIN_ID:
        builder.row(InlineKeyboardButton(text="🧪 Тестить", callback_data="admin_test"))
        builder.row(InlineKeyboardButton(text="⭐️ Выдать рефералку", callback_data="admin_give_ref"))
        builder.row(InlineKeyboardButton(text="📋 Заказы", callback_data="admin_orders"))
    return builder.as_markup()

def goods_menu(user_id: int):
    user = get_user(user_id)
    current_refs = user[3] if user and len(user) > 3 and user[3] else 0

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"🎮 Копия Блек Раша 2026 LITE (⭐️ {PRICE_STARS_PROJECT})",
        callback_data="buy_br_lite"
    ))

    if current_refs >= REFERRAL_COST:
        ref_text = f"👥 Потратить {REFERRAL_COST} рефералов (✅ {current_refs})"
    else:
        ref_text = f"👥 Потратить {REFERRAL_COST} рефералов (❌ {current_refs}/{REFERRAL_COST})"

    builder.row(InlineKeyboardButton(text=ref_text, callback_data="buy_with_refs"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return builder.as_markup()

def referrals_menu(user_id: int):
    builder = InlineKeyboardBuilder()
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    
    builder.row(InlineKeyboardButton(
        text="📤 Отправить друзьям",
        url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся к SANDER STARK!"
    ))
    
    builder.row(InlineKeyboardButton(
        text=f"🛒 Купить 5 рефералов (⭐️ {PRICE_STARS_5_REFS})",
        callback_data="buy_5_refs"
    ))
    
    builder.row(InlineKeyboardButton(
        text=f"🔥 Купить 10 рефералов (⭐️ {PRICE_STARS_10_REFS}) СКИДКА!",
        callback_data="buy_10_refs"
    ))
    
    builder.row(InlineKeyboardButton(
        text="🔗 Ввести реферальную ссылку",
        callback_data="input_ref_link"
    ))
    
    can_self = can_use_self_ref(user_id)
    if can_self:
        builder.row(InlineKeyboardButton(
            text="🎁 Получить +1 реферал (ежедневно)",
            callback_data="use_self_ref"
        ))
    else:
        builder.row(InlineKeyboardButton(
            text="🎁 Уже получено сегодня",
            callback_data="none"
        ))
    
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return builder.as_markup()

def cancel_button():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()

def back_button():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""

    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_part = args[1].replace("ref_", "")
            referrer_id = int(ref_part)
        except:
            referrer_id = None

    add_user(user_id, username, referrer_id)

    await message.answer(
        "♟️ <b>SANDER STARK</b> — твой личный создатель проектов!\n\n"
        "🤖 Используй кнопки внизу, чтобы управлять ботом.",
        reply_markup=main_menu(user_id)
    )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "♟️ <b>SANDER STARK</b>\n\nВыбери действие:",
        reply_markup=main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "cancel_action")
async def cancel_action(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Действие отменено.",
        reply_markup=main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "none")
async def none_callback(callback: types.CallbackQuery):
    await callback.answer("❌ Недоступно")

@dp.callback_query(F.data == "menu_tutorial")
async def show_tutorial(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📚 <b>Туториал: Как создать проект</b>\n\n"
        "🚧 <b>В разработке!</b>\n"
        "⏰ Туториал будет включён <b>завтра вечером</b>.\n\n"
        "Следи за обновлениями! 🔔",
        reply_markup=back_button()
    )

@dp.callback_query(F.data == "menu_goods")
async def show_goods(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    current_refs = user[3] if user and len(user) > 3 else 0

    await callback.message.edit_text(
        f"🛍 <b>Товары</b>\n\n"
        f"🎮 <b>Копия Блек Раша 2026 LITE</b>\n"
        f"├─ ⭐️ За звёзды: <b>{PRICE_STARS_PROJECT} ⭐️</b>\n"
        f"└─ 👥 За рефералов: <b>{REFERRAL_COST} шт.</b> (у вас: {current_refs})\n\n"
        f"💡 <b>Как получить рефералов?</b>\n"
        f"• Приглашай друзей (+1)\n"
        f"• Ежедневный бонус (+1)\n"
        f"• Купи рефералы в разделе «Рефералы»\n\n"
        f"Накопи <b>{REFERRAL_COST}</b> шт. и получи проект <b>БЕСПЛАТНО!</b>\n\n"
        f"⚠️ После оплаты заказ проверяется администратором.\n\n"
        f"Выбери способ:",
        reply_markup=goods_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "buy_br_lite")
async def buy_with_stars(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(payment_method="stars")
    await state.set_state(ProjectCreation.entering_name)
    await callback.message.edit_text(
        "📝 Введи <b>название проекта</b>:",
        reply_markup=cancel_button()
    )

@dp.callback_query(F.data == "buy_with_refs")
async def buy_with_referrals(callback: types.CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    if not user or user[3] < REFERRAL_COST:
        await callback.answer(f"❌ Недостаточно рефералов! Нужно {REFERRAL_COST}", show_alert=True)
        return

    await state.update_data(payment_method="referrals")
    await state.set_state(ProjectCreation.entering_name)
    await callback.message.edit_text(
        f"👥 <b>Оплата рефералами</b>\n\n"
        f"📝 Введи <b>название проекта</b>:\n"
        f"(Спишется {REFERRAL_COST} рефералов)",
        reply_markup=cancel_button()
    )

@dp.message(StateFilter(ProjectCreation.entering_name))
async def process_project_name(message: Message, state: FSMContext):
    project_name = message.text
    data = await state.get_data()
    method = data.get("payment_method")
    user_id = message.from_user.id

    if method == "referrals":
        user = get_user(user_id)
        if not user or user[3] < REFERRAL_COST:
            await message.answer("❌ Ошибка: недостаточно рефералов!", reply_markup=main_menu(user_id))
            await state.clear()
            return

        cursor.execute("UPDATE users SET referrals_count = referrals_count - ? WHERE user_id = ?",
                       (REFERRAL_COST, user_id))
        conn.commit()

        cursor.execute(
            "INSERT INTO projects (user_id, project_name, payment_method, payment_status, admin_approved) VALUES (?, ?, ?, 'оплачено', 0)",
            (user_id, project_name, "referrals")
        )
        conn.commit()
        increment_orders("pending")

        cursor.execute("SELECT last_insert_rowid()")
        order_id = cursor.fetchone()[0]

        admin_kb = InlineKeyboardBuilder()
        admin_kb.row(InlineKeyboardButton(text="✅ Принять заказ", callback_data=f"approve_{order_id}"))
        
        await notify_admin(
            f"🆕 <b>Новый проект #{order_id}</b>\n"
            f"👤 @{message.from_user.username or 'нет'} (ID: {user_id})\n"
            f"📛 Проект: {project_name}\n"
            f"💳 Оплата: рефералы\n\n"
            f"⏳ Ожидает подтверждения!",
            reply_markup=admin_kb.as_markup()
        )

        await message.answer(
            f"✅ Проект <b>«{project_name}»</b> создан!\n"
            f"💳 Оплачено: {REFERRAL_COST} рефералами\n"
            f"🎁 Создатель: {ADMIN_USERNAME}\n\n"
            f"⏳ <b>Ожидайте подтверждения администратора!</b>",
            reply_markup=main_menu(user_id)
        )
        await state.clear()

    elif method == "stars":
        await state.update_data(project_name=project_name)
        
        await message.answer_invoice(
            title="Создание проекта",
            description=f"Проект: {project_name}\nСоздатель: {ADMIN_USERNAME}",
            payload=f"project_{user_id}_{int(datetime.now().timestamp())}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Создание проекта", amount=PRICE_STARS_PROJECT)],
            start_parameter="create_project"
        )

    elif method == "admin_test":
        cursor.execute(
            "INSERT INTO projects (user_id, project_name, payment_method, payment_status, admin_approved) VALUES (?, ?, ?, 'админ_тест', 1)",
            (user_id, project_name, "admin_test")
        )
        conn.commit()
        increment_orders("completed")

        await message.answer(
            f"✅ <b>Тестовый проект создан!</b>\n"
            f"📛 Название: <b>«{project_name}»</b>\n"
            f"🔗 Доступ в канал:\n{PRIVATE_CHANNEL_LINK}",
            reply_markup=main_menu(user_id)
        )
        await state.clear()

@dp.callback_query(F.data == "menu_referrals")
async def show_referrals(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    stats = get_user_stats(user_id)
    referrals_count = stats['referrals'] if stats else 0

    await callback.message.edit_text(
        f"👥 <b>Рефералы</b>\n\n"
        f"🔢 У тебя: <b>{referrals_count}</b> рефералов\n"
        f"🎯 Для бесплатного проекта: <b>{REFERRAL_COST}</b> шт.\n\n"
        f"📤 Отправь друзьям ссылку\n"
        f"🛒 Купи 5 рефералов — {PRICE_STARS_5_REFS} ⭐️\n"
        f"🔥 Купи 10 рефералов — {PRICE_STARS_10_REFS} ⭐️\n"
        f"🔗 Введи чужую реферальную ссылку\n"
        f"🎁 Ежедневный бонус +1 реферал\n\n"
        f"🔗 Твоя ссылка:\n<code>{ref_link}</code>",
        reply_markup=referrals_menu(user_id)
    )

@dp.callback_query(F.data == "buy_5_refs")
async def buy_5_refs(callback: types.CallbackQuery):
    await callback.message.answer_invoice(
        title="Покупка 5 рефералов",
        description="+5 рефералов для использования в боте",
        payload=f"buy5refs_{callback.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="5 рефералов", amount=PRICE_STARS_5_REFS)],
        start_parameter="buy5"
    )
    await callback.answer("💳 Счёт выставлен")

@dp.callback_query(F.data == "buy_10_refs")
async def buy_10_refs(callback: types.CallbackQuery):
    await callback.message.answer_invoice(
        title="🔥 10 рефералов (скидка)",
        description="+10 рефералов со скидкой!",
        payload=f"buy10refs_{callback.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="10 рефералов", amount=PRICE_STARS_10_REFS)],
        start_parameter="buy10"
    )
    await callback.answer("🔥 Счёт выставлен")

@dp.callback_query(F.data == "input_ref_link")
async def input_ref_link_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ReferralInput.waiting_for_ref_link)
    await callback.message.edit_text(
        "🔗 <b>Введи реферальную ссылку</b>\n\n"
        f"Отправь ссылку от друга:\n"
        f"<code>https://t.me/{BOT_USERNAME}?start=ref_123456</code>",
        reply_markup=cancel_button()
    )

@dp.message(StateFilter(ReferralInput.waiting_for_ref_link))
async def process_ref_link(message: Message, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id

    if "?start=ref_" in text:
        try:
            ref_id = int(text.split("ref_")[1].split()[0])
            
            if ref_id == user_id:
                await message.answer(
                    "❌ Нельзя использовать свою ссылку здесь!\n"
                    "Используй кнопку «🎁 Получить +1 реферал»",
                    reply_markup=main_menu(user_id)
                )
                await state.clear()
                return

            referrer = get_user(ref_id)
            if not referrer:
                await message.answer("❌ Пользователь не найден!", reply_markup=main_menu(user_id))
                await state.clear()
                return

            success = add_referral(ref_id, user_id)
            if success:
                await message.answer(
                    f"✅ Реферальная ссылка активирована!\n"
                    f"Пользователь @{referrer[1] or 'без username'} получил +1 реферала.",
                    reply_markup=main_menu(user_id)
                )
            else:
                await message.answer("⚠️ Ошибка активации", reply_markup=main_menu(user_id))

        except Exception as e:
            await message.answer("❌ Неверный формат ссылки!", reply_markup=main_menu(user_id))
    else:
        await message.answer("❌ Отправь корректную реферальную ссылку!", reply_markup=cancel_button())

    await state.clear()

@dp.callback_query(F.data == "use_self_ref")
async def use_self_ref(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if not can_use_self_ref(user_id):
        await callback.answer("❌ Ты уже получил бонус сегодня!", show_alert=True)
        return

    success = add_referral(user_id, user_id, is_self_ref=True)
    if success:
        cursor.execute("UPDATE users SET last_self_ref_date = ? WHERE user_id = ?",
                       (date.today().isoformat(), user_id))
        conn.commit()

        user = get_user(user_id)
        refs = user[3] if user and len(user) > 3 else 0
        
        await callback.message.edit_text(
            f"🎁 <b>Ежедневный бонус получен!</b>\n\n"
            f"+1 реферал!\n"
            f"🔢 Теперь у тебя: <b>{refs}</b> рефералов\n\n"
            f"Приходи завтра снова!",
            reply_markup=main_menu(user_id)
        )
    else:
        await callback.answer("❌ Ошибка!", show_alert=True)

@dp.callback_query(F.data == "admin_orders")
async def show_admin_orders(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔️ Только для администратора!", show_alert=True)
        return

    orders = get_pending_orders()
    
    if not orders:
        await callback.message.edit_text(
            "📋 <b>Заказы на проверку</b>\n\n✅ Нет ожидающих заказов.",
            reply_markup=back_button()
        )
        return

    text = "📋 <b>Заказы на проверку:</b>\n\n"
    builder = InlineKeyboardBuilder()
    
    for order in orders:
        order_id, user_id, project_name, pay_method, _, created_at, username = order
        text += (
            f"🆔 <b>Заказ #{order_id}</b>\n"
            f"👤 @{username or 'нет'} (ID: {user_id})\n"
            f"📛 {project_name}\n"
            f"💳 {pay_method}\n\n"
        )
        builder.row(InlineKeyboardButton(
            text=f"✅ Принять заказ #{order_id}",
            callback_data=f"approve_{order_id}"
        ))
    
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("approve_"))
async def approve_order_handler(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔️ Только для администратора!", show_alert=True)
        return

    order_id = int(callback.data.split("_")[1])
    
    cursor.execute("SELECT user_id, project_name FROM projects WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    
    if order:
        user_id, project_name = order
        approve_order(order_id)
        
        try:
            await bot.send_message(
                user_id,
                f"🎉 <b>Твой заказ одобрен!</b>\n\n"
                f"📛 Проект: <b>«{project_name}»</b>\n"
                f"✅ Администратор подтвердил создание проекта.\n\n"
                f"🔗 Доступ в приватный канал:\n{PRIVATE_CHANNEL_LINK}"
            )
        except:
            pass
        
        await callback.message.edit_text(
            f"✅ Заказ #{order_id} принят! Пользователь уведомлён.",
            reply_markup=back_button()
        )
    else:
        await callback.answer("❌ Заказ не найден", show_alert=True)

@dp.callback_query(F.data == "admin_test")
async def admin_test_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔️ Только для администратора!", show_alert=True)
        return

    await state.update_data(payment_method="admin_test")
    await state.set_state(ProjectCreation.entering_name)
    await callback.message.edit_text(
        "🧪 <b>Режим тестирования</b>\n\n📝 Введи название проекта:",
        reply_markup=cancel_button()
    )

@dp.callback_query(F.data == "admin_give_ref")
async def admin_give_ref_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔️ Только для администратора!", show_alert=True)
        return

    await state.set_state(AdminGiveRef.waiting_for_user_id)
    await callback.message.edit_text(
        "⭐️ <b>Выдача рефералов</b>\n\n"
        "Введи <b>ID пользователя</b>:",
        reply_markup=cancel_button()
    )

@dp.message(StateFilter(AdminGiveRef.waiting_for_user_id))
async def admin_give_ref_user(message: Message, state: FSMContext):
    try:
        target_id = int(message.text.strip())
        target_user = get_user(target_id)

        if not target_user:
            await message.answer("❌ Пользователь не найден!", reply_markup=main_menu(message.from_user.id))
            await state.clear()
            return

        await state.update_data(target_user_id=target_id)
        await state.set_state(AdminGiveRef.waiting_for_amount)
        
        target_name = f"@{target_user[1]}" if target_user[1] else "без username"
        await message.answer(
            f"👤 {target_name} (ID: {target_id})\n"
            f"Текущие рефералы: {target_user[3]}\n\n"
            "📝 Введи <b>количество</b>:",
            reply_markup=cancel_button()
        )
    except ValueError:
        await message.answer("❌ Введи корректный ID!", reply_markup=cancel_button())

@dp.message(StateFilter(AdminGiveRef.waiting_for_amount))
async def admin_give_ref_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            await message.answer("❌ Количество должно быть больше 0!")
            return

        data = await state.get_data()
        target_id = data.get("target_user_id")

        cursor.execute(
            "UPDATE users SET referrals_count = referrals_count + ?, balance_ref = balance_ref + ? WHERE user_id = ?",
            (amount, amount, target_id)
        )
        conn.commit()

        target_user = get_user(target_id)
        target_name = f"@{target_user[1]}" if target_user and target_user[1] else "без username"

        try:
            await bot.send_message(
                target_id,
                f"🎉 <b>Поздравляем!</b>\n"
                f"Администратор начислил тебе +{amount} рефералов!\n"
                f"📊 Теперь у тебя: {target_user[3]} рефералов"
            )
        except:
            pass

        await message.answer(
            f"✅ Выдано +{amount} рефералов пользователю {target_name}",
            reply_markup=main_menu(message.from_user.id)
        )
        await state.clear()

    except ValueError:
        await message.answer("❌ Введи корректное число!")

@dp.callback_query(F.data == "menu_profile")
async def show_profile(callback: types.CallbackQuery):
    stats = get_user_stats(callback.from_user.id)
    
    if stats:
        text = (
            f"👤 <b>Профиль</b>\n\n"
            f"🆔 ID: <code>{stats['user_id']}</code>\n"
            f"📛 Username: @{stats['username'] or 'нет'}\n"
            f"⭐️ Статус: <b>{stats['status']}</b>\n"
            f"👥 Рефералов: {stats['referrals']}"
        )
    else:
        text = "❌ Профиль не найден"

    await callback.message.edit_text(text, reply_markup=back_button())

@dp.callback_query(F.data == "menu_support")
async def support_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SupportMessage.waiting_for_text)
    await callback.message.edit_text(
        "📞 <b>Поддержка</b>\n\nНапиши сообщение:",
        reply_markup=cancel_button()
    )

@dp.message(StateFilter(SupportMessage.waiting_for_text))
async def support_message_handler(message: Message, state: FSMContext):
    user = message.from_user
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="✉️ Ответить",
        url=f"tg://user?id={user.id}"
    ))

    await notify_admin(
        f"📞 <b>Поддержка</b>\n"
        f"👤 @{user.username or 'нет'} (ID: {user.id})\n\n"
        f"💬 {message.text}",
        reply_markup=builder.as_markup()
    )

    await message.answer("✅ Сообщение отправлено!", reply_markup=main_menu(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "menu_status")
async def show_status(callback: types.CallbackQuery):
    stats = get_bot_stats()

    await callback.message.edit_text(
        f"📊 <b>Статус бота</b>\n\n"
        f"👥 Использовали: <b>{stats['total_uses']}</b>\n"
        f"✅ Принято заказов: <b>{stats['orders_completed']}</b>\n"
        f"⏳ Ожидают: <b>{stats['orders_pending']}</b>",
        reply_markup=back_button()
    )

@dp.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def on_payment(message: Message, state: FSMContext):
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload

    if payload.startswith("project_"):
        data = await state.get_data()
        project_name = data.get("project_name", "Без названия")

        cursor.execute(
            "INSERT INTO projects (user_id, project_name, payment_method, payment_status, admin_approved) VALUES (?, ?, ?, 'оплачено', 0)",
            (user_id, project_name, "stars")
        )
        conn.commit()
        increment_orders("pending")

        cursor.execute("SELECT last_insert_rowid()")
        order_id = cursor.fetchone()[0]

        admin_kb = InlineKeyboardBuilder()
        admin_kb.row(InlineKeyboardButton(text="✅ Принять заказ", callback_data=f"approve_{order_id}"))
        
        await notify_admin(
            f"🆕 <b>Новый проект #{order_id}</b>\n"
            f"👤 @{message.from_user.username or 'нет'} (ID: {user_id})\n"
            f"📛 {project_name}\n"
            f"💳 Оплата: звёзды\n\n"
            f"⏳ Ожидает подтверждения!",
            reply_markup=admin_kb.as_markup()
        )

        await message.answer(
            f"✅ <b>Оплата прошла!</b>\n\n"
            f"📛 Проект: <b>«{project_name}»</b>\n"
            f"💳 Оплачено: {PRICE_STARS_PROJECT} ⭐️\n\n"
            f"⏳ <b>Ожидайте подтверждения администратора!</b>",
            reply_markup=main_menu(user_id)
        )
        await state.clear()

    elif payload.startswith("buy5refs_"):
        cursor.execute("UPDATE users SET referrals_count = referrals_count + 5, balance_ref = balance_ref + 5 WHERE user_id = ?", (user_id,))
        conn.commit()
        
        user = get_user(user_id)
        refs = user[3] if user else 0
        
        await message.answer(
            f"✅ <b>Покупка успешна!</b>\n\n"
            f"🛒 +5 рефералов\n"
            f"💳 Оплачено: {PRICE_STARS_5_REFS} ⭐️\n"
            f"📊 Теперь у тебя: <b>{refs}</b> рефералов",
            reply_markup=main_menu(user_id)
        )

    elif payload.startswith("buy10refs_"):
        cursor.execute("UPDATE users SET referrals_count = referrals_count + 10, balance_ref = balance_ref + 10 WHERE user_id = ?", (user_id,))
        conn.commit()
        
        user = get_user(user_id)
        refs = user[3] if user else 0
        
        await message.answer(
            f"🔥 <b>Покупка успешна!</b>\n\n"
            f"🛒 +10 рефералов (скидка)\n"
            f"💳 Оплачено: {PRICE_STARS_10_REFS} ⭐️\n"
            f"📊 Теперь у тебя: <b>{refs}</b> рефералов",
            reply_markup=main_menu(user_id)
        )

async def main():
    logger.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())