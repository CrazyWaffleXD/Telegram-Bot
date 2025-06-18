import telebot
from telebot import types
import sqlite3
from datetime import datetime
import logging
import os
import time
import threading # Для неблокирующей рассылки
import sys # Для sys.exit

# --- КОНФИГУРАЦИЯ ---
# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Получение токена из переменных окружения
# Для запуска: export TELEGRAM_BOT_TOKEN='ВАШ_ТОКЕН_ЗДЕСЬ'
# Или в Dockerfile/docker-compose.yml
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.error("Токен бота не найден в переменной окружения TELEGRAM_BOT_TOKEN.")
    logger.error("Пожалуйста, установите переменную окружения TELEGRAM_BOT_TOKEN.")
    logger.warning("Используется временный заглушечный токен. Это НЕБЕЗОПАСНО для продакшена!")
    # ВНИМАНИЕ: Замените на sys.exit(1) на проде, если токен обязателен
    TOKEN = '8094895160:AAGzj1vzPOWgs502sAcqC1ZP51_Y-3arv0s' # ВРЕМЕННАЯ ЗАГЛУШКА, УДАЛИТЕ НА ПРОДЕ!
    # sys.exit(1) # Раскомментируйте на проде для принудительного выхода без токена

bot = telebot.TeleBot(TOKEN)

# ID администраторов (могут быть добавлены в БД для динамического управления)
ADMIN_IDS = [5672359649, 1604969937]

# Подключение к базе данных (check_same_thread=False оправдано для pyTelegramBotAPI, т.к. обработчики работают в одном потоке)
conn = sqlite3.connect('tasks.db', check_same_thread=False)
cursor = conn.cursor()

# Константы
MAX_BUTTONS_PER_PAGE = 8 # Максимальное количество кнопок на странице для пагинации
MAX_LOG_ENTRIES = 50 # Максимальное количество записей в логе для отображения

# Предопределенные дисциплины для инициализации БД
PREDEFINED_DISCIPLINES = [
    "Учебная практика по ПМ.01",
    "Производственная практика по ПМ.01",
    "Иностранный язык в профессиональной деятельности",
    "Физическая культура",
    "Компьютерные сети",
    "Экзамен по ПМ.01",
    "Поддержка и тестирование программных модулей",
    "Разработка мобильных приложений",
    "Системное программирование",
    "Технология разработки программного обеспечения"
]

# --- КОНСТАНТЫ ДЛЯ CALLBACK_DATA ---
# Префиксы для callback_data, чтобы было легче маршрутизировать запросы
CB_PREFIX_DISC_SELECT = "select_disc:" # Выбор дисциплины для добавления задания
CB_PREFIX_DISC_PAGE_ADD = "disc_page_add:" # Пагинация дисциплин для добавления задания
CB_PREFIX_DISC_TASKS_VIEW = "show_disc_tasks:" # Выбор дисциплины для просмотра заданий
CB_PREFIX_DISC_PAGE_VIEW = "disc_page_view:" # Пагинация дисциплин для просмотра заданий
CB_PREFIX_TASK_VIEW = "view_task:" # Просмотр деталей задания
CB_PREFIX_PHOTO_NAV = "photo_nav:" # Навигация по фотографиям
CB_PREFIX_BACK_TO_TASK = "back_to_task:" # Назад к заданию из просмотра фото
CB_PREFIX_BACK_TO_DISC_TASKS_VIEW = "back_to_disc_tasks_view:" # Назад к списку заданий из деталей
CB_PREFIX_MANAGE_TASKS_DISC = "manage_disc_tasks:" # Выбор дисциплины для управления заданиями (админ)
CB_PREFIX_MANAGE_TASKS_PAGE = "manage_tasks_page:" # Пагинация дисциплин для управления заданиями (админ)
CB_PREFIX_ADMIN_DELETE_TASK = "admin_delete_task:" # Удаление задания (админ)
CB_PREFIX_CONFIRM_DELETE_TASK = "confirm_delete_task:" # Подтверждение удаления задания (админ)
CB_PREFIX_CANCEL_DELETE_TASK = "cancel_delete_task:" # Отмена удаления задания (админ)
CB_PREFIX_DELETE_DISC = "delete_discipline:" # Выбор дисциплины для удаления (админ)
CB_PREFIX_CONFIRM_DELETE_DISC = "confirm_delete_disc:" # Подтверждение удаления дисциплины (админ)
CB_PREFIX_CONFIRM_DELETE_DISC_W_TASKS = "confirm_delete_disc_with_tasks:" # Подтверждение удаления дисциплины с заданиями (админ)
CB_PREFIX_CANCEL_DELETE_DISC = "cancel_delete_disc:" # Отмена удаления дисциплины (админ)
CB_PREFIX_DELETE_DISC_PAGE = "delete_disc_page:" # Пагинация дисциплин для удаления (админ)
CB_PREFIX_RENAME_DISC = "rename_discipline:" # Выбор дисциплины для переименования (админ)
CB_PREFIX_RENAME_DISC_PAGE = "rename_disc_page:" # Пагинация дисциплин для переименования (админ)
CB_PREFIX_USERS_PAGE = "users_page:" # Пагинация списка пользователей (админ)

# Общие колбэки
CB_CANCEL = "cancel" # Общая отмена действия
CB_BACK_TO_MAIN_MENU = "back_to_main_menu" # Назад в главное меню
CB_BACK_TO_ADMIN_PANEL = "back_to_admin_panel" # Назад в админ-панель
CB_BACK_TO_MANAGE_DISCIPLINES = "back_to_manage_disciplines" # Назад в управление дисциплинами
CB_BACK_TO_MANAGE_TASKS = "back_to_manage_tasks" # Назад в управление заданиями
CB_BACK_TO_DISC_SELECTION_FOR_VIEW = "back_to_disc_select_view" # Назад к выбору дисциплины для просмотра заданий
CB_ANNOUNCE_CONFIRM = "announce_confirm" # Подтверждение рассылки
CB_ANNOUNCE_CANCEL = "announce_cancel" # Отмена рассылки

# --- СТАТУСЫ ПОЛЬЗОВАТЕЛЕЙ ---
class UserState:
    """Простая система состояний для пользователей."""
    def __init__(self):
        self.states = {} # {user_id: {'state': 'state_name', 'data': {}}}

    def set_state(self, user_id, state, data=None):
        self.states[user_id] = {'state': state, 'data': data or {}}
        logger.info(f"User {user_id} state set to: {state} with data: {data}")

    def get_state(self, user_id):
        return self.states.get(user_id, {'state': None, 'data': {}})

    def clear_state(self, user_id):
        if user_id in self.states:
            logger.info(f"User {user_id} state cleared.")
            del self.states[user_id]

user_state = UserState()

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def initialize_database():
    """Инициализирует структуру базы данных, создает таблицы и добавляет начальные данные."""
    try:
        cursor.execute("PRAGMA foreign_keys = ON;") # Включаем поддержку внешних ключей
        
        tables = [
            '''CREATE TABLE IF NOT EXISTS users (
               user_id INTEGER PRIMARY KEY,
               username TEXT,
               first_name TEXT,
               last_name TEXT,
               join_date TEXT,
               is_admin INTEGER DEFAULT 0)''',
               
            '''CREATE TABLE IF NOT EXISTS disciplines (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT UNIQUE)''',
                
            '''CREATE TABLE IF NOT EXISTS tasks (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               discipline_id INTEGER,
               name TEXT,
               description TEXT,
               deadline TEXT,
               added_by INTEGER,
               FOREIGN KEY(discipline_id) REFERENCES disciplines(id) ON DELETE CASCADE,
               FOREIGN KEY(added_by) REFERENCES users(user_id) ON DELETE SET NULL)''',
                
            '''CREATE TABLE IF NOT EXISTS solutions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               task_id INTEGER,
               text TEXT,
               added_by INTEGER,
               FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
               FOREIGN KEY(added_by) REFERENCES users(user_id) ON DELETE SET NULL)''',
                
            '''CREATE TABLE IF NOT EXISTS photos (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               task_id INTEGER,
               file_id TEXT,
               FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE)''',
                
            '''CREATE TABLE IF NOT EXISTS logs (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id INTEGER,
               action TEXT,
               timestamp TEXT)'''
        ]

        for table_sql in tables:
            cursor.execute(table_sql)

        # Проверяем и добавляем недостающие столбцы в таблицу users (если они были добавлены позже)
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'is_admin' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
            conn.commit()

        # Добавляем предопределенные дисциплины, если их нет
        for discipline_name in PREDEFINED_DISCIPLINES:
            try:
                cursor.execute("INSERT INTO disciplines (name) VALUES (?)", (discipline_name,))
                conn.commit()
            except sqlite3.IntegrityError:
                # Дисциплина уже существует, это нормально
                conn.rollback()
            except Exception as e:
                logger.error(f"Ошибка при добавлении дисциплины '{discipline_name}': {e}", exc_info=True)
                conn.rollback()

        # Убеждаемся, что администраторы из ADMIN_IDS есть в БД и имеют статус админа
        for admin_id in ADMIN_IDS:
            cursor.execute("""
                INSERT INTO users (user_id, is_admin, join_date)
                VALUES (?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET is_admin = 1
            """, (admin_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        logger.info("База данных успешно инициализирована.")

    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}", exc_info=True)
        raise # Перевыбрасываем исключение, так как без БД бот не будет работать корректно

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def log_action(user_id, action):
    """Логирование действий пользователя в БД."""
    try:
        cursor.execute(
            "INSERT INTO logs (user_id, action, timestamp) VALUES (?, ?, ?)",
            (user_id, action, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка логирования действия user_id={user_id}, action='{action}': {e}", exc_info=True)

def is_admin(user_id):
    """Проверка прав администратора."""
    try:
        # Быстрая проверка для предопределенных админов (опционально, можно только по БД)
        if user_id in ADMIN_IDS:
            return True
        
        cursor.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return bool(result and result[0])
    except Exception as e:
        logger.error(f"Ошибка в функции is_admin для user_id={user_id}: {e}", exc_info=True)
        return False

def _safe_edit_message(chat_id, message_id, text, reply_markup=None, parse_mode=None):
    """Безопасная попытка редактирования сообщения."""
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e).lower():
            logger.debug(f"Message {message_id} in chat {chat_id} not modified.")
            return True # Считаем успехом, так как сообщение уже в нужном состоянии
        elif "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
            logger.warning(f"Failed to edit message {message_id} in chat {chat_id}: {e}. Attempting to send new message.")
            # Сообщение не может быть отредактировано, возможно, оно слишком старое или удалено, попробуем отправить новое
            try:
                bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
                return True
            except Exception as send_e:
                logger.error(f"Failed to send new message after edit failure in chat {chat_id}: {send_e}", exc_info=True)
                return False
        else:
            logger.error(f"Unexpected Telegram API error when editing message {message_id} in chat {chat_id}: {e}", exc_info=True)
            return False
    except Exception as e:
        logger.error(f"An unexpected error occurred while editing message {message_id} in chat {chat_id}: {e}", exc_info=True)
        return False

def _generate_pagination_markup(current_page, total_pages, callback_prefix, item_id=None):
    """Генерирует кнопки пагинации."""
    markup = types.InlineKeyboardMarkup()
    nav_buttons = []
    
    base_data = f"{callback_prefix}"
    if item_id is not None:
        base_data += f"{item_id}:"
    
    if current_page > 0:
        nav_buttons.append(types.InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"{base_data}{current_page-1}"
        ))
    if current_page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=f"{base_data}{current_page+1}"
        ))
    
    if nav_buttons:
        markup.row(*nav_buttons)
    return markup

