from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class HealthRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def database_is_ready(self) -> bool:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
