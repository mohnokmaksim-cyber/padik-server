"""
Padik Messenger Backend - Flask приложение v2
Авторизация/Регистрация через email и коды подтверждения
Отправка кодов на реальную почту через SMTP
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import sqlite3
import secrets
import string
from datetime import datetime, timedelta
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Инициализация Flask приложения
app = Flask(__name__)

# Конфигурация JWT
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)

# Инициализация JWT
jwt = JWTManager(app)

# Включаем CORS для всех маршрутов
CORS(app, resources={r"/*": {"origins": "*"}})

# ============================================================================
# КОНФИГУРАЦИЯ SMTP
# ============================================================================

# Используйте переменные окружения для безопасности!
# Пример для Gmail:
# SMTP_SERVER = "smtp.gmail.com"
# SMTP_PORT = 587
# SMTP_EMAIL = "your-email@gmail.com"
# SMTP_PASSWORD = "your-app-password"  # Используйте App Password, не основной пароль!

# Пример для Yandex Mail:
# SMTP_SERVER = "smtp.yandex.ru"
# SMTP_PORT = 465
# SMTP_EMAIL = "your-email@yandex.ru"
# SMTP_PASSWORD = "your-password"

SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_EMAIL = os.getenv('SMTP_EMAIL', 'your-email@gmail.com')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', 'your-app-password')
SMTP_USE_TLS = os.getenv('SMTP_USE_TLS', 'True') == 'True'

# Путь к базе данных
DB_PATH = 'padik.db'

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
# ============================================================================

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            phone TEXT,
            bio TEXT,
            avatar_url TEXT,
            apartment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица кодов подтверждения
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS verification_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        )
    ''')
    
    # Таблица чатов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            is_group INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица участников чатов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES chats(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Таблица сообщений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES chats(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print('[DB] База данных инициализирована')

# Инициализируем БД при запуске
init_db()

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def generate_code(length=6):
    """Генерация случайного кода подтверждения"""
    return ''.join(secrets.choice(string.digits) for _ in range(length))

def get_db_connection():
    """Получение подключения к БД"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def send_email(to_email, subject, html_content):
    """
    Отправка email через SMTP
    """
    try:
        # Создаем сообщение
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        message['From'] = SMTP_EMAIL
        message['To'] = to_email
        
        # Добавляем HTML контент
        part = MIMEText(html_content, 'html')
        message.attach(part)
        
        # Подключаемся к SMTP серверу
        if SMTP_USE_TLS:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        
        # Авторизуемся
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        
        # Отправляем письмо
        server.sendmail(SMTP_EMAIL, to_email, message.as_string())
        server.quit()
        
        print(f'[EMAIL] ✅ Письмо отправлено на {to_email}')
        return True
    
    except Exception as e:
        print(f'[EMAIL] ❌ Ошибка отправки: {str(e)}')
        return False

def send_verification_code_email(to_email, code):
    """Отправка кода подтверждения на email"""
    html_content = f'''
    <html>
        <body style="font-family: Arial, sans-serif; background-color: #0a0e27; color: #fff; padding: 20px;">
            <div style="max-width: 400px; margin: 0 auto; background-color: #1a1f3a; border: 1px solid #00D9FF; border-radius: 12px; padding: 30px; box-shadow: 0 0 30px rgba(0, 217, 255, 0.2);">
                <h1 style="text-align: center; color: #00D9FF; text-shadow: 0 0 20px rgba(0, 217, 255, 0.5); margin-bottom: 20px;">P</h1>
                <p style="text-align: center; font-size: 14px; color: #999; margin-bottom: 30px;">Padik Messenger</p>
                
                <h2 style="text-align: center; color: #fff; font-size: 20px; margin-bottom: 20px;">Ваш код подтверждения</h2>
                
                <div style="background-color: #0a0e27; border: 2px solid #00D9FF; border-radius: 8px; padding: 20px; text-align: center; margin-bottom: 30px;">
                    <p style="font-size: 32px; font-weight: bold; color: #00D9FF; margin: 0; letter-spacing: 10px;">{code}</p>
                </div>
                
                <p style="text-align: center; font-size: 14px; color: #ccc; margin-bottom: 10px;">Код действует 10 минут</p>
                <p style="text-align: center; font-size: 12px; color: #666;">Если вы не запрашивали этот код, проигнорируйте это письмо</p>
                
                <hr style="border: none; border-top: 1px solid #333; margin: 30px 0;">
                
                <p style="text-align: center; font-size: 11px; color: #555;">© 2026 Padik Messenger. Все права защищены.</p>
            </div>
        </body>
    </html>
    '''
    
    return send_email(to_email, 'Код подтверждения Padik Messenger', html_content)

