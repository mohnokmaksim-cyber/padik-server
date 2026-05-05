"""
Padik Messenger Backend - Flask приложение
Поддерживает авторизацию через коды подтверждения, чаты и сообщения
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import sqlite3
import secrets
import string
from datetime import datetime, timedelta
import os

# Инициализация Flask приложения
app = Flask(__name__)

# Конфигурация JWT
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'padik-secret-key-change-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)

# Инициализация JWT
jwt = JWTManager(app)

# Включаем CORS для всех маршрутов
CORS(app, resources={r"/*": {"origins": "*"}})

# Путь к базе данных
DB_PATH = 'padik.db'

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
# ============================================================================

def init_db():
    """Инициализация SQLite базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            apartment TEXT,
            phone TEXT,
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
            name TEXT NOT NULL,
            description TEXT,
            type TEXT DEFAULT 'group',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    
    conn.commit()
    conn.close()
    print('[DB] База данных инициализирована')

# Инициализируем БД при запуске
init_db()

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def generate_code(length=4):
    """Генерация случайного кода подтверждения"""
    return ''.join(secrets.choice(string.digits) for _ in range(length))

def get_db_connection():
    """Получение подключения к БД"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================================
# МАРШРУТЫ АВТОРИЗАЦИИ
# ============================================================================

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
        code = generate_code(4)
        
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
        
        # Выводим код в консоль (вместо отправки по SMTP)
        print(f'[SEND_CODE] Email: {email}, Code: {code}')
        
        return jsonify({
            'status': 'ok',
            'message': f'Code sent to {email}',
            'debug_code': code  # Убрать в production!
        }), 200
    
    except Exception as e:
        print(f'[ERROR] send_code: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/verify_code', methods=['POST'])
def verify_code():
    """
    Проверка кода подтверждения и выдача JWT-токена
    POST /verify_code
    Body: {"email": "user@example.com", "code": "1234"}
    """
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return jsonify({'error': 'Email and code are required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Проверяем код
        cursor.execute(
            'SELECT * FROM verification_codes WHERE email = ? AND code = ? AND expires_at > ?',
            (email, code, datetime.now())
        )
        code_record = cursor.fetchone()
        
        if not code_record:
            conn.close()
            return jsonify({'error': 'Invalid or expired code'}), 401
        
        # Удаляем использованный код
        cursor.execute('DELETE FROM verification_codes WHERE id = ?', (code_record['id'],))
        
        # Проверяем/создаем пользователя
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        
        if not user:
            # Создаем нового пользователя
            cursor.execute(
                'INSERT INTO users (email, name) VALUES (?, ?)',
                (email, email.split('@')[0])
            )
            conn.commit()
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            user = cursor.fetchone()
        
        conn.close()
        
        # Генерируем JWT-токен
        token = create_access_token(identity=user['id'])
        
        print(f'[VERIFY_CODE] ✅ User {email} authenticated, Token: {token[:20]}...')
        
        return jsonify({
            'status': 'ok',
            'token': token,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'name': user['name']
            }
        }), 200
    
    except Exception as e:
        print(f'[ERROR] verify_code: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ============================================================================
# МАРШРУТ АВТОРИЗАЦИИ (HTML страница)
# ============================================================================

@app.route('/auth', methods=['GET'])
def auth_page():
    """
    HTML страница авторизации для WebView
    """
    html = '''
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Padik Web - Авторизация</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }
            .container {
                background: rgba(15, 20, 51, 0.8);
                border: 1px solid #00D9FF;
                border-radius: 12px;
                padding: 40px;
                max-width: 400px;
                width: 100%;
                box-shadow: 0 0 30px rgba(0, 217, 255, 0.2);
            }
            .logo {
                text-align: center;
                margin-bottom: 30px;
            }
            .logo h1 {
                font-size: 48px;
                color: #00D9FF;
                text-shadow: 0 0 20px rgba(0, 217, 255, 0.5);
                margin-bottom: 10px;
            }
            .logo p {
                color: #999;
                font-size: 14px;
            }
            .form-group {
                margin-bottom: 20px;
            }
            label {
                display: block;
                color: #ccc;
                font-size: 14px;
                font-weight: 600;
                margin-bottom: 8px;
            }
            input {
                width: 100%;
                padding: 12px 16px;
                background: #1a1f3a;
                border: 1px solid #00D9FF;
                border-radius: 8px;
                color: #fff;
                font-size: 16px;
                outline: none;
            }
            input:focus {
                box-shadow: 0 0 10px rgba(0, 217, 255, 0.3);
            }
            button {
                width: 100%;
                padding: 14px;
                background: #00D9FF;
                color: #0a0e27;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: 700;
                cursor: pointer;
                margin-top: 20px;
                box-shadow: 0 0 20px rgba(0, 217, 255, 0.3);
                transition: all 0.3s ease;
            }
            button:hover {
                transform: translateY(-2px);
                box-shadow: 0 0 30px rgba(0, 217, 255, 0.5);
            }
            button:active {
                transform: translateY(0);
            }
            .message {
                text-align: center;
                margin-top: 20px;
                font-size: 14px;
                color: #666;
            }
            .success {
                color: #00D9FF;
            }
            .error {
                color: #EF4444;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <h1>P2</h1>
                <p>Padik Messenger</p>
            </div>
            
            <div id="emailStep">
                <form onsubmit="handleSendCode(event)">
                    <div class="form-group">
                        <label for="email">Email</label>
                        <input type="email" id="email" placeholder="example@mail.com" required>
                    </div>
                    <button type="submit">Получить код</button>
                </form>
            </div>
            
            <div id="codeStep" style="display: none;">
                <form onsubmit="handleVerifyCode(event)">
                    <div class="form-group">
                        <label for="code">Код подтверждения</label>
                        <input type="text" id="code" placeholder="0000" maxlength="4" required>
                    </div>
                    <button type="submit">Войти</button>
                    <button type="button" onclick="backToEmail()" style="background: transparent; color: #00D9FF; border: 1px solid #00D9FF; margin-top: 10px;">← Назад</button>
                </form>
            </div>
            
            <div id="message" class="message"></div>
        </div>
        
        <script>
            let userEmail = '';
            
            async function handleSendCode(event) {
                event.preventDefault();
                const email = document.getElementById('email').value;
                userEmail = email;
                
                try {
                    const response = await fetch('/send_code', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        document.getElementById('emailStep').style.display = 'none';
                        document.getElementById('codeStep').style.display = 'block';
                        showMessage('Код отправлен на вашу почту', 'success');
                    } else {
                        showMessage(data.error || 'Ошибка', 'error');
                    }
                } catch (error) {
                    showMessage('Ошибка подключения: ' + error.message, 'error');
                }
            }
            
            async function handleVerifyCode(event) {
                event.preventDefault();
                const code = document.getElementById('code').value;
                
                try {
                    const response = await fetch('/verify_code', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email: userEmail, code })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok && data.token) {
                        showMessage('✅ Вход выполнен!', 'success');
                        
                        // Отправляем токен в приложение через postMessage
                        if (window.ReactNativeWebView) {
                            window.ReactNativeWebView.postMessage(JSON.stringify({
                                type: 'AUTH_SUCCESS',
                                token: data.token
                            }));
                        } else {
                            // Для тестирования в браузере
                            localStorage.setItem('auth_token', data.token);
                            console.log('Token saved:', data.token);
                        }
                    } else {
                        showMessage(data.error || 'Неверный код', 'error');
                    }
                } catch (error) {
                    showMessage('Ошибка подключения: ' + error.message, 'error');
                }
            }
            
            function backToEmail() {
                document.getElementById('emailStep').style.display = 'block';
                document.getElementById('codeStep').style.display = 'none';
                document.getElementById('message').textContent = '';
            }
            
            function showMessage(text, type) {
                const msg = document.getElementById('message');
                msg.textContent = text;
                msg.className = 'message ' + type;
            }
        </script>
    </body>
    </html>
    '''
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}

# ============================================================================
# МАРШРУТЫ ЧАТОВ
# ============================================================================

@app.route('/api/chats', methods=['GET'])
@jwt_required()
def get_chats():
    """
    Получение списка чатов для пользователя
    GET /api/chats
    Header: Authorization: Bearer <token>
    """
    try:
        user_id = get_jwt_identity()
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получаем чаты, в которых участвует пользователь
        cursor.execute('''
            SELECT c.* FROM chats c
            JOIN chat_members cm ON c.id = cm.chat_id
            WHERE cm.user_id = ?
            ORDER BY c.created_at DESC
        ''', (user_id,))
        
        chats = [dict(row) for row in cursor.fetchall()]
        
        # Если нет чатов, создаем тестовые
        if not chats:
            test_chats = [
                ('Общий чат', 'Общее обсуждение'),
                ('Курилка', 'Неформальное общение'),
                ('Админка', 'Для администраторов')
            ]
            
            for name, desc in test_chats:
                cursor.execute(
                    'INSERT INTO chats (name, description) VALUES (?, ?)',
                    (name, desc)
                )
                conn.commit()
                chat_id = cursor.lastrowid
                
                # Добавляем пользователя в чат
                cursor.execute(
                    'INSERT INTO chat_members (chat_id, user_id) VALUES (?, ?)',
                    (chat_id, user_id)
                )
                conn.commit()
            
            # Получаем созданные чаты
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

# ============================================================================
# МАРШРУТЫ СООБЩЕНИЙ
# ============================================================================

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
        
        # Получаем сообщения
        cursor.execute('''
            SELECT m.id, m.chat_id, m.user_id, m.content, m.created_at,
                   u.email, u.name
            FROM messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.chat_id = ?
            ORDER BY m.created_at ASC
            LIMIT 100
        ''', (chat_id,))
        
        messages = []
        for row in cursor.fetchall():
            messages.append({
                'id': row['id'],
                'chat_id': row['chat_id'],
                'user_id': row['user_id'],
                'content': row['content'],
                'created_at': row['created_at'],
                'user': {
                    'id': row['user_id'],
                    'email': row['email'],
                    'name': row['name']
                }
            })
        
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
        
        # Сохраняем сообщение
        cursor.execute(
            'INSERT INTO messages (chat_id, user_id, content) VALUES (?, ?, ?)',
            (chat_id, user_id, content)
        )
        conn.commit()
        message_id = cursor.lastrowid
        
        # Получаем сохраненное сообщение
        cursor.execute('''
            SELECT m.id, m.chat_id, m.user_id, m.content, m.created_at,
                   u.email, u.name
            FROM messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.id = ?
        ''', (message_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        message = {
            'id': row['id'],
            'chat_id': row['chat_id'],
            'user_id': row['user_id'],
            'content': row['content'],
            'created_at': row['created_at'],
            'user': {
                'id': row['user_id'],
                'email': row['email'],
                'name': row['name']
            }
        }
        
        print(f'[MESSAGE] User {user_id} sent message to chat {chat_id}: {content}')
        
        return jsonify({
            'status': 'ok',
            'message': message
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
    Получение профиля пользователя
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
    Body: {"name": "John", "apartment": "101", "phone": "+1234567890"}
    Header: Authorization: Bearer <token>
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Обновляем профиль
        cursor.execute('''
            UPDATE users
            SET name = ?, apartment = ?, phone = ?
            WHERE id = ?
        ''', (
            data.get('name'),
            data.get('apartment'),
            data.get('phone'),
            user_id
        ))
        conn.commit()
        
        # Получаем обновленный профиль
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        print(f'[PROFILE] User {user_id} updated profile')
        
        return jsonify({
            'status': 'ok',
            'user': dict(user)
        }), 200
    
    except Exception as e:
        print(f'[ERROR] update_profile: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.route('/health', methods=['GET'])
def health():
    """Health check маршрут"""
    return jsonify({'status': 'ok', 'message': 'Padik Backend is running'}), 200

# ============================================================================
# ГЛАВНАЯ СТРАНИЦА
# ============================================================================

@app.route('/', methods=['GET'])
def index():
    """Главная страница с информацией об API"""
    return jsonify({
        'name': 'Padik Messenger Backend',
        'version': '1.0.0',
        'endpoints': {
            'auth': {
                'POST /send_code': 'Отправка кода подтверждения',
                'POST /verify_code': 'Проверка кода и получение токена',
                'GET /auth': 'HTML страница авторизации'
            },
            'chats': {
                'GET /api/chats': 'Получение списка чатов (требует токен)'
            },
            'messages': {
                'GET /api/messages': 'Получение сообщений (требует токен)',
                'POST /api/messages': 'Отправка сообщения (требует токен)'
            },
            'profile': {
                'GET /api/profile': 'Получение профиля (требует токен)',
                'PUT /api/profile': 'Обновление профиля (требует токен)'
            }
        }
    }), 200

# ============================================================================
# ОБРАБОТКА ОШИБОК
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# ============================================================================
# ЗАПУСК ПРИЛОЖЕНИЯ
# ============================================================================

if __name__ == '__main__':
    print('[STARTUP] Padik Backend starting...')
    print('[STARTUP] Database: ' + DB_PATH)
    print('[STARTUP] CORS enabled for all origins')
    print('[STARTUP] JWT enabled')
    app.run(debug=True, host='0.0.0.0', port=5000)