def _get_discipline_info(discipline_id):
    """Получает информацию о дисциплине по ID."""
    cursor.execute("SELECT name FROM disciplines WHERE id = ?", (discipline_id,))
    return cursor.fetchone()

def _get_task_info(task_id):
    """Получает полную информацию о задании."""
    cursor.execute('''
        SELECT t.name, t.description, t.deadline, d.name AS discipline_name, t.discipline_id 
        FROM tasks t
        JOIN disciplines d ON t.discipline_id = d.id
        WHERE t.id = ?
    ''', (task_id,))
    return cursor.fetchone()

# --- КЛАВИАТУРЫ ---

def main_menu_markup(user_id):
    """Главное меню бота."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "➕ Добавить задание", 
        "📚 Список дисциплин",
        "📝 Список заданий",
        "ℹ️ Помощь"
    ]
    
    if is_admin(user_id):
        buttons.append("👑 Админ-панель")
    
    markup.add(*[types.KeyboardButton(btn) for btn in buttons])
    return markup

def admin_panel_markup():
    """Админ-панель."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "📊 Просмотреть логи", 
        "👥 Статистика пользователей",
        "📋 Список всех пользователей",
        "📌 Управление заданиями",
        "📚 Управление дисциплинами",
        "📢 Сделать объявление",
        "🔙 Назад в меню" # Возврат в главное меню
    ]
    markup.add(*[types.KeyboardButton(btn) for btn in buttons])
    return markup

def manage_disciplines_markup():
    """Меню управления дисциплинами."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "➕ Добавить дисциплину",
        "➖ Удалить дисциплину",
        "✏️ Переименовать дисциплину",
        "🔙 Назад" # Возврат в админ-панель
    ]
    markup.add(*[types.KeyboardButton(btn) for btn in buttons])
    return markup

# --- ДЕКОРАТОРЫ ---

def private_only(func):
    """Декоратор для обработки команд только в приватных чатах."""
    def wrapped(message):
        if message.chat.type != 'private':
            bot.send_message(message.chat.id, "🔒 Этот функционал доступен только в личных сообщениях. Пожалуйста, напишите мне в ЛС, чтобы продолжить.")
            return
        return func(message)
    return wrapped

def admin_only(func):
    """Декоратор для функций, доступных только администраторам."""
    def wrapped(message):
        if not is_admin(message.from_user.id):
            bot.send_message(message.chat.id, "⛔ У вас нет прав для этого действия.")
            log_action(message.from_user.id, f"Попытка доступа к админ-функции: {func.__name__}")
            return
        return func(message)
    return wrapped

# --- ОСНОВНЫЕ ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Обработчик команд /start и /help."""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Если команда вызвана в групповом чате, перенаправляем пользователя в ЛС
    if message.chat.type != 'private':
        try:
            bot.send_message(
                message.chat.id,
                f"Привет, {first_name}! 👋\nЯ бот для управления заданиями и дедлайнами. "
                f"Чтобы я мог помочь тебе, пожалуйста, напиши мне в личные сообщения. "
                f"Это безопасно и удобно для твоих данных! @{bot.get_me().username}"
            )
            log_action(user_id, f"Перенаправлен в ЛС из группы: {message.chat.id}")
        except Exception as e:
            logger.error(f"Ошибка при попытке перенаправить user_id={user_id} из группы {message.chat.id}: {e}", exc_info=True)
        return # Прекращаем выполнение в группе

    try:
        # Определяем статус админа для этого пользователя
        is_admin_flag = 1 if user_id in ADMIN_IDS else 0

        # Добавляем пользователя или обновляем информацию, сохраняя статус админа
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, join_date, is_admin)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                is_admin=?
        """, (user_id, username, first_name, last_name, current_time, is_admin_flag, is_admin_flag))
        
        conn.commit()
        
        log_action(user_id, "Запуск бота /start" if message.text == '/start' else "Запрос помощи /help")

        if message.text == '/start':
            welcome_msg = """
*Добро пожаловать, будущий светило науки!* (или уже мастер прогулов? 😊)

💬 *Я – твой учебный ассистент*, созданный легендарным дуэтом:
*Александр & Аркадий*
(да-да, те самые гуру кода с харизмой супергероев!)

💬 *Чем могу помочь:*
✅ Спасти от дедлайнов (ну, хотя бы предупредить)
✅ Найти задания (даже если ты пропустил... всё)
✅ Сохранить мотивацию (шоколадку не дам, но пнуть могу)

🚀 *Начнём?* Выбирай действие в меню ниже!
"""
            bot.send_message(
                user_id,
                welcome_msg,
                reply_markup=main_menu_markup(user_id),
                parse_mode="Markdown"
            )
        else: # /help
            help_msg = """
📚 *Помощь по боту*

✨ *Основные команды:*
/start - Перезапустить бота
/help - Это сообщение

🎯 *Возможности:*
- Добавлять и отслеживать задания
- Просматривать дисциплины
- Управлять учебным процессом

