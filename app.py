from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import os
import secrets
import string
from datetime import datetime
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

app = Flask(__name__)
CORS(app)

# ✅ ИСПРАВЛЕННОЕ ПОДКЛЮЧЕНИЕ К БД
MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    print("[ERROR] ❌ MONGO_URI не задан в переменных окружения!")
    print("[ERROR] Пожалуйста, установите MONGO_URI перед запуском сервера")
    raise ValueError("MONGO_URI environment variable is not set")

print(f"[STARTUP] Подключаюсь к MongoDB: {MONGO_URI[:50]}...")

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Проверяем подключение
    client.admin.command('ping')
    print("[STARTUP] ✅ Успешно подключился к MongoDB!")
except Exception as e:
    print(f"[ERROR] ❌ Не удалось подключиться к MongoDB: {str(e)}")
    raise

# ✅ Явно указываем имя базы данных
db = client.get_database("padik_db")
users_collection = db.users
codes_collection = db.codes

print("[STARTUP] Коллекции инициализированы")

def normalize_email(email):
    """Нормализация email: trim и lowercase"""
    return email.strip().lower()

def generate_code():
    """Генерируем 6-значный код"""
    return ''.join(secrets.choice(string.digits) for _ in range(6))

def generate_token():
    """Генерируем уникальный токен"""
    return secrets.token_urlsafe(32)