# ============================================================================
# МАРШРУТЫ АВТОРИЗАЦИИ
# ============================================================================

@app.route('/check_email', methods=['POST'])
def check_email():
    """
    Проверка, существует ли email в системе
    POST /check_email
    Body: {"email": "user@example.com"}
    """
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        conn.close()
        
        exists = user is not None
        
        return jsonify({
            'status': 'ok',
            'email': email,
            'exists': exists,
            'action': 'login' if exists else 'register'
        }), 200
    
    except Exception as e:
        print(f'[ERROR] check_email: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/send_code', methods=['POST'])
def send_code():
    """
    Отправка кода подтверждения на email
    POST /send_code
    Body: {"email": "user@example.com"}
    """
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        # Генерируем код
        code = generate_code(6)
        
        # Сохраняем код в БД
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Удаляем старые коды для этого email
        cursor.execute('DELETE FROM verification_codes WHERE email = ?', (email,))
        
        # Сохраняем новый код (действует 10 минут)
        expires_at = datetime.now() + timedelta(minutes=10)
        cursor.execute(
            'INSERT INTO verification_codes (email, code, expires_at) VALUES (?, ?, ?)',
            (email, code, expires_at)
        )
        conn.commit()
        conn.close()
        
        # Отправляем код на почту
        email_sent = send_verification_code_email(email, code)
        
        if not email_sent:
            # Если не удалось отправить, выводим в консоль для тестирования
            print(f'[SEND_CODE] Email: {email}, Code: {code} (SMTP ERROR - CHECK CONSOLE)')
        
        return jsonify({
            'status': 'ok',
            'message': f'Code sent to {email}',
            'email_sent': email_sent
        }), 200
    
    except Exception as e:
        print(f'[ERROR] send_code: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/verify_code', methods=['POST'])
def verify_code():
    """
    Проверка кода подтверждения и выдача JWT-токена
    POST /verify_code
    Body: {"email": "user@example.com", "code": "123456"}
    """
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return jsonify({'error': 'Email and code are required'}), 400
        
        # Проверяем код в БД
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT * FROM verification_codes WHERE email = ? AND code = ? AND expires_at > ?',
            (email, code, datetime.now())
        )
        verification = cursor.fetchone()
        
        if not verification:
            conn.close()
            return jsonify({'error': 'Invalid or expired code'}), 401
        
        # Удаляем использованный код
        cursor.execute('DELETE FROM verification_codes WHERE id = ?', (verification['id'],))
        
        # Проверяем, существует ли пользователь
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        
        is_new_user = False
        if not user:
            # Создаем нового пользователя
            is_new_user = True
            cursor.execute(
                'INSERT INTO users (email, name) VALUES (?, ?)',
                (email, email.split('@')[0])
            )
            conn.commit()
            
            # Получаем созданного пользователя
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            user = cursor.fetchone()
        
        # Генерируем JWT-токен
        token = create_access_token(identity=user['id'])
        
        action = 'registered' if is_new_user else 'authenticated'
        print(f'[VERIFY_CODE] ✅ User {email} {action}, Token: {token[:20]}...')
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'token': token,
            'is_new_user': is_new_user,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'name': user['name']
            }
        }), 200
    
    except Exception as e:
        print(f'[ERROR] verify_code: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/auth', methods=['GET'])
