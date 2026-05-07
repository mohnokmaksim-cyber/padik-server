# Padik SMTP Server

Микросервис для отправки писем (кодов подтверждения) для основного сервера Padik.

## Развертывание на Railway

1. Создайте новый проект на Railway
2. Подключите этот репозиторий
3. Добавьте переменные окружения:
   - `SMTP_SERVER` (например: smtp.gmail.com)
   - `SMTP_PORT` (например: 587)
   - `SMTP_EMAIL` (ваша почта)
   - `SMTP_PASSWORD` (пароль приложения)
   - `SMTP_USE_TLS` (True или False)

## API

### GET /
Проверка здоровья сервера

**Ответ:**
```json
{
  "status": "ok",
  "service": "Padik SMTP Server",
  "version": "1.0.0"
}
```

### POST /send
Отправляет email

**Запрос:**
```json
{
  "to": "user@example.com",
  "subject": "Тема письма",
  "html": "<html>...</html>"
}
```

**Ответ:**
```json
{
  "status": "ok",
  "message": "Email sent to user@example.com"
}
```

### POST /send_code
Отправляет код подтверждения

**Запрос:**
```json
{
  "to": "user@example.com",
  "code": "123456"
}
```

**Ответ:**
```json
{
  "status": "ok",
  "message": "Code sent to user@example.com"
}
```

## Использование из основного сервера

```python
import requests

SMTP_SERVER_URL = "https://padik-smtp.railway.app"

# Отправляем код
response = requests.post(
    f"{SMTP_SERVER_URL}/send_code",
    json={
        "to": "user@example.com",
        "code": "123456"
    }
)
```