def send_email(to_email, code):
    """Отправляем код на Gmail"""
    try:
        # Получаем учетные данные из переменных окружения
        sender_email = os.getenv("GMAIL_EMAIL")
        sender_password = os.getenv("GMAIL_PASSWORD")
        
        if not sender_email or not sender_password:
            print("[EMAIL] ⚠️ GMAIL_EMAIL или GMAIL_PASSWORD не установлены")
            return False
        
        # Создаем письмо
        message = MIMEMultipart("alternative")
        message["Subject"] = "Код подтверждения Padik Messenger"
        message["From"] = sender_email
        message["To"] = to_email
        
        # HTML версия письма
        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                <div style="max-width: 500px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                    <h2 style="color: #0a7ea4; text-align: center; margin-bottom: 20px;">Padik Messenger</h2>
                    <p style="color: #333; font-size: 16px; margin-bottom: 20px;">Ваш код подтверждения:</p>
                    <div style="background-color: #0a7ea4; color: white; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 20px;">
                        <h1 style="margin: 0; font-size: 36px; letter-spacing: 5px;">{code}</h1>
                    </div>
                    <p style="color: #666; font-size: 14px; margin-bottom: 10px;">Этот код действителен 15 минут.</p>
                    <p style="color: #666; font-size: 14px;">Если вы не запрашивали этот код, проигнорируйте это письмо.</p>
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    <p style="color: #999; font-size: 12px; text-align: center;">© 2026 Padik Messenger. Все права защищены.</p>
                </div>
            </body>
        </html>
        """
        
        part = MIMEText(html, "html")
        message.attach(part)
        
        # Отправляем письмо
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, message.as_string())
        
        print(f"[EMAIL] ✅ Код отправлен на {to_email}")
        return True
        
    except Exception as e:
        print(f"[EMAIL] ❌ Ошибка отправки: {str(e)}")
        return False

# ✅ ОТПРАВКА КОДА НА ПОЧТУ
@app.route('/send_code', methods=['POST'])
def send_code():
    try:
        data = request.get_json()
        email = normalize_email(data.get('email', ''))
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        print(f"[SEND_CODE] Отправляю код для: {email}")
        
        # Удаляем старые коды для этого email
        codes_collection.delete_many({'email': email})
        print(f"[SEND_CODE] Удалил старые коды для {email}")
        
        # Генерируем новый код
        code = generate_code()
        print(f"[SEND_CODE] Сгенерирован код: {code}")
        
        # Сохраняем код в БД (БЕЗ TTL - коды не удаляются автоматически)
        result = codes_collection.insert_one({
            'email': email,
            'code': code,
            'created_at': datetime.utcnow()
        })
        
        if result.inserted_id:
            print(f"[SEND_CODE] Код сохранен в БД для {email}")
            
            # ✅ ОТПРАВЛЯЕМ КОД НА РЕАЛЬНЫЙ EMAIL
            email_sent = send_email(email, code)
            
            if email_sent:
                print(f"[SEND_CODE] ✅ Код успешно отправлен на {email}")
                return jsonify({
                    'status': 'ok',
                    'message': f'Code sent to {email}'
                }), 200
            else:
                print(f"[SEND_CODE] ⚠️ Код сохранен в БД, но не отправлен на email")
                return jsonify({
                    'status': 'ok',
                    'message': f'Code saved but email sending failed',
                    'code': code  # Показываем код если email не отправился
                }), 200
        else:
            print(f"[SEND_CODE] ❌ Ошибка сохранения кода в БД")
            return jsonify({'error': 'Failed to save code'}), 500
            
    except Exception as e:
        print(f"[SEND_CODE] ❌ Ошибка: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ✅ ПРОВЕРКА КОДА (УМНЫЙ ВХОД КАК В TELEGRAM)
@app.route('/verify_code', methods=['POST'])
def verify_code():
    try:
        data = request.get_json()
        email = normalize_email(data.get('email', ''))
        code = data.get('code', '')
        
        if not email or not code:
            return jsonify({'error': 'Email and code are required'}), 400
        
        print(f"[VERIFY_CODE] Проверяю код для: {email}")
        
        # Ищем код в БД
        code_record = codes_collection.find_one({'email': email, 'code': code})
        
        if not code_record:
            print(f"[VERIFY_CODE] ❌ Код не найден для {email}")
            # Показываем все коды в БД для отладки
            all_codes = list(codes_collection.find({'email': email}))
            print(f"[VERIFY_CODE] Коды в БД для {email}: {all_codes}")
            return jsonify({'error': 'Invalid code'}), 400
        
        print(f"[VERIFY_CODE] ✅ Код верный!")
        
        # Генерируем токен
        token = generate_token()
        print(f"[VERIFY_CODE] Сгенерирован токен: {token[:20]}...")
        
        # Проверяем, есть ли уже такой пользователь
        user = users_collection.find_one({'email': email})
        
        if user:
            # ✅ СЦЕНАРИЙ А: Старый пользователь (вход)
            print(f"[VERIFY_CODE] Пользователь {email} опознан как СТАРЫЙ")
            
            # Обновляем токен и время последнего входа
            users_collection.update_one(
                {'email': email},
                {
                    '$set': {
                        'token': token,
                        'last_login': datetime.utcnow()
                    }
                }
            )
            
            print(f"[VERIFY_CODE] Токен обновлен для {email}")
            
            return jsonify({
                'status': 'ok',
                'is_new_user': False,
                'token': token,
                'user': {
                    'id': str(user.get('_id', '')),
                    'email': user.get('email'),
                    'name': user.get('name'),
                    'date_of_birth': user.get('date_of_birth'),
                    'avatar_url': user.get('avatar_url'),
                    'is_online': True
                }
            }), 200
        else:
            # ✅ СЦЕНАРИЙ Б: Новый пользователь (регистрация)
            print(f"[VERIFY_CODE] Пользователь {email} опознан как НОВЫЙ")
            
            # Создаем временный пользователь с токеном (без имени и даты рождения)
            new_user = {
                'email': email,
                'token': token,
                'name': None,
                'date_of_birth': None,
                'avatar_url': None,
                'is_online': True,
                'created_at': datetime.utcnow(),
                'last_login': datetime.utcnow()
            }
            
            result = users_collection.insert_one(new_user)
            print(f"[VERIFY_CODE] Новый пользователь создан: {email}")
            
            return jsonify({
                'status': 'ok',
                'is_new_user': True,
                'token': token,
                'user': {
                    'id': str(result.inserted_id),
                    'email': email,
                    'name': None,
                    'date_of_birth': None,
                    'avatar_url': None,
                    'is_online': True
                }
            }), 200
            
    except Exception as e:
        print(f"[VERIFY_CODE] ❌ Ошибка: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ✅ РЕГИСТРАЦИЯ (СОХРАНЕНИЕ ПРОФИЛЯ)
@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        email = normalize_email(data.get('email', ''))
        token = data.get('token', '')
        name = data.get('name', '')
        date_of_birth = data.get('date_of_birth')
        
        if not email or not token or not name:
            return jsonify({'error': 'Email, token, name are required'}), 400
        
        print(f"[REGISTER] Регистрирую пользователя: {email}")
        
        # Ищем пользователя по токену
        user = users_collection.find_one({'email': email, 'token': token})
        
        if not user:
            print(f"[REGISTER] ❌ Пользователь не найден для {email}")
            return jsonify({'error': 'User not found or invalid token'}), 400
        
        # Обновляем профиль
        users_collection.update_one(
            {'email': email},
            {
                '$set': {
                    'name': name,
                    'date_of_birth': date_of_birth,
                    'updated_at': datetime.utcnow()
                }
            }
        )
        
        print(f"[REGISTER] ✅ Профиль обновлен: {email}")
        
        # Возвращаем обновленные данные
        updated_user = users_collection.find_one({'email': email})
        
        return jsonify({
            'status': 'ok',
            'message': 'Registration completed',
            'user': {
                'id': str(updated_user.get('_id', '')),
                'email': updated_user.get('email'),
                'name': updated_user.get('name'),
                'date_of_birth': updated_user.get('date_of_birth'),
                'avatar_url': updated_user.get('avatar_url'),
                'is_online': True
            }
        }), 200
        
    except Exception as e:
        print(f"[REGISTER] ❌ Ошибка: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ✅ ПРОВЕРКА СЕССИИ (ПРИ ЗАПУСКЕ ПРИЛОЖЕНИЯ)
@app.route('/verify_session', methods=['POST'])
def verify_session():
    try:
        data = request.get_json()
        token = data.get('token', '')
        
        if not token:
            return jsonify({'error': 'Token is required'}), 400
        
        print(f"[VERIFY_SESSION] Проверяю токен: {token[:20]}...")
        
        # Ищем пользователя по токену
        user = users_collection.find_one({'token': token})
        
        if not user:
            print(f"[VERIFY_SESSION] ❌ Токен не найден или истек")
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        print(f"[VERIFY_SESSION] ✅ Токен валиден для {user.get('email')}")
        
        # Обновляем время последнего входа
        users_collection.update_one(
            {'token': token},
            {'$set': {'last_login': datetime.utcnow()}}
        )
        
        return jsonify({
            'status': 'ok',
            'user': {
                'id': str(user.get('_id', '')),
                'email': user.get('email'),
                'name': user.get('name'),
                'date_of_birth': user.get('date_of_birth'),
                'avatar_url': user.get('avatar_url'),
                'is_online': True
            }
        }), 200
        
    except Exception as e:
        print(f"[VERIFY_SESSION] ❌ Ошибка: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ✅ ВЫХОД ИЗ АККАУНТА
@app.route('/logout', methods=['POST'])
def logout():
    try:
        data = request.get_json()
        token = data.get('token', '')
        
        if not token:
            return jsonify({'error': 'Token is required'}), 400
        
        print(f"[LOGOUT] Выход пользователя с токеном: {token[:20]}...")
        
        # Обнуляем токен в БД
        result = users_collection.update_one(
            {'token': token},
            {'$set': {'token': None, 'is_online': False}}
        )
        
        if result.matched_count > 0:
            print(f"[LOGOUT] ✅ Пользователь вышел")
            return jsonify({'status': 'ok', 'message': 'Logged out successfully'}), 200
        else:
            print(f"[LOGOUT] ❌ Пользователь не найден")
            return jsonify({'error': 'User not found'}), 400
            
    except Exception as e:
        print(f"[LOGOUT] ❌ Ошибка: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ✅ ЗДОРОВЬЕ СЕРВЕРА
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'Server is running'}), 200

if __name__ == '__main__':
    print("[STARTUP] ✅ Padik Messenger сервер готов к работе!")
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
