#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Padik Messenger Backend v3.0 - Полностью переработанный
Полнофункциональный мессенджер с авторизацией, чатами, WebSocket и медиа
"""

import os
import json
import secrets
import string
import smtplib
import pyotp
import qrcode
import requests
import hashlib
from io import BytesIO
from datetime import datetime, timedelta
from urllib.parse import urlparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson import ObjectId

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# JWT конфигурация
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-this')
app.config['JWT_SECRET_KEY'] = JWT_SECRET_KEY
jwt = JWTManager(app)

# WebSocket
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ============================================================================
# MONGODB
# ============================================================================

MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    print('[ERROR] MONGO_URI не установлена!')
    exit(1)

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    
    # Парсим имя БД из MONGO_URI
    parsed = urlparse(MONGO_URI)
    db_name = parsed.path.lstrip('/')
    if not db_name:
        db_name = 'padik'
    
    db = client[db_name]
    print(f'[DB] ✅ MongoDB подключена к БД: {db_name}')
except Exception as e:
    print(f'[ERROR] Ошибка подключения к MongoDB: {e}')
    exit(1)

# Коллекции
users_col = db['users']
verification_codes_col = db['verification_codes']
chats_col = db['chats']
chat_members_col = db['chat_members']
messages_col = db['messages']
push_tokens_col = db['push_tokens']

# Индексы
users_col.create_index('email', unique=True)
verification_codes_col.create_index('expires_at', expireAfterSeconds=0)
messages_col.create_index('chat_id')
messages_col.create_index('created_at')

# ============================================================================
# SMTP КОНФИГУРАЦИЯ
# ============================================================================

# SMTP микросервис на Railway
SMTP_MICROSERVICE_URL = os.getenv('SMTP_MICROSERVICE_URL', 'https://web-production-4e5a.up.railway.app')
print(f'[SMTP] Микросервис: {SMTP_MICROSERVICE_URL}')

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def generate_code(length=6):
    """Генерирует случайный код"""
    return ''.join(secrets.choice(string.digits) for _ in range(length))

def send_email(to_email, subject, html_content):
    """Отправляет email через SMTP сервер"""
    try:
        print(f'[EMAIL] Отправка письма на {to_email}')
        
        # SMTP параметры
        SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
        SMTP_EMAIL = os.getenv('SMTP_EMAIL')
        SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
        SMTP_USE_TLS = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
        
        if not SMTP_EMAIL or not SMTP_PASSWORD:
            print(f'[EMAIL ERROR] ❌ SMTP учетные данные не установлены')
            return False
        
        # Создаем сообщение
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_EMAIL
        msg['To'] = to_email
        
        # Добавляем HTML контент
        msg.attach(MIMEText(html_content, 'html'))
        
        # Подключаемся к SMTP серверу
        print(f'[EMAIL] Подключение к {SMTP_SERVER}:{SMTP_PORT}')
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30)
        
        if SMTP_USE_TLS:
            server.starttls()
        
        # Логинимся
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        
        # Отправляем письмо
        server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        server.quit()
        
        print(f'[EMAIL] ✅ Письмо отправлено на {to_email}')
        return True
    except smtplib.SMTPAuthenticationError:
        print(f'[EMAIL ERROR] ❌ Ошибка аутентификации SMTP')
        return False
    except smtplib.SMTPException as e:
        print(f'[EMAIL ERROR] ❌ SMTP ошибка: {str(e)}')
        return False
    except Exception as e:
        print(f'[EMAIL ERROR] ❌ {str(e)}')
        return False

def user_to_dict(user):
    """Конвертирует MongoDB документ в словарь"""
    if user:
        user['id'] = str(user['_id'])
        user.pop('_id', None)
    return user

def chat_to_dict(chat):
    """Конвертирует чат в словарь"""
    if chat:
        chat['id'] = str(chat['_id'])
        chat.pop('_id', None)
    return chat

def message_to_dict(msg):
    """Конвертирует сообщение в словарь"""
    if msg:
        msg['id'] = str(msg['_id'])
        msg['user_id'] = str(msg.get('user_id', ''))
        msg['chat_id'] = str(msg.get('chat_id', ''))
        msg.pop('_id', None)
    return msg

# ============================================================================
# АВТОРИЗАЦИЯ
# ============================================================================

def hash_password(password):
    """Хеширует пароль"""
    return hashlib.sha256(password.encode()).hexdigest()

@app.route('/check_email', methods=['POST'])
def check_email():
    """Проверяет существование email"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email or '@' not in email:
            return jsonify({'error': 'Valid email required'}), 400
        
        user = users_col.find_one({'email': email})
        
        return jsonify({
            'status': 'ok',
            'email': email,
            'exists': user is not None,
            'action': 'login' if user else 'register'
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/register', methods=['POST'])
def register():
    """Регистрирует пользователя с email и паролем"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '').strip()
        name = data.get('name', email.split('@')[0]).strip()
        
        if not email or '@' not in email:
            return jsonify({'error': 'Valid email required'}), 400
        
        if not password or len(password) < 4:
            return jsonify({'error': 'Password must be at least 4 characters'}), 400
        
        # Проверяем существует ли пользователь
        existing_user = users_col.find_one({'email': email})
        if existing_user:
            return jsonify({'error': 'Email already registered'}), 400
        
        # Создаем пользователя
        hashed_password = hash_password(password)
        result = users_col.insert_one({
            'email': email,
            'password': hashed_password,
            'name': name,
            'phone': '',
            'bio': '',
            'avatar_url': '',
            'apartment': '',
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        
        # Создаем JWT токен
        token = create_access_token(identity=str(result.inserted_id))
        user = users_col.find_one({'_id': result.inserted_id})
        user_dict = user_to_dict(user)
        
        return jsonify({
            'status': 'ok',
            'token': token,
            'is_new_user': True,
            'user': {
                'id': user_dict['id'],
                'email': user_dict['email'],
                'name': user_dict['name']
            }
        }), 200
    except Exception as e:
        print(f'[ERROR] register: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    """Логинит пользователя с email и паролем"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '').strip()
        
        if not email or '@' not in email:
            return jsonify({'error': 'Valid email required'}), 400
        
        if not password:
            return jsonify({'error': 'Password required'}), 400
        
        # Ищем пользователя
        user = users_col.find_one({'email': email})
        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Проверяем пароль
        hashed_password = hash_password(password)
        if user.get('password') != hashed_password:
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Создаем JWT токен
        token = create_access_token(identity=str(user['_id']))
        user_dict = user_to_dict(user)
        
        return jsonify({
            'status': 'ok',
            'token': token,
            'is_new_user': False,
            'user': {
                'id': user_dict['id'],
                'email': user_dict['email'],
                'name': user_dict['name']
            }
        }), 200
    except Exception as e:
        print(f'[ERROR] login: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/send_code', methods=['POST'])
def send_code():
    """Отправляет код подтверждения на email"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email or '@' not in email:
            return jsonify({'error': 'Valid email required'}), 400
        
        code = generate_code(6)
        expires_at = datetime.now() + timedelta(minutes=10)
        
        # Удаляем старые коды
        verification_codes_col.delete_many({'email': email})
        
        # Сохраняем новый код
        verification_codes_col.insert_one({
            'email': email,
            'code': code,
            'created_at': datetime.now(),
            'expires_at': expires_at
        })
        
        # HTML письмо
        html = f'''<html><body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <h1 style="color: #00D9FF; text-align: center; margin-bottom: 30px;">🔐 Padik Messenger</h1>
                <p style="color: #333; font-size: 16px; text-align: center; margin-bottom: 20px;">Ваш код подтверждения:</p>
                <div style="background: #00D9FF; color: white; font-size: 32px; font-weight: bold; text-align: center; padding: 20px; border-radius: 10px; letter-spacing: 5px; margin: 30px 0;">{code}</div>
                <p style="color: #666; font-size: 14px; text-align: center; margin-top: 20px;">Код действует <strong>10 минут</strong></p>
                <p style="color: #999; font-size: 12px; text-align: center; margin-top: 30px; border-top: 1px solid #eee; padding-top: 20px;">Если вы не запрашивали этот код, проигнорируйте это письмо.</p>
            </div>
        </body></html>'''
        
        email_sent = send_email(email, 'Padik Messenger - Код подтверждения', html)
        
        return jsonify({
            'status': 'ok',
            'message': f'Code sent to {email}',
            'email_sent': email_sent,
            'expires_in_minutes': 10
        }), 200
    except Exception as e:
        print(f'[ERROR] send_code: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/verify_code', methods=['POST'])
def verify_code():
    """Проверяет код и выдает JWT токен"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return jsonify({'error': 'Email and code required'}), 400
        
        # Ищем код
        verification = verification_codes_col.find_one({
            'email': email,
            'code': code,
            'expires_at': {'$gt': datetime.now()}
        })
        
        if not verification:
            return jsonify({'error': 'Invalid or expired code'}), 401
        
        # Удаляем использованный код
        verification_codes_col.delete_one({'_id': verification['_id']})
        
        # Ищем или создаем пользователя
        user = users_col.find_one({'email': email})
        is_new_user = False
        
        if not user:
            is_new_user = True
            result = users_col.insert_one({
                'email': email,
                'name': email.split('@')[0],
                'phone': '',
                'bio': '',
                'avatar_url': '',
                'apartment': '',
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            })
            user = users_col.find_one({'_id': result.inserted_id})
        
        # Создаем JWT токен
        token = create_access_token(identity=str(user['_id']))
        user_dict = user_to_dict(user)
        
        return jsonify({
            'status': 'ok',
            'token': token,
            'is_new_user': is_new_user,
            'user': {
                'id': user_dict['id'],
                'email': user_dict['email'],
                'name': user_dict['name']
            }
        }), 200
    except Exception as e:
        print(f'[ERROR] verify_code: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ
# ============================================================================

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """Получает профиль пользователя"""
    try:
        user_id = get_jwt_identity()
        user = users_col.find_one({'_id': ObjectId(user_id)})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'status': 'ok',
            'user': user_to_dict(user)
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    """Обновляет профиль пользователя"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        update_data = {}
        if 'name' in data:
            update_data['name'] = data['name']
        if 'phone' in data:
            update_data['phone'] = data['phone']
        if 'bio' in data:
            update_data['bio'] = data['bio']
        if 'avatar_url' in data:
            update_data['avatar_url'] = data['avatar_url']
        if 'apartment' in data:
            update_data['apartment'] = data['apartment']
        
        update_data['updated_at'] = datetime.now()
        
        result = users_col.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': update_data}
        )
        
        if result.matched_count == 0:
            return jsonify({'error': 'User not found'}), 404
        
        user = users_col.find_one({'_id': ObjectId(user_id)})
        return jsonify({
            'status': 'ok',
            'user': user_to_dict(user)
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ЧАТЫ И СООБЩЕНИЯ
# ============================================================================

@app.route('/api/chats', methods=['GET'])
@jwt_required()
def get_chats():
    """Получает список чатов пользователя"""
    try:
        user_id = get_jwt_identity()
        
        # Ищем чаты где пользователь участник
        chats = list(chats_col.find({
            'members': ObjectId(user_id)
        }).sort('last_message_at', -1))
        
        chats_list = []
        for chat in chats:
            chat_dict = chat_to_dict(chat)
            chats_list.append(chat_dict)
        
        return jsonify({
            'status': 'ok',
            'chats': chats_list
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages', methods=['GET'])
@jwt_required()
def get_messages():
    """Получает сообщения из чата"""
    try:
        user_id = get_jwt_identity()
        chat_id = request.args.get('chat_id')
        limit = int(request.args.get('limit', 50))
        
        if not chat_id:
            return jsonify({'error': 'chat_id required'}), 400
        
        # Проверяем что пользователь в чате
        chat = chats_col.find_one({
            '_id': ObjectId(chat_id),
            'members': ObjectId(user_id)
        })
        
        if not chat:
            return jsonify({'error': 'Chat not found'}), 404
        
        # Получаем сообщения
        messages = list(messages_col.find({
            'chat_id': ObjectId(chat_id)
        }).sort('created_at', -1).limit(limit))
        
        messages_list = [message_to_dict(msg) for msg in messages]
        
        return jsonify({
            'status': 'ok',
            'messages': messages_list
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages', methods=['POST'])
@jwt_required()
def send_message():
    """Отправляет сообщение в чат"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        chat_id = data.get('chat_id')
        content = data.get('content', '').strip()
        
        if not chat_id or not content:
            return jsonify({'error': 'chat_id and content required'}), 400
        
        # Проверяем что пользователь в чате
        chat = chats_col.find_one({
            '_id': ObjectId(chat_id),
            'members': ObjectId(user_id)
        })
        
        if not chat:
            return jsonify({'error': 'Chat not found'}), 404
        
        # Создаем сообщение
        message_doc = {
            'chat_id': ObjectId(chat_id),
            'user_id': ObjectId(user_id),
            'content': content,
            'status': 'sent',
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
        
        result = messages_col.insert_one(message_doc)
        
        # Обновляем чат
        chats_col.update_one(
            {'_id': ObjectId(chat_id)},
            {
                '$set': {
                    'last_message': content,
                    'last_message_at': datetime.now()
                }
            }
        )
        
        # Отправляем через WebSocket
        message_doc['_id'] = result.inserted_id
        socketio.emit('new_message', message_to_dict(message_doc), room=chat_id)
        
        return jsonify({
            'status': 'ok',
            'message': message_to_dict(message_doc)
        }), 201
    except Exception as e:
        print(f'[ERROR] send_message: {str(e)}')
        return jsonify({'error': str(e)}), 500

# ============================================================================
# WEBSOCKET
# ============================================================================

@socketio.on('join_chat')
def on_join_chat(data):
    """Присоединяется к чату"""
    try:
        chat_id = data.get('chat_id')
        user_id = data.get('user_id')
        
        if chat_id and user_id:
            join_room(chat_id)
            emit('user_joined', {
                'user_id': user_id,
                'chat_id': chat_id
            }, room=chat_id)
    except Exception as e:
        print(f'[ERROR] on_join_chat: {str(e)}')

@socketio.on('leave_chat')
def on_leave_chat(data):
    """Покидает чат"""
    try:
        chat_id = data.get('chat_id')
        user_id = data.get('user_id')
        
        if chat_id and user_id:
            leave_room(chat_id)
            emit('user_left', {
                'user_id': user_id,
                'chat_id': chat_id
            }, room=chat_id)
    except Exception as e:
        print(f'[ERROR] on_leave_chat: {str(e)}')

@socketio.on('typing')
def on_typing(data):
    """Пользователь печатает"""
    try:
        chat_id = data.get('chat_id')
        user_id = data.get('user_id')
        
        if chat_id and user_id:
            emit('user_typing', {
                'user_id': user_id,
                'chat_id': chat_id
            }, room=chat_id)
    except Exception as e:
        print(f'[ERROR] on_typing: {str(e)}')

# ============================================================================
# ИНФОРМАЦИЯ
# ============================================================================

@app.route('/', methods=['GET'])
def index():
    """Информация об API"""
    return jsonify({
        'name': 'Padik Messenger Backend',
        'version': '3.0',
        'database': 'MongoDB',
        'websocket': True,
        'features': [
            'Email Authentication',
            'WebSocket Real-time',
            'Chats & Messages',
            'User Profiles',
            'JWT Protection'
        ]
    }), 200

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    try:
        client.admin.command('ping')
        return jsonify({
            'status': 'ok',
            'service': 'Padik Messenger',
            'version': '3.0',
            'database': 'MongoDB',
            'websocket': True
        }), 200
    except:
        return jsonify({'status': 'error', 'message': 'Database connection failed'}), 500

@app.route('/auth', methods=['GET'])
def auth_page():
    """HTML страница авторизации"""
    html = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Padik Messenger - Авторизация</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1a3e 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #fff;
        }
        .container {
            width: 100%;
            max-width: 400px;
            padding: 20px;
        }
        .card {
            background: rgba(20, 20, 40, 0.8);
            border: 1px solid #00D9FF;
            border-radius: 15px;
            padding: 40px;
            box-shadow: 0 0 30px rgba(0, 217, 255, 0.2);
        }
        h1 {
            text-align: center;
            margin-bottom: 30px;
            color: #00D9FF;
            font-size: 28px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #00D9FF;
            font-size: 14px;
        }
        input {
            width: 100%;
            padding: 12px;
            border: 1px solid #00D9FF;
            border-radius: 8px;
            background: rgba(0, 217, 255, 0.1);
            color: #fff;
            font-size: 16px;
            transition: all 0.3s;
        }
        input:focus {
            outline: none;
            background: rgba(0, 217, 255, 0.2);
            box-shadow: 0 0 10px rgba(0, 217, 255, 0.5);
        }
        button {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #00D9FF 0%, #0099CC 100%);
            border: none;
            border-radius: 8px;
            color: #000;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
            margin-top: 10px;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(0, 217, 255, 0.4);
        }
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .message {
            text-align: center;
            margin-top: 15px;
            padding: 10px;
            border-radius: 8px;
            font-size: 14px;
        }
        .message.error {
            background: rgba(255, 0, 0, 0.2);
            color: #ff6b6b;
            border: 1px solid #ff6b6b;
        }
        .message.success {
            background: rgba(0, 255, 0, 0.2);
            color: #51cf66;
            border: 1px solid #51cf66;
        }
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(0, 217, 255, 0.3);
            border-top-color: #00D9FF;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .token-display {
            background: rgba(0, 217, 255, 0.1);
            border: 1px solid #00D9FF;
            border-radius: 8px;
            padding: 15px;
            margin-top: 20px;
            word-break: break-all;
            font-family: monospace;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>🔐 Padik Messenger</h1>
            
            <div id="step1">
                <div class="form-group">
                    <label>Email</label>
                    <input type="email" id="email" placeholder="your@email.com">
                </div>
                <button onclick="sendCode()">Продолжить</button>
            </div>
            
            <div id="step2" style="display:none;">
                <div class="form-group">
                    <label>Код подтверждения</label>
                    <input type="text" id="code" placeholder="123456" maxlength="6">
                </div>
                <button onclick="verifyCode()">Подтвердить</button>
                <button onclick="backToStep1()" style="background: rgba(0,217,255,0.2); color: #00D9FF;">Назад</button>
            </div>
            
            <div id="step3" style="display:none;">
                <p style="text-align:center; margin-bottom:20px;">✅ Авторизация успешна!</p>
                <div class="token-display" id="tokenDisplay"></div>
                <button onclick="copyToken()" style="margin-top:15px;">Скопировать токен</button>
            </div>
            
            <div id="message"></div>
        </div>
    </div>

    <script>
        const API_URL = window.location.origin;
        
        async function sendCode() {
            const email = document.getElementById('email').value.trim();
            if (!email) {
                showError('Введите email');
                return;
            }
            
            showLoading('Отправка кода...');
            try {
                const res = await fetch(API_URL + '/send_code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                
                if (res.ok) {
                    showSuccess('Код отправлен на почту');
                    document.getElementById('step1').style.display = 'none';
                    document.getElementById('step2').style.display = 'block';
                    document.getElementById('code').focus();
                } else {
                    showError('Ошибка при отправке кода');
                }
            } catch (e) {
                showError('Ошибка: ' + e.message);
            }
        }
        
        async function verifyCode() {
            const email = document.getElementById('email').value.trim();
            const code = document.getElementById('code').value.trim();
            
            if (!code || code.length !== 6) {
                showError('Введите 6-значный код');
                return;
            }
            
            showLoading('Проверка кода...');
            try {
                const res = await fetch(API_URL + '/verify_code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, code })
                });
                
                const data = await res.json();
                
                if (res.ok) {
                    document.getElementById('step2').style.display = 'none';
                    document.getElementById('step3').style.display = 'block';
                    document.getElementById('tokenDisplay').textContent = data.token;
                    showSuccess('Добро пожаловать!');
                } else {
                    showError(data.error || 'Неверный код');
                }
            } catch (e) {
                showError('Ошибка: ' + e.message);
            }
        }
        
        function copyToken() {
            const token = document.getElementById('tokenDisplay').textContent;
            navigator.clipboard.writeText(token).then(() => {
                showSuccess('Токен скопирован в буфер обмена!');
            });
        }
        
        function backToStep1() {
            document.getElementById('step2').style.display = 'none';
            document.getElementById('step1').style.display = 'block';
            document.getElementById('email').focus();
        }
        
        function showError(msg) {
            const el = document.getElementById('message');
            el.textContent = msg;
            el.className = 'message error';
        }
        
        function showSuccess(msg) {
            const el = document.getElementById('message');
            el.textContent = msg;
            el.className = 'message success';
        }
        
        function showLoading(msg) {
            const el = document.getElementById('message');
            el.innerHTML = '<span class="spinner"></span> ' + msg;
            el.className = 'message';
        }
        
        document.getElementById('email').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendCode();
        });
        
        document.getElementById('code').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') verifyCode();
        });
    </script>
</body>
</html>'''
    return render_template_string(html)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f'[STARTUP] Padik Messenger Backend v3.0')
    print(f'[STARTUP] Слушаю на порту {port}')
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
