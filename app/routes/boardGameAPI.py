from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from app.connection import SessionDep
from fastapi import APIRouter
from sqlmodel import Field, Session, SQLModel, create_engine, select
from app.models import BoardGame
from app.models.boardGame import BoardGameFeedItem
from app.services import reviewsService, feedService, get_general_trending_feed
from app.models import BoardGameDesigner
from app.models import BoardGameDesignerLink
from app.services.boardGameService import get_trending_with_friends_feed
from app.services.bombBoardGames import bomb_board_games
from app.models.hotBoardGame import HotBoardGame
from app.models.user import UserBoardGame
from app.services.userService import get_current_user
from app.utilities.limiter import limiter


router = APIRouter(
    prefix="/boardGames",
)

@router.get("/search/{name}", response_model=list[BoardGame])
@limiter.limit("300/hour")
def read_board_game_by_name(request: Request, name: str, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    statement = select(BoardGame).where(BoardGame.name.ilike(f'%{name}%'))
    board_games = session.exec(statement).all()
    if not board_games:
        raise HTTPException(status_code=404, detail="Board game not found")
    return board_games

@router.get("/userFeed/{user_id}", response_model=list[BoardGame])
@limiter.limit("300/hour")
def get_user_board_games_feed(request: Request, user_id: int, session: SessionDep, lastSeenID: int = 0, _: UserBoardGame = Depends(get_current_user)):
    statement = select(BoardGame).offset(lastSeenID).order_by(BoardGame.id).limit(25)
    board_games = session.exec(statement).all()
    return board_games

@router.get("/userFeed/{user_id}/rehydrate", response_model=list[BoardGame])
@limiter.limit("60/hour")
def rehydrate_user_board_games(request: Request, user_id: int, session: SessionDep, board_game_ids: list[int] = Query(...), _: UserBoardGame = Depends(get_current_user)):
    statement = select(BoardGame).where(BoardGame.id.in_(board_game_ids)).order_by(BoardGame.id)
    board_games = session.exec(statement).all()
    return board_games

@router.get("/trendingFeed", response_model=list[BoardGame])
@limiter.limit("300/hour")
def get_trending_board_games_feed(request: Request, session: SessionDep, offset: int = 0, _: UserBoardGame = Depends(get_current_user)):
    return get_general_trending_feed(session=session, offset=offset)

@router.get("/trendingFriends/{user_id}", response_model=list[BoardGame])
@limiter.limit("300/hour")
def get_trending_friends_board_games_feed(request: Request, user_id: int, session: SessionDep, offset: int = 0, _: UserBoardGame = Depends(get_current_user)):
    return get_trending_with_friends_feed(user_id=user_id, session=session, offset=offset)

#Deprecated
@router.get("/feed", response_model=list[BoardGame])
@limiter.limit("300/hour")
def get_board_games(request: Request, session: SessionDep, offset: int = 0, limit: Annotated[int, Query(le=100)] = 100, _: UserBoardGame = Depends(get_current_user)):
    board_games = select(BoardGame).offset(offset).limit(limit)
    boardGames = session.exec(board_games).all()
    return boardGames

#get individual board game by id
@router.get("/fetchBoardGame/{board_game_id}", response_model=BoardGame)
@limiter.limit("300/hour")
def get_board_game_by_id(request: Request, board_game_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    statemenet = select(BoardGame).where(BoardGame.id == board_game_id)
    board_game = session.exec(statemenet).first()
    if board_game == None:
        raise HTTPException(status_code=404, detail="Board game not found")
    return board_game

#get designers
@router.get("/designers/{board_game_id}", response_model=list[BoardGameDesigner])
@limiter.limit("300/hour")
def get_board_game_designers(request: Request, board_game_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    statement = (
        select(BoardGameDesigner)
        .join(BoardGameDesignerLink)
        .where(BoardGameDesignerLink.board_game_id == board_game_id)
    )
    results = session.exec(statement).all()
    return results

@router.get("/boardGamesByIds", response_model=list[BoardGame])
@limiter.limit("60/hour")
def get_board_games_by_ids(request: Request, session: SessionDep, board_game_ids: list[int] = Query(...), _: UserBoardGame = Depends(get_current_user)):
    statement = select(BoardGame).where(BoardGame.id.in_(board_game_ids)).order_by(BoardGame.id)
    board_games = session.exec(statement).all()
    return board_games

@router.get("/hot", response_model=list[BoardGame])
@limiter.limit("300/hour")
def get_hot_board_games_feed(request: Request, session: SessionDep, offset: int = 0, limit: Annotated[int, Query(le=50)] = 25, _: UserBoardGame = Depends(get_current_user)):
    statement = (
        select(BoardGame)
        .join(HotBoardGame, HotBoardGame.board_game_id == BoardGame.id)
        .order_by(HotBoardGame.rank)
        .offset(offset)
        .limit(limit)
    )
    return session.exec(statement).all()

@router.post("/bomb")
@limiter.limit("1/hour")
def bomb_games(request: Request, session: SessionDep):
    added = bomb_board_games(session)
    return {"added": added}
