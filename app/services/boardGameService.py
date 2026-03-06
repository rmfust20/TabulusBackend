from datetime import datetime, timedelta, timezone
from requests import session
from app.connection import SessionDep
from app.models import BoardGame, GameNight, GameSession, UserFriendLink, UserBoardGame
from sqlmodel import Session, select, func, join, case

def get_general_trending_feed(session: SessionDep, offset: int = 0) -> list[BoardGame]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    statement = (
        select(GameSession.board_game_id, func.count(GameSession.board_game_id).label("count"))
        .where(GameSession.session_date >= cutoff)  # Only consider sessions from the last 30 days
        .group_by(GameSession.board_game_id)
        .order_by(func.count(GameSession.board_game_id).desc())
        .offset(offset)
        .limit(25)
    )

    results = session.exec(statement).all()
    board_game_ids = [result[0] for result in results]
    statement = select(BoardGame).where(BoardGame.id.in_(board_game_ids))
    board_games = session.exec(statement).all()
    return board_games

def get_trending_with_friends_feed(user_id: int, session: SessionDep, offset: int = 0) -> list[BoardGame]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    # Get the user's friends' IDs (this assumes you have a way to determine friends)
    statement = (
        select(GameSession.board_game_id, func.count(GameSession.board_game_id).label("count"))
        .where(
            GameSession.session_date >= cutoff,
            GameSession.winner_user_id.in_(
                select(UserFriendLink.friend_user_id)
                .where(UserFriendLink.user_id == user_id)
            )  # Only consider sessions where a friend won
        )
        .group_by(GameSession.board_game_id)
        .order_by(func.count(GameSession.board_game_id).desc())
        .offset(offset)
        .limit(25)
        #trigger build
    )

#commit triiger
    results = session.exec(statement).all()
    board_game_ids = [result[0] for result in results]
    statement = select(BoardGame).where(BoardGame.id.in_(board_game_ids))
    board_games = session.exec(statement).all()
    return board_games


