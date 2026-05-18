import logging
from fastapi import APIRouter, Depends, HTTPException
from web.schemas.schemas import PromptCard
from web.services.auth import PromptService
from web.security import get_current_user_optional
from db.models import WebUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("/all", response_model=list[PromptCard])
async def get_all_prompts(current_user: WebUser = Depends(get_current_user_optional)):
    """
    Получить все доступные промпты.
    - Для неавторизованных или без активной подписки – только бесплатные.
    - Для активных подписчиков – все.
    """
    data = await PromptService.get_prompts_data()
    if not current_user or not current_user.is_active:
        # Возвращаем только бесплатные промпты
        free_prompts = [p for p in data["prompts"] if p.get("is_free", False)]
        return free_prompts
    return data["prompts"]


@router.get("/categories", response_model=list[str])
async def get_categories():
    """Получить список категорий (доступно без авторизации)"""
    return await PromptService.get_categories()


@router.get("/{prompt_id}")
async def get_prompt(
    prompt_id: int,
    current_user: WebUser = Depends(get_current_user_optional)
):
    """Получить промпт по ID (для платных нужна активная подписка)"""
    prompt = await PromptService.get_prompt_by_id(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Бесплатный промпт – доступен всем
    if prompt.get("is_free", False):
        return prompt

    # Платный – проверяем подписку
    if not current_user or not current_user.is_active:
        raise HTTPException(status_code=403, detail="Active subscription required")
    return prompt