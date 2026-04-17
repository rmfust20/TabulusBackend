from requests import session
from sqlalchemy.orm import selectinload
from sqlmodel import select
from app.connection import SessionDep
from app.models import Review, BoardGameDesigner, BoardGameDesignerLink, BoardGame, BoardGameFeedItem
from sqlmodel import Session, select, func, join, case
from app.models.gameNight import GameNight, GameNightPublic, GameNightImage, GameSessionHelper, GameNightCreate
from app.models.gameNightUserLink import GameNightUserLink
from app.models.user import UserBoardGamePublic
from app.models.gameSession import GameSession
from app.models.gameSessionUserLink import GameSessionUserLink
from app.models.userFriendLink import UserFriendLink
from app.models.report import Report
#rebuild
def get_game_night_profile(user_id: int, offset: int, session: SessionDep) -> list[GameNight]:
    stmt = (
        select(GameNight)
        .join(GameNightUserLink, GameNight.id == GameNightUserLink.game_night_id)
        .where(GameNightUserLink.user_id == user_id)
        .options(
            selectinload(GameNight.images)  # night.sessions + session.images
        )
        .order_by(GameNight.id.desc())
        .offset(offset)
        .limit(10)
    )

    nights = session.exec(stmt).unique().all()
    return nights

def get_game_night_feed(user_id: int, offset: int, session: SessionDep, limit: int = 10, current_user_id: int | None = None) -> list[GameNightPublic]:
    reported_ids = select(Report.content_id).where(
        Report.reporter_user_id == (current_user_id or user_id),
        Report.content_type == "game_night",
    )
    stmt = (
        select(GameNight)
        .where(
            (GameNight.host_user_id == user_id) |
            GameNight.host_user_id.in_(
                select(UserFriendLink.friend_user_id)
                .where(UserFriendLink.user_id == user_id)
            )
        )
        .where(GameNight.id.notin_(reported_ids))
        .options(
            selectinload(GameNight.images),
            selectinload(GameNight.sessions).selectinload(GameSession.winners),
            selectinload(GameNight.sessions).selectinload(GameSession.board_game),
            selectinload(GameNight.users)
        )
        .order_by(GameNight.id.desc())
        .offset(offset)
        .limit(limit)
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
                    board_game=game_session.board_game,
                    duration_minutes=game_session.duration_minutes,
                    winners_user_id=[winner.id for winner in game_session.winners]
                )
                for game_session in night.sessions
            ],
            images=[image.image_url for image in night.images],
            users=[UserBoardGamePublic(id=user.id, username=user.username, email=user.email, profile_image_url=user.profile_image_url) for user in night.users]
        )
        result.append(night_public)
   
    #ok so result is a list of GameNightPublic objects
    return result


def get_user_game_nights(user_id: int, session: SessionDep, offset: int = 0, limit: int = 10) -> list[GameNightPublic]:
    stmt = (
        select(GameNight)
        .where(GameNight.host_user_id == user_id)
        .options(
            selectinload(GameNight.images),
            selectinload(GameNight.sessions).selectinload(GameSession.winners),
            selectinload(GameNight.sessions).selectinload(GameSession.board_game),
            selectinload(GameNight.users)
        )
        .order_by(GameNight.id.desc())
        .offset(offset)
        .limit(limit)
    )
    nights = session.exec(stmt).unique().all()
    return [
        GameNightPublic(
            id=night.id,
            host_user_id=night.host_user_id,
            game_night_date=night.game_night_date,
            description=night.description,
            sessions=[
                GameSessionHelper(
                    board_game=gs.board_game,
                    duration_minutes=gs.duration_minutes,
                    winners_user_id=[w.id for w in gs.winners]
                )
                for gs in night.sessions
            ],
            images=[image.image_url for image in night.images],
            users=[UserBoardGamePublic(id=u.id, username=u.username, email=u.email, profile_image_url=u.profile_image_url) for u in night.users]
        )
        for night in nights
    ]

def get_user_game_night(game_night_id: int, session: SessionDep) -> GameNightPublic | None:
    stmt = (
        select(GameNight)
        .where(GameNight.id == game_night_id)
        .options(
            selectinload(GameNight.images),
            selectinload(GameNight.sessions).selectinload(GameSession.winners),
            selectinload(GameNight.sessions).selectinload(GameSession.board_game),
            selectinload(GameNight.users)
        )
    )
    night = session.exec(stmt).unique().first()
    if not night:
        return None
    return GameNightPublic(
        id=night.id,
        host_user_id=night.host_user_id,
        game_night_date=night.game_night_date,
        description=night.description,
        sessions=[
            GameSessionHelper(
                board_game=gs.board_game,
                duration_minutes=gs.duration_minutes,
                winners_user_id=[w.id for w in gs.winners]
            )
            for gs in night.sessions
        ],
        images=[image.image_url for image in night.images],
        users=[UserBoardGamePublic(id=u.id, username=u.username, email=u.email, profile_image_url=u.profile_image_url) for u in night.users]
    )

