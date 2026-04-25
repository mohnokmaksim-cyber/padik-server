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
SMTP_PORT = 465  # Changed to 465 for SMTP_SSL

print(f"[STARTUP] EMAIL_USER: {EMAIL_USER}")
print(f"[STARTUP] EMAIL_PASS configured: {bool(EMAIL_PASS)}")
print(f"[STARTUP] MONGODB_URI: {MONGODB_URI[:50]}...")

# Helper functions
def generate_verification_code():
    """Generate a 6-digit verification code"""
    return ''.join(random.choices(string.digits, k=6))

def send_verification_email(email, code):
    """Send verification code via Gmail SMTP_SSL - PLAIN TEXT ONLY"""
    try:
        print(f"[EMAIL] ===== Starting send_verification_email =====")
        print(f"[EMAIL] Recipient: {email}")
        print(f"[EMAIL] Sender: {EMAIL_USER}")
        
        if not EMAIL_USER or not EMAIL_PASS:
            print(f"[EMAIL ERROR] Email credentials not configured. EMAIL_USER: {EMAIL_USER}, EMAIL_PASS: {bool(EMAIL_PASS)}")
            return False
        
        print(f"[EMAIL] Creating message...")
        # Create message - PLAIN TEXT ONLY, NO HTML
        msg = MIMEMultipart()
        msg['Subject'] = 'Padik - Код подтверждения'
        msg['From'] = EMAIL_USER
        msg['To'] = email
        msg['Reply-To'] = EMAIL_USER
        
        # PLAIN TEXT ONLY - no HTML, no formatting
        text = f"""Ваш код для входа в Padik: {code}

Код действует 3 минуты.

Если вы не запрашивали этот код, проигнорируйте это письмо."""
        
        msg.attach(MIMEText(text, 'plain'))
        
        print(f"!!! СРОЧНО: ВВОДИ ЭТОТ КОД В ПРИЛОЖЕНИИ: {code} !!!")
        
        print(f"[EMAIL] Connecting to SMTP_SSL server {SMTP_HOST}:{SMTP_PORT}...")
        # Send email using SMTP_SSL on port 465
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            # Enable debug logging
            server.set_debuglevel(1)
            print(f"[EMAIL] Connected to SMTP_SSL server")
            
            print(f"[EMAIL] Logging in as {EMAIL_USER}...")
            server.login(EMAIL_USER, EMAIL_PASS)
            print(f"[EMAIL] Successfully logged in as {EMAIL_USER}")
            
            print(f"[EMAIL] Sending message to {email}...")
            server.send_message(msg)
            print(f"[EMAIL] Message sent successfully to {email}")
        
        print(f"[EMAIL SUCCESS] Code sent to {email}")
        print(f"[EMAIL] ===== Finished send_verification_email =====")
        return True
    
    except smtplib.SMTPAuthenticationError as e:
        print(f"\n[EMAIL ERROR] ===== ОШИБКА АУТЕНТИФИКАЦИИ ПОЧТЫ =====")
        print(f"[EMAIL ERROR] Тип: SMTPAuthenticationError")
        print(f"[EMAIL ERROR] Сообщение: {str(e)}")
        print(f"[EMAIL ERROR] EMAIL_USER: {EMAIL_USER}")
        print(f"[EMAIL ERROR] EMAIL_PASS установлен: {bool(EMAIL_PASS)}")
        print(f"[EMAIL ERROR] Проверьте: пароль приложения Gmail, двухфакторную аутентификацию")
        import traceback
        traceback.print_exc()
        return False
    except smtplib.SMTPRecipientsRefused as e:
        print(f"\n[EMAIL ERROR] ===== ОШИБКА ПОЛУЧАТЕЛЯ =====")
        print(f"[EMAIL ERROR] Тип: SMTPRecipientsRefused")
        print(f"[EMAIL ERROR] Сообщение: {str(e)}")
        print(f"[EMAIL ERROR] Получатель: {email}")
        import traceback
        traceback.print_exc()
        return False
    except smtplib.SMTPSenderRefused as e:
        print(f"\n[EMAIL ERROR] ===== ОШИБКА ОТПРАВИТЕЛЯ =====")
        print(f"[EMAIL ERROR] Тип: SMTPSenderRefused")
        print(f"[EMAIL ERROR] Сообщение: {str(e)}")
        print(f"[EMAIL ERROR] Отправитель: {EMAIL_USER}")
        import traceback
        traceback.print_exc()
        return False
    except smtplib.SMTPDataError as e:
        print(f"\n[EMAIL ERROR] ===== ОШИБКА ДАННЫХ SMTP =====")
        print(f"[EMAIL ERROR] Тип: SMTPDataError")
        print(f"[EMAIL ERROR] Сообщение: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    except smtplib.SMTPException as e:
        print(f"\n[EMAIL ERROR] ===== ОШИБКА SMTP =====")
        print(f"[EMAIL ERROR] Тип: SMTPException")
        print(f"[EMAIL ERROR] Сообщение: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n[EMAIL ERROR] ===== НЕИЗВЕСТНАЯ ОШИБКА ПОЧТЫ =====")
        print(f"[EMAIL ERROR] Тип: {type(e).__name__}")
        print(f"[EMAIL ERROR] Сообщение: {str(e)}")
        print(f"[EMAIL ERROR] Получатель: {email}")
        print(f"[EMAIL ERROR] SMTP хост: {SMTP_HOST}")
        print(f"[EMAIL ERROR] SMTP порт: {SMTP_PORT}")
        print(f"[EMAIL ERROR] Отправитель: {EMAIL_USER}")
        import traceback
        print(f"[EMAIL ERROR] Полный traceback:")
        traceback.print_exc()
        return False

def generate_jwt_token(user_id, email):
    """Generate JWT token"""
    payload = {
        'user_id': str(user_id),
        'email': email,
        'exp': datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

def verify_jwt_token(token):
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def token_required(f):
    """Decorator to check JWT token"""
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
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Padik server is running'}), 200

# ─── Authentication Endpoints ───────────────────────────────────────────────

@app.route('/send_code', methods=['POST', 'OPTIONS'])
def send_code():
    """Send verification code to email"""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response, 200
    
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    
    print(f"\n[DEBUG] ===== send_code called =====")
    print(f"[DEBUG] Email: {email}")
    
    if not email:
        print(f"[DEBUG] Email is empty")
        return jsonify({'error': 'Email is required'}), 400
    
    # Check if email is valid (basic validation)
    if '@' not in email:
        print(f"[DEBUG] Invalid email format")
        return jsonify({'error': 'Invalid email format'}), 400
    
    try:
        # Generate verification code
        code = generate_verification_code()
        print(f"[DEBUG] Generated code: {code}")
        
        # Store verification code in database
        print(f"[DEBUG] Storing code in database...")
        verification_codes_collection.update_one(
            {'email': email},
            {
                '$set': {
                    'code': code,
                    'created_at': datetime.utcnow(),
                    'expires_at': datetime.utcnow() + timedelta(minutes=3)
                }
            },
            upsert=True
        )
        print(f"[DEBUG] Code stored in database")
        
        # Send email with code
        print(f"[DEBUG] Calling send_verification_email...")
        email_sent = send_verification_email(email, code)
        print(f"[DEBUG] send_verification_email returned: {email_sent}")
        
        # ✅ FIXED: Return error status if email send failed
        if not email_sent:
            print(f"[ERROR] Failed to send verification email to {email}")
            response = jsonify({
                'error': 'Could not send verification email. Please check your email address or try again later.',
                'code': 'EMAIL_SEND_FAILED'
            })
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response, 500
        
        # ✅ Success response
        print(f"[DEBUG] Returning success response")
        response = jsonify({
            'success': True,
            'message': 'Verification code sent to email',
            'code': code  # For testing purposes - remove in production
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"[ERROR] Exception in send_code: {e}")
        import traceback
        traceback.print_exc()
        response = jsonify({
            'error': 'An unexpected error occurred while sending verification code',
            'code': 'INTERNAL_ERROR'
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

@app.route('/verify_code', methods=['POST', 'OPTIONS'])
def verify_code():
    """Verify code and create draft user"""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response, 200
    
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()
    
    if not email or not code:
        return jsonify({'error': 'Email and code are required'}), 400
    
    try:
        # Check if code is valid
        verification_record = verification_codes_collection.find_one({'email': email})
        
        if not verification_record:
            return jsonify({'error': 'No verification code found for this email'}), 400
        
        if verification_record['code'] != code:
            return jsonify({'error': 'Invalid verification code'}), 400
        
        if datetime.utcnow() > verification_record['expires_at']:
            return jsonify({'error': 'Verification code has expired'}), 400
        
        # Check if user exists and if profile is complete
        user = users_collection.find_one({'email': email})
        is_new_user = False
        
        if user:
            # User exists - update last login
            users_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'last_login': datetime.utcnow()}}
            )
            user_id = str(user['_id'])
            # Check if profile is complete (name is filled)
            is_new_user = not user.get('is_profile_complete', False) or user.get('name') is None
        else:
            # New user - create draft user (only email)
            new_user = {
                'email': email,
                'name': None,
                'date_of_birth': None,
                'age': None,
                'created_at': datetime.utcnow(),
                'last_login': datetime.utcnow(),
                'is_online': True,
                'bio': '',
                'avatar_url': '',
                'is_profile_complete': False
            }
            result = users_collection.insert_one(new_user)
            user_id = str(result.inserted_id)
            is_new_user = True
        
        # Generate JWT token
        token = generate_jwt_token(user_id, email)
        
        # Delete verification code
        verification_codes_collection.delete_one({'email': email})
        
        response = jsonify({
            'status': 'success',
            'message': 'Code verified',
            'token': token,
            'user_id': user_id,
            'email': email,
            'is_new_user': is_new_user
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"Error verifying code: {e}")
        response = jsonify({'error': 'Failed to verify code'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

@app.route('/update_profile', methods=['POST', 'OPTIONS'])
@token_required
def update_profile():
    """Update user profile (name, date of birth)"""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response, 200
    
    data = request.get_json()
    name = data.get('name', '').strip()
    date_of_birth = data.get('date_of_birth', '')
    
    if not name or not date_of_birth:
        return jsonify({'error': 'Name and date of birth are required'}), 400
    
    try:
        from bson import ObjectId
        
        # Parse date of birth
        dob = datetime.strptime(date_of_birth, '%Y-%m-%d')
        age = (datetime.utcnow() - dob).days // 365
        
        if age < 10:
            return jsonify({'error': 'You must be at least 10 years old to register'}), 400
        
        # Update user profile
        users_collection.update_one(
            {'_id': ObjectId(request.user_id)},
            {
                '$set': {
                    'name': name,
                    'date_of_birth': dob,
                    'age': age,
                    'is_profile_complete': True
                }
            }
        )
        
        response = jsonify({
            'status': 'success',
            'message': 'Profile updated',
            'name': name,
            'age': age
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    except Exception as e:
        print(f"Error updating profile: {e}")
        response = jsonify({'error': 'Failed to update profile'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

@app.route('/me', methods=['GET'])
@token_required
def get_current_user():
    """Get current user info"""
    try:
        from bson import ObjectId
        user = users_collection.find_one({'_id': ObjectId(request.user_id)})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        response = jsonify({
            'id': str(user['_id']),
            'email': user['email'],
            'name': user.get('name'),
            'date_of_birth': user.get('date_of_birth'),
            'age': user.get('age'),
            'bio': user.get('bio', ''),
            'avatar_url': user.get('avatar_url', ''),
            'is_online': user.get('is_online', False),
            'is_profile_complete': user.get('is_profile_complete', False)
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"Error getting user: {e}")
        response = jsonify({'error': 'Failed to get user info'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

# ─── Chat Endpoints ────────────────────────────────────────────────────────

@app.route('/chats', methods=['GET', 'OPTIONS'])
@token_required
def get_chats():
    """Get user's chats"""
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
        
        response = jsonify({'chats': result})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"Error getting chats: {e}")
        response = jsonify({'error': 'Failed to get chats'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

@app.route('/messages/<chat_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_messages(chat_id):
    """Get messages from a chat"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response, 200
    
    try:
        from bson import ObjectId
        messages = list(messages_collection.find({'chat_id': ObjectId(chat_id)}).sort('timestamp', 1))
        
        result = []
        for msg in messages:
            result.append({
                'id': str(msg['_id']),
                'sender_id': str(msg['sender_id']),
                'text': msg['text'],
                'timestamp': msg['timestamp']
            })
        
        response = jsonify({'messages': result})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"Error getting messages: {e}")
        response = jsonify({'error': 'Failed to get messages'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

@app.route('/send_message', methods=['POST', 'OPTIONS'])
@token_required
def send_message():
    """Send a message"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response, 200
    
    data = request.get_json()
    chat_id = data.get('chat_id')
    text = data.get('text', '').strip()
    
    if not chat_id or not text:
        return jsonify({'error': 'Chat ID and message text are required'}), 400
    
    try:
        from bson import ObjectId
        
        message = {
            'chat_id': ObjectId(chat_id),
            'sender_id': ObjectId(request.user_id),
            'text': text,
            'timestamp': datetime.utcnow()
        }
        
        result = messages_collection.insert_one(message)
        
        # Update chat's last message
        chats_collection.update_one(
            {'_id': ObjectId(chat_id)},
            {
                '$set': {
                    'last_message': text,
                    'last_message_time': datetime.utcnow()
                }
            }
        )
        
        response = jsonify({
            'status': 'success',
            'message_id': str(result.inserted_id)
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"Error sending message: {e}")
        response = jsonify({'error': 'Failed to send message'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

@app.route('/users/search', methods=['GET', 'OPTIONS'])
@token_required
def search_users():
    """Search for users by name or email"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response, 200
    
    query = request.args.get('q', '').strip()
    
    if not query or len(query) < 2:
        return jsonify({'users': []})
    
    try:
        from bson import ObjectId
        
        # Search by name or email
        users = list(users_collection.find({
            '$or': [
                {'name': {'$regex': query, '$options': 'i'}},
                {'email': {'$regex': query, '$options': 'i'}}
            ],
            '_id': {'$ne': ObjectId(request.user_id)}  # Exclude current user
        }).limit(10))
        
        result = []
        for user in users:
            result.append({
                'id': str(user['_id']),
                'name': user.get('name'),
                'email': user['email'],
                'avatar_url': user.get('avatar_url', ''),
                'is_online': user.get('is_online', False)
            })
        
        response = jsonify({'users': result})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"Error searching users: {e}")
        response = jsonify({'error': 'Failed to search users'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

@app.route('/upload_avatar', methods=['POST', 'OPTIONS'])
@token_required
def upload_avatar():
    """Upload user avatar"""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response, 200
    
    data = request.get_json()
    avatar_base64 = data.get('avatar_base64', '')
    
    if not avatar_base64:
        return jsonify({'error': 'Avatar data is required'}), 400
    
    try:
        from bson import ObjectId
        import base64
        import hashlib
        
        # Decode base64 image
        if ',' in avatar_base64:
            # Remove data URL prefix (e.g., "data:image/jpeg;base64,")
            avatar_base64 = avatar_base64.split(',')[1]
        
        avatar_bytes = base64.b64decode(avatar_base64)
        
        # Generate unique filename
        user_id = request.user_id
        timestamp = datetime.utcnow().timestamp()
        filename = f"avatars/{user_id}_{int(timestamp)}.jpg"
        
        # In a real app, you would upload to S3 here
        # For now, we'll just store the base64 string in the database
        # This is not ideal for production but works for MVP
        
        # Update user avatar
        users_collection.update_one(
            {'_id': ObjectId(user_id)},
            {
                '$set': {
                    'avatar_url': avatar_base64,  # Store base64 for MVP
                    'avatar_filename': filename,
                    'avatar_updated_at': datetime.utcnow()
                }
            }
        )
        
        response = jsonify({
            'status': 'success',
            'message': 'Avatar uploaded',
            'avatar_url': avatar_base64
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"Error uploading avatar: {e}")
        response = jsonify({'error': 'Failed to upload avatar'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
