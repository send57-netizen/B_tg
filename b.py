import logging
import smtplib
import sqlite3
import json
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler
)
import asyncio

# Включаем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Определяем состояния
(
    CATEGORY,
    CAR_INFO,
    PARTS_QUERY,
    MANAGER_TRANSFER,
    REPAIR_REASON,
) = range(5)

# Настройки менеджеров (ID телеграм)
MANAGERS = {
    "👨‍💼 Менеджер 1": 123456789,  # Замените на реальный ID менеджера
    "👩‍💼 Менеджер 2": 987654321,  # Замените на реальный ID менеджера
}

# Настройки почты
EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'sender_email': 'your_email@gmail.com',
    'sender_password': 'your_app_password',
    'recipient_emails': ['manager1@example.com', 'manager2@example.com']
}

# Клавиатуры
main_keyboard = ReplyKeyboardMarkup(
    [["🛞 Автозапчасти", "🔧 Ремонт"], ["🛒 Покупка товаров"], ["📋 Мои заявки"]],
    resize_keyboard=True
)

back_keyboard = ReplyKeyboardMarkup(
    [["◀️ Назад"]],
    resize_keyboard=True
)

manager_keyboard = ReplyKeyboardMarkup(
    [["👨‍💼 Менеджер 1", "👩‍💼 Менеджер 2"], ["◀️ Назад"]],
    resize_keyboard=True
)

# Инициализация базы данных
def init_database():
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    
    # Таблица заявок
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  username TEXT,
                  category TEXT,
                  car_info TEXT,
                  parts TEXT,
                  reason TEXT,
                  manager TEXT,
                  status TEXT DEFAULT 'new',
                  timestamp TEXT,
                  notification_sent INTEGER DEFAULT 0)''')
    
    # Таблица истории статусов
    c.execute('''CREATE TABLE IF NOT EXISTS order_status_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  order_id INTEGER,
                  status TEXT,
                  manager_id INTEGER,
                  comment TEXT,
                  timestamp TEXT,
                  FOREIGN KEY (order_id) REFERENCES orders (id))''')
    
    conn.commit()
    conn.close()

# Сохранение заявки в БД
def save_order_to_db(order_data):
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    
    c.execute('''INSERT INTO orders 
                 (user_id, username, category, car_info, parts, reason, manager, timestamp, status)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (order_data['user_id'],
               order_data['username'],
               order_data['category'],
               order_data['car_info'],
               order_data.get('parts', ''),
               order_data.get('reason', ''),
               order_data['manager'],
               order_data['timestamp'],
               'new'))
    
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    return order_id

