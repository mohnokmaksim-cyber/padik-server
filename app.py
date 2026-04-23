import os
import jwt
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

# MongoDB Connection
MONGODB_URI = os.getenv('MONGODB_URI')
client = MongoClient(MONGODB_URI)
db = client['padik_messenger']

# Collections
users_collection = db['users']
chats_collection = db['chats']
messages_collection = db['messages']
verification_codes_collection = db['verification_codes']

# Create indexes
users_collection.create_index('email', unique=True)
chats_collection.create_index([('user1_id', 1), ('user2_id', 1)], unique=True)
messages_collection.create_index('chat_id')
verification_codes_collection.create_index('email')

# Email Configuration
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASS = os.getenv('EMAIL_PASS')
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587

# Helper functions
def generate_verification_code():
    return ''.join(random.choices(string.digits, k=6))

def send_verification_email(email, code):
    try:
        if not EMAIL_USER or not EMAIL_PASS:
            print(f"[WARNING] Email credentials not configured. Code: {code}")
            return False
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Padik - Код подтверждения'
        msg['From'] = EMAIL_USER
        msg['To'] = email
        
        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                <div style="max-width: 500px; margin: 0 auto; background-color: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h2 style="color: #1A56DB; text-align: center; margin-bottom: 20px;">Padik Messenger</h2>
                    <p style="color: #333; font-size: 16px; margin-bottom: 20px;">Здравствуйте!</p>
                    <p style="color: #666; font-size: 14px; margin-bottom: 20px;">Вы запросили вход в приложение Padik. Используйте код подтверждения ниже:</p>
                    <div style="background-color: #1A56DB; color: white; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 20px;">
                        <p style="font-size: 32px; font-weight: bold; margin: 0; letter-spacing: 5px;">{code}</p>
                    </div>
                    <p style="color: #999; font-size: 12px; text-align: center; margin-bottom: 20px;">Код действует 10 минут</p>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="color: #999; font-size: 12px; text-align: center;">Если вы не запрашивали этот код, проигнорируйте это письмо.</p>
                </div>
            </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        
        print(f"[EMAIL SENT] Code sent to {email}")
        return True
    
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send email to {email}: {str(e)}")
        return False

def generate_jwt_token(user_id, email):
    payload = {
        'user_id': str(user_id),
        'email': email,
        'exp': datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

def verify_jwt_token(token):
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def token_required(f):
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
        
        payload = verify_jwt_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        request.user_id = payload['user_id']
        request.email = payload['email']
        return f(*args, **kwargs)
    
    return decorated

# Routes
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'Padik server is running'}), 200

@app.route('/send_code', methods=['POST'])
def send_code():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    
    if not email or '@' not in email:
        return jsonify({'error': 'Invalid email format'}), 400
    
    try:
        code = generate_verification_code()
        
        verification_codes_collection.update_one(
            {'email': email},
            {
                '$set': {
                    'code': code,
                    'created_at': datetime.utcnow(),
                    'expires_at': datetime.utcnow() + timedelta(minutes=10)
                }
            },
            upsert=True
        )
        
        email_sent = send_verification_email(email, code)
        
        return jsonify({
            'success': True,
            'message': 'Verification code sent to email' if email_sent else 'Code saved (email service unavailable)',
            'code': code
        }), 200
    
    except Exception as e:
        print(f"Error sending code: {e}")
        return jsonify({'error': 'Failed to send verification code'}), 500

@app.route('/verify_code', methods=['POST'])
def verify_code():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()
    name = data.get('name', '').strip()
    date_of_birth = data.get('date_of_birth', '')
    
    if not email or not code:
        return jsonify({'error': 'Email and code are required'}), 400
    
    try:
        verification_record = verification_codes_collection.find_one({'email': email})
        
        if not verification_record or verification_record['code'] != code:
            return jsonify({'error': 'Invalid verification code'}), 400
        
        if datetime.utcnow() > verification_record['expires_at']:
            return jsonify({'error': 'Verification code has expired'}), 400
        
        user = users_collection.find_one({'email': email})
        
        if user:
            users_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'last_login': datetime.utcnow()}}
            )
            user_id = str(user['_id'])
        else:
            if not name or not date_of_birth:
                return jsonify({'error': 'Name and date of birth are required for new users'}), 400
            
            dob = datetime.strptime(date_of_birth, '%Y-%m-%d')
            age = (datetime.utcnow() - dob).days // 365
            
            if age < 10:
                return jsonify({'error': 'You must be at least 10 years old to register'}), 400
            
            new_user = {
                'email': email,
                'name': name,
                'date_of_birth': dob,
                'age': age,
                'created_at': datetime.utcnow(),
                'last_login': datetime.utcnow(),
                'is_online': True,
                'bio': '',
                'avatar_url': ''
            }
            result = users_collection.insert_one(new_user)
            user_id = str(result.inserted_id)
        
        token = generate_jwt_token(user_id, email)
        verification_codes_collection.delete_one({'email': email})
        
        return jsonify({
            'success': True,
            'message': 'Authentication successful',
            'token': token,
            'user_id': user_id,
            'email': email
        }), 200
    
    except Exception as e:
        print(f"Error verifying code: {e}")
        return jsonify({'error': 'Failed to verify code'}), 500

@app.route('/me', methods=['GET'])
@token_required
def get_current_user():
    try:
        from bson import ObjectId
        user = users_collection.find_one({'_id': ObjectId(request.user_id)})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'id': str(user['_id']),
            'email': user['email'],
            'name': user['name'],
            'bio': user.get('bio', ''),
            'avatar_url': user.get('avatar_url', ''),
            'is_online': user.get('is_online', False),
            'created_at': user['created_at'].isoformat()
        }), 200
    
    except Exception as e:
        print(f"Error getting user: {e}")
        return jsonify({'error': 'Failed to get user info'}), 500

