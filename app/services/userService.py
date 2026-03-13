# security.py
from fastapi.security import HTTPBearer
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlmodel import select
from app.connection import SessionDep
from app.models import UserBoardGame
from app.models.boardGame import BoardGame
from app.models.gameNightUserLink import GameNightUserLink
from app.models.gameSession import GameSession
from app.models.review import Review
from app.services.tokenService import decode_access_token

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

bearer = HTTPBearer(auto_error=False)

def get_current_user(
    session: SessionDep,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> UserBoardGame:
    if not creds or creds.scheme.lower() != "bearer":
        raise HTTPException(401, "Missing auth token")

    try:
        payload = decode_access_token(creds.credentials)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid auth token")

    user = session.exec(select(UserBoardGame).where(UserBoardGame.id == user_id)).first()
    if not user:
        raise HTTPException(401, "User not found")
    return user

def get_user_board_games(user_id: int, db: SessionDep):
    reviewed = (
        select(BoardGame)
        .join(Review, BoardGame.id == Review.board_game_id)
        .where(Review.user_id == user_id)
    )

    played = (
        select(BoardGame)
        .join(GameSession, BoardGame.id == GameSession.board_game_id)
        .join(GameNightUserLink, GameSession.game_night_id == GameNightUserLink.game_night_id)
        .where(GameNightUserLink.user_id == user_id)
    )

    board_game_ids = set()
    result = []
    for bg in db.exec(reviewed).all() + db.exec(played).all():
        if bg.id not in board_game_ids:
            board_game_ids.add(bg.id)
            result.append(bg)
    return result
