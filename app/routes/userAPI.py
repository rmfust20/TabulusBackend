from requests import session

from app.models import UserBoardGame, UserBoardGameCreate, UserBoardGamePublic, UserBoardGameUpdate, LoginRequest, UserFriendLink, UserBoardGameClientFacing
from fastapi import APIRouter, Request
from app.connection import SessionDep
from fastapi import Depends, FastAPI, HTTPException, Query
from app.utilities.limiter import limiter
from sqlmodel import Field, Session, SQLModel, create_engine, insert, select, delete, func
from app.connection import SessionDep
from typing import Annotated
from app.models.boardGame import BoardGame
from app.models.user import UserBoardGameBase
from app.models.userFriendsPending import UserFriendPending
from app.models.userBlockLink import UserBlockLink
from app.models.gameNightUserLink import GameNightUserLink
from app.models.gameSessionUserLink import GameSessionUserLink
from app.models.gameNight import GameNight, GameNightImage
from app.models.gameSession import GameSession
from app.models import Review
from app.services.tokenService import create_access_token
from app.services.userService import get_current_user, get_user_board_games, hash_password, verify_password
from app.services.tokenService import new_refresh_token, hash_refresh_token
from app.models.refreshToken import RefreshToken
from app.models.passwordResetToken import PasswordResetToken
from app.models.emailVerificationToken import EmailVerificationToken
from app.models.report import Report
from app.models.inviteToken import InviteToken
from app.services.appleAuthService import verify_apple_token
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel


class RefreshTokenRequest(BaseModel):
    refresh_token: str

class AppleAuthRequest(BaseModel):
    identity_token: str


class AppleCompleteRequest(BaseModel):
    apple_id: str
    username: str
    email: str | None = None

