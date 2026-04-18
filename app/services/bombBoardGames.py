# "Bomb" bulk game importer — fetches the top-ranked board games from BGG
# by scraping their ranked browse pages, then batch-fetching full details
# using comma-separated IDs in a single API call.

import re
import time
import os
import requests
import xmltodict
from dotenv import load_dotenv
from sqlmodel import Session

from app.models.boardGame import BoardGame
from app.models.boardGameCategory import BoardGameCategory
from app.models.boardGameMechanic import BoardGameMechanic
from app.models.boardGameCategoryLink import BoardGameCategoryLink
from app.models.boardGameMechanicLink import BoardGameMechanicLink
from app.models.publisher import Publisher
from app.models.boardGamePublisherLink import BoardGamePublisherLink
from app.models.boardGameDesigner import BoardGameDesigner
from app.models.boardGameDesignerLink import BoardGameDesignerLink


BATCH_SIZE = 20
SLEEP_BETWEEN_BATCHES = 10  # seconds
GAMES_PER_BROWSE_PAGE = 100


def _scrape_ranked_ids(count: int) -> list[int]:
    """Scrape BGG's browse pages to get game IDs in rank order."""
    pages_needed = (count + GAMES_PER_BROWSE_PAGE - 1) // GAMES_PER_BROWSE_PAGE
    all_ids: list[int] = []

    for page in range(1, pages_needed + 1):
        url = f"https://boardgamegeek.com/browse/boardgame/page/{page}"
        print(f"[bomb] scraping ranked page {page}/{pages_needed}")

        try:
            r = requests.get(url)
            r.raise_for_status()
        except Exception as e:
            print(f"[bomb] failed to fetch browse page {page}: {e}")
            continue

        # Each game row has a link like /boardgame/174430/gloomhaven
        ids = re.findall(r'/boardgame/(\d+)/', r.text)
        # deduplicate while preserving order (page can repeat IDs in links)
        seen = set(all_ids)
        for gid_str in ids:
            gid = int(gid_str)
            if gid not in seen:
                all_ids.append(gid)
                seen.add(gid)

        if len(all_ids) >= count:
            break

        time.sleep(1)

    return all_ids[:count]


def _parse_and_insert_game(game_id: int, item: dict, session: Session) -> bool:
    """Parse a single BGG item dict and insert the game + relationships.
    Returns True on success, False on skip/error."""
    if item.get("@type") != "boardgame":
        return False

    try:
        name = item.get("name")
        if not name:
            return False
        if isinstance(name, list):
            name = name[0]
        if isinstance(name, dict):
            name = name.get("@value")
        if not name:
            return False

        thumbnail = item.get("thumbnail")
        image = item.get("image")
        description = item.get("description")
        year_published = (item.get("yearpublished") or {}).get("@value")
        min_players = (item.get("minplayers") or {}).get("@value")
        max_players = (item.get("maxplayers") or {}).get("@value")
        play_time = (item.get("playingtime") or {}).get("@value")
        min_age = (item.get("minage") or {}).get("@value")

        links = item.get("link", [])
        if isinstance(links, dict):
            links = [links]
    except Exception:
        return False

    categories = []
    mechanics = []
    publishers = []
    designers = []

    for link in links:
        link_type = link.get("@type")
        if link_type == "boardgamecategory":
            categories.append((link["@value"], link["@id"]))
        elif link_type == "boardgamemechanic":
            mechanics.append((link["@value"], link["@id"]))
        elif link_type == "boardgamepublisher":
            publishers.append((link["@value"], link["@id"]))
        elif link_type == "boardgamedesigner":
            designers.append((link["@value"], link["@id"]))

    try:
        board_game = BoardGame(
            id=game_id,
            name=name,
            thumbnail=thumbnail,
            image=image,
            year_published=year_published,
            description=description,
            min_players=min_players,
            max_players=max_players,
            play_time=play_time,
            min_age=min_age,
        )
        board_game = BoardGame.model_validate(board_game)
        session.add(board_game)
        session.flush()
    except Exception:
        session.rollback()
        return False

    for cat_name, cat_id in categories:
        if not session.get(BoardGameCategory, cat_id):
            session.add(BoardGameCategory.model_validate(
                BoardGameCategory(id=cat_id, name=cat_name)))
            session.flush()
        session.add(BoardGameCategoryLink.model_validate(
            BoardGameCategoryLink(board_game_id=game_id, category_id=cat_id)))
        session.flush()

    for mech_name, mech_id in mechanics:
        if not session.get(BoardGameMechanic, mech_id):
            session.add(BoardGameMechanic.model_validate(
                BoardGameMechanic(id=mech_id, name=mech_name)))
            session.flush()
        session.add(BoardGameMechanicLink.model_validate(
            BoardGameMechanicLink(board_game_id=game_id, mechanic_id=mech_id)))
        session.flush()

    for des_name, des_id in designers:
        if not session.get(BoardGameDesigner, des_id):
            session.add(BoardGameDesigner.model_validate(
                BoardGameDesigner(id=des_id, name=des_name)))
            session.flush()
        session.add(BoardGameDesignerLink.model_validate(
            BoardGameDesignerLink(board_game_id=game_id, designer_id=des_id)))
        session.flush()

    for pub_name, pub_id in publishers:
        if not session.get(Publisher, pub_id):
            session.add(Publisher.model_validate(
                Publisher(id=pub_id, name=pub_name)))
            session.flush()
        session.add(BoardGamePublisherLink.model_validate(
            BoardGamePublisherLink(board_game_id=game_id, publisher_id=pub_id)))
        session.flush()

    session.commit()
    return True


