from ..config import Settings
from ..llm_models import normalize_model_id
from ..models import UserProfile
from .llm import LLMService, create_llm_service


class LLMServiceFactory:
    def __init__(self, settings: Settings):
        self.settings = settings

    def for_user(self, profile: UserProfile) -> LLMService:
        model = normalize_model_id(profile.llm_model or self.settings.llm_model)
        return create_llm_service(self.settings, model=model)

    def default_service(self) -> LLMService:
        return create_llm_service(self.settings)
