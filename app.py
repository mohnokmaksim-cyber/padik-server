import os
import uuid
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

CORS(app)

# MongoDB Connection
MONGODB_URI = os.getenv('MONGODB_URI')
client = MongoClient(MONGODB_URI)
db = client['padik_messenger']

# Collections
users_collection = db['users']
codes_collection = db['codes']  # Временные коды для авторизации
chats_collection = db['chats']
messages_collection = db['messages']

# Create indexes
users_collection.create_index('email', unique=True)
users_collection.create_index('access_token')  # ✅ NEW: Индекс для быстрого поиска по токену
codes_collection.create_index('email')
codes_collection.create_index('created_at', expireAfterSeconds=900)  # TTL: 15 минут
chats_collection.create_index([('user1_id', 1), ('user2_id', 1)], unique=True)
messages_collection.create_index('chat_id')

# Email Configuration
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASS = os.getenv('EMAIL_PASS')
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587

print(f"[STARTUP] EMAIL_USER: {EMAIL_USER}")
print(f"[STARTUP] EMAIL_PASS configured: {bool(EMAIL_PASS)}")
print(f"[STARTUP] MONGODB_URI: {MONGODB_URI[:50]}...")

# ─── Helper Functions ───────────────────────────────────────────────────────

def normalize_email(email):
    """Нормализация email: lowercase + strip"""
    return email.strip().lower()

def generate_verification_code():
    """Генерирует 6-значный код подтверждения"""
    return ''.join(random.choices(string.digits, k=6))

def generate_access_token():
    """✅ NEW: Генерирует уникальный access token"""
    return str(uuid.uuid4())

