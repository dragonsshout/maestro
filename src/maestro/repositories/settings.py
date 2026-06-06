from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func
from maestro.database.session import get_db
from maestro.database.models import UISettings


class UISettingsRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def get_all(self) -> dict[str, str | None]:
        result = await self.db.execute(select(UISettings).order_by(UISettings.key))
        rows = result.scalars().all()
        return {row.key: row.value for row in rows}

    async def get(self, key: str) -> str | None:
        result = await self.db.execute(
            select(UISettings).where(UISettings.key == key)
        )
        row = result.scalars().first()
        return row.value if row else None

    async def upsert(self, key: str, value: str | None) -> None:
        """Insere ou atualiza uma configuração pelo key."""
        dialect_name = self.db.bind.dialect.name if self.db.bind else "postgresql"

        if dialect_name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = (
                sqlite_insert(UISettings)
                .values(key=key, value=value)
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={"value": value, "updated_at": func.now()},
                )
            )
        else:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = (
                pg_insert(UISettings)
                .values(key=key, value=value)
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={"value": value, "updated_at": func.now()},
                )
            )

        await self.db.execute(stmt)
        await self.db.commit()

    async def upsert_many(self, settings: dict[str, str | None]) -> None:
        """Salva múltiplas configurações de uma vez."""
        for key, value in settings.items():
            await self.upsert(key, value)