def auth_page():
    """
    HTML страница авторизации/регистрации для WebView
    """
    html = '''
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Padik Messenger - Вход</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }
            
            .container {
                width: 100%;
                max-width: 400px;
                background: rgba(26, 31, 58, 0.8);
                border: 1px solid rgba(0, 217, 255, 0.3);
                border-radius: 16px;
                padding: 40px 30px;
                box-shadow: 0 0 50px rgba(0, 217, 255, 0.15);
                backdrop-filter: blur(10px);
            }
            
            .logo {
                text-align: center;
                margin-bottom: 30px;
            }
            
            .logo-text {
                font-size: 48px;
                font-weight: bold;
                color: #00D9FF;
                text-shadow: 0 0 20px rgba(0, 217, 255, 0.5);
                margin-bottom: 10px;
            }
            
            .logo-subtitle {
                font-size: 14px;
                color: #999;
            }
            
            .form-group {
                margin-bottom: 20px;
            }
            
            label {
                display: block;
                font-size: 14px;
                color: #ccc;
                margin-bottom: 8px;
                font-weight: 500;
            }
            
            input {
                width: 100%;
                padding: 12px 16px;
                background: rgba(10, 14, 39, 0.5);
                border: 1px solid rgba(0, 217, 255, 0.3);
                border-radius: 8px;
                color: #fff;
                font-size: 14px;
                transition: all 0.3s ease;
            }
            
            input:focus {
                outline: none;
                border-color: #00D9FF;
                box-shadow: 0 0 15px rgba(0, 217, 255, 0.2);
                background: rgba(10, 14, 39, 0.8);
            }
            
            button {
                width: 100%;
                padding: 12px 16px;
                background: linear-gradient(135deg, #00D9FF 0%, #0099cc 100%);
                border: none;
                border-radius: 8px;
                color: #0a0e27;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                margin-top: 10px;
            }
            
            button:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 20px rgba(0, 217, 255, 0.3);
            }
            
            button:active {
                transform: translateY(0);
            }
            
            button:disabled {
                opacity: 0.6;
                cursor: not-allowed;
            }
            
            .message {
                text-align: center;
                margin-top: 20px;
                font-size: 14px;
                padding: 12px;
                border-radius: 8px;
            }
            
            .success {
                color: #22C55E;
                background: rgba(34, 197, 94, 0.1);
                border: 1px solid rgba(34, 197, 94, 0.3);
            }
            
            .error {
                color: #EF4444;
                background: rgba(239, 68, 68, 0.1);
                border: 1px solid rgba(239, 68, 68, 0.3);
            }
            
            .loading {
                display: inline-block;
                width: 16px;
                height: 16px;
                border: 2px solid rgba(0, 217, 255, 0.3);
                border-top-color: #00D9FF;
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
                margin-right: 8px;
            }
            
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
            
            .step-indicator {
                display: flex;
                gap: 8px;
                margin-bottom: 20px;
                justify-content: center;
            }
            
            .step {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: rgba(0, 217, 255, 0.2);
                transition: all 0.3s ease;
            }
            
            .step.active {
                background: #00D9FF;
                box-shadow: 0 0 10px rgba(0, 217, 255, 0.5);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <div class="logo-text">P</div>
                <div class="logo-subtitle">Padik Messenger</div>
            </div>
            
            <div class="step-indicator">
                <div class="step active" id="step1"></div>
                <div class="step" id="step2"></div>
            </div>
            
            <div id="emailStep">
                <div class="form-group">
                    <label for="email">Email</label>
                    <input type="email" id="email" placeholder="your@email.com">
                </div>
                <button onclick="handleCheckEmail(event)">Продолжить</button>
            </div>
            
            <div id="codeStep" style="display: none;">
                <div class="form-group">
                    <label for="code">Код подтверждения</label>
                    <input type="text" id="code" placeholder="000000" maxlength="6">
                </div>
                <button onclick="handleVerifyCode(event)">Подтвердить</button>
                <button onclick="backToEmail()" style="background: rgba(0, 217, 255, 0.1); color: #00D9FF; margin-top: 10px;">Назад</button>
            </div>
            
            <div id="message"></div>
        </div>
        
        <script>
            let currentEmail = '';
            let isNewUser = false;
            
            async function handleCheckEmail(event) {
                event.preventDefault();
                const email = document.getElementById('email').value.trim();
                
                if (!email) {
                    showMessage('Введите email', 'error');
                    return;
                }
                
                try {
                    const checkResponse = await fetch('/check_email', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email })
                    });
                    
                    const checkData = await checkResponse.json();
                    
                    if (!checkResponse.ok) {
                        showMessage(checkData.error || 'Ошибка проверки email', 'error');
                        return;
                    }
                    
                    isNewUser = !checkData.exists;
                    const action = isNewUser ? 'регистрацию' : 'вход';
                    
                    // Отправляем код
                    const codeResponse = await fetch('/send_code', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email })
                    });
                    
                    const codeData = await codeResponse.json();
                    
                    if (codeResponse.ok) {
                        currentEmail = email;
                        showMessage(`✅ Код отправлен на почту (${action})`, 'success');
                        
                        // Переходим на шаг ввода кода
                        setTimeout(() => {
                            document.getElementById('emailStep').style.display = 'none';
                            document.getElementById('codeStep').style.display = 'block';
                            document.getElementById('step1').classList.remove('active');
                            document.getElementById('step2').classList.add('active');
                            document.getElementById('code').focus();
                        }, 1000);
                    } else {
                        showMessage(codeData.error || 'Ошибка отправки кода', 'error');
                    }
                } catch (error) {
                    showMessage('Ошибка подключения: ' + error.message, 'error');
                }
            }
            
            async function handleVerifyCode(event) {
                event.preventDefault();
                const code = document.getElementById('code').value.trim();
                
                if (!code || code.length !== 6) {
                    showMessage('Введите 6-значный код', 'error');
                    return;
                }
                
                try {
                    const response = await fetch('/verify_code', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email: currentEmail, code })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok && data.token) {
                        const action = isNewUser ? '✅ Добро пожаловать!' : '✅ Вы вошли!';
                        showMessage(action, 'success');
                        
                        // Отправляем токен в мобильное приложение
                        if (window.ReactNativeWebView) {
                            window.ReactNativeWebView.postMessage(JSON.stringify({
                                type: 'AUTH_TOKEN',
                                token: data.token,
                                user: data.user
                            }));
                        }
                        
                        // Сохраняем токен в localStorage для веб
                        localStorage.setItem('auth_token', data.token);
                        
                        // Перенаправляем на главную страницу
                        setTimeout(() => {
                            window.location.href = '/';
                        }, 1500);
                    } else {
                        showMessage(data.error || 'Неверный код', 'error');
                    }
                } catch (error) {
                    showMessage('Ошибка подключения: ' + error.message, 'error');
                }
            }
            
            function backToEmail() {
                document.getElementById('code').value = '';
                document.getElementById('emailStep').style.display = 'block';
                document.getElementById('codeStep').style.display = 'none';
                document.getElementById('step1').classList.add('active');
                document.getElementById('step2').classList.remove('active');
                document.getElementById('email').focus();
            }
            
            function showMessage(text, type) {
                const messageDiv = document.getElementById('message');
                messageDiv.textContent = text;
                messageDiv.className = 'message ' + type;
                messageDiv.style.display = 'block';
            }
            
            // Обработка Enter в полях
            document.getElementById('email').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') handleCheckEmail(e);
            });
            
            document.getElementById('code').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') handleVerifyCode(e);
            });
        </script>
    </body>
    </html>
    '''
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}

