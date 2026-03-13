from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, Query
from app.connection import SessionDep
from fastapi import APIRouter
from sqlmodel import Field, Session, SQLModel, create_engine, select
from app.models import BoardGame
from app.models.boardGame import BoardGameFeedItem
from app.models.gameNight import GameNight, GameNightPublic
from app.services import getBoardGameByName, reviewsService, feedService
from app.models import BoardGameDesigner
from app.models import BoardGameDesignerLink
from app.services import get_game_night_feed
from app.services.gameNightService import add_game_night, get_user_game_nights


router = APIRouter(
    prefix="/gameNights",
    )

@router.get("/userFeed/{user_id}", response_model=list[GameNightPublic])
def get_game_nights(user_id: int, session:SessionDep, offset: int = 0):
    print("logging user id and offset", user_id, offset)
    feed = get_game_night_feed(user_id=user_id, offset=offset, session=session)
    return feed
    
    
@router.post("/postNight")
def post_game_night(game_night_public: GameNightPublic, session: SessionDep):
    add_game_night(payload=game_night_public, session=session)
    return {"message": "Game night added successfully"}

@router.get("/userGameNights/{user_id}", response_model=list[GameNightPublic])
def get_user_game_nights_route(user_id: int, session: SessionDep):
    return get_user_game_nights(user_id, session)