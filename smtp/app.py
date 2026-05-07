# -*- coding: utf-8 -*-
"""
Padik SMTP Server - Микросервис для отправки писем
Используется основным сервером Padik для отправки кодов подтверждения
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ============================================================================
# SMTP КОНФИГУРАЦИЯ
# ============================================================================

SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_EMAIL = os.getenv('SMTP_EMAIL')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SMTP_USE_TLS = os.getenv('SMTP_USE_TLS', 'True') == 'True'

print(f'[SMTP] Сервер: {SMTP_SERVER}:{SMTP_PORT}')
print(f'[SMTP] Email: {SMTP_EMAIL}')

if not SMTP_EMAIL or not SMTP_PASSWORD:
    print('[ERROR] SMTP_EMAIL или SMTP_PASSWORD не установлены!')
    exit(1)

# ============================================================================
# ФУНКЦИИ
# ============================================================================

def send_email(to_email, subject, html_content):
    """Отправляет email через SMTP"""
    try:
        print(f'[EMAIL] Отправка письма на {to_email}')
        
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        message['From'] = SMTP_EMAIL
        message['To'] = to_email
        message.attach(MIMEText(html_content, 'html'))
        
        # Подключаемся к SMTP серверу
        if SMTP_USE_TLS:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10)
        
        # Авторизуемся
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        
        # Отправляем письмо
        server.sendmail(SMTP_EMAIL, to_email, message.as_string())
        server.quit()
        
        print(f'[EMAIL] ✅ Письмо отправлено на {to_email}')
        return True
    except Exception as e:
        print(f'[EMAIL ERROR] ❌ {str(e)}')
        return False

# ============================================================================
# МАРШРУТЫ
# ============================================================================

@app.route('/', methods=['GET'])
def health():
    """Проверка здоровья сервера"""
    return jsonify({
        'status': 'ok',
        'service': 'Padik SMTP Server',
        'version': '1.0.0'
    }), 200

@app.route('/send', methods=['POST'])
def send():
    """Отправляет email
    
    JSON:
    {
        "to": "user@example.com",
        "subject": "Тема письма",
        "html": "<html>...</html>"
    }
    """
    try:
        data = request.get_json()
        
        to_email = data.get('to', '').strip().lower()
        subject = data.get('subject', '').strip()
        html_content = data.get('html', '').strip()
        
        if not to_email or not subject or not html_content:
            return jsonify({
                'status': 'error',
                'message': 'Missing required fields: to, subject, html'
            }), 400
        
        # Отправляем письмо
        success = send_email(to_email, subject, html_content)
        
        if success:
            return jsonify({
                'status': 'ok',
                'message': f'Email sent to {to_email}'
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send email'
            }), 500
    
    except Exception as e:
        print(f'[ERROR] send: {str(e)}')
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/send_code', methods=['POST'])
def send_code():
    """Отправляет код подтверждения на email
    
    JSON:
    {
        "to": "user@example.com",
        "code": "123456"
    }
    """
    try:
        data = request.get_json()
        
        to_email = data.get('to', '').strip().lower()
        code = data.get('code', '').strip()
        
        if not to_email or not code:
            return jsonify({
                'status': 'error',
                'message': 'Missing required fields: to, code'
            }), 400
        
        # HTML письмо с кодом
        html = f'''<html><body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <h1 style="color: #00D9FF; text-align: center; margin-bottom: 30px;">🔐 Padik Messenger</h1>
                <p style="color: #333; font-size: 16px; text-align: center; margin-bottom: 20px;">Ваш код подтверждения:</p>
                <div style="background: #00D9FF; color: white; font-size: 32px; font-weight: bold; text-align: center; padding: 20px; border-radius: 10px; letter-spacing: 5px; margin: 30px 0;">{code}</div>
                <p style="color: #666; font-size: 14px; text-align: center; margin-top: 20px;">Код действует <strong>10 минут</strong></p>
                <p style="color: #999; font-size: 12px; text-align: center; margin-top: 30px; border-top: 1px solid #eee; padding-top: 20px;">Если вы не запрашивали этот код, проигнорируйте это письмо.</p>
            </div>
        </body></html>'''
        
        # Отправляем письмо
        success = send_email(to_email, 'Padik Messenger - Код подтверждения', html)
        
        if success:
            return jsonify({
                'status': 'ok',
                'message': f'Code sent to {to_email}'
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send code'
            }), 500
    
    except Exception as e:
        print(f'[ERROR] send_code: {str(e)}')
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
