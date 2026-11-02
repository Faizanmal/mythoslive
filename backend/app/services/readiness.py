from app.repositories.health import HealthRepository


class ReadinessService:
    def __init__(self, repository: HealthRepository) -> None:
        self._repository = repository

    async def is_ready(self) -> bool:
        try:
            return await self._repository.database_is_ready()
        except Exception:
            return False