# Обновление статуса заявки
def update_order_status(order_id, status, manager_id, comment=''):
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    
    # Обновляем статус заявки
    c.execute('''UPDATE orders SET status = ? WHERE id = ?''', (status, order_id))
    
    # Добавляем запись в историю
    c.execute('''INSERT INTO order_status_history 
                 (order_id, status, manager_id, comment, timestamp)
                 VALUES (?, ?, ?, ?, ?)''',
              (order_id, status, manager_id, comment, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    
    conn.commit()
    conn.close()

# Получение заявок пользователя
def get_user_orders(user_id):
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    
    c.execute('''SELECT id, category, car_info, status, timestamp 
                 FROM orders 
                 WHERE user_id = ? 
                 ORDER BY timestamp DESC''', (user_id,))
    
    orders = c.fetchall()
    conn.close()
    return orders

# Получение деталей заявки
def get_order_details(order_id):
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    
    c.execute('''SELECT * FROM orders WHERE id = ?''', (order_id,))
    order = c.fetchone()
    
    if order:
        c.execute('''SELECT * FROM order_status_history 
                     WHERE order_id = ? 
                     ORDER BY timestamp DESC''', (order_id,))
        history = c.fetchall()
    else:
        history = []
    
    conn.close()
    return order, history

async def send_email_notification(order_data: dict, order_id: int):
    """Отправка уведомления на почту"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG['sender_email']
        msg['To'] = ', '.join(EMAIL_CONFIG['recipient_emails'])
        msg['Subject'] = f"Новая заявка #{order_id} от клиента"

        body = f"""
        Новая заявка #{order_id}!
        
        Категория: {order_data.get('category')}
        Информация об авто: {order_data.get('car_info')}
        """
        
        if order_data.get('parts'):
            body += f"Запчасти: {order_data.get('parts')}\n"
        if order_data.get('reason'):
            body += f"Причина обращения: {order_data.get('reason')}\n"
            
        body += f"""
        Выбранный менеджер: {order_data.get('manager')}
        Время заявки: {order_data.get('timestamp')}
        ID заявки: {order_id}
        
        Свяжитесь с клиентом как можно скорее!
        """
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        server.starttls()
        server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
        server.send_message(msg)
        server.quit()
        
        logger.info(f"Email уведомление для заявки #{order_id} отправлено успешно")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки email: {e}")
        return False

async def notify_managers(update: Update, context: ContextTypes.DEFAULT_TYPE, order_data: dict, order_id: int):
    """Уведомление менеджеров в Telegram с инлайн-кнопками"""
    try:
        # Формируем сообщение для менеджеров
        manager_message = (
            f"🔔 НОВАЯ ЗАЯВКА #{order_id}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Клиент: @{update.effective_user.username or 'не указан'}\n"
            f"🆔 ID: {update.effective_user.id}\n"
            f"📊 Категория: {order_data.get('category')}\n"
            f"🚗 Авто: {order_data.get('car_info')}\n"
        )
        
        if order_data.get('parts'):
            manager_message += f"🔧 Запчасти: {order_data.get('parts')}\n"
        if order_data.get('reason'):
            manager_message += f"⚠️ Причина: {order_data.get('reason')}\n"
            
        manager_message += (
            f"👨‍💼 Выбран: {order_data.get('manager')}\n"
            f"⏰ Время: {order_data.get('timestamp')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        # Создаем инлайн-кнопки для менеджеров
        keyboard = [
            [
                InlineKeyboardButton("✅ Принять", callback_data=f"accept_{order_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{order_id}")
            ],
            [InlineKeyboardButton("📞 Связаться с клиентом", url=f"tg://user?id={update.effective_user.id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем всем менеджерам
        for manager_name, manager_id in MANAGERS.items():
            try:
                await context.bot.send_message(
                    chat_id=manager_id,
                    text=manager_message,
                    reply_markup=reply_markup
                )
                logger.info(f"Уведомление отправлено менеджеру {manager_name}")
            except Exception as e:
                logger.error(f"Ошибка отправки менеджеру {manager_name}: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при уведомлении менеджеров: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на инлайн-кнопки"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    manager_id = query.from_user.id
    manager_name = query.from_user.full_name
    
    if data.startswith('accept_'):
        order_id = int(data.split('_')[1])
        
        # Обновляем статус в БД
        update_order_status(order_id, 'accepted', manager_id, f'Принято менеджером {manager_name}')
        
        # Получаем информацию о заявке
        conn = sqlite3.connect('orders.db')
        c = conn.cursor()
        c.execute('SELECT user_id FROM orders WHERE id = ?', (order_id,))
        result = c.fetchone()
        conn.close()
        
        if result:
            user_id = result[0]
            # Отправляем уведомление клиенту
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Ваша заявка #{order_id} принята менеджером {manager_name}!\n"
                     f"Скоро с вами свяжутся."
            )
        
        # Обновляем сообщение менеджера
        await query.edit_message_text(
            text=query.message.text + f"\n\n✅ Заявка принята менеджером {manager_name}",
            reply_markup=None
        )
        
    elif data.startswith('reject_'):
        order_id = int(data.split('_')[1])
        
        # Обновляем статус в БД
        update_order_status(order_id, 'rejected', manager_id, f'Отклонено менеджером {manager_name}')
        
        # Получаем информацию о заявке
        conn = sqlite3.connect('orders.db')
        c = conn.cursor()
        c.execute('SELECT user_id FROM orders WHERE id = ?', (order_id,))
        result = c.fetchone()
        conn.close()
        
        if result:
            user_id = result[0]
            # Отправляем уведомление клиенту
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ К сожалению, ваша заявка #{order_id} отклонена.\n"
                     f"Попробуйте создать новую заявку или свяжитесь с поддержкой."
            )
        
        # Обновляем сообщение менеджера
        await query.edit_message_text(
            text=query.message.text + f"\n\n❌ Заявка отклонена менеджером {manager_name}",
            reply_markup=None
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало диалога, приветствие и выбор категории."""
    await update.message.reply_text(
        "Добро пожаловать в консультацию!\n"
        "Выберите интересующий вас раздел:",
        reply_markup=main_keyboard
    )
    return CATEGORY

async def category_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора категории."""
    text = update.message.text

    if text == "📋 Мои заявки":
        return await show_my_orders(update, context)
    elif "Автозапчасти" in text:
        context.user_data['category'] = 'Автозапчасти'
        await update.message.reply_text(
            "Вы выбрали автозапчасти для иномарки.\n"
            "Уточните, пожалуйста, марку, модель и VIN автомобиля:",
            reply_markup=back_keyboard
        )
        return CAR_INFO
    elif "Ремонт" in text:
        context.user_data['category'] = 'Ремонт автомобиля'
        await update.message.reply_text(
            "Вы выбрали ремонт автомобиля.\n"
            "Уточните, пожалуйста, марку и модель:",
            reply_markup=back_keyboard
        )
        return CAR_INFO
    elif "Покупка" in text:
        context.user_data['category'] = 'Покупка автозапчастей'
        await update.message.reply_text(
            "Вы выбрали покупку автозапчастей, автохимии и прочих товаров.\n"
            "Уточните, пожалуйста, марку, модель и VIN автомобиля:",
            reply_markup=back_keyboard
        )
        return CAR_INFO
    else:
        await update.message.reply_text(
            "Пожалуйста, выберите пункт из меню.",
            reply_markup=main_keyboard
        )
        return CATEGORY

async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать историю заявок пользователя"""
    user_id = update.effective_user.id
    orders = get_user_orders(user_id)
    
    if not orders:
        await update.message.reply_text(
            "У вас пока нет заявок.",
            reply_markup=main_keyboard
        )
        return CATEGORY
    
    message = "📋 Ваши заявки:\n\n"
    for order in orders:
        status_emoji = {
            'new': '🆕',
            'accepted': '✅',
            'rejected': '❌',
            'completed': '🎉'
        }.get(order[3], '📝')
        
        message += f"{status_emoji} Заявка #{order[0]}\n"
        message += f"   Категория: {order[1]}\n"
        message += f"   Авто: {order[2][:50]}...\n" if len(order[2]) > 50 else f"   Авто: {order[2]}\n"
        message += f"   Статус: {order[3]}\n"
        message += f"   Время: {order[4]}\n\n"
    
    message += "Для просмотра деталей заявки введите ее номер: /order_НОМЕР"
    
    await update.message.reply_text(message, reply_markup=main_keyboard)
    return CATEGORY

async def order_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать детали конкретной заявки"""
    try:
        order_id = int(context.args[0])
        user_id = update.effective_user.id
        
        order, history = get_order_details(order_id)
        
        if not order or order[1] != user_id:  # order[1] это user_id
            await update.message.reply_text("Заявка не найдена или не принадлежит вам.")
            return
        
        # Формируем сообщение с деталями
        status_emoji = {
            'new': '🆕',
            'accepted': '✅',
            'rejected': '❌',
            'completed': '🎉'
        }.get(order[8], '📝')  # order[8] это status
        
        message = (
            f"📋 Детали заявки #{order[0]}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Статус: {status_emoji} {order[8]}\n"
            f"Категория: {order[3]}\n"
            f"Авто: {order[4]}\n"
        )
        
        if order[5]:  # parts
            message += f"Запчасти: {order[5]}\n"
        if order[6]:  # reason
            message += f"Причина: {order[6]}\n"
            
        message += f"Менеджер: {order[7]}\n"
        message += f"Время создания: {order[9]}\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━\n"
        message += "📊 История изменений:\n"
        
        for h in history:
            message += f"  • {h[4]}: {h[2]}\n"
            if h[3]:  # comment
                message += f"    Комментарий: {h[3]}\n"
        
        await update.message.reply_text(message)
        
    except (IndexError, ValueError):
        await update.message.reply_text("Использование: /order_номер")

async def car_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода информации об авто."""
    if update.message.text == "◀️ Назад":
        await start(update, context)
        return CATEGORY

    # Сохраняем введённую информацию
    context.user_data['car_info'] = update.message.text

    # Если категория ремонт — сразу запрашиваем причину
    if context.user_data.get('category') == 'Ремонт автомобиля':
        await update.message.reply_text(
            "Уточните, причину обращения:",
            reply_markup=back_keyboard
        )
        return REPAIR_REASON
    else:
        # Для запчастей и покупок — запрашиваем, что именно нужно
        await update.message.reply_text(
            "Какие автозапчасти Вас интересуют?",
            reply_markup=back_keyboard
        )
        return PARTS_QUERY

async def parts_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка запроса запчастей."""
    if update.message.text == "◀️ Назад":
        await update.message.reply_text(
            "Уточните, пожалуйста, марку, модель и VIN автомобиля:",
            reply_markup=back_keyboard
        )
        return CAR_INFO

    context.user_data['parts'] = update.message.text

    # Предлагаем выбор менеджера
    await update.message.reply_text(
        "Выберите менеджера для продолжения:",
        reply_markup=manager_keyboard
    )
    return MANAGER_TRANSFER

async def repair_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка причины обращения для ремонта."""
    if update.message.text == "◀️ Назад":
        await update.message.reply_text(
            "Уточните, пожалуйста, марку и модель:",
            reply_markup=back_keyboard
        )
        return CAR_INFO

    context.user_data['reason'] = update.message.text

    # Предлагаем выбор менеджера
    await update.message.reply_text(
        "Выберите менеджера для продолжения:",
        reply_markup=manager_keyboard
    )
    return MANAGER_TRANSFER

async def manager_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Финальный шаг — перевод на специалиста"""
    if update.message.text == "◀️ Назад":
        if context.user_data.get('category') == 'Ремонт автомобиля':
            await update.message.reply_text(
                "Уточните, причину обращения:",
                reply_markup=back_keyboard
            )
            return REPAIR_REASON
        else:
            await update.message.reply_text(
                "Какие автозапчасти Вас интересуют?",
                reply_markup=back_keyboard
            )
            return PARTS_QUERY

    # Сохраняем выбор менеджера и время
    context.user_data['manager'] = update.message.text
    context.user_data['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    context.user_data['user_id'] = update.effective_user.id
    context.user_data['username'] = update.effective_user.username or 'не указан'

    # Сохраняем заявку в БД
    order_id = save_order_to_db(context.user_data)

    # Формируем итоговое сообщение для клиента
    client_summary = (
        f"✅ Заявка #{order_id} сформирована!\n\n"
        f"📋 Детали заявки:\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Категория: {context.user_data.get('category')}\n"
        f"Авто: {context.user_data.get('car_info')}\n"
    )
    if context.user_data.get('parts'):
        client_summary += f"Запчасти: {context.user_data.get('parts')}\n"
    if context.user_data.get('reason'):
        client_summary += f"Причина: {context.user_data.get('reason')}\n"
    client_summary += (
        f"Перевод на: {context.user_data.get('manager')}\n"
        f"Время: {context.user_data.get('timestamp')}\n"
        f"Статус: 🆕 Новая\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📢 Менеджеры уже получили уведомление и скоро свяжутся с вами!\n"
        f"Вы можете отслеживать статус заявки в разделе «Мои заявки».\n"
        f"Номер заявки: #{order_id}"
    )

    await update.message.reply_text(client_summary, reply_markup=main_keyboard)

    # Отправляем уведомления менеджерам
    await notify_managers(update, context, context.user_data, order_id)
    
    # Отправляем на почту
    asyncio.create_task(send_email_notification(context.user_data, order_id))

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена диалога."""
    await update.message.reply_text(
        "Диалог завершён. Для нового обращения нажмите /start",
        reply_markup=main_keyboard
    )
    return ConversationHandler.END

def main() -> None:
    """Запуск бота."""
    # Инициализируем базу данных
    init_database()
    
    # Вставьте сюда ваш токен
    application = Application.builder().token(8688135237:AAGeTK9ah-YCa2KlpEsPJRv3bNPbY_nhRK4).build()

    # Добавляем обработчик инлайн-кнопок
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Добавляем обработчик для просмотра деталей заявки
    application.add_handler(CommandHandler("order", order_details))

    # Обработчик диалога
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, category_choice)],
            CAR_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_info)],
            PARTS_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, parts_query)],
            REPAIR_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, repair_reason)],
            MANAGER_TRANSFER: [MessageHandler(filters.TEXT & ~filters.COMMAND, manager_transfer)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)

    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()