def bomb_board_games(
    session: Session,
    count: int = 1000,
) -> int:
    """Bulk-fetch the top `count` ranked board games from BGG.
    Skips games already in the DB. Returns the number of games added."""
    load_dotenv()
    bearer = os.getenv("bearer_token")
    headers = {"Authorization": f"Bearer {bearer}"}

    # Step 1: scrape BGG browse pages to get ranked game IDs
    print(f"[bomb] scraping top {count} ranked game IDs from BGG...")
    ranked_ids = _scrape_ranked_ids(count)
    print(f"[bomb] found {len(ranked_ids)} ranked game IDs")

    # Step 2: filter out games we already have
    candidate_ids = [gid for gid in ranked_ids if not session.get(BoardGame, gid)]
    print(f"[bomb] {len(ranked_ids) - len(candidate_ids)} already in DB, {len(candidate_ids)} to fetch")

    if not candidate_ids:
        print("[bomb] nothing new to add")
        return 0

    # Step 3: batch-fetch full details from BGG API
    added = 0
    batches = [candidate_ids[i:i + BATCH_SIZE]
               for i in range(0, len(candidate_ids), BATCH_SIZE)]

    for batch_num, batch in enumerate(batches, 1):
        ids_str = ",".join(str(gid) for gid in batch)
        url = f"https://api.geekdo.com/xmlapi2/thing?id={ids_str}&stats=1"

        print(f"[bomb] batch {batch_num}/{len(batches)} — fetching {len(batch)} games")

        try:
            r = requests.get(url, headers=headers)
            r.raise_for_status()
            data = xmltodict.parse(r.text)
        except Exception as e:
            print(f"[bomb] batch {batch_num} request failed: {e}")
            time.sleep(SLEEP_BETWEEN_BATCHES)
            continue

        items = data.get("items", {}).get("item")
        if not items:
            time.sleep(SLEEP_BETWEEN_BATCHES)
            continue

        if isinstance(items, dict):
            items = [items]

        for item in items:
            game_id = int(item.get("@id", 0))
            if not game_id:
                continue
            if _parse_and_insert_game(game_id, item, session):
                added += 1
                print(f"[bomb]   added {item.get('name', '?')} (id={game_id})")

        print(f"[bomb] batch {batch_num} done — {added} total added so far")
        time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"[bomb] finished — {added} games added")
    return added
