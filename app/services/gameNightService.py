from requests import session
from sqlalchemy.orm import selectinload
from sqlmodel import select
from app.connection import SessionDep
from app.models import Review, BoardGameDesigner, BoardGameDesignerLink, BoardGame, BoardGameFeedItem
from sqlmodel import Session, select, func, join, case
from app.models.gameNight import GameNight, GameNightPublic, GameNightImage, GameSessionHelper
from app.models.gameNightUserLink import GameNightUserLink
from app.models.user import UserBoardGameClientFacing
from app.models.gameSession import GameSession
from app.models.gameSessionUserLink import GameSessionUserLink
from app.models.userFriendLink import UserFriendLink

def get_game_night_profile(user_id: int, offset: int, session: SessionDep) -> list[GameNight]:
    stmt = (
        select(GameNight)
        .join(GameNightUserLink, GameNight.id == GameNightUserLink.game_night_id)
        .where(GameNightUserLink.user_id == user_id)
        .options(
            selectinload(GameNight.images)  # night.sessions + session.images
        )
        .order_by(GameNight.game_night_date.desc())
        .offset(offset)
        .limit(25)
    )

    nights = session.exec(stmt).unique().all()
    return nights

def get_game_night_feed(user_id: int, offset: int, session: SessionDep) -> list[GameNightPublic]:
    stmt = (
        select(GameNight)
        .join(GameNightUserLink, GameNight.id == GameNightUserLink.game_night_id)
        .where(
            (GameNightUserLink.user_id == user_id) |
            GameNightUserLink.user_id.in_(
                select(UserFriendLink.friend_user_id)
                .where(UserFriendLink.user_id == user_id)
            )
        )
        .options(
            selectinload(GameNight.images),
            selectinload(GameNight.sessions).selectinload(GameSession.winners),
            selectinload(GameNight.users)
        )
        .order_by(GameNight.game_night_date.desc())
        .offset(offset)
        .limit(25)
    )
    nights = session.exec(stmt).unique().all()
    result = []
    for night in nights:
        night_public = GameNightPublic(
            id=night.id,
            host_user_id=night.host_user_id,
            game_night_date=night.game_night_date,
            description=night.description,
            sessions=[
                GameSessionHelper(
                    board_game_id=game_session.board_game_id,
                    duration_minutes=game_session.duration_minutes,
                    winners_user_id=[winner.id for winner in game_session.winners]
                )
                for game_session in night.sessions
            ],
            images=[image.image_url for image in night.images],
            users=[UserBoardGameClientFacing(id=user.id, username=user.username) for user in night.users]
        )
        result.append(night_public)
    print(result)
    return result


def get_game_night(game_night_id: int, session: SessionDep) -> GameNight | None:
    stmt = (
        select(GameNight)
        .where(GameNight.id == game_night_id)
        .options(
            selectinload(GameNight.images),
            selectinload(GameNight.sessions).selectinload(GameSession.winners)
        )
    )
    return session.exec(stmt).unique().first()

def add_game_night(payload: GameNightPublic, session: SessionDep):
    # 1) Create the night
    game_night_db = GameNight(
        host_user_id=payload.host_user_id,
        game_night_date=func.now(),
        description=payload.description
    )
    session.add(game_night_db)
    session.flush()  # assigns game_night_db.id

    # 2) Night images
    for url in payload.images:
        session.add(GameNightImage(game_night_id=game_night_db.id, image_url=url))
    host_ids = {user.id for user in payload.users}
    if payload.host_user_id not in host_ids:
        session.add(GameNightUserLink(game_night_id=game_night_db.id, user_id=payload.host_user_id))
    for user in payload.users:
        session.add(GameNightUserLink(game_night_id=game_night_db.id, user_id=user.id))

    # 3) Sessions + their images
    for s in payload.sessions:
        game_session_db = GameSession(
            game_night_id=game_night_db.id,
            board_game_id=s.board_game_id,
            duration_minutes=s.duration_minutes,
            session_date = func.now()
        )
        session.add(game_session_db)
        session.flush()  # assigns game_session_db.id (needed for session images)
        for winner_id in s.winners_user_id:
            session.add(GameSessionUserLink(game_session_id=game_session_db.id, winner_user_id=winner_id))

        # If your session DTO includes image
    session.commit()
    session.refresh(game_night_db)
    return game_night_db


        