def send_verification_email(email, code):
    """Отправляет код подтверждения на email"""
    try:
        print(f"[EMAIL] Начинаю отправку кода на {email}")
        
        if not EMAIL_USER or not EMAIL_PASS:
            print(f"[EMAIL ERROR] Учетные данные не настроены!")
            return False
        
        # Создаем сообщение
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Padik - Код подтверждения'
        msg['From'] = EMAIL_USER
        msg['To'] = email
        
        # HTML шаблон письма
        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                <div style="max-width: 500px; margin: 0 auto; background-color: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h2 style="color: #1A56DB; text-align: center; margin-bottom: 20px;">Padik Messenger</h2>
                    
                    <p style="color: #333; font-size: 16px; margin-bottom: 20px;">
                        Здравствуйте!
                    </p>
                    
                    <p style="color: #666; font-size: 14px; margin-bottom: 20px;">
                        Вы запросили вход в приложение Padik. Используйте код подтверждения ниже:
                    </p>
                    
                    <div style="background-color: #1A56DB; color: white; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 20px;">
                        <p style="font-size: 32px; font-weight: bold; margin: 0; letter-spacing: 5px;">
                            {code}
                        </p>
                    </div>
                    
                    <p style="color: #999; font-size: 12px; text-align: center; margin-bottom: 20px;">
                        Код действует 15 минут
                    </p>
                    
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                    
                    <p style="color: #999; font-size: 12px; text-align: center;">
                        Если вы не запрашивали этот код, проигнорируйте это письмо.
                    </p>
                </div>
            </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))
        
        print(f"[EMAIL] Подключаюсь к SMTP серверу {SMTP_HOST}:{SMTP_PORT}")
        # Отправляем письмо
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        
        print(f"[EMAIL SUCCESS] Код успешно отправлен на {email}")
        return True
    
    except Exception as e:
        print(f"[EMAIL ERROR] Ошибка при отправке письма: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def token_required(f):
    """Декоратор для проверки токена"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        # Ищем пользователя с таким токеном
        user = users_collection.find_one({'access_token': token})
        if not user:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        request.user_id = str(user['_id'])
        request.email = user['email']
        return f(*args, **kwargs)
    
    return decorated

# ─── Routes ────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Padik server is running'}), 200

# ─── Authentication Endpoints (Telegram-like) ───────────────────────────────

@app.route('/send_code', methods=['POST', 'OPTIONS'])
def send_code():
    """
    Шаг 1: Отправка кода на email
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response, 200
    
    try:
        data = request.get_json()
        email = normalize_email(data.get('email', ''))
        
        print(f"\n[SEND_CODE] Запрос на отправку кода для: {email}")
        
        if not email:
            print(f"[SEND_CODE ERROR] Email пуст")
            return jsonify({'error': 'Email is required'}), 400
        
        if '@' not in email:
            print(f"[SEND_CODE ERROR] Неверный формат email")
            return jsonify({'error': 'Invalid email format'}), 400
        
        # Генерируем код
        code = generate_verification_code()
        print(f"[SEND_CODE] Сгенерирован код: {code}")
        
        # Удаляем старые коды для этого email
        print(f"[SEND_CODE] Удаляю старые коды для {email}")
        codes_collection.delete_many({'email': email})
        
        # Сохраняем новый код в БД
        print(f"[SEND_CODE] Сохраняю новый код в БД")
        codes_collection.insert_one({
            'email': email,
            'code': code,
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(minutes=15)
        })
        print(f"[SEND_CODE] Код сохранен в БД")
        
        # Отправляем письмо
        print(f"[SEND_CODE] Отправляю письмо на {email}")
        email_sent = send_verification_email(email, code)
        
        if not email_sent:
            print(f"[SEND_CODE ERROR] Не удалось отправить письмо")
            return jsonify({
                'error': 'Could not send verification email. Please try again later.',
                'code': 'EMAIL_SEND_FAILED'
            }), 500
        
        print(f"[SEND_CODE SUCCESS] Код успешно отправлен на {email}")
        response = jsonify({
            'status': 'ok',
            'message': 'Verification code sent to email',
            'code': code  # Только для тестирования! Удалить в продакшене
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"[SEND_CODE EXCEPTION] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/verify_code', methods=['POST', 'OPTIONS'])
def verify_code():
    """
    Шаг 2: Проверка кода и определение действия (login или register)
    ✅ NEW: Генерирует и возвращает access_token
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response, 200
    
    try:
        data = request.get_json()
        email = normalize_email(data.get('email', ''))
        code = data.get('code', '').strip()
        
        print(f"\n[VERIFY_CODE] Проверка кода для: {email}")
        print(f"[VERIFY_CODE] Введенный код: {code}")
        
        if not email or not code:
            print(f"[VERIFY_CODE ERROR] Email или код пусты")
            return jsonify({'error': 'Email and code are required'}), 400
        
        # Ищем код в БД
        print(f"[VERIFY_CODE] Ищу код в коллекции codes")
        code_record = codes_collection.find_one({'email': email})
        
        if not code_record:
            print(f"[VERIFY_CODE ERROR] Код не найден для {email}")
            return jsonify({'error': 'No verification code found for this email'}), 400
        
        # Проверяем, совпадает ли код
        if code_record['code'] != code:
            print(f"[VERIFY_CODE ERROR] Код не совпадает! Ожидается: {code_record['code']}, получено: {code}")
            return jsonify({'error': 'Invalid verification code'}), 400
        
        print(f"[VERIFY_CODE] Код совпадает!")
        
        # Проверяем, не истек ли код
        if datetime.utcnow() > code_record['expires_at']:
            print(f"[VERIFY_CODE ERROR] Код истек! Время истечения: {code_record['expires_at']}")
            return jsonify({'error': 'Verification code has expired'}), 400
        
        print(f"[VERIFY_CODE] Код валиден!")
        
        # ─── ГЛАВНАЯ ЛОГИКА: Проверяем, есть ли пользователь ───
        print(f"[VERIFY_CODE] Ищу пользователя {email} в коллекции users")
        user = users_collection.find_one({'email': email})
        
        # ✅ NEW: Генерируем access token
        access_token = generate_access_token()
        print(f"[VERIFY_CODE] Сгенерирован access_token: {access_token}")
        
        if user:
            # Сценарий А: Авторизация (пользователь уже существует)
            print(f"[VERIFY_CODE] Пользователь {email} опознан как СТАРЫЙ (авторизация)")
            
            # ✅ NEW: Сохраняем токен в БД
            users_collection.update_one(
                {'_id': user['_id']},
                {
                    '$set': {
                        'access_token': access_token,
                        'last_login': datetime.utcnow()
                    }
                }
            )
            print(f"[VERIFY_CODE] Токен сохранен в БД для пользователя {email}")
            
            # Удаляем использованный код
            codes_collection.delete_one({'email': email})
            
            response = jsonify({
                'status': 'ok',
                'action': 'login',
                'token': access_token,  # ✅ NEW: Возвращаем токен
                'user': {
                    'id': str(user['_id']),
                    'email': user['email'],
                    'name': user.get('name'),
                    'avatar_url': user.get('avatar_url', ''),
                    'is_profile_complete': user.get('is_profile_complete', False)
                }
            })
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response, 200
        
        else:
            # Сценарий Б: Регистрация (новый пользователь)
            print(f"[VERIFY_CODE] Пользователь {email} опознан как НОВЫЙ (регистрация)")
            
            # Удаляем использованный код
            codes_collection.delete_one({'email': email})
            
            response = jsonify({
                'status': 'ok',
                'action': 'register',
                'email': email,
                'token': access_token  # ✅ NEW: Возвращаем токен и для регистрации
            })
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response, 200
    
    except Exception as e:
        print(f"[VERIFY_CODE EXCEPTION] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/verify_session', methods=['POST', 'OPTIONS'])
def verify_session():
    """
    ✅ NEW: Проверка сохраненной сессии
    
    Логика:
    1. Приложение отправляет сохраненный токен
    2. Сервер ищет пользователя с таким токеном
    3. Если нашел: возвращает данные пользователя
    4. Если не нашел: возвращает ошибку
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response, 200
    
    try:
        data = request.get_json()
        token = data.get('token', '').strip()
        
        print(f"\n[VERIFY_SESSION] Проверка сессии с токеном: {token[:20]}...")
        
        if not token:
            print(f"[VERIFY_SESSION ERROR] Токен пуст")
            return jsonify({'error': 'Token is required'}), 400
        
        # Ищем пользователя с таким токеном
        print(f"[VERIFY_SESSION] Ищу пользователя в БД")
        user = users_collection.find_one({'access_token': token})
        
        if not user:
            print(f"[VERIFY_SESSION ERROR] Пользователь с таким токеном не найден")
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        email = user['email']
        print(f"[VERIFY_SESSION SUCCESS] Пользователь {email} зашел по токену")
        
        # ✅ NEW: Обновляем дату последнего входа
        users_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'last_login': datetime.utcnow()}}
        )
        print(f"[VERIFY_SESSION] Обновлена дата последнего входа для {email}")
        
        response = jsonify({
            'status': 'ok',
            'user': {
                'id': str(user['_id']),
                'email': user['email'],
                'name': user.get('name'),
                'avatar_url': user.get('avatar_url', ''),
                'bio': user.get('bio', ''),
                'is_profile_complete': user.get('is_profile_complete', False),
                'is_online': user.get('is_online', False),
                'age': user.get('age')
            }
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"[VERIFY_SESSION EXCEPTION] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/register', methods=['POST', 'OPTIONS'])
def register():
    """
    Шаг 3: Регистрация нового пользователя (заполнение профиля)
    ✅ NEW: Принимает токен и сохраняет его в БД
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response, 200
    
    try:
        data = request.get_json()
        email = normalize_email(data.get('email', ''))
        name = data.get('name', '').strip()
        date_of_birth = data.get('date_of_birth', '').strip()
        token = data.get('token', '').strip()  # ✅ NEW: Получаем токен
        
        print(f"\n[REGISTER] Регистрация нового пользователя: {email}")
        print(f"[REGISTER] Имя: {name}, DOB: {date_of_birth}")
        print(f"[REGISTER] Токен: {token[:20]}...")
        
        if not email or not name or not date_of_birth or not token:
            print(f"[REGISTER ERROR] Отсутствуют обязательные поля")
            return jsonify({'error': 'Email, name, date_of_birth, and token are required'}), 400
        
        # Проверяем, не существует ли уже такой пользователь
        if users_collection.find_one({'email': email}):
            print(f"[REGISTER ERROR] Пользователь {email} уже существует")
            return jsonify({'error': 'User with this email already exists'}), 400
        
        # Парсим дату рождения
        try:
            dob = datetime.strptime(date_of_birth, '%Y-%m-%d')
            age = (datetime.utcnow() - dob).days // 365
            
            if age < 10:
                print(f"[REGISTER ERROR] Пользователь слишком молодой: {age} лет")
                return jsonify({'error': 'You must be at least 10 years old'}), 400
        except ValueError:
            print(f"[REGISTER ERROR] Неверный формат даты: {date_of_birth}")
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
        
        # Создаем нового пользователя
        print(f"[REGISTER] Создаю нового пользователя в БД")
        new_user = {
            'email': email,
            'name': name,
            'date_of_birth': dob,
            'age': age,
            'avatar_url': '',
            'bio': '',
            'is_profile_complete': True,
            'is_online': True,
            'access_token': token,  # ✅ NEW: Сохраняем токен
            'created_at': datetime.utcnow(),
            'last_login': datetime.utcnow()
        }
        
        result = users_collection.insert_one(new_user)
        user_id = result.inserted_id
        
        print(f"[REGISTER SUCCESS] Пользователь создан с ID: {user_id}")
        print(f"[REGISTER] Токен сохранен для пользователя {email}")
        
        response = jsonify({
            'status': 'ok',
            'message': 'User registered successfully',
            'token': token,  # ✅ Возвращаем тот же токен
            'user': {
                'id': str(user_id),
                'email': email,
                'name': name,
                'age': age,
                'avatar_url': '',
                'is_profile_complete': True
            }
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"[REGISTER EXCEPTION] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/logout', methods=['POST', 'OPTIONS'])
@token_required
def logout():
    """
    ✅ NEW: Выход из аккаунта
    
    Логика:
    1. Удаляет токен из БД
    2. Приложение удаляет токен из памяти
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response, 200
    
    try:
        from bson import ObjectId
        
        print(f"\n[LOGOUT] Выход пользователя: {request.email}")
        
        # Удаляем токен из БД
        users_collection.update_one(
            {'_id': ObjectId(request.user_id)},
            {'$set': {'access_token': None}}
        )
        
        print(f"[LOGOUT SUCCESS] Токен удален для пользователя {request.email}")
        
        response = jsonify({
            'status': 'ok',
            'message': 'Logged out successfully'
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"[LOGOUT EXCEPTION] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/me', methods=['GET', 'OPTIONS'])
@token_required
def get_me():
    """Получить профиль текущего пользователя"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response, 200
    
    try:
        from bson import ObjectId
        user = users_collection.find_one({'_id': ObjectId(request.user_id)})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        response = jsonify({
            'status': 'ok',
            'user': {
                'id': str(user['_id']),
                'email': user['email'],
                'name': user.get('name'),
                'age': user.get('age'),
                'avatar_url': user.get('avatar_url', ''),
                'bio': user.get('bio', ''),
                'is_profile_complete': user.get('is_profile_complete', False),
                'is_online': user.get('is_online', False),
                'created_at': user.get('created_at'),
                'last_login': user.get('last_login')
            }
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"[GET_ME ERROR] {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


# ─── Chat Endpoints ────────────────────────────────────────────────────────

@app.route('/chats', methods=['GET', 'OPTIONS'])
@token_required
def get_chats():
    """Получить список чатов пользователя"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response, 200
    
    try:
        from bson import ObjectId
        user_id = ObjectId(request.user_id)
        
        chats = list(chats_collection.find({
            '$or': [
                {'user1_id': user_id},
                {'user2_id': user_id}
            ]
        }).sort('last_message_time', -1))
        
        result = []
        for chat in chats:
            result.append({
                'id': str(chat['_id']),
                'user1_id': str(chat['user1_id']),
                'user2_id': str(chat['user2_id']),
                'last_message': chat.get('last_message', ''),
                'last_message_time': chat.get('last_message_time')
            })
        
        response = jsonify({'status': 'ok', 'chats': result})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"[GET_CHATS ERROR] {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
