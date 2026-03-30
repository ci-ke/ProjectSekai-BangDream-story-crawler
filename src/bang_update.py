import time, asyncio
from typing import Any
from aiohttp import ClientSession

from . import util, bang


async def find_newest_events(
    lang: str, session: ClientSession | None, timestamp13: int | None, quantity: int
) -> list[int]:
    fetcher = util.Base_fetcher('assets', True, True, True)
    await fetcher.init(session)
    event_all_3_urls = bang.URLS['bestdori.com']['events_all_3']

    event_all_3_json: dict[str, dict[str, Any]] = await util.fetch_url_json_simple(
        event_all_3_urls, fetcher
    )

    if timestamp13 is None:
        timestamp13 = int(time.time() * 1000)

    old_events: list[tuple[int, int]] = []

    for str_id, event in event_all_3_json.items():
        if (
            startAt := event['startAt'][bang.Constant.lang_index[lang]] is not None
        ) and int(startAt) < timestamp13:
            old_events.append((int(startAt), int(str_id)))

    new_events = sorted(old_events)[-quantity:]

    return [x[1] for x in new_events]


async def find_newest_cards(
    lang: str, session: ClientSession | None, timestamp13: int | None, quantity: int
) -> list[int]:
    fetcher = util.Base_fetcher('assets', True, True, True)
    await fetcher.init(session)
    cards_all_5_urls = bang.URLS['bestdori.com']['cards_all_5']

    cards_all_5_json: dict[str, dict[str, Any]] = await util.fetch_url_json_simple(
        cards_all_5_urls, fetcher
    )

    if timestamp13 is None:
        timestamp13 = int(time.time() * 1000)

    old_cards: list[tuple[int, int]] = []

    for str_id, card in cards_all_5_json.items():
        if (
            (releaseAt := card['releasedAt'][bang.Constant.lang_index[lang]])
            is not None
        ) and int(releaseAt) < timestamp13:
            old_cards.append((int(releaseAt), int(str_id)))

    new_cards = sorted(old_cards)[-quantity:]

    return [x[1] for x in new_cards]


async def get_newest_contents(
    lang: str,
    mark_lang: str,
    event_getter: bang.Event_story_getter,
    card_getter: bang.Card_story_getter,
    event_quantity: int = 10,
    card_quantity: int = 50,
    timestamp13: int | None = None,
) -> None:
    newest_event_ids = await find_newest_events(
        lang, event_getter.session, timestamp13, event_quantity
    )
    newest_card_ids = await find_newest_cards(
        lang, card_getter.session, timestamp13, card_quantity
    )

    tasks = []

    for i in newest_event_ids:
        tasks.append(event_getter.get(i, lang, mark_lang))
    for i in newest_card_ids:
        tasks.append(card_getter.get(i, lang, mark_lang))

    await asyncio.gather(*tasks)
