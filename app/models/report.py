from datetime import datetime, timezone
from sqlmodel import Field, SQLModel


class Report(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    reporter_user_id: int = Field(foreign_key="userboardgame.id", index=True)
    content_type: str  # "game_night" or "review"
    content_id: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

#