from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import os
import secrets
import string
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/padik_messenger")
client = MongoClient(MONGO_URI)
db = client.get_database()

users_collection = db.users
codes_collection = db.codes

# ✅ ГЛОБАЛЬНАЯ ЧИСТКА БД ПРИ ЗАПУСКЕ
print("[STARTUP] Очищаю базу данных...")
users_collection.delete_many({})
codes_collection.delete_many({})
print("[STARTUP] База данных очищена! Готово к тестированию.")

def normalize_email(email):
    """Нормализация email: trim и lowercase"""
    return email.strip().lower()

def generate_code():
    """Генерируем 6-значный код"""
    return ''.join(secrets.choice(string.digits) for _ in range(6))

def generate_token():
    """Генерируем уникальный токен"""
    return secrets.token_urlsafe(32)

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
            # В реальном приложении здесь отправляем email
            print(f"[SEND_CODE] 📧 Код отправлен на {email}: {code}")
            return jsonify({
                'status': 'ok',
                'message': f'Code sent to {email}',
                'code': code  # В тестировании показываем код
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
    print("[STARTUP] Запускаю Padik Messenger сервер...")
    app.run(debug=True, host='0.0.0.0', port=5000)
