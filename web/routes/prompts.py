import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from web.schemas.schemas import PromptCard
from web.services.auth import PromptService, SubscriptionService
from db.base import get_db
from sqlalchemy import select
from db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/prompts", tags=["prompts"])

@router.get("/all", response_model=list[PromptCard])
async def get_all_prompts(user_id: int = None, db: Session = Depends(get_db)):
    """Получить все доступные промпты"""
    if user_id:
        stmt = select(User).where(User.id == user_id)
        user = db.execute(stmt).scalars().first()
        
        if not user or not user.is_active:
            raise HTTPException(status_code=403, detail="Active subscription required")
    
    return PromptService.get_all_prompts()

@router.get("/{prompt_id}", response_model=PromptCard)
async def get_prompt(prompt_id: int, user_id: int = None, db: Session = Depends(get_db)):
    """Получить промпт по ID"""
    if user_id:
        stmt = select(User).where(User.id == user_id)
        user = db.execute(stmt).scalars().first()
        
        if not user or not user.is_active:
            raise HTTPException(status_code=403, detail="Active subscription required")
    
    prompt = PromptService.get_prompt_by_id(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    
    return prompt
