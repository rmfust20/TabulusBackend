from typing import TYPE_CHECKING
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine, select
from app.models.gameSessionUserLink import GameSessionUserLink
from app.models.gameNightUserLink import GameNightUserLink

if TYPE_CHECKING:
    from app.models.gameSession import GameSession
    from app.models.gameNight import GameNight

class UserBoardGameBase(SQLModel):
    username: str = Field(index=True, sa_column_kwargs={"unique": True})
    email: str = Field(index = True)
    profile_image_url: str | None = None

class UserBoardGame(UserBoardGameBase,table=True):
    id: int | None = Field(default=None, primary_key=True)
    password_hash : str
    won_sessions: list["GameSession"] = Relationship(back_populates="winners", link_model=GameSessionUserLink)
    game_nights: list["GameNight"] = Relationship(link_model=GameNightUserLink, back_populates="users")
    profile_image_url: str | None = None

class UserBoardGamePublic(UserBoardGameBase):
    id: int
    profile_image_url: str | None = None

class UserBoardGameCreate(UserBoardGameBase):
    password : str

class UserBoardGameUpdate(UserBoardGameBase):
    password: str | None = None
    profile_image_url: str | None = None

class UserBoardGameClientFacing(SQLModel):
    id: int
    username: str

