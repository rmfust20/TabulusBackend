from requests import session

from app.models import UserBoardGame, UserBoardGameCreate, UserBoardGamePublic, UserBoardGameUpdate, LoginRequest, UserFriendLink, UserBoardGameClientFacing
from fastapi import APIRouter
from app.connection import SessionDep
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlmodel import Field, Session, SQLModel, create_engine, insert, select
from app.connection import SessionDep
from typing import Annotated
from app.models.boardGame import BoardGame
from app.models.user import UserBoardGameBase
from app.services.tokenService import create_access_token
from app.services.userService import get_current_user, get_user_board_games, hash_password, verify_password
from app.services.tokenService import new_refresh_token, hash_refresh_token
from app.models.refreshToken import RefreshToken
from datetime import datetime, timezone, timedelta

router = APIRouter(
    prefix="/users",
)

@router.post("/register")
def register_user(user: UserBoardGameCreate, session: SessionDep):
    existing = session.exec(select(UserBoardGame).where(UserBoardGame.username == user.username)).first()
    if existing:
        raise HTTPException(400, "Username already exists")

    user = UserBoardGame(username=user.username, password_hash=hash_password(user.password), email=user.email)
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"id": user.id, "username": user.username}

@router.post("/login")
def login_user(login_request: LoginRequest, session: SessionDep):
    user = session.exec(select(UserBoardGame).where(UserBoardGame.username == login_request.username)).first()
    if not user or not verify_password(login_request.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    
    access = create_access_token(user.id)

    raw_refresh = new_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
    )
    session.add(rt)
    session.commit()

    return {
        "access_token": access,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "user": {"id": user.id, "username": user.username},
    }

@router.post("/refresh")
def refresh(refresh_token: str, session: SessionDep):
    token_hash = hash_refresh_token(refresh_token)

    rt = session.exec(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).first()
    if not rt:
        raise HTTPException(401, "Invalid refresh token")

    now = datetime.now(timezone.utc)
    if rt.revoked_at is not None or rt.expires_at <= now:
        raise HTTPException(401, "Refresh token expired or revoked")

    # Optional (recommended): rotate refresh token
    rt.revoked_at = now
    new_raw = new_refresh_token()
    new_rt = RefreshToken(
        user_id=rt.user_id,
        token_hash=hash_refresh_token(new_raw),
        expires_at=now + timedelta(days=90),
    )
    session.add(new_rt)
    session.add(rt)
    session.commit()

    access = create_access_token(rt.user_id)
    return {"access_token": access, "refresh_token": new_raw, "token_type": "bearer"}


@router.post("/logout")
def logout(refresh_token: str, session: SessionDep):
    token_hash = hash_refresh_token(refresh_token)
    rt = session.exec(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).first()
    if rt:
        rt.revoked_at = datetime.now(timezone.utc)
        session.add(rt)
        session.commit()
    return {"ok": True}

@router.post("/addFriend/{user_id}/{friend_id}")
def add_friend(user_id: int, friend_id: int, session: SessionDep):
    if user_id != user_id:
        raise HTTPException(403, "Cannot add friend for another user")
    
    statement = insert(UserFriendLink).values(user_id=user_id, friend_user_id=friend_id)
    session.exec(statement)
    session.commit()
    return {"message": "Friend added successfully"}

    # Implement the logic to add a friend here

@router.get("/friends/{user_id}", response_model=list[UserBoardGameClientFacing])
def get_friends(user_id: int, session: SessionDep): 
    statement = (
        select(UserBoardGame)
        .join(UserFriendLink, UserBoardGame.id == UserFriendLink.friend_user_id)
        .where(UserFriendLink.user_id == user_id)
    )
    friends = session.exec(statement).all()
    return [{"id": friend.id, "username": friend.username} for friend in friends]

@router.get("/userBoardGames/{user_id}", response_model=list[BoardGame])
def get_user_board_games_route(user_id: int, session: SessionDep):
    return get_user_board_games(user_id, session)

@router.patch("/updateUser", response_model=UserBoardGamePublic)
def update_user(updates: UserBoardGameUpdate, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    if updates.profile_image_url is not None:
        current_user.profile_image_url = updates.profile_image_url
    if updates.username is not None:
        current_user.username = updates.username
    if updates.email is not None:
        current_user.email = updates.email
    if updates.password is not None:
        current_user.password_hash = hash_password(updates.password)
    print(current_user)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user

@router.get("/userBoardGames/{user_id}", response_model=list[BoardGame])
def get_user_board_games_route(user_id: int, session: SessionDep):
    return get_user_board_games(user_id, session)