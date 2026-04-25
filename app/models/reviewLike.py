from sqlmodel import Field, SQLModel


class ReviewLike(SQLModel, table=True):
    user_id: int = Field(foreign_key="userboardgame.id", primary_key=True)
    review_id: int = Field(foreign_key="review.id", primary_key=True)
