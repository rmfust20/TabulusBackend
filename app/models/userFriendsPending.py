from sqlmodel import Field, Session, SQLModel, create_engine, select

class UserFriendPending(SQLModel, table=True):
    user_id: int = Field(foreign_key="userboardgame.id", primary_key=True)
    incoming_friend_user_id: int = Field(foreign_key="userboardgame.id", primary_key=True)
