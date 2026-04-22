from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from app.connection import SessionDep
from fastapi import APIRouter
from sqlmodel import Field, Session, SQLModel, create_engine, select
from app.models import Review, UserBoardGame, ReviewUpdate, ReviewPublic
from sqlalchemy.orm import selectinload
from app.services import reviewsService
from app.services.userService import get_current_user
from app.utilities.limiter import limiter
from app.utilities.profanity import contains_profanity
from app.models.report import Report
from app.models.userBlockLink import UserBlockLink


router = APIRouter(
    prefix="/reviews",
)

@router.get("/boardGame/{board_game_id}", response_model=list[ReviewPublic])
@limiter.limit("300/hour")
def read_reviews_by_board_game_name(request: Request, board_game_id, session: SessionDep, limit = 20, offset: int = 0, current_user: UserBoardGame = Depends(get_current_user)):
    blocked_ids = select(UserBlockLink.blocked_user_id).where(UserBlockLink.user_id == current_user.id)
    blocked_by_ids = select(UserBlockLink.user_id).where(UserBlockLink.blocked_user_id == current_user.id)
    reported_review_ids = select(Report.content_id).where(
        Report.reporter_user_id == current_user.id,
        Report.content_type == "review",
    )
    statement = (
        select(Review)
        .where(Review.board_game_id == board_game_id)
        .where(Review.user_id.notin_(blocked_ids))
        .where(Review.user_id.notin_(blocked_by_ids))
        .where(Review.id.notin_(reported_review_ids))
        .options(selectinload(Review.user))
        .order_by(Review.id.desc())
        .offset(offset)
        .limit(limit)
    )
    reviews = session.exec(statement).all()
    return reviews

@router.get("/reviewStats/{board_game_id}")
@limiter.limit("300/hour")
def read_computed_average_rating(request: Request, board_game_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    stats = reviewsService.getReviewStats(board_game_id, session)
    if stats is None:
        raise HTTPException(404, "No reviews found for this board game")
    return {"average_rating": stats[0], "number_of_ratings": stats[1], "number_of_reviews": stats[2]}

@router.post("/postReview", response_model=Review)
@limiter.limit("20/hour")
def create_review_for_board_game(request: Request, review: Review, session: SessionDep,
                                 user: UserBoardGame = Depends(get_current_user)):
    if review.user_id != user.id:
        raise HTTPException(403, "Cannot create review for another user")
    if contains_profanity(review.comment or ""):
        raise HTTPException(400, "Review contains inappropriate language")
    existing = session.exec(
        select(Review).where(Review.user_id == user.id, Review.board_game_id == review.board_game_id)
    ).first()
    if existing:
        raise HTTPException(409, "You have already reviewed this game")
    return reviewsService.insert_review_for_board_game(review, session)

@router.patch("/editReview/{review_id}", response_model=ReviewUpdate)
@limiter.limit("60/hour")
def edit_review_for_board_game(request: Request, review_id: int, updated_review: ReviewUpdate, session: SessionDep,
                               current_user: UserBoardGame = Depends(get_current_user)):
    statement = select(Review).where(Review.id == review_id)
    existing_review = session.exec(statement).first()
    if not existing_review:
        raise HTTPException(404, "Review not found")
    if existing_review.user_id != current_user.id:
        raise HTTPException(403, "Cannot edit another user's review")
    if contains_profanity(updated_review.comment or ""):
        raise HTTPException(400, "Review contains inappropriate language")

    data = updated_review.model_dump(exclude_unset=True)
    existing_review.sqlmodel_update(data)

    session.add(existing_review)
    session.commit()
    session.refresh(existing_review)

    return existing_review

@router.get("/userBoardGame/{user_id}/{board_game_id}", response_model=Review | None)
@limiter.limit("300/hour")
def get_user_review_for_board_game(request: Request, user_id: int, board_game_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    statement = (
        select(Review)
        .where(Review.user_id == user_id, Review.board_game_id == board_game_id)
        .options(selectinload(Review.user))
        .order_by(Review.id.desc())
    )
    review = session.exec(statement).first()
    return review

@router.get("/pinnedUser/{user_id}/{board_game_id}", response_model=ReviewPublic | None)
@limiter.limit("300/hour")
def get_user_review_for_board_game(request: Request, user_id: int, board_game_id: int, session: SessionDep, _: UserBoardGame = Depends(get_current_user)):
    statement = (
        select(Review)
        .where(Review.user_id == user_id, Review.board_game_id == board_game_id)
        .options(selectinload(Review.user))
        .order_by(Review.id.desc())
    )
    review = session.exec(statement).first()
    return review

@router.delete("/{review_id}")
@limiter.limit("60/hour")
def delete_review(request: Request, review_id: int, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    review = session.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    if review.user_id != current_user.id:
        raise HTTPException(403, "Cannot delete another user's review")
    session.delete(review)
    session.commit()
    return {"message": "Review deleted"}

@router.post("/reportReview/{review_id}")
@limiter.limit("20/hour")
def report_review(request: Request, review_id: int, session: SessionDep, current_user: UserBoardGame = Depends(get_current_user)):
    review = session.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    report = Report(reporter_user_id=current_user.id, content_type="review", content_id=review_id)
    session.add(report)
    session.commit()
    return {"message": "Review reported"}




    