"""
Padik Messenger Backend - ПОЛНАЯ ВЕРСИЯ
Авторизация через email + Чаты + Медиа + Статусы + Typing + Поиск + Push + Группы + 2FA + WebSocket
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson.objectid import ObjectId
import secrets
import string
from datetime import datetime, timedelta
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pyotp
import qrcode
from io import BytesIO
import boto3
import firebase_admin
from firebase_admin import credentials, messaging
import json

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-secret-key')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)

jwt = JWTManager(app)
socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app)

# ============================================================================
# MONGODB
# ============================================================================

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/padik')
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client.get_database()
    print('[DB] ✅ MongoDB подключена')
except:
    client = MongoClient('mongodb://localhost:27017/padik')
    db = client.padik

users_col = db.users
messages_col = db.messages
chats_col = db.chats
chat_members_col = db.chat_members
verification_codes_col = db.verification_codes
push_tokens_col = db.push_tokens
media_col = db.media

# Индексы
users_col.create_index('email', unique=True)
messages_col.create_index('chat_id')
messages_col.create_index('created_at')
chat_members_col.create_index([('chat_id', 1), ('user_id', 1)], unique=True)

# ============================================================================
# S3 КОНФИГУРАЦИЯ
# ============================================================================

S3_ENABLED = os.getenv('S3_BUCKET') is not None

if S3_ENABLED:
    s3_client = boto3.client(
        's3',
        region_name=os.getenv('S3_REGION', 'us-east-1'),
        aws_access_key_id=os.getenv('S3_ACCESS_KEY'),
        aws_secret_access_key=os.getenv('S3_SECRET_KEY')
    )
    S3_BUCKET = os.getenv('S3_BUCKET')

# ============================================================================
# FIREBASE
# ============================================================================

FIREBASE_ENABLED = os.getenv('FIREBASE_CREDENTIALS') is not None

if FIREBASE_ENABLED:
    try:
        creds_dict = json.loads(os.getenv('FIREBASE_CREDENTIALS'))
        firebase_admin.initialize_app(credentials.Certificate(creds_dict))
    except:
        FIREBASE_ENABLED = False

# ============================================================================
# SMTP
# ============================================================================

SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_EMAIL = os.getenv('SMTP_EMAIL', 'your-email@gmail.com')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', 'your-password')
SMTP_USE_TLS = os.getenv('SMTP_USE_TLS', 'True') == 'True'

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def generate_code(length=6):
    return ''.join(secrets.choice(string.digits) for _ in range(length))

def send_email(to_email, subject, html_content):
    try:
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        message['From'] = SMTP_EMAIL
        message['To'] = to_email
        message.attach(MIMEText(html_content, 'html'))
        
        if SMTP_USE_TLS:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, to_email, message.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f'[EMAIL ERROR] {str(e)}')
        return False

def send_push_notification(user_id, title, body, data=None):
    if not FIREBASE_ENABLED:
        return False
    
    try:
        token_doc = push_tokens_col.find_one({'user_id': ObjectId(user_id)})
        if not token_doc:
            return False
        
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            token=token_doc['token']
        )
        messaging.send(message)
        return True
    except:
        return False

def user_to_dict(user):
    if user:
        user['id'] = str(user['_id'])
        user.pop('_id', None)
    return user

# ============================================================================
# АВТОРИЗАЦИЯ
# ============================================================================

@app.route('/check_email', methods=['POST'])
def check_email():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({'error': 'Email required'}), 400
        
        user = users_col.find_one({'email': email})
        
        return jsonify({
            'status': 'ok',
            'email': email,
            'exists': user is not None,
            'action': 'login' if user else 'register'
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/send_code', methods=['POST'])
def send_code():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({'error': 'Email required'}), 400
        
        code = generate_code(6)
        expires_at = datetime.now() + timedelta(minutes=10)
        
        verification_codes_col.delete_many({'email': email})
        verification_codes_col.insert_one({
            'email': email,
            'code': code,
            'created_at': datetime.now(),
            'expires_at': expires_at
        })
        
        html = f'<h1>Ваш код: {code}</h1><p>Действует 10 минут</p>'
        email_sent = send_email(email, 'Padik Code', html)
        
        return jsonify({
            'status': 'ok',
            'message': f'Code sent to {email}',
            'email_sent': email_sent
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/verify_code', methods=['POST'])
def verify_code():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return jsonify({'error': 'Email and code required'}), 400
        
        verification = verification_codes_col.find_one({
            'email': email,
            'code': code,
            'expires_at': {'$gt': datetime.now()}
        })
        
        if not verification:
            return jsonify({'error': 'Invalid or expired code'}), 401
        
        verification_codes_col.delete_one({'_id': verification['_id']})
        
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
                'created_at': datetime.now()
            })
            user = users_col.find_one({'_id': result.inserted_id})
        
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
        return jsonify({'error': str(e)}), 500

# ============================================================================
# 2FA
# ============================================================================

@app.route('/api/2fa/setup', methods=['POST'])
@jwt_required()
def setup_2fa():
    try:
        user_id = get_jwt_identity()
        secret = pyotp.random_base32()
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(pyotp.totp.TOTP(secret).provisioning_uri(name=user_id, issuer_name='Padik'))
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        
        return jsonify({
            'status': 'ok',
            'secret': secret
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/2fa/verify', methods=['POST'])
@jwt_required()
def verify_2fa():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        code = data.get('code', '')
        secret = data.get('secret', '')
        
        totp = pyotp.TOTP(secret)
        if totp.verify(code):
            users_col.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {'totp_secret': secret, 'totp_enabled': True}}
            )
            return jsonify({'status': 'ok', 'message': '2FA enabled'}), 200
        else:
            return jsonify({'error': 'Invalid code'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ЧАТЫ И СООБЩЕНИЯ
# ============================================================================

@app.route('/api/chats', methods=['GET'])
@jwt_required()
def get_chats():
    try:
        user_id = get_jwt_identity()
        
        chats = list(chat_members_col.aggregate([
            {'$match': {'user_id': ObjectId(user_id)}},
            {'$lookup': {
                'from': 'chats',
                'localField': 'chat_id',
                'foreignField': '_id',
                'as': 'chat'
            }},
            {'$unwind': '$chat'},
            {'$project': {
                '_id': '$chat._id',
                'name': '$chat.name',
                'is_group': '$chat.is_group',
                'created_at': '$chat.created_at'
            }}
        ]))
        
        return jsonify({
            'status': 'ok',
            'chats': [{'id': str(c['_id']), **{k: v for k, v in c.items() if k != '_id'}} for c in chats]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages', methods=['GET'])
@jwt_required()
def get_messages():
    try:
        user_id = get_jwt_identity()
        chat_id = request.args.get('chat_id')
        
        if not chat_id:
            return jsonify({'error': 'chat_id required'}), 400
        
        messages = list(messages_col.find(
            {'chat_id': ObjectId(chat_id)},
            sort=[('created_at', -1)],
            limit=100
        ))
        
        return jsonify({
            'status': 'ok',
            'messages': [{'id': str(m['_id']), **{k: v for k, v in m.items() if k != '_id'}} for m in messages]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages', methods=['POST'])
@jwt_required()
def send_message():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        chat_id = data.get('chat_id')
        content = data.get('content')
        
        if not chat_id or not content:
            return jsonify({'error': 'chat_id and content required'}), 400
        
        message = {
            'chat_id': ObjectId(chat_id),
            'user_id': ObjectId(user_id),
            'content': content,
            'status': 'sent',
            'created_at': datetime.now(),
            'delivered_at': None,
            'read_at': None,
            'edited_at': None,
            'deleted': False
        }
        
        result = messages_col.insert_one(message)
        
        socketio.emit('new_message', {
            'message_id': str(result.inserted_id),
            'chat_id': chat_id,
            'user_id': user_id,
            'content': content,
            'status': 'sent',
            'created_at': datetime.now().isoformat()
        }, room=chat_id)
        
        send_push_notification(user_id, 'New message', content)
        
        return jsonify({
            'status': 'ok',
            'message_id': str(result.inserted_id)
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages/<message_id>/status', methods=['PUT'])
@jwt_required()
def update_message_status(message_id):
    try:
        data = request.get_json()
        status = data.get('status')
        
        if status not in ['sent', 'delivered', 'read']:
            return jsonify({'error': 'Invalid status'}), 400
        
        update_data = {f'{status}_at': datetime.now()}
        
        messages_col.update_one(
            {'_id': ObjectId(message_id)},
            {'$set': {'status': status, **update_data}}
        )
        
        message = messages_col.find_one({'_id': ObjectId(message_id)})
        
        socketio.emit('message_status_updated', {
            'message_id': message_id,
            'status': status,
            'updated_at': datetime.now().isoformat()
        }, room=str(message['chat_id']))
        
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ
# ============================================================================

@app.route('/api/messages/<message_id>', methods=['PUT'])
@jwt_required()
def edit_message(message_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        content = data.get('content')
        
        message = messages_col.find_one({'_id': ObjectId(message_id)})
        
        if str(message['user_id']) != user_id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        messages_col.update_one(
            {'_id': ObjectId(message_id)},
            {'$set': {'content': content, 'edited_at': datetime.now()}}
        )
        
        socketio.emit('message_edited', {
            'message_id': message_id,
            'content': content,
            'edited_at': datetime.now().isoformat()
        }, room=str(message['chat_id']))
        
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages/<message_id>', methods=['DELETE'])
@jwt_required()
def delete_message(message_id):
    try:
        user_id = get_jwt_identity()
        
        message = messages_col.find_one({'_id': ObjectId(message_id)})
        
        if str(message['user_id']) != user_id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        messages_col.update_one(
            {'_id': ObjectId(message_id)},
            {'$set': {'deleted': True}}
        )
        
        socketio.emit('message_deleted', {
            'message_id': message_id
        }, room=str(message['chat_id']))
        
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ПОИСК
# ============================================================================

@app.route('/api/search', methods=['GET'])
@jwt_required()
def search_messages():
    try:
        q = request.args.get('q', '')
        chat_id = request.args.get('chat_id')
        
        if not q:
            return jsonify({'error': 'q required'}), 400
        
        query = {'content': {'$regex': q, '$options': 'i'}}
        
        if chat_id:
            query['chat_id'] = ObjectId(chat_id)
        
        results = list(messages_col.find(query, limit=50))
        
        return jsonify({
            'status': 'ok',
            'results': [{'id': str(r['_id']), **{k: v for k, v in r.items() if k != '_id'}} for r in results]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# МЕДИА ЗАГРУЗКА
# ============================================================================

@app.route('/api/media/upload', methods=['POST'])
@jwt_required()
def upload_media():
    try:
        user_id = get_jwt_identity()
        
        if 'file' not in request.files:
            return jsonify({'error': 'file required'}), 400
        
        file = request.files['file']
        chat_id = request.form.get('chat_id')
        
        if not file or not chat_id:
            return jsonify({'error': 'file and chat_id required'}), 400
        
        if S3_ENABLED:
            filename = f"{user_id}/{datetime.now().timestamp()}/{file.filename}"
            s3_client.upload_fileobj(file, S3_BUCKET, filename)
            url = f"https://{S3_BUCKET}.s3.amazonaws.com/{filename}"
        else:
            url = f"/uploads/{file.filename}"
        
        media_doc = {
            'user_id': ObjectId(user_id),
            'chat_id': ObjectId(chat_id),
            'filename': file.filename,
            'url': url,
            'created_at': datetime.now()
        }
        
        result = media_col.insert_one(media_doc)
        
        return jsonify({
            'status': 'ok',
            'media_id': str(result.inserted_id),
            'url': url
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ПРОФИЛЬ
# ============================================================================

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    try:
        user_id = get_jwt_identity()
        user = users_col.find_one({'_id': ObjectId(user_id)})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        user_dict = user_to_dict(user)
        
        return jsonify({
            'status': 'ok',
            'user': user_dict
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        update_data = {}
        for field in ['name', 'phone', 'bio', 'avatar_url', 'apartment']:
            if field in data:
                update_data[field] = data[field].strip() if isinstance(data[field], str) else data[field]
        
        users_col.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': update_data}
        )
        
        return jsonify({
            'status': 'ok',
            'message': 'Profile updated'
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# PUSH NOTIFICATIONS
# ============================================================================

@app.route('/api/push/register', methods=['POST'])
@jwt_required()
def register_push_token():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        token = data.get('token')
        
        if not token:
            return jsonify({'error': 'token required'}), 400
        
        push_tokens_col.update_one(
            {'user_id': ObjectId(user_id)},
            {'$set': {'token': token, 'updated_at': datetime.now()}},
            upsert=True
        )
        
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# WEBSOCKET СОБЫТИЯ
# ============================================================================

@socketio.on('join_chat')
def on_join_chat(data):
    chat_id = data.get('chat_id')
    user_id = data.get('user_id')
    
    join_room(chat_id)
    
    emit('user_joined', {
        'chat_id': chat_id,
        'user_id': user_id,
        'timestamp': datetime.now().isoformat()
    }, room=chat_id)

@socketio.on('leave_chat')
def on_leave_chat(data):
    chat_id = data.get('chat_id')
    user_id = data.get('user_id')
    
    leave_room(chat_id)
    
    emit('user_left', {
        'chat_id': chat_id,
        'user_id': user_id,
        'timestamp': datetime.now().isoformat()
    }, room=chat_id)

@socketio.on('typing')
def on_typing(data):
    chat_id = data.get('chat_id')
    user_id = data.get('user_id')
    
    emit('user_typing', {
        'chat_id': chat_id,
        'user_id': user_id,
        'timestamp': datetime.now().isoformat()
    }, room=chat_id, skip_sid=True)

@socketio.on('stop_typing')
def on_stop_typing(data):
    chat_id = data.get('chat_id')
    user_id = data.get('user_id')
    
    emit('user_stopped_typing', {
        'chat_id': chat_id,
        'user_id': user_id
    }, room=chat_id, skip_sid=True)

# ============================================================================
# ГРУППЫ
# ============================================================================

@app.route('/api/groups', methods=['POST'])
@jwt_required()
def create_group():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        name = data.get('name')
        members = data.get('members', [])
        
        if not name:
            return jsonify({'error': 'name required'}), 400
        
        chat = {
            'name': name,
            'is_group': True,
            'creator_id': ObjectId(user_id),
            'created_at': datetime.now()
        }
        
        result = chats_col.insert_one(chat)
        chat_id = result.inserted_id
        
        # Добавляем создателя
        chat_members_col.insert_one({
            'chat_id': chat_id,
            'user_id': ObjectId(user_id),
            'joined_at': datetime.now()
        })
        
        # Добавляем членов
        for member_id in members:
            chat_members_col.insert_one({
                'chat_id': chat_id,
                'user_id': ObjectId(member_id),
                'joined_at': datetime.now()
            })
        
        return jsonify({
            'status': 'ok',
            'group_id': str(chat_id)
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/groups/<group_id>/members', methods=['POST'])
@jwt_required()
def add_group_member(group_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        member_id = data.get('member_id')
        
        if not member_id:
            return jsonify({'error': 'member_id required'}), 400
        
        chat_members_col.insert_one({
            'chat_id': ObjectId(group_id),
            'user_id': ObjectId(member_id),
            'joined_at': datetime.now()
        })
        
        socketio.emit('user_joined', {
            'chat_id': group_id,
            'user_id': member_id
        }, room=group_id)
        
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'service': 'Padik Messenger - Full Version',
        'version': '2.0',
        'database': 'MongoDB',
        'features': [
            'Email Authentication',
            'WebSocket Real-time',
            'Chats & Messages',
            'Media Upload',
            'Message Status',
            'Typing Indicator',
            'Search',
            '2FA',
            'Push Notifications',
            'Groups'
        ]
    }), 200

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'name': 'Padik Messenger Backend - Full Version',
        'version': '2.0',
        'description': 'Полнофункциональный мессенджер',
        'database': 'MongoDB',
        'websocket': True,
        'features': 10
    }), 200

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == '__main__':
    print('[STARTUP] Padik Backend v2.0 (Full) starting...')
    print('[STARTUP] Database: MongoDB')
    print('[STARTUP] WebSocket: Enabled')
    print('[STARTUP] S3: ' + ('Enabled' if S3_ENABLED else 'Disabled'))
    print('[STARTUP] Firebase: ' + ('Enabled' if FIREBASE_ENABLED else 'Disabled'))
    
    socketio.run(
        app,
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5000)),
        debug=os.getenv('FLASK_ENV', 'development') == 'development'
    )