@app.route('/users/search', methods=['GET'])
@token_required
def search_users():
    query = request.args.get('q', '').strip()
    
    if not query or len(query) < 2:
        return jsonify({'error': 'Search query must be at least 2 characters'}), 400
    
    try:
        from bson import ObjectId
        current_user_id = ObjectId(request.user_id)
        
        results = users_collection.find({
            '$and': [
                {'_id': {'$ne': current_user_id}},
                {'$or': [
                    {'name': {'$regex': query, '$options': 'i'}},
                    {'email': {'$regex': query, '$options': 'i'}}
                ]}
            ]
        }).limit(10)
        
        users = []
        for user in results:
            users.append({
                'id': str(user['_id']),
                'name': user['name'],
                'email': user['email'],
                'avatar_url': user.get('avatar_url', ''),
                'is_online': user.get('is_online', False)
            })
        
        return jsonify({'users': users}), 200
    
    except Exception as e:
        print(f"Error searching users: {e}")
        return jsonify({'error': 'Failed to search users'}), 500

@app.route('/chats', methods=['GET'])
@token_required
def get_chats():
    try:
        from bson import ObjectId
        current_user_id = ObjectId(request.user_id)
        
        chats = list(chats_collection.find({
            '$or': [
                {'user1_id': current_user_id},
                {'user2_id': current_user_id}
            ]
        }).sort('last_message_at', -1))
        
        result = []
        for chat in chats:
            partner_id = chat['user2_id'] if chat['user1_id'] == current_user_id else chat['user1_id']
            partner = users_collection.find_one({'_id': partner_id})
            
            result.append({
                'id': str(chat['_id']),
                'partner': {
                    'id': str(partner['_id']),
                    'name': partner['name'],
                    'avatar_url': partner.get('avatar_url', '')
                },
                'last_message': chat.get('last_message', ''),
                'last_message_at': chat.get('last_message_at', '').isoformat() if chat.get('last_message_at') else None,
                'unread_count': chat.get('unread_count', 0)
            })
        
        return jsonify({'chats': result}), 200
    
    except Exception as e:
        print(f"Error getting chats: {e}")
        return jsonify({'error': 'Failed to get chats'}), 500

@app.route('/chats/get-or-create', methods=['POST'])
@token_required
def get_or_create_chat():
    data = request.get_json()
    partner_id = data.get('partner_id', '').strip()
    
    if not partner_id:
        return jsonify({'error': 'Partner ID is required'}), 400
    
    try:
        from bson import ObjectId
        current_user_id = ObjectId(request.user_id)
        partner_obj_id = ObjectId(partner_id)
        
        chat = chats_collection.find_one({
            '$or': [
                {'user1_id': current_user_id, 'user2_id': partner_obj_id},
                {'user1_id': partner_obj_id, 'user2_id': current_user_id}
            ]
        })
        
        if chat:
            return jsonify({
                'id': str(chat['_id']),
                'created': False
            }), 200
        
        new_chat = {
            'user1_id': current_user_id,
            'user2_id': partner_obj_id,
            'created_at': datetime.utcnow(),
            'last_message_at': datetime.utcnow(),
            'last_message': '',
            'unread_count': 0
        }
        result = chats_collection.insert_one(new_chat)
        
        return jsonify({
            'id': str(result.inserted_id),
            'created': True
        }), 201
    
    except Exception as e:
        print(f"Error creating chat: {e}")
        return jsonify({'error': 'Failed to create chat'}), 500

@app.route('/messages/<chat_id>', methods=['GET'])
@token_required
def get_messages(chat_id):
    try:
        from bson import ObjectId
        chat_obj_id = ObjectId(chat_id)
        
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        messages = list(messages_collection.find(
            {'chat_id': chat_obj_id}
        ).sort('created_at', -1).skip(offset).limit(limit))
        
        result = []
        for msg in messages:
            sender = users_collection.find_one({'_id': msg['sender_id']})
            result.append({
                'id': str(msg['_id']),
                'chat_id': str(msg['chat_id']),
                'sender': {
                    'id': str(msg['sender_id']),
                    'name': sender['name'] if sender else 'Unknown'
                },
                'text': msg.get('text', ''),
                'image_url': msg.get('image_url', ''),
                'created_at': msg['created_at'].isoformat(),
                'is_read': msg.get('is_read', False)
            })
        
        return jsonify({'messages': result}), 200
    
    except Exception as e:
        print(f"Error getting messages: {e}")
        return jsonify({'error': 'Failed to get messages'}), 500

@app.route('/messages/<chat_id>/send', methods=['POST'])
@token_required
def send_message(chat_id):
    data = request.get_json()
    text = data.get('text', '').strip()
    image_url = data.get('image_url', '').strip()
    
    if not text and not image_url:
        return jsonify({'error': 'Message text or image is required'}), 400
    
    try:
        from bson import ObjectId
        chat_obj_id = ObjectId(chat_id)
        sender_id = ObjectId(request.user_id)
        
        new_message = {
            'chat_id': chat_obj_id,
            'sender_id': sender_id,
            'text': text if text else None,
            'image_url': image_url if image_url else None,
            'created_at': datetime.utcnow(),
            'is_read': False
        }
        result = messages_collection.insert_one(new_message)
        
        chats_collection.update_one(
            {'_id': chat_obj_id},
            {
                '$set': {
                    'last_message': text if text else '[Image]',
                    'last_message_at': datetime.utcnow()
                }
            }
        )
        
        return jsonify({
            'id': str(result.inserted_id),
            'success': True,
            'message': 'Message sent'
        }), 201
    
    except Exception as e:
        print(f"Error sending message: {e}")
        return jsonify({'error': 'Failed to send message'}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