def get_user_recent_game_nights_with_images(user_id: int, session: SessionDep) -> list[GameNightPublic]:
    stmt = (
        select(GameNight)
        .where(GameNight.host_user_id == user_id)
        .where(GameNight.images.any())
        .options(
            selectinload(GameNight.images),
            selectinload(GameNight.sessions).selectinload(GameSession.winners),
            selectinload(GameNight.sessions).selectinload(GameSession.board_game),
            selectinload(GameNight.users)
        )
        .order_by(GameNight.id.desc())
        .limit(4)
    )
    nights = session.exec(stmt).unique().all()
    return [
        GameNightPublic(
            id=night.id,
            host_user_id=night.host_user_id,
            game_night_date=night.game_night_date,
            description=night.description,
            sessions=[
                GameSessionHelper(
                    board_game=gs.board_game,
                    duration_minutes=gs.duration_minutes,
                    winners_user_id=[w.id for w in gs.winners]
                )
                for gs in night.sessions
            ],
            images=[image.image_url for image in night.images],
            users=[UserBoardGamePublic(id=u.id, username=u.username, email=u.email, profile_image_url=u.profile_image_url) for u in night.users]
        )
        for night in nights
    ]

def delete_game_night(game_night_id: int, user_id: int, session: SessionDep) -> bool:
    from sqlmodel import delete as sql_delete
    from azure.storage.blob import BlobServiceClient
    from azure.identity import DefaultAzureCredential
    from azure.core.exceptions import ResourceNotFoundError, AzureError

    night = session.get(GameNight, game_night_id)
    if not night:
        return False
    if night.host_user_id != user_id:
        raise ValueError("Not authorized to delete this game night")

    # Fetch blob names before touching anything
    image_rows = session.exec(
        select(GameNightImage).where(GameNightImage.game_night_id == game_night_id)
    ).all()
    blob_names = [img.image_url for img in image_rows]

    # Delete blobs FIRST — if this fails the DB is untouched and data remains intact
    if blob_names:
        bsc = BlobServiceClient(
            account_url="https://tabulususerimages.blob.core.windows.net",
            credential=DefaultAzureCredential(),
        )
        container = bsc.get_container_client("images")
        failed: list[str] = []
        for blob_name in blob_names:
            try:
                container.get_blob_client(blob_name).delete_blob(delete_snapshots="include")
            except ResourceNotFoundError:
                pass  # already gone — that's fine
            except AzureError as e:
                failed.append(blob_name)

        if failed:
            raise RuntimeError(f"Failed to delete {len(failed)} blob(s) from Azure: {failed}")

    # All blobs confirmed gone — now clean up the DB
    session_ids = session.exec(
        select(GameSession.id).where(GameSession.game_night_id == game_night_id)
    ).all()
    if session_ids:
        session.exec(sql_delete(GameSessionUserLink).where(GameSessionUserLink.game_session_id.in_(session_ids)))

    session.exec(sql_delete(GameSession).where(GameSession.game_night_id == game_night_id))
    session.exec(sql_delete(GameNightImage).where(GameNightImage.game_night_id == game_night_id))
    session.exec(sql_delete(GameNightUserLink).where(GameNightUserLink.game_night_id == game_night_id))
    session.delete(night)
    session.commit()

    return True

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

def add_game_night(payload: GameNightCreate, session: SessionDep):
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

    # 3) Attendees — always include host
    user_ids = set(payload.users)
    user_ids.add(payload.host_user_id)
    for uid in user_ids:
        session.add(GameNightUserLink(game_night_id=game_night_db.id, user_id=uid))

    # 4) Sessions + winners
    for s in payload.sessions:
        game_session_db = GameSession(
            game_night_id=game_night_db.id,
            board_game_id=s.board_game_id,
            duration_minutes=s.duration_minutes,
            session_date=func.now()
        )
        session.add(game_session_db)
        session.flush()
        for winner_id in s.winner_user_ids:
            session.add(GameSessionUserLink(game_session_id=game_session_db.id, winner_user_id=winner_id))

    session.commit()
    session.refresh(game_night_db)
    return game_night_db


        





