import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select
from passlib.context import CryptContext
from db.models import User

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthService:
    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    async def create_user(
        db: Session,
        email: str,
        password: str,
        username: Optional[str] = None,
        source: str = "web"
    ) -> Optional[User]:
        try:
            # Проверяем, существует ли пользователь
            stmt = select(User).where(User.email == email)
            existing_user = db.execute(stmt).scalars().first()
            if existing_user:
                logger.warning(f"User with email {email} already exists")
                return None
            
            hashed_password = AuthService.hash_password(password)
            user = User(
                email=email,
                hashed_password=hashed_password,
                username=username or email.split("@")[0],
                source=source,
                is_active=False,  # Будет активирован после первого платежа
                created_at=datetime.utcnow()
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            db.rollback()
            return None
    
    @staticmethod
    async def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
        try:
            stmt = select(User).where(User.email == email)
            user = db.execute(stmt).scalars().first()
            if not user or not AuthService.verify_password(password, user.hashed_password or ""):
                return None
            return user
        except Exception as e:
            logger.error(f"Error authenticating user: {e}")
            return None
    
    @staticmethod
    async def get_user_by_email(db: Session, email: str) -> Optional[User]:
        try:
            stmt = select(User).where(User.email == email)
            return db.execute(stmt).scalars().first()
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    @staticmethod
    async def get_user_by_telegram_id(db: Session, telegram_id: int) -> Optional[User]:
        try:
            stmt = select(User).where(User.user_id == telegram_id)
            return db.execute(stmt).scalars().first()
        except Exception as e:
            logger.error(f"Error getting user by telegram_id: {e}")
            return None

class SubscriptionService:
    @staticmethod
    async def activate_subscription(
        db: Session,
        user: User,
        days: int = 30
    ) -> bool:
        try:
            now = datetime.utcnow()
            expiry_date = now + timedelta(days=days)
            
            user.is_active = True
            user.expiry_date = expiry_date
            user.updated_at = now
            
            db.commit()
            db.refresh(user)
            logger.info(f"Subscription activated for user {user.id} until {expiry_date}")
            return True
        except Exception as e:
            logger.error(f"Error activating subscription: {e}")
            db.rollback()
            return False
    
    @staticmethod
    async def renew_subscription(
        db: Session,
        user: User,
        days: int = 30
    ) -> bool:
        try:
            now = datetime.utcnow()
            if user.expiry_date and user.expiry_date > now:
                # Подписка ещё активна, продлеваем с текущей даты
                new_expiry_date = user.expiry_date + timedelta(days=days)
            else:
                # Подписка истекла, считаем с сегодня
                new_expiry_date = now + timedelta(days=days)
            
            user.is_active = True
            user.expiry_date = new_expiry_date
            user.updated_at = now
            
            db.commit()
            db.refresh(user)
            logger.info(f"Subscription renewed for user {user.id} until {new_expiry_date}")
            return True
        except Exception as e:
            logger.error(f"Error renewing subscription: {e}")
            db.rollback()
            return False
    
    @staticmethod
    def get_days_remaining(user: User) -> Optional[int]:
        if not user.expiry_date or not user.is_active:
            return None
        
        now = datetime.utcnow()
        if user.expiry_date <= now:
            return None
        
        delta = user.expiry_date - now
        return delta.days

class PromptService:
    # Пример промптов для тестирования
    PROMPTS = [
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
        },
        {
            "id": 3,
            "title": "Генерация идей контента",
            "description": "Креативный промпт для генерации 100+ идей контента на месяц",
            "category": "Создание контента",
            "usage_count": 2100,
            "rating": 4.7
        },
        {
            "id": 4,
            "title": "Copywriting для Ads",
            "description": "Профессиональный промпт для написания продающих объявлений в соцсетях",
            "category": "Реклама",
            "usage_count": 1560,
            "rating": 4.9
        },
        {
            "id": 5,
            "title": "Email маркетинг",
            "description": "Промпт для создания холодных и теплых email-кампаний",
            "category": "Email маркетинг",
            "usage_count": 950,
            "rating": 4.8
        },
        {
            "id": 6,
            "title": "Создание видеоскрипта",
            "description": "Полный промпт для написания скриптов YouTube и TikTok видео",
            "category": "Видео",
            "usage_count": 1420,
            "rating": 4.6
        },
        {
            "id": 7,
            "title": "Midjourney Prompts Master",
            "description": "Набор профессиональных промптов для генерации изображений в Midjourney",
            "category": "AI Арт",
            "usage_count": 3200,
            "rating": 5.0
        },
        {
            "id": 8,
            "title": "Лендинг копия",
            "description": "Промпт для написания убедительных текстов лендинг-страниц",
            "category": "Веб-дизайн",
            "usage_count": 1680,
            "rating": 4.7
        },
        {
            "id": 9,
            "title": "ChatGPT для бизнеса",
            "description": "Расширенные промпты для автоматизации рутинных процессов в бизнесе",
            "category": "Автоматизация",
            "usage_count": 2300,
            "rating": 4.8
        },
        {
            "id": 10,
            "title": "Разработка стратегии",
            "description": "Комплексный промпт для разработки маркетинг-стратегии на 6 месяцев",
            "category": "Стратегия",
            "usage_count": 780,
            "rating": 4.9
        },
    ]
    
    @staticmethod
    def get_all_prompts():
        return PromptService.PROMPTS
    
    @staticmethod
    def get_prompt_by_id(prompt_id: int):
        for prompt in PromptService.PROMPTS:
            if prompt["id"] == prompt_id:
                return prompt
        return None