# ============================================================================
# МАРШРУТЫ ЧАТОВ И СООБЩЕНИЙ
# ============================================================================

@app.route('/api/chats', methods=['GET'])
@jwt_required()
def get_chats():
    """
    Получение списка чатов текущего пользователя
    GET /api/chats
    Header: Authorization: Bearer <token>
    """
    try:
        user_id = get_jwt_identity()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT c.* FROM chats c
            JOIN chat_members cm ON c.id = cm.chat_id
            WHERE cm.user_id = ?
            ORDER BY c.created_at DESC
        ''', (user_id,))
        
        chats = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'chats': chats
        }), 200
    
    except Exception as e:
        print(f'[ERROR] get_chats: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages', methods=['GET'])
@jwt_required()
def get_messages():
    """
    Получение сообщений из чата
    GET /api/messages?chat_id=1
    Header: Authorization: Bearer <token>
    """
    try:
        user_id = get_jwt_identity()
        chat_id = request.args.get('chat_id', type=int)
        
        if not chat_id:
            return jsonify({'error': 'chat_id is required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT m.*, u.name, u.avatar_url FROM messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.chat_id = ?
            ORDER BY m.created_at ASC
        ''', (chat_id,))
        
        messages = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'messages': messages
        }), 200
    
    except Exception as e:
        print(f'[ERROR] get_messages: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages', methods=['POST'])