-----Бот в тесте-----
Если нашли баг/баги пиши мне в личку 
@sunflowerghoat
"""
            bot.send_message(
                user_id,
                help_msg,
                reply_markup=main_menu_markup(user_id),
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Ошибка в send_welcome для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))


@bot.message_handler(func=lambda message: message.text == "🔙 Назад в меню")
@private_only
def handle_back_to_menu(message):
    """Возвращает пользователя в главное меню."""
    try:
        user_state.clear_state(message.from_user.id) # Очищаем состояние при возврате в меню
        bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu_markup(message.from_user.id))
        log_action(message.from_user.id, "Вернулся в главное меню")
    except Exception as e:
        logger.error(f"Ошибка в handle_back_to_menu для user_id={message.from_user.id}: {e}", exc_info=True)
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == "ℹ️ Помощь")
@private_only
def handle_help_button(message):
    """Показывает справку по кнопке."""
    send_welcome(message) # Используем тот же обработчик, что и для /help

# --- ОБРАБОТЧИКИ ГЛАВНОГО МЕНЮ ---

@bot.message_handler(func=lambda message: message.text == "➕ Добавить задание")
@private_only
def handle_add_task(message):
    """Начинает процесс добавления нового задания."""
    user_state.clear_state(message.from_user.id) # Очищаем состояние, чтобы избежать зацикливания
    # Pass message object to show_disciplines_for_selection, which handles both Message and CallbackQuery
    show_disciplines_for_selection(message, 0, CB_PREFIX_DISC_SELECT, CB_PREFIX_DISC_PAGE_ADD, CB_CANCEL)

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_DISC_SELECT))
def process_task_discipline(call):
    """Обрабатывает выбор дисциплины для нового задания."""
    user_id = call.from_user.id
    discipline_id = int(call.data.split(':')[1])
    
    discipline_info = _get_discipline_info(discipline_id)
    if not discipline_info:
        bot.answer_callback_query(call.id, "⚠️ Дисциплина не найдена.", show_alert=True)
        return
    discipline_name = discipline_info[0]

    try:
        if not _safe_edit_message(call.message.chat.id, call.message.message_id, f"📚 Выбрана дисциплина: *{discipline_name}*", parse_mode="Markdown"):
            bot.send_message(call.message.chat.id, f"📚 Выбрана дисциплина: *{discipline_name}*", parse_mode="Markdown")
        
        msg = bot.send_message(user_id, "📝 Введите название задания:", reply_markup=types.ReplyKeyboardRemove())
        user_state.set_state(user_id, 'waiting_for_task_name', {'discipline_id': discipline_id})
        bot.register_next_step_handler(msg, process_task_name)
        bot.answer_callback_query(call.id) # Отвечаем на колбэк
    except Exception as e:
        logger.error(f"Ошибка в process_task_discipline для user_id={user_id}, discipline_id={discipline_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

def process_task_name(message):
    """Обрабатывает ввод названия задания."""
    user_id = message.from_user.id
    state_data = user_state.get_state(user_id)['data']
    
    try:
        if message.text and message.text.lower() == "отмена":
            bot.send_message(user_id, "❌ Добавление задания отменено.", reply_markup=main_menu_markup(user_id))
            user_state.clear_state(user_id)
            return

        if message.content_type != 'text':
            msg = bot.send_message(user_id, "⚠️ Пожалуйста, введите название задания текстом.")
            bot.register_next_step_handler(msg, process_task_name)
            return

        task_name = message.text.strip()
        if not task_name:
            msg = bot.send_message(user_id, "⚠️ Название задания не может быть пустым. Введите название задания:")
            bot.register_next_step_handler(msg, process_task_name)
            return
        
        state_data['task_name'] = task_name
        user_state.set_state(user_id, 'waiting_for_task_description', state_data)
        
        msg = bot.send_message(user_id, "📄 Введите описание задания:")
        bot.register_next_step_handler(msg, process_task_description)
    except Exception as e:
        logger.error(f"Ошибка в process_task_name для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))

def process_task_description(message):
    """Обрабатывает ввод описания задания."""
    user_id = message.from_user.id
    state_data = user_state.get_state(user_id)['data']

    try:
        if message.text and message.text.lower() == "отмена":
            bot.send_message(user_id, "❌ Добавление задания отменено.", reply_markup=main_menu_markup(user_id))
            user_state.clear_state(user_id)
            return
        
        if message.content_type != 'text':
            msg = bot.send_message(user_id, "⚠️ Пожалуйста, введите описание задания текстом.")
            bot.register_next_step_handler(msg, process_task_description)
            return
            
        task_description = message.text.strip()
        if not task_description:
            msg = bot.send_message(user_id, "⚠️ Описание задания не может быть пустым. Введите описание задания:")
            bot.register_next_step_handler(msg, process_task_description)
            return
            
        state_data['task_description'] = task_description
        user_state.set_state(user_id, 'waiting_for_task_deadline', state_data)
        
        msg = bot.send_message(user_id, "📅 Введите дату выполнения (ДД.ММ.ГГГГ):\nПример: 31.12.2023")
        bot.register_next_step_handler(msg, process_task_deadline)
    except Exception as e:
        logger.error(f"Ошибка в process_task_description для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))

def process_task_deadline(message):
    """Обрабатывает ввод срока выполнения задания."""
    user_id = message.from_user.id
    state_data = user_state.get_state(user_id)['data']

    try:
        if message.text and message.text.lower() == "отмена":
            bot.send_message(user_id, "❌ Добавление задания отменено.", reply_markup=main_menu_markup(user_id))
            user_state.clear_state(user_id)
            return

        if message.content_type != 'text':
            msg = bot.send_message(user_id, "⚠️ Пожалуйста, введите дату текстом.")
            bot.register_next_step_handler(msg, process_task_deadline)
            return

        deadline = message.text.strip()
        try:
            # Проверяем только формат. Валидация, что дата в будущем, может быть добавлена
            datetime.strptime(deadline, "%d.%m.%Y") 
        except ValueError:
            msg = bot.send_message(user_id, "⚠️ Неверный формат даты. Используйте ДД.ММ.ГГГГ\nПример: 31.12.2023")
            bot.register_next_step_handler(msg, process_task_deadline)
            return
        
        # Сохраняем задание в БД
        cursor.execute(
            "INSERT INTO tasks (discipline_id, name, description, deadline, added_by) VALUES (?, ?, ?, ?, ?)",
            (state_data['discipline_id'], state_data['task_name'], 
             state_data['task_description'], deadline, user_id)
        )
        conn.commit()
        task_id = cursor.lastrowid
        log_action(user_id, f"Добавлено задание '{state_data['task_name']}' в дисциплину {state_data['discipline_id']}")
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add("✅ Да", "❌ Нет")
        
        msg = bot.send_message(
            user_id,
            "🖼 Хотите добавить фотографии к заданию?",
            reply_markup=markup
        )
        
        state_data['task_id'] = task_id
        user_state.set_state(user_id, 'waiting_for_photo_decision', state_data)
        bot.register_next_step_handler(msg, process_photo_decision)
    except Exception as e:
        logger.error(f"Ошибка в process_task_deadline для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))

def process_photo_decision(message):
    """Обрабатывает решение пользователя о добавлении фотографий."""
    user_id = message.from_user.id
    state_data = user_state.get_state(user_id)['data']
    task_id = state_data['task_id']
    
    try:
        if message.content_type != 'text' or message.text.lower() not in ["нет", "❌ нет", "да", "✅ да"]:
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            markup.add("✅ Да", "❌ Нет")
            msg = bot.send_message(user_id, "Пожалуйста, выберите вариант из предложенных: 'Да' или 'Нет'.\n🖼 Хотите добавить фотографии к заданию?", reply_markup=markup)
            bot.register_next_step_handler(msg, process_photo_decision)
            return

        if message.text.lower() in ["нет", "❌ нет"]:
            ask_for_solution(user_id, task_id)
            return
        
        if message.text.lower() in ["да", "✅ да"]:
            msg = bot.send_message(
                user_id,
                "📸 Отправьте фотографии для задания (можно несколько, по одной):",
                reply_markup=types.ReplyKeyboardRemove()
            )
            user_state.set_state(user_id, 'waiting_for_task_photos', state_data)
            bot.register_next_step_handler(msg, process_task_photos)
    except Exception as e:
        logger.error(f"Ошибка в process_photo_decision для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))

@bot.message_handler(content_types=['photo', 'text'], func=lambda m: user_state.get_state(m.from_user.id).get('state') in ['waiting_for_task_photos', 'waiting_for_more_photos'])
def process_task_photos(message):
    """Обрабатывает добавление фотографий к заданию и решение о добавлении большего количества."""
    user_id = message.from_user.id
    state_data = user_state.get_state(user_id)['data']
    
    try:
        task_id = state_data['task_id']
        
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id # Берем самое большое разрешение
            
            cursor.execute(
                "INSERT INTO photos (task_id, file_id) VALUES (?, ?)",
                (task_id, file_id)
            )
            conn.commit()
            log_action(user_id, f"Добавлена фотография к заданию {task_id}")
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            markup.add("✅ Готово", "➕ Добавить еще фото")
            
            msg = bot.send_message(
                user_id,
                "📸 Фото добавлено. Что дальше?",
                reply_markup=markup
            )
            
            user_state.set_state(user_id, 'waiting_for_more_photos', state_data)
            bot.register_next_step_handler(msg, process_task_photos) # Перерегистрируем на эту же функцию
            return
        
        elif message.content_type == 'text':
            if message.text.lower() in ["готово", "✅ готово"]:
                ask_for_solution(user_id, task_id)
                return
            
            if message.text.lower() in ["добавить еще фото", "➕ добавить еще фото"]:
                msg = bot.send_message(
                    user_id,
                    "📸 Отправьте следующую фотографию:",
                    reply_markup=types.ReplyKeyboardRemove()
                )
                user_state.set_state(user_id, 'waiting_for_task_photos', state_data)
                bot.register_next_step_handler(msg, process_task_photos) # Перерегистрируем на эту же функцию
                return
            else:
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
                markup.add("✅ Готово", "➕ Добавить еще фото")
                msg = bot.send_message(user_id, "Пожалуйста, выберите вариант из предложенных: 'Готово' или 'Добавить еще фото'.", reply_markup=markup)
                bot.register_next_step_handler(msg, process_task_photos)
                return
        else:
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            markup.add("✅ Готово", "➕ Добавить еще фото")
            msg = bot.send_message(user_id, "⚠️ Неизвестный тип сообщения. Пожалуйста, отправьте фото или выберите действие.", reply_markup=markup)
            bot.register_next_step_handler(msg, process_task_photos)
            return

    except Exception as e:
        logger.error(f"Ошибка в process_task_photos для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка при добавлении фото. Попробуйте позже.", reply_markup=main_menu_markup(user_id))

def ask_for_solution(user_id, task_id):
    """Спрашивает пользователя, хочет ли он добавить решение."""
    try:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add("✅ Да", "❌ Нет")
        
        msg = bot.send_message(
            user_id,
            "📝 Хотите добавить решение к заданию?",
            reply_markup=markup
        )
        
        user_state.set_state(user_id, 'waiting_for_solution_decision', {'task_id': task_id})
        bot.register_next_step_handler(msg, process_solution_decision)
    except Exception as e:
        logger.error(f"Ошибка в ask_for_solution для user_id={user_id}, task_id={task_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))

def process_solution_decision(message):
    """Обрабатывает решение пользователя о добавлении решения."""
    user_id = message.from_user.id
    state_data = user_state.get_state(user_id)['data']
    task_id = state_data['task_id']
    
    try:
        if message.content_type != 'text' or message.text.lower() not in ["нет", "❌ нет", "да", "✅ да"]:
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            markup.add("✅ Да", "❌ Нет")
            msg = bot.send_message(user_id, "Пожалуйста, выберите вариант из предложенных: 'Да' или 'Нет'.\n📝 Хотите добавить решение к заданию?", reply_markup=markup)
            bot.register_next_step_handler(msg, process_solution_decision)
            return

        if message.text.lower() in ["нет", "❌ нет"]:
            bot.send_message(
                user_id,
                "✅ Задание успешно сохранено!",
                reply_markup=main_menu_markup(user_id)
            )
            user_state.clear_state(user_id)
            log_action(user_id, f"Задание {task_id} сохранено без решения.")
            return
        
        if message.text.lower() in ["да", "✅ да"]:
            msg = bot.send_message(
                user_id,
                "📝 Введите решение задания:",
                reply_markup=types.ReplyKeyboardRemove()
            )
            user_state.set_state(user_id, 'waiting_for_solution_text', {'task_id': task_id})
            bot.register_next_step_handler(msg, process_task_solution)
    except Exception as e:
        logger.error(f"Ошибка в process_solution_decision для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))

def process_task_solution(message):
    """Обрабатывает ввод текста решения."""
    user_id = message.from_user.id
    state_data = user_state.get_state(user_id)['data']
    task_id = state_data['task_id']
    
    try:
        if message.content_type != 'text':
            msg = bot.send_message(user_id, "⚠️ Пожалуйста, введите решение задания текстом.")
            bot.register_next_step_handler(msg, process_task_solution)
            return

        solution_text = message.text.strip()
        if not solution_text:
            msg = bot.send_message(user_id, "⚠️ Решение не может быть пустым. Введите решение задания:")
            bot.register_next_step_handler(msg, process_task_solution)
            return

        cursor.execute(
            "INSERT INTO solutions (task_id, text, added_by) VALUES (?, ?, ?)",
            (task_id, solution_text, user_id)
        )
        conn.commit()
        log_action(user_id, f"Добавлено решение к заданию {task_id}.")
        
        bot.send_message(
            user_id,
            "✅ Задание и решение успешно сохранены!",
            reply_markup=main_menu_markup(user_id)
        )
        user_state.clear_state(user_id)
    except Exception as e:
        logger.error(f"Ошибка в process_task_solution для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))

# --- ОБРАБОТЧИКИ ПРОСМОТРА СПИСКОВ ---

@bot.message_handler(func=lambda message: message.text == "📚 Список дисциплин")
@private_only
def handle_show_disciplines(message):
    """Показывает список всех доступных дисциплин."""
    try:
        cursor.execute("SELECT name FROM disciplines ORDER BY name")
        disciplines = [d[0] for d in cursor.fetchall()]

        if not disciplines:
            bot.send_message(message.chat.id, "📭 Список дисциплин пуст.", reply_markup=main_menu_markup(message.from_user.id))
            return

        response_parts = []
        current_response = "📚 Доступные дисциплины:\n\n"
        for i, name in enumerate(disciplines):
            line = f"{i+1}. {name}\n"
            if len(current_response) + len(line) > 4000: # Проверка на лимит размера сообщения
                response_parts.append(current_response)
                current_response = line
            else:
                current_response += line
        response_parts.append(current_response) # Добавляем последнюю часть

        for part in response_parts:
            bot.send_message(
                message.chat.id,
                part,
                reply_markup=main_menu_markup(message.from_user.id)
            )
        log_action(message.from_user.id, "Просмотрен список дисциплин")

    except Exception as e:
        logger.error(f"Ошибка в handle_show_disciplines для user_id={message.from_user.id}: {e}", exc_info=True)
        bot.send_message(message.chat.id, "⚠️ Не удалось загрузить список дисциплин.", reply_markup=main_menu_markup(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == "📝 Список заданий")
@private_only
def handle_show_tasks(message):
    """Начинает процесс просмотра заданий, предлагая выбрать дисциплину."""
    user_state.clear_state(message.from_user.id) # Очищаем состояние
    show_disciplines_for_selection(message, 0, CB_PREFIX_DISC_TASKS_VIEW, CB_PREFIX_DISC_PAGE_VIEW, CB_BACK_TO_MAIN_MENU)

def show_disciplines_for_selection(message_obj, page, select_callback_prefix, page_callback_prefix, cancel_callback):
    """Показывает пагинированный список дисциплин для выбора.
    message_obj может быть как Message, так и CallbackQuery."""
    user_id = message_obj.from_user.id
    try:
        cursor.execute("SELECT id, name FROM disciplines ORDER BY name")
        disciplines = cursor.fetchall()
        
        total_pages = (len(disciplines) + MAX_BUTTONS_PER_PAGE - 1) // MAX_BUTTONS_PER_PAGE
        disciplines_page = disciplines[page*MAX_BUTTONS_PER_PAGE:(page+1)*MAX_BUTTONS_PER_PAGE]
        
        markup = types.InlineKeyboardMarkup()
        
        if not disciplines:
            text = "📭 Нет доступных дисциплин. Добавьте их через админ-панель."
            if hasattr(message_obj, 'message_id'): # Если это CallbackQuery
                _safe_edit_message(message_obj.chat.id, message_obj.message_id, text, reply_markup=main_menu_markup(user_id))
            else: # Если это Message
                bot.send_message(user_id, text, reply_markup=main_menu_markup(user_id))
            if hasattr(message_obj, 'id') and isinstance(message_obj, types.CallbackQuery):
                bot.answer_callback_query(message_obj.id)
            return
            
        for disc_id, disc_name in disciplines_page:
            markup.add(types.InlineKeyboardButton(
                text=disc_name,
                callback_data=f"{select_callback_prefix}{disc_id}"
            ))
        
        # Добавляем навигацию по страницам
        pagination_markup = _generate_pagination_markup(page, total_pages, page_callback_prefix)
        if pagination_markup.keyboard: # Если есть кнопки пагинации
            for row in pagination_markup.keyboard:
                markup.row(*row)
        
        markup.add(types.InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_callback))
        
        text = "📚 Выберите дисциплину:" + (f" (Страница {page+1}/{total_pages})" if total_pages > 1 else "")
        
        if hasattr(message_obj, 'message_id'): # Если это CallbackQuery
            if not _safe_edit_message(message_obj.chat.id, message_obj.message_id, text, reply_markup=markup):
                bot.send_message(user_id, text, reply_markup=markup)
        else: # Если это Message
            bot.send_message(user_id, text, reply_markup=markup)
    except Exception as e:
        logger.error(f"Ошибка в show_disciplines_for_selection для user_id={message_obj.from_user.id}, page={page}: {e}", exc_info=True)
        bot.send_message(message_obj.from_user.id, "⚠️ Ошибка загрузки дисциплин. Попробуйте позже.", reply_markup=main_menu_markup(message_obj.from_user.id))
    finally: # Answer the callback query regardless of success/failure
        if hasattr(message_obj, 'id') and isinstance(message_obj, types.CallbackQuery):
            bot.answer_callback_query(message_obj.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_DISC_TASKS_VIEW))
def show_tasks_for_discipline(call):
    """Показывает список заданий для выбранной дисциплины с пагинацией."""
    user_id = call.from_user.id
    data_parts = call.data.split(':')
    discipline_id = int(data_parts[1])
    page = int(data_parts[2]) if len(data_parts) > 2 else 0 # Для первоначального вызова без страницы

    discipline_info = _get_discipline_info(discipline_id)
    if not discipline_info:
        bot.answer_callback_query(call.id, "⚠️ Дисциплина не найдена.", show_alert=True)
        return
    discipline_name = discipline_info[0]
    
    try:
        # Получаем задания с пагинацией
        cursor.execute('''
            SELECT id, name, deadline 
            FROM tasks 
            WHERE discipline_id = ?
            ORDER BY deadline
            LIMIT ? OFFSET ?
        ''', (discipline_id, MAX_BUTTONS_PER_PAGE, page * MAX_BUTTONS_PER_PAGE))
        tasks = cursor.fetchall()
        
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE discipline_id = ?", (discipline_id,))
        total_tasks = cursor.fetchone()[0]
        total_pages = (total_tasks + MAX_BUTTONS_PER_PAGE - 1) // MAX_BUTTONS_PER_PAGE
        
        markup = types.InlineKeyboardMarkup()
        
        if not tasks:
            markup.add(types.InlineKeyboardButton(text="🔙 Назад к выбору дисциплины", callback_data=CB_BACK_TO_DISC_SELECTION_FOR_VIEW))
            if not _safe_edit_message(
                call.message.chat.id,
                call.message.message_id,
                text=f"📭 В дисциплине '{discipline_name}' нет заданий.",
                reply_markup=markup
            ):
                bot.send_message(call.message.chat.id, f"📭 В дисциплине '{discipline_name}' нет заданий.", reply_markup=markup)
            bot.answer_callback_query(call.id)
            return
        
        # Добавляем кнопки заданий
        for task_id, task_name, deadline in tasks:
            markup.add(types.InlineKeyboardButton(
                text=f"{task_name} (до {deadline})",
                callback_data=f"{CB_PREFIX_TASK_VIEW}{task_id}"
            ))
        
        # Добавляем навигацию
        pagination_markup = _generate_pagination_markup(page, total_pages, CB_PREFIX_DISC_TASKS_VIEW, discipline_id)
        if pagination_markup.keyboard:
            for row in pagination_markup.keyboard:
                markup.row(*row)
        
        markup.add(types.InlineKeyboardButton(
            text="🔙 Назад к выбору дисциплины", # Теперь ведет к списку дисциплин для просмотра
            callback_data=CB_BACK_TO_DISC_SELECTION_FOR_VIEW 
        ))
        
        if not _safe_edit_message(
            call.message.chat.id,
            call.message.message_id,
            text=f"📌 Задания по дисциплине '*{discipline_name}*':\n(Страница {page+1}/{total_pages})",
            reply_markup=markup,
            parse_mode='Markdown'
        ):
            bot.send_message(call.message.chat.id, f"📌 Задания по дисциплине '*{discipline_name}*':\n(Страница {page+1}/{total_pages})", reply_markup=markup, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"Ошибка в show_tasks_for_discipline для user_id={user_id}, disc_id={discipline_id}, page={page}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Ошибка при загрузке заданий. Попробуйте позже.", reply_markup=main_menu_markup(user_id))
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_TASK_VIEW))
def view_task_details(call):
    """Показывает детали выбранного задания."""
    user_id = call.from_user.id
    task_id = int(call.data.split(':')[1])
    
    task_info = _get_task_info(task_id)
    if not task_info:
        bot.answer_callback_query(call.id, "⚠️ Задание не найдено.", show_alert=True)
        return
    
    task_name, description, deadline, discipline_name, discipline_id = task_info
    
    try:
        # Получаем фотографии для задания
        cursor.execute("SELECT file_id FROM photos WHERE task_id = ?", (task_id,))
        photos = cursor.fetchall()
        
        # Получаем решение для задания
        cursor.execute("SELECT text FROM solutions WHERE task_id = ?", (task_id,))
        solution = cursor.fetchone()
        
        # Формируем сообщение с информацией о задании
        response = f"📌 <b>{task_name}</b>\n"
        response += f"📚 Дисциплина: {discipline_name}\n"
        response += f"📅 Срок выполнения: {deadline}\n\n"
        response += f"📄 Описание:\n{description}\n\n"
        
        if solution:
            response += f"📝 Решение:\n{solution[0]}\n\n"
        
        if photos:
            response += f"🖼 Прикреплено фотографий: {len(photos)}"
        
        # Создаем клавиатуру
        markup = types.InlineKeyboardMarkup()
        
        # Кнопка для просмотра фотографий, если они есть
        if photos:
            markup.add(types.InlineKeyboardButton(
                text="🖼 Просмотреть фотографии",
                callback_data=f"{CB_PREFIX_PHOTO_NAV}{task_id}:0" # Индекс первой фотографии
            ))
        
        markup.add(types.InlineKeyboardButton(
            text="🔙 Назад к заданиям дисциплины",
            callback_data=f"{CB_PREFIX_BACK_TO_DISC_TASKS_VIEW}{discipline_id}"
        ))
        
        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=response,
            reply_markup=markup,
            parse_mode='HTML'
        ):
            bot.send_message(call.message.chat.id, response, reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"Ошибка в view_task_details для user_id={user_id}, task_id={task_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

def send_photo_with_navigation(chat_id, message_id, photos, current_index, task_id):
    """Отправляет или редактирует сообщение с фотографией и кнопками навигации."""
    try:
        markup = types.InlineKeyboardMarkup()
        
        # Кнопки навигации по фото
        if len(photos) > 1:
            row_buttons = []
            if current_index > 0:
                row_buttons.append(types.InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"{CB_PREFIX_PHOTO_NAV}{task_id}:{current_index-1}"
                ))
            if current_index < len(photos) - 1:
                row_buttons.append(types.InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"{CB_PREFIX_PHOTO_NAV}{task_id}:{current_index+1}"
                ))
            markup.row(*row_buttons)
        
        markup.add(types.InlineKeyboardButton(
            text="🔙 Назад к заданию",
            callback_data=f"{CB_PREFIX_BACK_TO_TASK}{task_id}"
        ))
        
        # Отправляем/редактируем сообщение с фотографией
        media = types.InputMediaPhoto(
            media=photos[current_index][0],
            caption=f"🖼 Фото {current_index+1} из {len(photos)}"
        )
        
        if message_id:
            try:
                bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id,
                    media=media,
                    reply_markup=markup
                )
            except telebot.apihelper.ApiTelegramException as e:
                # Если редактирование медиа не удалось, возможно, сообщение было удалено или слишком старое
                logger.warning(f"Failed to edit message media {message_id} in chat {chat_id}: {e}. Attempting to send new photo message.")
                bot.send_photo(
                    chat_id=chat_id,
                    photo=photos[current_index][0],
                    caption=f"🖼 Фото {current_index+1} из {len(photos)}",
                    reply_markup=markup
                )
        else:
            bot.send_photo(
                chat_id=chat_id,
                photo=photos[current_index][0],
                caption=f"🖼 Фото {current_index+1} из {len(photos)}",
                reply_markup=markup
            )
    except Exception as e:
        logger.error(f"Ошибка в send_photo_with_navigation для task_id={task_id}, photo_index={current_index}: {e}", exc_info=True)
        bot.send_message(chat_id, "⚠️ Произошла ошибка при загрузке фото. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_PHOTO_NAV))
def handle_photo_navigation(call):
    """Обрабатывает навигацию по фотографиям задания."""
    user_id = call.from_user.id
    _, task_id, photo_index = call.data.split(':')
    task_id = int(task_id)
    photo_index = int(photo_index)
    
    try:
        cursor.execute("SELECT file_id FROM photos WHERE task_id = ?", (task_id,))
        photos = cursor.fetchall()
        
        if not photos:
            bot.answer_callback_query(call.id, "⚠️ Нет фотографий для этого задания.", show_alert=True)
            return
        
        if photo_index < 0 or photo_index >= len(photos):
            bot.answer_callback_query(call.id, "⚠️ Достигнут конец списка фотографий.", show_alert=True)
            return
        
        send_photo_with_navigation(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            photos=photos,
            current_index=photo_index,
            task_id=task_id
        )
        bot.answer_callback_query(call.id) # Отвечаем на колбэк
    except Exception as e:
        logger.error(f"Ошибка в handle_photo_navigation для user_id={user_id}, task_id={task_id}, photo_index={photo_index}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

# --- ОБРАБОТЧИКИ НАВИГАЦИОННЫХ КНОПОК ---

@bot.callback_query_handler(func=lambda call: call.data == CB_CANCEL)
def handle_cancel(call):
    """Обрабатывает общую кнопку отмены."""
    user_id = call.from_user.id
    try:
        _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ Действие отменено."
        )
        bot.send_message(user_id, "Выберите действие:", reply_markup=main_menu_markup(user_id))
        user_state.clear_state(user_id)
        bot.answer_callback_query(call.id) # Отвечаем на колбэк
    except Exception as e:
        logger.error(f"Ошибка в handle_cancel для user_id={user_id}: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "⚠️ Ошибка при отмене действия.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_DISC_PAGE_ADD))
def handle_disc_page_add(call):
    """Обрабатывает пагинацию при выборе дисциплины для добавления задания."""
    page = int(call.data.split(':')[1])
    show_disciplines_for_selection(call.message, page, CB_PREFIX_DISC_SELECT, CB_PREFIX_DISC_PAGE_ADD, CB_CANCEL)
    # bot.answer_callback_query(call.id) # Handled inside show_disciplines_for_selection

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_DISC_PAGE_VIEW))
def handle_disc_page_view(call):
    """Обрабатывает пагинацию при выборе дисциплины для просмотра заданий."""
    page = int(call.data.split(':')[1])
    show_disciplines_for_selection(call.message, page, CB_PREFIX_DISC_TASKS_VIEW, CB_PREFIX_DISC_PAGE_VIEW, CB_BACK_TO_MAIN_MENU)
    # bot.answer_callback_query(call.id) # Handled inside show_disciplines_for_selection

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_BACK_TO_DISC_TASKS_VIEW))
def handle_back_to_discipline_tasks_view(call):
    """Возвращает к списку заданий для конкретной дисциплины при просмотре."""
    user_id = call.from_user.id
    discipline_id = int(call.data.split(':')[1])

    try:
        # Для простоты, вернемся на первую страницу заданий этой дисциплины
        call.data = f"{CB_PREFIX_DISC_TASKS_VIEW}{discipline_id}:0" 
        show_tasks_for_discipline(call)
        # bot.answer_callback_query(call.id) # Handled inside show_tasks_for_discipline
    except Exception as e:
        logger.error(f"Ошибка при возврате к заданиям дисциплины {discipline_id} для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Ошибка при возврате к списку заданий. Попробуйте позже.", reply_markup=main_menu_markup(user_id))
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data == CB_BACK_TO_DISC_SELECTION_FOR_VIEW)
def handle_back_to_disc_selection_for_view(call):
    """Возвращает к списку дисциплин для выбора просмотра заданий."""
    user_id = call.from_user.id
    try:
        show_disciplines_for_selection(call.message, 0, CB_PREFIX_DISC_TASKS_VIEW, CB_PREFIX_DISC_PAGE_VIEW, CB_BACK_TO_MAIN_MENU)
        # bot.answer_callback_query(call.id) # Handled inside show_disciplines_for_selection
    except Exception as e:
        logger.error(f"Error in handle_back_to_disc_selection_for_view for user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_BACK_TO_TASK))
def handle_back_to_task(call):
    """Возвращает к деталям задания из просмотра фото."""
    user_id = call.from_user.id
    task_id = int(call.data.split(':')[1])
    
    try:
        call.data = f"{CB_PREFIX_TASK_VIEW}{task_id}"
        view_task_details(call)
        # bot.answer_callback_query(call.id) # Handled inside view_task_details
    except Exception as e:
        logger.error(f"Ошибка в handle_back_to_task для user_id={user_id}, task_id={task_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data == CB_BACK_TO_MAIN_MENU)
def handle_back_to_main_menu_callback(call):
    """Обрабатывает колбэк для возврата в главное меню."""
    user_id = call.from_user.id
    try:
        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Главное меню:",
            reply_markup=main_menu_markup(user_id)
        ):
            bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=main_menu_markup(user_id))
        user_state.clear_state(user_id)
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка в handle_back_to_main_menu_callback для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=main_menu_markup(user_id))
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")


# --- АДМИНИСТРАТИВНЫЕ ФУНКЦИИ ---

@bot.message_handler(func=lambda message: message.text == "👑 Админ-панель")
@private_only
@admin_only
def handle_admin_panel(message):
    """Показывает админ-панель."""
    try:
        user_state.clear_state(message.from_user.id) # Очищаем состояние при входе в админку
        bot.send_message(message.chat.id, "👑 Админ-панель:", reply_markup=admin_panel_markup())
        log_action(message.from_user.id, "Вошел в админ-панель")
    except Exception as e:
        logger.error(f"Ошибка в handle_admin_panel для user_id={message.from_user.id}: {e}", exc_info=True)
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.")

@bot.message_handler(func=lambda message: message.text == "🔙 Назад" and message.chat.type == 'private')
@private_only
@admin_only
def handle_back_from_admin_menus(message):
    """Обработчик кнопки 'Назад' из админских подменю (ReplyKeyboard).
    Ведет из 'Управление дисциплинами' в 'Админ-панель'."""
    try:
        user_state.clear_state(message.from_user.id) # Всегда очищаем состояние
        bot.send_message(message.chat.id, "👑 Админ-панель:", reply_markup=admin_panel_markup())
        log_action(message.from_user.id, "Нажал 'Назад' из меню управления дисциплинами")
    except Exception as e:
        logger.error(f"Ошибка в handle_back_from_admin_menus для user_id={message.from_user.id}: {e}", exc_info=True)
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=admin_panel_markup())

@bot.callback_query_handler(func=lambda call: call.data == CB_BACK_TO_ADMIN_PANEL)
def handle_back_to_admin_panel_callback(call):
    """Обрабатывает колбэк для возврата в админ-панель."""
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔ У вас нет прав.", show_alert=True)
        return

    try:
        user_state.clear_state(user_id) # Очищаем состояние
        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="👑 Админ-панель:",
            reply_markup=admin_panel_markup()
        ):
            bot.send_message(call.message.chat.id, "👑 Админ-панель:", reply_markup=admin_panel_markup())
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка в handle_back_to_admin_panel_callback для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=admin_panel_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

# --- АДМИН: ЛОГИ И СТАТИСТИКА ---

@bot.message_handler(func=lambda message: message.text == "📊 Просмотреть логи")
@private_only
@admin_only
def handle_view_logs(message):
    """Показывает последние записи в логах."""
    try:
        cursor.execute("SELECT logs.timestamp, users.username, users.first_name, users.last_name, logs.action FROM logs LEFT JOIN users ON logs.user_id = users.user_id ORDER BY logs.timestamp DESC LIMIT ?", (MAX_LOG_ENTRIES,))
        logs = cursor.fetchall()
        
        if not logs:
            bot.send_message(message.chat.id, "📭 Логи пусты.")
            return
        
        response = "📜 Последние действия:\n\n"
        for log_entry in logs:
            timestamp, username, first_name, last_name, action = log_entry
            name_display = f"{first_name} {last_name}" if first_name and last_name else (first_name if first_name else "")
            user_display = f"@{username}" if username else (name_display if name_display else "Неизвестный пользователь")
            response += f"⏰ {timestamp}\n👤 {user_display}\n🔹 {action}\n\n"
        
        # Разбиваем на части, если сообщение слишком длинное
        for i in range(0, len(response), 4000):
            bot.send_message(message.chat.id, response[i:i+4000])
        log_action(message.from_user.id, "Просмотрел логи")
    except Exception as e:
        logger.error(f"Ошибка в view_logs для user_id={message.from_user.id}: {e}", exc_info=True)
        bot.send_message(message.chat.id, "⚠️ Ошибка загрузки логов. Попробуйте позже.", reply_markup=admin_panel_markup())

@bot.message_handler(func=lambda message: message.text == "👥 Статистика пользователей")
@private_only
@admin_only
def handle_user_stats(message):
    """Показывает статистику пользователей."""
    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT user_id, COUNT(*) FROM logs GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 10")
        active_users = cursor.fetchall()

        response = f"📊 Статистика пользователей:\n\n"
        response += f"👥 Всего пользователей: {total_users}\n\n"
        response += "🏆 Топ-10 активных пользователей:\n"

        for i, (user_id, count) in enumerate(active_users, 1):
            cursor.execute("SELECT username, first_name, last_name FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
            if user:
                username, first_name, last_name = user
                name = f"{first_name} {last_name}" if last_name else first_name
                response += f"{i}. {name} (@{username if username else 'нет'}) - {count} действий\n"
            else:
                response += f"{i}. ID: {user_id} - {count} действий\n"

        bot.send_message(message.chat.id, response)
        log_action(message.from_user.id, "Просмотрел статистику пользователей")
    except Exception as e:
        logger.error(f"Ошибка в handle_user_stats для user_id={message.from_user.id}: {e}", exc_info=True)
        bot.send_message(message.chat.id, "⚠️ Ошибка загрузки статистики. Попробуйте позже.", reply_markup=admin_panel_markup())

@bot.message_handler(func=lambda message: message.text == "📋 Список всех пользователей")
@private_only
@admin_only
def handle_view_all_users(message):
    """Показывает список всех пользователей с пагинацией."""
    view_all_users(message, 0) # Начинаем с первой страницы

def view_all_users(message_obj, page):
    """Отображает список всех пользователей с пагинацией.
    message_obj может быть как Message, так и CallbackQuery."""
    user_id = message_obj.from_user.id
    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("""
            SELECT user_id, username, first_name, last_name, join_date, is_admin
            FROM users 
            ORDER BY join_date DESC 
            LIMIT ? OFFSET ?
        """, (MAX_BUTTONS_PER_PAGE, page * MAX_BUTTONS_PER_PAGE))
        users = cursor.fetchall()

        total_pages = (total_users + MAX_BUTTONS_PER_PAGE - 1) // MAX_BUTTONS_PER_PAGE
        
        response = f"📋 Список пользователей (Страница {page+1}/{total_pages}):\n\n"
        
        if not users:
            response = "📭 Нет зарегистрированных пользователей."

        for user_data in users:
            user_id, username, first_name, last_name, join_date, is_admin_flag = user_data
            name_display = f"{first_name} {last_name}" if first_name and last_name else (first_name if first_name else "Без имени")
            admin_status = " (Админ)" if is_admin_flag else ""
            response += f"👤 {name_display}{admin_status}\n"
            response += f"🆔 ID: {user_id}\n"
            response += f"📧 @{username if username else 'нет'}\n"
            response += f"📅 Регистрация: {join_date}\n\n"

        markup = _generate_pagination_markup(page, total_pages, CB_PREFIX_USERS_PAGE)
        markup.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data=CB_BACK_TO_ADMIN_PANEL))

        if hasattr(message_obj, 'message_id'):
            if not _safe_edit_message(message_obj.chat.id, message_obj.message_id, response, reply_markup=markup):
                bot.send_message(user_id, response, reply_markup=markup)
        else:
            bot.send_message(user_id, response, reply_markup=markup)
            
    except Exception as e:
        logger.error(f"Ошибка в view_all_users для user_id={user_id}, page={page}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Ошибка загрузки пользователей. Попробуйте позже.", reply_markup=admin_panel_markup())
    finally:
        if hasattr(message_obj, 'id') and isinstance(message_obj, types.CallbackQuery):
            bot.answer_callback_query(message_obj.id, "⚠️ Ошибка." if 'e' in locals() else None) # Answer with alert on error


@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_USERS_PAGE))
def handle_users_page(call):
    """Обрабатывает пагинацию списка пользователей."""
    page = int(call.data.split(':')[1])
    view_all_users(call.message, page)
    # bot.answer_callback_query(call.id) # Handled in view_all_users

# --- АДМИН: УПРАВЛЕНИЕ ЗАДАНИЯМИ ---

@bot.message_handler(func=lambda message: message.text == "📌 Управление заданиями")
@private_only
@admin_only
def handle_manage_tasks(message):
    """Показывает список дисциплин для управления заданиями."""
    user_state.clear_state(message.from_user.id) # Очищаем состояние
    manage_tasks_disciplines_step(message, 0)

def manage_tasks_disciplines_step(message_obj, page):
    """Отображает пагинированный список дисциплин для выбора управления заданиями.
    message_obj может быть как Message, так и CallbackQuery."""
    user_id = message_obj.from_user.id
    try:
        cursor.execute("SELECT id, name FROM disciplines ORDER BY name")
        disciplines = cursor.fetchall()

        total_pages = (len(disciplines) + MAX_BUTTONS_PER_PAGE - 1) // MAX_BUTTONS_PER_PAGE
        disciplines_page = disciplines[page*MAX_BUTTONS_PER_PAGE:(page+1)*MAX_BUTTONS_PER_PAGE]

        markup = types.InlineKeyboardMarkup()
        
        if not disciplines:
            text = "📭 Нет доступных дисциплин."
            if hasattr(message_obj, 'message_id'):
                _safe_edit_message(message_obj.chat.id, message_obj.message_id, text, reply_markup=admin_panel_markup())
            else:
                bot.send_message(user_id, text, reply_markup=admin_panel_markup())
            if hasattr(message_obj, 'id') and isinstance(message_obj, types.CallbackQuery):
                bot.answer_callback_query(message_obj.id)
            return

        for disc_id, disc_name in disciplines_page:
            markup.add(types.InlineKeyboardButton(
                text=f"📌 {disc_name}",
                callback_data=f"{CB_PREFIX_MANAGE_TASKS_DISC}{disc_id}"
            ))

        pagination_markup = _generate_pagination_markup(page, total_pages, CB_PREFIX_MANAGE_TASKS_PAGE)
        if pagination_markup.keyboard:
            for row in pagination_markup.keyboard:
                markup.row(*row)

        markup.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data=CB_BACK_TO_ADMIN_PANEL))

        text = "📌 Выберите дисциплину для управления заданиями:" + (f" (Страница {page+1}/{total_pages})" if total_pages > 1 else "")
        if hasattr(message_obj, 'message_id'):
            if not _safe_edit_message(message_obj.chat.id, message_obj.message_id, text, reply_markup=markup):
                bot.send_message(user_id, text, reply_markup=markup)
        else:
            bot.send_message(user_id, text, reply_markup=markup)
            
    except Exception as e:
        logger.error(f"Ошибка в manage_tasks_disciplines_step для user_id={user_id}, page={page}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Ошибка загрузки дисциплин. Попробуйте позже.", reply_markup=admin_panel_markup())
    finally:
        if hasattr(message_obj, 'id') and isinstance(message_obj, types.CallbackQuery):
            bot.answer_callback_query(message_obj.id, "⚠️ Ошибка." if 'e' in locals() else None)

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_MANAGE_TASKS_PAGE))
def handle_manage_tasks_page(call):
    """Обрабатывает пагинацию при выборе дисциплины для управления заданиями."""
    page = int(call.data.split(':')[1])
    manage_tasks_disciplines_step(call.message, page)
    # bot.answer_callback_query(call.id) # Handled in manage_tasks_disciplines_step

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_MANAGE_TASKS_DISC))
def show_tasks_for_management(call):
    """Показывает список заданий выбранной дисциплины для управления (удаления)."""
    user_id = call.from_user.id
    discipline_id = int(call.data.split(':')[1])

    discipline_info = _get_discipline_info(discipline_id)
    if not discipline_info:
        bot.answer_callback_query(call.id, "⚠️ Дисциплина не найдена.", show_alert=True)
        return
    discipline_name = discipline_info[0]

    try:
        cursor.execute("""
            SELECT id, name, deadline 
            FROM tasks 
            WHERE discipline_id = ?
            ORDER BY deadline
        """, (discipline_id,))
        tasks = cursor.fetchall()

        markup = types.InlineKeyboardMarkup()
        if not tasks:
            markup.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data=CB_BACK_TO_MANAGE_TASKS))
            if not _safe_edit_message(
                call.message.chat.id,
                call.message.message_id,
                text=f"📭 В дисциплине '{discipline_name}' нет заданий для управления.",
                reply_markup=markup
            ):
                bot.send_message(call.message.chat.id, f"📭 В дисциплине '{discipline_name}' нет заданий для управления.", reply_markup=markup)
            bot.answer_callback_query(call.id)
            return

        for task_id, task_name, deadline in tasks:
            markup.add(types.InlineKeyboardButton(
                text=f"❌ Удалить: {task_name} (до {deadline})",
                callback_data=f"{CB_PREFIX_ADMIN_DELETE_TASK}{task_id}"
            ))

        markup.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data=CB_BACK_TO_MANAGE_TASKS))
        
        if not _safe_edit_message(
            call.message.chat.id,
            call.message.message_id,
            text=f"📌 Задания дисциплины '*{discipline_name}*':",
            reply_markup=markup,
            parse_mode="Markdown"
        ):
            bot.send_message(call.message.chat.id, f"📌 Задания дисциплины '*{discipline_name}*':", reply_markup=markup, parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка в show_tasks_for_management для user_id={user_id}, disc_id={discipline_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=admin_panel_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_ADMIN_DELETE_TASK))
def admin_delete_task_confirm_step(call):
    """Запрашивает подтверждение удаления задания."""
    user_id = call.from_user.id
    task_id = int(call.data.split(':')[1])

    task_info = _get_task_info(task_id)
    if not task_info:
        bot.answer_callback_query(call.id, "⚠️ Задание не найдено.", show_alert=True)
        return
    task_name, _, _, discipline_name, discipline_id = task_info

    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"{CB_PREFIX_CONFIRM_DELETE_TASK}{task_id}:{discipline_id}"))
        markup.add(types.InlineKeyboardButton(text="❌ Нет, отмена", callback_data=f"{CB_PREFIX_CANCEL_DELETE_TASK}{task_id}:{discipline_id}"))

        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"⚠️ Вы уверены, что хотите удалить задание:\n\n📌 *{task_name}*\n📚 *{discipline_name}*?",
            reply_markup=markup,
            parse_mode="Markdown"
        ):
            bot.send_message(call.message.chat.id, f"⚠️ Вы уверены, что хотите удалить задание:\n\n📌 *{task_name}*\n📚 *{discipline_name}*?", reply_markup=markup, parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка в admin_delete_task_confirm_step для user_id={user_id}, task_id={task_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=admin_panel_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_CONFIRM_DELETE_TASK))
def confirm_delete_task(call):
    """Выполняет удаление задания после подтверждения."""
    user_id = call.from_user.id
    _, task_id, discipline_id = call.data.split(':')
    task_id = int(task_id)
    discipline_id = int(discipline_id)

    try:
        cursor.execute("DELETE FROM photos WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM solutions WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        log_action(user_id, f"Удалено задание {task_id}.")

        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ Задание успешно удалено!"
        ):
            bot.send_message(call.message.chat.id, "✅ Задание успешно удалено!")
        # Возвращаем к списку заданий в этой дисциплине
        call.data = f"{CB_PREFIX_MANAGE_TASKS_DISC}{discipline_id}"
        show_tasks_for_management(call) # Передаем call, чтобы он мог быть отредактирован
        # bot.answer_callback_query(call.id) # Handled in show_tasks_for_management
    except Exception as e:
        logger.error(f"Ошибка в confirm_delete_task для user_id={user_id}, task_id={task_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка при удалении задания.", reply_markup=admin_panel_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_CANCEL_DELETE_TASK))
def cancel_delete_task(call):
    """Отменяет удаление задания."""
    user_id = call.from_user.id
    _, task_id, discipline_id = call.data.split(':')
    discipline_id = int(discipline_id)
    
    try:
        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ Удаление задания отменено."
        ):
            bot.send_message(call.message.chat.id, "❌ Удаление задания отменено.")
        # Возвращаем к списку заданий в этой дисциплине
        call.data = f"{CB_PREFIX_MANAGE_TASKS_DISC}{discipline_id}"
        show_tasks_for_management(call) # Передаем call, чтобы он мог быть отредактирован
        # bot.answer_callback_query(call.id) # Handled in show_tasks_for_management
    except Exception as e:
        logger.error(f"Ошибка в cancel_delete_task для user_id={user_id}, task_id={task_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=admin_panel_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data == CB_BACK_TO_MANAGE_TASKS)
def handle_back_to_manage_tasks_callback(call):
    """Обрабатывает колбэк для возврата к выбору дисциплин для управления заданиями."""
    user_id = call.from_user.id
    manage_tasks_disciplines_step(call.message, 0) # Возвращаемся на первую страницу
    # bot.answer_callback_query(call.id) # Handled in manage_tasks_disciplines_step

# --- АДМИН: УПРАВЛЕНИЕ ДИСЦИПЛИНАМИ ---

@bot.message_handler(func=lambda message: message.text == "📚 Управление дисциплинами")
@private_only
@admin_only
def handle_manage_disciplines(message):
    """Показывает меню управления дисциплинами."""
    try:
        user_state.clear_state(message.from_user.id) # Очищаем состояние при входе
        bot.send_message(message.chat.id, "📚 Управление дисциплинами:", reply_markup=manage_disciplines_markup())
        log_action(message.from_user.id, "Вошел в управление дисциплинами")
    except Exception as e:
        logger.error(f"Ошибка в handle_manage_disciplines для user_id={message.from_user.id}: {e}", exc_info=True)
        bot.send_message(message.chat.id, "⚠️ Ошибка загрузки меню. Попробуйте позже.", reply_markup=admin_panel_markup())

@bot.message_handler(func=lambda message: message.text == "➕ Добавить дисциплину")
@private_only
@admin_only
def handle_add_discipline(message):
    """Начинает процесс добавления новой дисциплины."""
    try:
        msg = bot.send_message(
            message.from_user.id,
            "📝 Введите название новой дисциплины (для отмены напишите 'отмена'):",
            reply_markup=types.ReplyKeyboardRemove()
        )
        user_state.set_state(message.from_user.id, 'waiting_for_new_discipline_name')
        bot.register_next_step_handler(msg, process_new_discipline)
    except Exception as e:
        logger.error(f"Ошибка в handle_add_discipline для user_id={message.from_user.id}: {e}", exc_info=True)
        bot.send_message(message.from_user.id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=manage_disciplines_markup())

def process_new_discipline(message):
    """Обрабатывает ввод названия новой дисциплины."""
    user_id = message.from_user.id
    try:
        if message.text and message.text.lower() == "отмена":
            bot.send_message(user_id, "❌ Добавление дисциплины отменено.", reply_markup=manage_disciplines_markup())
            user_state.clear_state(user_id)
            return

        if message.content_type != 'text':
            msg = bot.send_message(user_id, "⚠️ Пожалуйста, введите название дисциплины текстом.")
            bot.register_next_step_handler(msg, process_new_discipline)
            return

        discipline_name = message.text.strip()
        if not discipline_name:
            msg = bot.send_message(user_id, "⚠️ Название дисциплины не может быть пустым. Введите название новой дисциплины:")
            bot.register_next_step_handler(msg, process_new_discipline)
            return
        
        try:
            cursor.execute("INSERT INTO disciplines (name) VALUES (?)", (discipline_name,))
            conn.commit()
            bot.send_message(
                user_id,
                f"✅ Дисциплина '{discipline_name}' успешно добавлена!",
                reply_markup=manage_disciplines_markup()
            )
            log_action(user_id, f"Добавлена дисциплина '{discipline_name}'")
            user_state.clear_state(user_id)
        except sqlite3.IntegrityError:
            bot.send_message(
                user_id,
                f"⚠️ Дисциплина с названием '{discipline_name}' уже существует! Попробуйте другое имя.",
                reply_markup=manage_disciplines_markup()
            )
            user_state.clear_state(user_id)
        except Exception as e:
            logger.error(f"Ошибка при добавлении дисциплины '{discipline_name}' для user_id={user_id}: {e}", exc_info=True)
            bot.send_message(user_id, "⚠️ Произошла ошибка при добавлении дисциплины. Пожалуйста, попробуйте позже.", reply_markup=manage_disciplines_markup())
            user_state.clear_state(user_id)
    except Exception as e:
        logger.error(f"Ошибка в process_new_discipline для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=manage_disciplines_markup())


@bot.message_handler(func=lambda message: message.text == "➖ Удалить дисциплину")
@private_only
@admin_only
def handle_delete_discipline(message):
    """Начинает процесс удаления дисциплины."""
    user_state.clear_state(message.from_user.id) # Очищаем состояние
    delete_discipline_step1(message, 0)

def delete_discipline_step1(message_obj, page):
    """Отображает список дисциплин для удаления с пагинацией.
    message_obj может быть как Message, так и CallbackQuery."""
    user_id = message_obj.from_user.id
    try:
        cursor.execute("SELECT id, name FROM disciplines ORDER BY name")
        disciplines = cursor.fetchall()
        
        total_pages = (len(disciplines) + MAX_BUTTONS_PER_PAGE - 1) // MAX_BUTTONS_PER_PAGE
        disciplines_page = disciplines[page*MAX_BUTTONS_PER_PAGE:(page+1)*MAX_BUTTONS_PER_PAGE]
        
        markup = types.InlineKeyboardMarkup()

        if not disciplines:
            text = "📭 Нет доступных дисциплин для удаления."
            if hasattr(message_obj, 'message_id'):
                _safe_edit_message(message_obj.chat.id, message_obj.message_id, text, reply_markup=manage_disciplines_markup())
            else:
                bot.send_message(user_id, text, reply_markup=manage_disciplines_markup())
            if hasattr(message_obj, 'id') and isinstance(message_obj, types.CallbackQuery):
                bot.answer_callback_query(message_obj.id)
            return
            
        for disc_id, disc_name in disciplines_page:
            markup.add(types.InlineKeyboardButton(
                text=f"❌ {disc_name}",
                callback_data=f"{CB_PREFIX_DELETE_DISC}{disc_id}"
            ))
        
        pagination_markup = _generate_pagination_markup(page, total_pages, CB_PREFIX_DELETE_DISC_PAGE)
        if pagination_markup.keyboard:
            for row in pagination_markup.keyboard:
                markup.row(*row)
        
        markup.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data=CB_BACK_TO_MANAGE_DISCIPLINES))
        
        text = "📚 Выберите дисциплину для удаления:" + (f" (Страница {page+1}/{total_pages})" if total_pages > 1 else "")
        if hasattr(message_obj, 'message_id'):
            if not _safe_edit_message(message_obj.chat.id, message_obj.message_id, text, reply_markup=markup):
                bot.send_message(user_id, text, reply_markup=markup)
        else:
            bot.send_message(user_id, text, reply_markup=markup)

    except Exception as e:
        logger.error(f"Ошибка в delete_discipline_step1 для user_id={user_id}, page={page}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Ошибка загрузки дисциплин. Попробуйте позже.", reply_markup=manage_disciplines_markup())
    finally:
        if hasattr(message_obj, 'id') and isinstance(message_obj, types.CallbackQuery):
            bot.answer_callback_query(message_obj.id, "⚠️ Ошибка." if 'e' in locals() else None)

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_DELETE_DISC_PAGE))
def handle_delete_disc_page(call):
    """Обрабатывает пагинацию при выборе дисциплины для удаления."""
    page = int(call.data.split(':')[1])
    delete_discipline_step1(call.message, page)
    # bot.answer_callback_query(call.id) # Handled in delete_discipline_step1

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_DELETE_DISC))
def delete_discipline_step2(call):
    """Запрашивает подтверждение удаления дисциплины."""
    user_id = call.from_user.id
    discipline_id = int(call.data.split(':')[1])
    
    discipline_info = _get_discipline_info(discipline_id)
    if not discipline_info:
        bot.answer_callback_query(call.id, "⚠️ Дисциплина не найдена.", show_alert=True)
        return
    discipline_name = discipline_info[0]

    try:
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE discipline_id = ?", (discipline_id,))
        task_count = cursor.fetchone()[0]
        
        markup = types.InlineKeyboardMarkup()
        if task_count > 0:
            markup.add(types.InlineKeyboardButton(text="✅ Да, удалить с заданиями", callback_data=f"{CB_PREFIX_CONFIRM_DELETE_DISC_W_TASKS}{discipline_id}"))
            markup.add(types.InlineKeyboardButton(text="❌ Нет, отмена", callback_data=f"{CB_PREFIX_CANCEL_DELETE_DISC}{discipline_id}"))
            text = f"⚠️ В дисциплине '*{discipline_name}*' есть {task_count} заданий. Удалить вместе с ними?"
        else:
            markup.add(types.InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"{CB_PREFIX_CONFIRM_DELETE_DISC}{discipline_id}"))
            markup.add(types.InlineKeyboardButton(text="❌ Нет, отмена", callback_data=f"{CB_PREFIX_CANCEL_DELETE_DISC}{discipline_id}"))
            text = f"⚠️ Вы уверены, что хотите удалить дисциплину '*{discipline_name}*'?"
            
        if not _safe_edit_message(call.message.chat.id, call.message.message_id, text, reply_markup=markup, parse_mode="Markdown"):
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка в delete_discipline_step2 для user_id={user_id}, disc_id={discipline_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=manage_disciplines_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_CONFIRM_DELETE_DISC) and not call.data.startswith(CB_PREFIX_CONFIRM_DELETE_DISC_W_TASKS))
def confirm_delete_discipline(call):
    """Выполняет удаление дисциплины без заданий."""
    user_id = call.from_user.id
    discipline_id = int(call.data.split(':')[1])
    
    try:
        cursor.execute("DELETE FROM disciplines WHERE id = ?", (discipline_id,))
        conn.commit()
        log_action(user_id, f"Удалена дисциплина {discipline_id} (без заданий).")
        
        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ Дисциплина успешно удалена!"
        ):
            bot.send_message(call.message.chat.id, "✅ Дисциплина успешно удалена!")
        delete_discipline_step1(call.message, 0) # Обновляем список дисциплин
        # bot.answer_callback_query(call.id) # Handled in delete_discipline_step1
    except Exception as e:
        logger.error(f"Ошибка в confirm_delete_discipline для user_id={user_id}, disc_id={discipline_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка при удалении дисциплины.", reply_markup=manage_disciplines_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_CONFIRM_DELETE_DISC_W_TASKS))
def confirm_delete_discipline_with_tasks(call):
    """Выполняет удаление дисциплины со всеми связанными заданиями, фото и решениями."""
    user_id = call.from_user.id
    discipline_id = int(call.data.split(':')[1])
    
    try:
        cursor.execute("DELETE FROM disciplines WHERE id = ?", (discipline_id,))
        conn.commit()
        log_action(user_id, f"Удалена дисциплина {discipline_id} со всеми заданиями.")
        
        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ Дисциплина и все связанные задания успешно удалены!"
        ):
            bot.send_message(call.message.chat.id, "✅ Дисциплина и все связанные задания успешно удалены!")
        delete_discipline_step1(call.message, 0) # Обновляем список дисциплин
        # bot.answer_callback_query(call.id) # Handled in delete_discipline_step1
    except Exception as e:
        logger.error(f"Ошибка в confirm_delete_discipline_with_tasks для user_id={user_id}, disc_id={discipline_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка при удалении дисциплины.", reply_markup=manage_disciplines_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_CANCEL_DELETE_DISC))
def cancel_delete_discipline(call):
    """Отменяет удаление дисциплины."""
    user_id = call.from_user.id
    discipline_id = int(call.data.split(':')[1])
    
    try:
        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ Удаление дисциплины отменено."
        ):
            bot.send_message(call.message.chat.id, "❌ Удаление дисциплины отменено.")
        delete_discipline_step1(call.message, 0) # Возвращаемся к списку дисциплин
        # bot.answer_callback_query(call.id) # Handled in delete_discipline_step1
    except Exception as e:
        logger.error(f"Ошибка в cancel_delete_discipline для user_id={user_id}, disc_id={discipline_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=manage_disciplines_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")


@bot.message_handler(func=lambda message: message.text == "✏️ Переименовать дисциплину")
@private_only
@admin_only
def handle_rename_discipline(message):
    """Начинает процесс переименования дисциплины."""
    user_state.clear_state(message.from_user.id) # Очищаем состояние
    rename_discipline_step1(message, 0)

def rename_discipline_step1(message_obj, page):
    """Отображает список дисциплин для переименования с пагинацией.
    message_obj может быть как Message, так и CallbackQuery."""
    user_id = message_obj.from_user.id
    try:
        cursor.execute("SELECT id, name FROM disciplines ORDER BY name")
        disciplines = cursor.fetchall()
        
        total_pages = (len(disciplines) + MAX_BUTTONS_PER_PAGE - 1) // MAX_BUTTONS_PER_PAGE
        disciplines_page = disciplines[page*MAX_BUTTONS_PER_PAGE:(page+1)*MAX_BUTTONS_PER_PAGE]
        
        markup = types.InlineKeyboardMarkup()
        
        if not disciplines:
            text = "📭 Нет доступных дисциплин для переименования."
            if hasattr(message_obj, 'message_id'):
                _safe_edit_message(message_obj.chat.id, message_obj.message_id, text, reply_markup=manage_disciplines_markup())
            else:
                bot.send_message(user_id, text, reply_markup=manage_disciplines_markup())
            if hasattr(message_obj, 'id') and isinstance(message_obj, types.CallbackQuery):
                bot.answer_callback_query(message_obj.id)
            return

        for disc_id, disc_name in disciplines_page:
            markup.add(types.InlineKeyboardButton(
                text=f"✏️ {disc_name}",
                callback_data=f"{CB_PREFIX_RENAME_DISC}{disc_id}"
            ))
        
        pagination_markup = _generate_pagination_markup(page, total_pages, CB_PREFIX_RENAME_DISC_PAGE)
        if pagination_markup.keyboard:
            for row in pagination_markup.keyboard:
                markup.row(*row)
        
        markup.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data=CB_BACK_TO_MANAGE_DISCIPLINES))
        
        text = "📚 Выберите дисциплину для переименования:" + (f" (Страница {page+1}/{total_pages})" if total_pages > 1 else "")
        if hasattr(message_obj, 'message_id'):
            if not _safe_edit_message(message_obj.chat.id, message_obj.message_id, text, reply_markup=markup):
                bot.send_message(user_id, text, reply_markup=markup)
        else:
            bot.send_message(user_id, text, reply_markup=markup)

    except Exception as e:
        logger.error(f"Ошибка в rename_discipline_step1 для user_id={user_id}, page={page}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Ошибка загрузки дисциплин. Попробуйте позже.", reply_markup=manage_disciplines_markup())
    finally:
        if hasattr(message_obj, 'id') and isinstance(message_obj, types.CallbackQuery):
            bot.answer_callback_query(message_obj.id, "⚠️ Ошибка." if 'e' in locals() else None)

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_RENAME_DISC_PAGE))
def handle_rename_disc_page(call):
    """Обрабатывает пагинацию при выборе дисциплины для переименования."""
    page = int(call.data.split(':')[1])
    rename_discipline_step1(call.message, page)
    # bot.answer_callback_query(call.id) # Handled in rename_discipline_step1

@bot.callback_query_handler(func=lambda call: call.data.startswith(CB_PREFIX_RENAME_DISC))
def rename_discipline_step2(call):
    """Запрашивает новое название для выбранной дисциплины."""
    user_id = call.from_user.id
    discipline_id = int(call.data.split(':')[1])
    
    discipline_info = _get_discipline_info(discipline_id)
    if not discipline_info:
        bot.answer_callback_query(call.id, "⚠️ Дисциплина не найдена.", show_alert=True)
        return
    discipline_name = discipline_info[0]

    try:
        if not _safe_edit_message(call.message.chat.id, call.message.message_id, text=f"✏️ Введите новое название для дисциплины '*{discipline_name}*' (для отмены напишите 'отмена'):", parse_mode="Markdown"):
            bot.send_message(call.message.chat.id, f"✏️ Введите новое название для дисциплины '*{discipline_name}*' (для отмены напишите 'отмена'):", parse_mode="Markdown")
        
        user_state.set_state(user_id, 'waiting_for_new_discipline_name', {'discipline_id': discipline_id})
        bot.register_next_step_handler(call.message, process_rename_discipline)
        
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка в rename_discipline_step2 для user_id={user_id}, disc_id={discipline_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=manage_disciplines_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

def process_rename_discipline(message):
    """Выполняет переименование дисциплины."""
    user_id = message.from_user.id
    state = user_state.get_state(user_id)
    
    try:
        if message.text and message.text.lower() == "отмена":
            bot.send_message(user_id, "❌ Переименование дисциплины отменено.", reply_markup=manage_disciplines_markup())
            user_state.clear_state(user_id)
            return

        if message.content_type != 'text':
            msg = bot.send_message(user_id, "⚠️ Пожалуйста, введите новое название дисциплины текстом.")
            bot.register_next_step_handler(msg, process_rename_discipline)
            return

        discipline_id = state['data']['discipline_id']
        new_name = message.text.strip()
        
        if not new_name:
            msg = bot.send_message(user_id, "⚠️ Название дисциплины не может быть пустым. Введите новое название дисциплины:")
            bot.register_next_step_handler(msg, process_rename_discipline)
            return
        
        try:
            cursor.execute("UPDATE disciplines SET name = ? WHERE id = ?", (new_name, discipline_id))
            conn.commit()
            bot.send_message(
                user_id,
                f"✅ Дисциплина успешно переименована на '{new_name}'!",
                reply_markup=manage_disciplines_markup()
            )
            log_action(user_id, f"Переименована дисциплина {discipline_id} в '{new_name}'")
            user_state.clear_state(user_id)
        except sqlite3.IntegrityError:
            bot.send_message(
                user_id,
                f"⚠️ Дисциплина с названием '{new_name}' уже существует! Попробуйте другое имя.",
                reply_markup=manage_disciplines_markup()
            )
            user_state.clear_state(user_id)
        except Exception as e:
            logger.error(f"Ошибка при переименовании дисциплины {discipline_id} в '{new_name}' для user_id={user_id}: {e}", exc_info=True)
            bot.send_message(user_id, "⚠️ Произошла ошибка при переименовании дисциплины. Пожалуйста, попробуйте позже.", reply_markup=manage_disciplines_markup())
            user_state.clear_state(user_id)
    except Exception as e:
        logger.error(f"Ошибка в process_rename_discipline для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=manage_disciplines_markup())

@bot.callback_query_handler(func=lambda call: call.data == CB_BACK_TO_MANAGE_DISCIPLINES)
def handle_back_to_manage_disciplines_callback(call):
    """Обрабатывает колбэк для возврата в меню управления дисциплинами."""
    user_id = call.from_user.id
    try:
        user_state.clear_state(user_id) # Очищаем состояние
        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="📚 Управление дисциплинами:",
            reply_markup=manage_disciplines_markup()
        ):
            bot.send_message(call.message.chat.id, "📚 Управление дисциплинами:", reply_markup=manage_disciplines_markup())
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка в handle_back_to_manage_disciplines_callback для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.", reply_markup=manage_disciplines_markup())
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")

# --- АДМИН: ОБЪЯВЛЕНИЯ ---

def send_announcement_thread(chat_ids, text, photo_file_id, admin_chat_id):
    """Функция для отправки объявлений в отдельном потоке."""
    success_count = 0
    failed_count = 0
    total_users = len(chat_ids)
    
    # Отправляем начальное сообщение администратору
    try:
        bot.send_message(admin_chat_id, f"⏳ Рассылка начата для {total_users} пользователей...")
    except Exception as e:
        logger.error(f"Не удалось отправить начальное уведомление админу: {e}", exc_info=True)

    for i, chat_id in enumerate(chat_ids):
        try:
            if photo_file_id:
                bot.send_photo(chat_id, photo_file_id, caption=f"📢 *Важное объявление*\n\n{text}", parse_mode="Markdown")
            else:
                bot.send_message(chat_id, f"📢 *Важное объявление*\n\n{text}", parse_mode="Markdown")
            success_count += 1
            if (i + 1) % 10 == 0: # Обновляем каждые 10 пользователей, чтобы не спамить Telegram API
                time.sleep(0.1) # Небольшая задержка, чтобы избежать превышения лимитов
        except telebot.apihelper.ApiTelegramException as e:
            logger.warning(f"Не удалось отправить объявление пользователю {chat_id}: {e}")
            failed_count += 1
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при отправке объявления пользователю {chat_id}: {e}", exc_info=True)
            failed_count += 1
    
    final_message = (
        f"✅ Рассылка завершена:\n\n"
        f"• Успешно: {success_count}\n"
        f"• Не удалось: {failed_count}"
    )
    try:
        bot.send_message(admin_chat_id, final_message, reply_markup=admin_panel_markup())
        log_action(admin_chat_id, f"Завершена рассылка: {success_count} успешно, {failed_count} провалено.")
    except Exception as e:
        logger.error(f"Не удалось отправить финальное уведомление админу: {e}", exc_info=True)

@bot.message_handler(func=lambda message: message.text == "📢 Сделать объявление")
@private_only
@admin_only
def handle_announcement(message):
    """Начинает процесс создания объявления."""
    try:
        user_id = message.from_user.id
        msg = bot.send_message(
            user_id,
            "📝 Введите текст объявления (можно с форматированием Markdown) или отправьте *фотографию*. "
            "Если отправляете фото, то текст объявления нужно будет отправить *после* фото.\n\n"
            "Пример:\n"
            "*Важное обновление!*\n"
            "Завтра технические работы с 10:00 до 12:00\n\n"
            "Для отмены напишите 'отмена'.",
            reply_markup=types.ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        user_state.set_state(user_id, 'waiting_for_announcement_content', {'photo': None, 'text': None})
        bot.register_next_step_handler(msg, process_announcement_content)
    except Exception as e:
        logger.error(f"Ошибка в handle_announcement для user_id={message.from_user.id}: {e}", exc_info=True)
        bot.send_message(message.chat.id, "⚠️ Ошибка. Попробуйте позже.")

@bot.message_handler(content_types=['text', 'photo'], func=lambda m: user_state.get_state(m.from_user.id).get('state') == 'waiting_for_announcement_content')
def process_announcement_content(message):
    """Обрабатывает текст или фото для объявления."""
    user_id = message.from_user.id
    state_data = user_state.get_state(user_id)['data']

    try:
        if message.text and message.text.lower() == "отмена":
            bot.send_message(user_id, "❌ Объявление отменено.", reply_markup=admin_panel_markup())
            user_state.clear_state(user_id)
            return

        if message.content_type == 'photo':
            photo_file_id = message.photo[-1].file_id # Берем самое большое разрешение
            state_data['photo'] = photo_file_id
            # Если это первая часть объявления (фото), ожидаем текст следующей
            if not state_data.get('text'): # Если текста еще нет
                user_state.set_state(user_id, 'waiting_for_announcement_content', state_data) # Обновляем состояние с фото
                msg = bot.send_message(user_id, "📸 Фото получено. Теперь, пожалуйста, введите текст объявления (или отправьте 'отмена'):")
                bot.register_next_step_handler(msg, process_announcement_content) # Перезапускаем для получения текста
                return
            # Если текст уже был, а теперь пришло еще фото, обновляем фото и переходим к подтверждению
            else:
                pass # Пройдет к подтверждению ниже
        
        elif message.content_type == 'text':
            announcement_text = message.text.strip()
            if not announcement_text and not state_data.get('photo'): # Если ни текста, ни фото еще нет
                msg = bot.send_message(user_id, "⚠️ Объявление не может быть пустым. Отправьте текст или фото с текстом.")
                bot.register_next_step_handler(msg, process_announcement_content)
                return
            state_data['text'] = announcement_text
        else:
            msg = bot.send_message(user_id, "⚠️ Неподдерживаемый тип контента. Пожалуйста, отправьте текст или фото.")
            bot.register_next_step_handler(msg, process_announcement_content)
            return

        # Если дошли сюда, значит получили либо текст, либо фото+текст, и готовы к подтверждению
        user_state.set_state(user_id, 'confirming_announcement', state_data)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Да, отправить", callback_data=CB_ANNOUNCE_CONFIRM),
            types.InlineKeyboardButton("❌ Нет, отменить", callback_data=CB_ANNOUNCE_CANCEL)
        )
        
        preview_text = f"📢 *Подтвердите объявление:*\n\n{state_data['text'] or '(Без текста, только фото)'}\n\nОтправить всем пользователям?"
        
        if state_data['photo']:
            bot.send_photo(user_id, state_data['photo'], caption=preview_text, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(user_id, preview_text, reply_markup=markup, parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Ошибка в process_announcement_content для user_id={user_id}: {e}", exc_info=True)
        bot.send_message(user_id, "⚠️ Ошибка. Попробуйте позже.", reply_markup=admin_panel_markup())


@bot.callback_query_handler(func=lambda call: call.data == CB_ANNOUNCE_CONFIRM)
def send_announcement_confirmed(call):
    """Запускает рассылку объявления в отдельном потоке."""
    user_id = call.from_user.id
    state = user_state.get_state(user_id)
    
    if state.get('state') != 'confirming_announcement':
        bot.answer_callback_query(call.id, "⚠️ Сессия истекла или объявление уже было обработано.", show_alert=True)
        return
            
    announcement_text = state['data'].get('text', '') # Может быть пустой строкой, если только фото
    photo_file_id = state['data'].get('photo')

    cursor.execute("SELECT user_id FROM users WHERE user_id != ?", (user_id,)) # Исключаем самого админа
    users_to_send = [user[0] for user in cursor.fetchall()]
    
    if not _safe_edit_message(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"⏳ Запускаю рассылку... Ожидайте уведомления о завершении."
    ):
        bot.send_message(call.message.chat.id, f"⏳ Запускаю рассылку... Ожидайте уведомления о завершении.")
    bot.answer_callback_query(call.id, "Рассылка запущена в фоновом режиме.")
    
    threading.Thread(target=send_announcement_thread, args=(users_to_send, announcement_text, photo_file_id, user_id)).start()
    user_state.clear_state(user_id)

@bot.callback_query_handler(func=lambda call: call.data == CB_ANNOUNCE_CANCEL)
def cancel_announcement(call):
    """Отменяет создание объявления."""
    user_id = call.from_user.id
    try:
        if not _safe_edit_message(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ Рассылка отменена."
        ):
            bot.send_message(call.message.chat.id, "❌ Рассылка отменена.")
        bot.send_message(user_id, "Объявление не было отправлено.", reply_markup=admin_panel_markup())
        user_state.clear_state(user_id)
        bot.answer_callback_query(call.id, "Объявление отменено.")
    except Exception as e:
        logger.error(f"Ошибка в cancel_announcement для user_id={user_id}: {e}", exc_info=True)    
        bot.send_message(user_id, "⚠️ Ошибка при отмене рассылки.")
        bot.answer_callback_query(call.id, "⚠️ Ошибка.")


# --- ОБЩИЙ ОБРАБОТЧИК ДЛЯ НЕИЗВЕСТНЫХ СООБЩЕНИЙ ---
@bot.message_handler(func=lambda message: True, content_types=['text', 'photo', 'sticker', 'audio', 'video', 'document', 'voice', 'contact', 'location'])
@private_only # Оставляем этот декоратор, чтобы посторонние сообщения в группах не обрабатывались
def handle_unknown_messages(message):
    """Обрабатывает любые сообщения, которые не были пойманы другими хендлерами."""
    user_id = message.from_user.id
    current_state = user_state.get_state(user_id)['state']
    
    if current_state:
        # Если пользователь в каком-то состоянии, но прислал что-то неожиданное,
        # сообщаем о неверном вводе.
        logger.warning(f"User {user_id} in state '{current_state}' sent unexpected message type: {message.content_type}")
        bot.send_message(user_id, "🤔 Извините, я не понял ваше сообщение. Пожалуйста, следуйте инструкциям или нажмите 'Отмена'.")
        # Важно: register_next_step_handler не будет работать, если здесь не перерегистрировать
        # текущий шаг. Но это сложно сделать без знания контекста.
        # Поэтому полагаемся, что функции-шаги сами себя перерегистрируют
        # при получении неверного типа ввода (что уже реализовано).
    else:
        # Если пользователь не в состоянии, то это просто неизвестная команда/сообщение
        bot.send_message(user_id, "🤔 Извините, я не понимаю вашу команду. Пожалуйста, воспользуйтесь кнопками меню.", reply_markup=main_menu_markup(user_id))
    log_action(user_id, f"Получено неизвестное сообщение: {message.content_type}")


# --- ЗАПУСК БОТА ---

if __name__ == '__main__':
    try:
        initialize_database()
        logger.info("Бот запущен...")
        print("Бот успешно запущен!")
        bot.polling(none_stop=True, interval=0)
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
    finally:
        conn.close()