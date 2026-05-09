"""
API Documentation и примеры использования NeuroPrompt Premium
"""

# ============================================
# 1. РЕГИСТРАЦИЯ И АУТЕНТИФИКАЦИЯ
# ============================================

"""
POST /api/auth/register
Регистрация нового пользователя
"""
# Example Request:
{
    "email": "user@example.com",
    "password": "secure_password",
    "username": "username",
    "source": "web"
}

# Response (201):
{
    "id": 1,
    "email": "user@example.com",
    "message": "Registration successful. Please proceed to payment."
}


"""
POST /api/auth/login
Вход в аккаунт
"""
# Example Request:
{
    "email": "user@example.com",
    "password": "secure_password"
}

# Response (200):
{
    "id": 1,
    "email": "user@example.com",
    "is_active": False
}


"""
GET /api/auth/profile/{user_id}
Получить профиль пользователя
"""
# Example Request:
GET /api/auth/profile/1

# Response (200):
{
    "id": 1,
    "email": "user@example.com",
    "username": "username",
    "is_active": True,
    "expiry_date": "2024-05-28T12:00:00",
    "created_at": "2024-04-28T12:00:00"
}


# ============================================
# 2. ПЛАТЕЖИ И ПОДПИСКИ
# ============================================

"""
POST /api/payment/create/{user_id}?plan=monthly
Создание платежа в Yookassa
"""
# Example Request:
POST /api/payment/create/1?plan=monthly

# Response (200):
{
    "payment_id": "2a2a86a7-000f-5000-a000-1a11aa1a1a1a",
    "status": "pending",
    "confirmation_url": "https://yookassa.ru/checkout/3d-secure?orderId=2a2a86a7-000f-5000-a000-1a11aa1a1a1a",
    "created_at": "2024-04-28T12:00:00"
}


"""
GET /api/payment/status/{payment_id}
Получить статус платежа
"""
# Example Request:
GET /api/payment/status/2a2a86a7-000f-5000-a000-1a11aa1a1a1a

# Response (200):
{
    "payment_id": "2a2a86a7-000f-5000-a000-1a11aa1a1a1a",
    "status": "succeeded"  # или "pending", "failed"
}


"""
GET /api/payment/subscription-info/{user_id}
Получить информацию о подписке
"""
# Example Request:
GET /api/payment/subscription-info/1

# Response (200):
{
    "is_active": True,
    "days_remaining": 20,
    "expiry_date": "2024-05-28T12:00:00"
}


"""
POST /api/payment/activate/{user_id}/{telegram_id}?plan=monthly
Активировать платёж из Telegram (для бота)
"""
# Example Request:
POST /api/payment/activate/1/123456789?plan=monthly

# Response (200):
{
    "payment_id": "2a2a86a7-000f-5000-a000-1a11aa1a1a1a",
    "status": "pending",
    "confirmation_url": "https://yookassa.ru/checkout/...",
    "created_at": "2024-04-28T12:00:00"
}


"""
POST /api/payment/webhook/yookassa
Webhook от Yookassa (автоматический, вызывается Yookassa)
"""
# Example Request (from Yookassa):
{
    "type": "notification",
    "event": "payment.succeeded",
    "object": {
        "id": "2a2a86a7-000f-5000-a000-1a11aa1a1a1a",
        "status": "succeeded",
        "amount": {
            "value": "290.00",
            "currency": "RUB"
        },
        "metadata": {
            "user_id": 1,
            "plan": "monthly",
            "source": "web_app"
        }
    }
}

# Response (200):
{
    "status": "ok"
}


# ============================================
# 3. ПРОМПТЫ
# ============================================

"""
GET /api/prompts/all?user_id=1
Получить все промпты (требует активной подписки)
"""
# Example Request:
GET /api/prompts/all?user_id=1

# Response (200):
[
    {
        "id": 1,
        "title": "Создание SEO статьи",
        "description": "Профессиональный промпт для генерации SEO-оптимизированных статей для блога",
        "category": "Контент-маркетинг",
        "usage_count": 1250,
        "rating": 4.8
    },
    {
        "id": 2,
        "title": "Анализ конкурентов",
        "description": "Умный промпт для детального анализа конкурентов и выявления ниш",
        "category": "Аналитика",
        "usage_count": 890,
        "rating": 4.9
    }
]


"""
GET /api/prompts/{prompt_id}?user_id=1
Получить конкретный промпт
"""
# Example Request:
GET /api/prompts/1?user_id=1

# Response (200):
{
    "id": 1,
    "title": "Создание SEO статьи",
    "description": "Профессиональный промпт для генерации SEO-оптимизированных статей для блога",
    "category": "Контент-маркетинг",
    "usage_count": 1250,
    "rating": 4.8
}


# ============================================
# 4. ПРИМЕРЫ CURL КОМАНД
# ============================================

# Регистрация:
"""
curl -X POST "http://localhost:8000/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123",
    "username": "user",
    "source": "web"
  }'
"""

# Создание платежа:
"""
curl -X POST "http://localhost:8000/api/payment/create/1?plan=monthly" \
  -H "Content-Type: application/json"
"""

# Получить промпты:
"""
curl -X GET "http://localhost:8000/api/prompts/all?user_id=1" \
  -H "Content-Type: application/json"
"""


# ============================================
# 5. КОДЫ ОШИБОК
# ============================================

"""
400 Bad Request - Неверные параметры
401 Unauthorized - Не авторизован
403 Forbidden - Нет доступа (нет активной подписки)
404 Not Found - Ресурс не найден
500 Internal Server Error - Ошибка сервера
"""


# ============================================
# 6. ИНТЕГРАЦИЯ С TELEGRAM БОТОМ
# ============================================

# В обработчике Telegram команды:
"""
@router.message(Command("buy"))
async def buy_subscription(message: Message, db: AsyncSession = Depends(get_async_db)):
    user_id = message.from_user.id
    
    # Переход на страницу оплаты
    pay_url = f"https://neuroprompt.ai/pay/{user_id}"
    
    await message.answer(
        f"Оформить подписку: {pay_url}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить подписку", url=pay_url)]
        ])
    )
"""


# ============================================
# 7. ПРИМЕР ФРОНТЕНДА (JavaScript)
# ============================================

"""
// Регистрация
async function register(email, password) {
    const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            email: email,
            password: password,
            username: email.split('@')[0],
            source: 'web'
        })
    });
    
    const data = await response.json();
    if (response.ok) {
        window.location.href = `/dashboard?user_id=${data.id}`;
    }
}

// Создание платежа
async function createPayment(userId, plan) {
    const response = await fetch(`/api/payment/create/${userId}?plan=${plan}`, {
        method: 'POST'
    });
    
    const data = await response.json();
    if (data.confirmation_url) {
        window.location.href = data.confirmation_url;
    }
}

// Получить промпты
async function getPrompts(userId) {
    const response = await fetch(`/api/prompts/all?user_id=${userId}`);
    const prompts = await response.json();
    return prompts;
}
"""
