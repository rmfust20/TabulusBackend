from sqlmodel import Field, SQLModel
from datetime import datetime

class PasswordResetToken(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userboardgame.id", index=True)
    token_hash: str = Field(index=True)
    expires_at: datetime
    used_at: datetime | None = Field(default=None)
