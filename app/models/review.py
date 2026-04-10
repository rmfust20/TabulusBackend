from typing import TYPE_CHECKING
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine, select

from app.models.user import UserBoardGamePublic

if TYPE_CHECKING:
    from app.models.user import UserBoardGame


class Review(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    board_game_id: int = Field(foreign_key="boardgame.id", index=True)
    user_id: int = Field(foreign_key="userboardgame.id", index=True)
    username: str = Field(index=True)
    rating: int | None = Field(default=None)
    comment: str | None = Field(default=None)
    date_created: str | None = Field(default=None)

    user: "UserBoardGame" = Relationship()

class ReviewUpdate(SQLModel):
    rating: int | None = Field(default=None)
    comment: str | None = Field(default=None)
    date_created: str | None = Field(default=None)

class ReviewPublic(SQLModel):
    id: int
    board_game_id: int
    rating: int | None = None
    comment: str | None = None
    date_created: str | None = None
    user: UserBoardGamePublic | None = None


