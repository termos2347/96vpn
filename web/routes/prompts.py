import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from web.schemas.schemas import PromptCard
from web.services.auth import PromptService, SubscriptionService
from web.security import get_current_user_optional
from db.base import get_db
from db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/prompts", tags=["prompts"])

@router.get("/all", response_model=list[PromptCard])
async def get_all_prompts(current_user: User = Depends(get_current_user_optional)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="Active subscription required")
    prompts = await PromptService.get_all_prompts()
    return prompts

@router.get("/{prompt_id}")
async def get_prompt(prompt_id: int, current_user: User = Depends(get_current_user_optional)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="Active subscription required")
    prompt = await PromptService.get_prompt_by_id(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt

@router.get("/categories", response_model=list[str])
async def get_categories():
    """Получить список категорий (доступно без авторизации)"""
    return await PromptService.get_categories()