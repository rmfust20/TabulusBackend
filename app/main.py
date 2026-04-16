from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlmodel import Field, Session, SQLModel, create_engine, select
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.connection import engine
import app.models
from app.models import UserBoardGame, UserBoardGameCreate, UserBoardGamePublic, UserBoardGameUpdate, GameNight, GameSession
from app.routes import boardGameAPI
from app.routes import reviewsAPI
from app.routes import userAPI
from app.routes import gameNightAPI
from app.routes import imagesAPI
from app.utilities.limiter import limiter


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

SessionDep = Annotated[Session, Depends(get_session)]

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.include_router(boardGameAPI.router)
app.include_router(reviewsAPI.router)
app.include_router(userAPI.router)
app.include_router(gameNightAPI.router)
app.include_router(imagesAPI.router)
#trigger deploy

@app.get("/.well-known/apple-app-site-association")
def apple_app_site_association():
    return JSONResponse(
        content={
            "applinks": {
                "apps": [],
                "details": [
                    {
                        "appID": "FZ8JM6H768.robertm.boardGameReview",
                        "paths": ["/users/invite/*"],
                    }
                ],
            }
        },
        media_type="application/json",
    )

@app.on_event("startup")
def on_startup():
    create_db_and_tables()









'''
@app.get("/")
def populate(session: SessionDep):
    create_board_games(session)
    return {"message": "Database populated with board games."}
'''