@jwt_required()
def send_message():
    """
    Отправка сообщения в чат
    POST /api/messages
    Body: {"chat_id": 1, "content": "Hello"}
    Header: Authorization: Bearer <token>
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        chat_id = data.get('chat_id')
        content = data.get('content', '').strip()
        
        if not chat_id or not content:
            return jsonify({'error': 'chat_id and content are required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO messages (chat_id, user_id, content) VALUES (?, ?, ?)',
            (chat_id, user_id, content)
        )
        conn.commit()
        
        cursor.execute('SELECT last_insert_rowid() as id')
        message_id = cursor.fetchone()['id']
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'message_id': message_id
        }), 201
    
    except Exception as e:
        print(f'[ERROR] send_message: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ============================================================================
# МАРШРУТЫ ПРОФИЛЯ
# ============================================================================

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """
    Получение профиля текущего пользователя
    GET /api/profile
    Header: Authorization: Bearer <token>
    """
    try:
        user_id = get_jwt_identity()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'status': 'ok',
            'user': dict(user)
        }), 200
    
    except Exception as e:
        print(f'[ERROR] get_profile: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    """
    Обновление профиля пользователя
    PUT /api/profile
    Body: {"name": "John", "phone": "+1234567890", "bio": "Hello", "avatar_url": "https://..."}
    Header: Authorization: Bearer <token>
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        bio = data.get('bio', '').strip()
        avatar_url = data.get('avatar_url', '').strip()
        apartment = data.get('apartment', '').strip()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users SET name = ?, phone = ?, bio = ?, avatar_url = ?, apartment = ?
            WHERE id = ?
        ''', (name, phone, bio, avatar_url, apartment, user_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'message': 'Profile updated'
        }), 200
    
    except Exception as e:
        print(f'[ERROR] update_profile: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ============================================================================
# МАРШРУТЫ ЗДОРОВЬЯ И ИНФОРМАЦИИ
# ============================================================================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'Padik Messenger Backend',
        'version': '2.0'
    }), 200

@app.route('/', methods=['GET'])
def index():
    """API информация"""
    return jsonify({
        'name': 'Padik Messenger Backend',
        'version': '2.0',
        'description': 'Flask backend для мессенджера Padik',
        'endpoints': {
            'auth': [
                'POST /check_email - Проверка существования email',
                'POST /send_code - Отправка кода подтверждения',
                'POST /verify_code - Проверка кода и получение токена',
                'GET /auth - HTML страница авторизации'
            ],
            'chats': [
                'GET /api/chats - Получение списка чатов (требует токен)',
                'GET /api/messages - Получение сообщений (требует токен)',
                'POST /api/messages - Отправка сообщения (требует токен)'
            ],
            'profile': [
                'GET /api/profile - Получение профиля (требует токен)',
                'PUT /api/profile - Обновление профиля (требует токен)'
            ],
            'health': [
                'GET /health - Health check',
                'GET / - Информация об API'
            ]
        }
    }), 200

# ============================================================================
# ЗАПУСК ПРИЛОЖЕНИЯ
# ============================================================================

if __name__ == '__main__':
    print('[STARTUP] Padik Backend starting...')
    print('[STARTUP] Database: ' + DB_PATH)
    print('[STARTUP] CORS enabled for all origins')
    print('[STARTUP] JWT enabled')
    
    # Запускаем приложение
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5000)),
        debug=os.getenv('FLASK_ENV', 'development') == 'development'
    )
