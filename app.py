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
SMTP_PORT = 587

# Helper functions
def generate_verification_code():
    """Generate a 6-digit verification code"""
    return ''.join(random.choices(string.digits, k=6))

def send_verification_email(email, code):
    """Send verification code via Gmail SMTP"""
    try:
        if not EMAIL_USER or not EMAIL_PASS:
            print(f"[WARNING] Email credentials not configured. Code: {code}")
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Padik - Код подтверждения'
        msg['From'] = EMAIL_USER
        msg['To'] = email
        
        # HTML email template
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
                        Код действует 3 минуты
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
        
        # Send email
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
    
    if not email:
        return jsonify({'error': 'Email is required'}), 400
    
    # Check if email is valid (basic validation)
    if '@' not in email:
        return jsonify({'error': 'Invalid email format'}), 400
    
    try:
        # Generate verification code
        code = generate_verification_code()
        
        # Store verification code in database
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
        
        # Send email with code
        email_sent = send_verification_email(email, code)
        
        response = jsonify({
            'success': True,
            'message': 'Verification code sent to email' if email_sent else 'Code saved (email service unavailable)',
            'code': code  # For testing purposes - remove in production
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    
    except Exception as e:
        print(f"Error sending code: {e}")
        response = jsonify({'error': 'Failed to send verification code'})
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
        
        # Check if user exists
        user = users_collection.find_one({'email': email})
        is_new_user = False
        
        if user:
            # User exists - update last login
            users_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'last_login': datetime.utcnow()}}
            )
            user_id = str(user['_id'])
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

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000) 