def _send_verification_email(user_id: int, email: str, session: SessionDep):
    import uuid, hashlib, os
    from azure.communication.email import EmailClient

    raw_token = str(uuid.uuid4())
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    session.exec(
        delete(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.used_at == None,
        )
    )

    verification_token = EmailVerificationToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    session.add(verification_token)
    session.commit()

    client = EmailClient.from_connection_string(os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING"))
    client.begin_send({
        "senderAddress": os.getenv("AZURE_EMAIL_SENDER"),
        "recipients": {"to": [{"address": email}]},
        "content": {
            "subject": "Verify your Tabulus email",
            "plainText": f"Tap the link to verify your email. It expires in 24 hours.\n\nhttps://tabulusapp.bravegrass-0afbc7b6.westus2.azurecontainerapps.io/users/verifyEmail?token={raw_token}",
        },
    })

router = APIRouter(
    prefix="/users",
)

@router.post("/register")
@limiter.limit("5/minute")
def register_user(request: Request, user: UserBoardGameCreate, session: SessionDep):
    existing = session.exec(select(UserBoardGame).where(UserBoardGame.username == user.username)).first()
    if existing:
        raise HTTPException(400, "Username already exists")

    if user.email:
        existing_email = session.exec(select(UserBoardGame).where(UserBoardGame.email == user.email)).first()
        if existing_email:
            raise HTTPException(400, "Email already in use")

    user = UserBoardGame(username=user.username, password_hash=hash_password(user.password), email=user.email)
    session.add(user)
    session.commit()
    session.refresh(user)

    if user.email:
        _send_verification_email(user.id, user.email, session)

    return {"id": user.id, "username": user.username}

@router.post("/login")
@limiter.limit("10/minute")
def login_user(request: Request, login_request: LoginRequest, session: SessionDep):
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
@limiter.limit("20/minute")
def refresh(request: Request, session: SessionDep, body: RefreshTokenRequest | None = None, refresh_token: str | None = None):
    token = body.refresh_token if body else refresh_token
    if not token:
        raise HTTPException(400, "refresh_token is required")
    token_hash = hash_refresh_token(token)

    rt = session.exec(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).first()
    if not rt:
        raise HTTPException(401, "Invalid refresh token")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
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
@limiter.limit("20/minute")
def logout(request: Request, session: SessionDep, body: RefreshTokenRequest | None = None, refresh_token: str | None = None):
    token = body.refresh_token if body else refresh_token
    if not token:
        raise HTTPException(400, "refresh_token is required")
    token_hash = hash_refresh_token(token)
    rt = session.exec(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).first()
    if rt:
        rt.revoked_at = datetime.now(timezone.utc)
        session.add(rt)
        session.commit()
    return {"ok": True}

@router.get("/pendingFriends/{user_id}", response_model=list[UserBoardGameClientFacing])
@limiter.limit("300/hour")
def get_pending_friends(request: Request, user_id: int, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    if current_user.id != user_id:
        raise HTTPException(403, "Cannot view another user's pending friends")
    statement = (
        select(UserBoardGame)
        .join(UserFriendPending, UserBoardGame.id == UserFriendPending.incoming_friend_user_id)
        .where(UserFriendPending.user_id == user_id)
    )
    pending_friends = session.exec(statement).all()
    return [{"id": friend.id, "username": friend.username} for friend in pending_friends]

@router.get("/sentFriendRequests/{user_id}", response_model=list[UserBoardGameClientFacing])
@limiter.limit("300/hour")
def get_sent_friend_requests(request: Request, user_id: int, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    if current_user.id != user_id:
        raise HTTPException(403, "Cannot view another user's sent requests")
    statement = (
        select(UserBoardGame)
        .join(UserFriendPending, UserBoardGame.id == UserFriendPending.user_id)
        .where(UserFriendPending.incoming_friend_user_id == user_id)
    )
    users = session.exec(statement).all()
    return [{"id": u.id, "username": u.username} for u in users]

@router.post("/rejectFriend/{user_id}/{friend_id}")
@limiter.limit("60/hour")
def reject_friend(request: Request, user_id: int, friend_id: int, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    if current_user.id != user_id:
        raise HTTPException(403, "Cannot reject friend for another user")

    session.exec(
        delete(UserFriendPending)
        .where(UserFriendPending.user_id == user_id, UserFriendPending.incoming_friend_user_id == friend_id)
    )
    session.commit()
    return {"message": "Friend request rejected"}

@router.post("/sendFriendRequest/{user_id}/{friend_id}")
@limiter.limit("20/hour")
def send_friend_request(request: Request, user_id: int, friend_id: int, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    if current_user.id != user_id:
        raise HTTPException(403, "Cannot send friend request for another user")

    # user_id = recipient, incoming_friend_user_id = sender
    statement = insert(UserFriendPending).values(user_id=friend_id, incoming_friend_user_id=user_id)
    session.exec(statement)
    session.commit()
    return {"message": "Friend request sent"}

@router.post("/acceptFriend/{user_id}/{friend_id}")
@limiter.limit("60/hour")
def accept_friend(request: Request, user_id: int, friend_id: int, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    if current_user.id != user_id:
        raise HTTPException(403, "Cannot accept friend for another user")

    # Remove from pending (recipient=user_id, sender=friend_id)
    session.exec(
        delete(UserFriendPending)
        .where(UserFriendPending.user_id == user_id, UserFriendPending.incoming_friend_user_id == friend_id)
    )
    # Add to friends (both directions)
    session.exec(insert(UserFriendLink).values(user_id=user_id, friend_user_id=friend_id))
    session.exec(insert(UserFriendLink).values(user_id=friend_id, friend_user_id=user_id))
    session.commit()
    return {"message": "Friend request accepted"}

@router.delete("/removeFriend/{user_id}/{friend_id}")
@limiter.limit("60/hour")
def remove_friend(request: Request, user_id: int, friend_id: int, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    if current_user.id != user_id:
        raise HTTPException(403, "Cannot remove friend for another user")

    session.exec(delete(UserFriendLink).where(UserFriendLink.user_id == user_id, UserFriendLink.friend_user_id == friend_id))
    session.exec(delete(UserFriendLink).where(UserFriendLink.user_id == friend_id, UserFriendLink.friend_user_id == user_id))
    session.commit()
    return {"message": "Friend removed"}

@router.get("/friends/{user_id}", response_model=list[UserBoardGameClientFacing])
@limiter.limit("300/hour")
def get_friends(request: Request, user_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    statement = (
        select(UserBoardGame)
        .join(UserFriendLink, UserBoardGame.id == UserFriendLink.friend_user_id)
        .where(UserFriendLink.user_id == user_id)
    )
    friends = session.exec(statement).all()
    return [{"id": friend.id, "username": friend.username} for friend in friends]

@router.get("/boardGames/{user_id}", response_model=list[BoardGame])
@limiter.limit("300/hour")
def get_user_board_games_route(request: Request, user_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    return get_user_board_games(user_id, session)

@router.patch("/updateUser", response_model=UserBoardGamePublic)
@limiter.limit("60/hour")
def update_user(request: Request, updates: UserBoardGameUpdate, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    if updates.profile_image_url is not None:
        current_user.profile_image_url = updates.profile_image_url
    if updates.username is not None:
        current_user.username = updates.username
    if updates.email is not None:
        current_user.email = updates.email
    if updates.password is not None:
        current_user.password_hash = hash_password(updates.password)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user

@router.get("/search", response_model=list[UserBoardGameClientFacing])
@limiter.limit("300/hour")
def search_users(request: Request, username: str, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    statement = select(UserBoardGame).where(UserBoardGame.username.ilike(f"%{username}%")).limit(25)
    users = session.exec(statement).all()
    return [{"id": u.id, "username": u.username} for u in users]

@router.get("/winRate/{user_id}")
@limiter.limit("300/hour")
def get_win_rate(request: Request, user_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    # Total sessions at game nights the user attended
    attended_night_ids = select(GameNightUserLink.game_night_id).where(GameNightUserLink.user_id == user_id)
    total = session.exec(
        select(func.count(GameSession.id)).where(GameSession.game_night_id.in_(attended_night_ids))
    ).one()

    # Sessions where user was a winner
    wins = session.exec(
        select(func.count(GameSessionUserLink.game_session_id))
        .where(GameSessionUserLink.winner_user_id == user_id)
    ).one()

    win_rate = round(wins / total, 4) if total > 0 else 0.0
    return {"user_id": user_id, "wins": wins, "total_sessions": total, "win_rate": win_rate}

@router.get("/winRate/{user_id}/{board_game_id}")
@limiter.limit("300/hour")
def get_win_rate_for_board_game(request: Request, user_id: int, board_game_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    # Sessions of this specific game at nights the user attended
    attended_night_ids = select(GameNightUserLink.game_night_id).where(GameNightUserLink.user_id == user_id)
    total = session.exec(
        select(func.count(GameSession.id))
        .where(GameSession.game_night_id.in_(attended_night_ids), GameSession.board_game_id == board_game_id)
    ).one()

    # Wins for this specific game
    wins_subquery = select(GameSessionUserLink.game_session_id).where(GameSessionUserLink.winner_user_id == user_id)
    wins = session.exec(
        select(func.count(GameSession.id))
        .where(GameSession.id.in_(wins_subquery), GameSession.board_game_id == board_game_id)
    ).one()

    win_rate = round(wins / total, 4) if total > 0 else 0.0
    return {"user_id": user_id, "board_game_id": board_game_id, "wins": wins, "total_sessions": total, "win_rate": win_rate}

@router.post("/block/{blocked_user_id}")
@limiter.limit("60/hour")
def block_user(request: Request, blocked_user_id: int, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    if current_user.id == blocked_user_id:
        raise HTTPException(400, "Cannot block yourself")
    existing = session.get(UserBlockLink, (current_user.id, blocked_user_id))
    if existing:
        return {"message": "User already blocked"}
    session.add(UserBlockLink(user_id=current_user.id, blocked_user_id=blocked_user_id))
    # Remove friendship in both directions if it exists
    session.exec(delete(UserFriendLink).where(UserFriendLink.user_id == current_user.id, UserFriendLink.friend_user_id == blocked_user_id))
    session.exec(delete(UserFriendLink).where(UserFriendLink.user_id == blocked_user_id, UserFriendLink.friend_user_id == current_user.id))
    # Remove any pending friend requests in both directions
    session.exec(delete(UserFriendPending).where(UserFriendPending.user_id == current_user.id, UserFriendPending.incoming_friend_user_id == blocked_user_id))
    session.exec(delete(UserFriendPending).where(UserFriendPending.user_id == blocked_user_id, UserFriendPending.incoming_friend_user_id == current_user.id))
    session.commit()
    return {"message": "User blocked"}

@router.get("/gameNightsHosted/{user_id}")
@limiter.limit("300/hour")
def get_game_nights_hosted_count(request: Request, user_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    count = session.exec(
        select(func.count(GameNight.id)).where(GameNight.host_user_id == user_id)
    ).one()
    return count

@router.get("/userProfile/{user_id}", response_model=UserBoardGamePublic)
@limiter.limit("300/hour")
def get_user_profile_route(request: Request, user_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    return session.exec(select(UserBoardGame).where(UserBoardGame.id == user_id)).first()

@router.get("/userProfiles", response_model=list[UserBoardGamePublic])
@limiter.limit("60/hour")
def get_user_profiles(session: SessionDep, request: Request, user_ids: list[int] = Query(), _: UserBoardGame = Depends(get_current_user)):
    return session.exec(select(UserBoardGame).where(UserBoardGame.id.in_(user_ids))).all()

@router.post("/auth/apple")
@limiter.limit("10/minute")
async def apple_auth(request: Request, body: AppleAuthRequest, session: SessionDep):
    try:
        claims = await verify_apple_token(body.identity_token)
    except Exception as e:
        raise HTTPException(401, "Invalid Apple identity token")

    apple_id = claims["sub"]
    email = claims.get("email")

    existing = session.exec(select(UserBoardGame).where(UserBoardGame.apple_id == apple_id)).first()
    if existing:
        access = create_access_token(existing.id)
        raw_refresh = new_refresh_token()
        rt = RefreshToken(
            user_id=existing.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=90),
        )
        session.add(rt)
        session.commit()
        return {
            "access_token": access,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
            "user": {"id": existing.id, "username": existing.username},
        }

    # New Apple user — client must supply a username before account is created
    return {"needs_username": True, "apple_id": apple_id, "email": email}

@router.post("/auth/apple/complete")
@limiter.limit("10/minute")
def apple_complete(request: Request, body: AppleCompleteRequest, session: SessionDep):
    if session.exec(select(UserBoardGame).where(UserBoardGame.username == body.username)).first():
        raise HTTPException(400, "Username already taken")

    user = UserBoardGame(
        username=body.username,
        email=body.email or "",
        password_hash="",
        apple_id=body.apple_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

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

@router.delete("/deleteAccount")
@limiter.limit("60/hour")
def delete_account(request: Request, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient
    from azure.core.exceptions import ResourceNotFoundError, AzureError

    user_id = current_user.id

    # Collect all blob names that need to be deleted from Azure
    blob_names: list[str] = []

    # Game night images for hosted nights
    hosted_night_ids = session.exec(
        select(GameNight.id).where(GameNight.host_user_id == user_id)
    ).all()
    if hosted_night_ids:
        image_rows = session.exec(
            select(GameNightImage).where(GameNightImage.game_night_id.in_(hosted_night_ids))
        ).all()
        blob_names.extend(img.image_url for img in image_rows)

        hosted_session_ids = session.exec(
            select(GameSession.id).where(GameSession.game_night_id.in_(hosted_night_ids))
        ).all()
        if hosted_session_ids:
            session.exec(delete(GameSessionUserLink).where(GameSessionUserLink.game_session_id.in_(hosted_session_ids)))
        session.exec(delete(GameSession).where(GameSession.game_night_id.in_(hosted_night_ids)))
        session.exec(delete(GameNightImage).where(GameNightImage.game_night_id.in_(hosted_night_ids)))
        session.exec(delete(GameNightUserLink).where(GameNightUserLink.game_night_id.in_(hosted_night_ids)))
        session.exec(delete(GameNight).where(GameNight.host_user_id == user_id))

    # User profile image
    if current_user.profile_image_url:
        blob_names.append(current_user.profile_image_url)

    # Delete blobs from Azure before touching the DB
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
                pass
            except AzureError:
                failed.append(blob_name)
        if failed:
            raise HTTPException(500, f"Failed to delete {len(failed)} image(s) from storage")

    # Friend links
    session.exec(delete(UserFriendLink).where(UserFriendLink.user_id == user_id))
    session.exec(delete(UserFriendLink).where(UserFriendLink.friend_user_id == user_id))

    # Pending friend requests
    session.exec(delete(UserFriendPending).where(UserFriendPending.user_id == user_id))
    session.exec(delete(UserFriendPending).where(UserFriendPending.incoming_friend_user_id == user_id))

    # Game night participation (non-hosted)
    session.exec(delete(GameNightUserLink).where(GameNightUserLink.user_id == user_id))

    # Game session wins
    session.exec(delete(GameSessionUserLink).where(GameSessionUserLink.winner_user_id == user_id))

    # Reviews
    session.exec(delete(Review).where(Review.user_id == user_id))

    # Refresh tokens
    session.exec(delete(RefreshToken).where(RefreshToken.user_id == user_id))

    # Block links
    session.exec(delete(UserBlockLink).where(UserBlockLink.user_id == user_id))
    session.exec(delete(UserBlockLink).where(UserBlockLink.blocked_user_id == user_id))

    # Password reset tokens
    session.exec(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))

    # Email verification tokens
    session.exec(delete(EmailVerificationToken).where(EmailVerificationToken.user_id == user_id))

    # Reports
    session.exec(delete(Report).where(Report.reporter_user_id == user_id))

    # Invite tokens
    session.exec(delete(InviteToken).where(InviteToken.inviter_user_id == user_id))

    session.delete(current_user)
    session.commit()
    return {"message": "Account deleted"}

@router.get("/verifyEmail")
def verify_email(token: str, session: SessionDep):
    import hashlib
    from fastapi.responses import RedirectResponse

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    verification = session.exec(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.used_at == None,
        )
    ).first()

    if not verification:
        raise HTTPException(400, "Invalid or expired verification token")
    if verification.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(400, "Invalid or expired verification token")

    user = session.get(UserBoardGame, verification.user_id)
    if not user:
        raise HTTPException(400, "Invalid or expired verification token")

    user.email_verified = True
    verification.used_at = datetime.now(timezone.utc)
    session.add(user)
    session.add(verification)
    session.commit()

    return RedirectResponse(url="tabulus://emailVerified")

class ResendVerificationRequest(BaseModel):
    email: str

@router.post("/resendVerification")
@limiter.limit("3/hour")
def resend_verification(request: Request, body: ResendVerificationRequest, session: SessionDep):
    user = session.exec(select(UserBoardGame).where(UserBoardGame.email == body.email)).first()
    if not user or user.email_verified:
        return {"message": "If that email is registered and unverified, a verification link has been sent"}

    _send_verification_email(user.id, user.email, session)

    return {"message": "If that email is registered and unverified, a verification link has been sent"}

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@router.get("/resetPassword")
def redirect_reset_password(token: str):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"tabulus://resetPassword?token={token}")

@router.post("/forgotPassword")
@limiter.limit("3/hour")
def forgot_password(request: Request, body: ForgotPasswordRequest, session: SessionDep):
    import uuid, hashlib, os
    from azure.communication.email import EmailClient

    user = session.exec(select(UserBoardGame).where(UserBoardGame.email == body.email)).first()
    # Always return 200 so we don't leak whether an email is registered
    if not user:
        return {"message": "If that email is registered you will receive a reset link"}

    if not user.email_verified:
        raise HTTPException(403, "Email not verified. Please verify your email before resetting your password.")

    raw_token = str(uuid.uuid4())
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    # Invalidate any existing unused tokens for this user
    session.exec(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at == None
        )
    )

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    session.add(reset_token)
    session.commit()

    client = EmailClient.from_connection_string(os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING"))
    client.begin_send({
        "senderAddress": os.getenv("AZURE_EMAIL_SENDER"),
        "recipients": {"to": [{"address": user.email}]},
        "content": {
            "subject": "Reset your Tabulus password",
            "plainText": f"Tap the link to reset your password. It expires in 30 minutes.\n\nhttps://tabulusapp.bravegrass-0afbc7b6.westus2.azurecontainerapps.io/users/resetPassword?token={raw_token}",
        },
    })

    return {"message": "If that email is registered you will receive a reset link"}

@router.post("/resetPassword")
@limiter.limit("5/minute")
def reset_password(request: Request, body: ResetPasswordRequest, session: SessionDep):
    import hashlib
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()

    reset_token = session.exec(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at == None,
        )
    ).first()

    if not reset_token:
        raise HTTPException(400, "Invalid or expired reset token")
    if reset_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(400, "Invalid or expired reset token")

    user = session.get(UserBoardGame, reset_token.user_id)
    if not user:
        raise HTTPException(400, "Invalid or expired reset token")

    user.password_hash = hash_password(body.new_password)
    reset_token.used_at = datetime.now(timezone.utc)
    session.add(user)
    session.add(reset_token)
    session.commit()

    return {"message": "Password reset successfully"}


