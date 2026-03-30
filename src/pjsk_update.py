import time, asyncio
from aiohttp import ClientSession

from . import util, pjsk


async def find_newest_event(
    lang: str, session: ClientSession | None, timestamp13: int | None, is_jp: bool
) -> int:
    fetcher = util.Base_fetcher('assets', True, True, True)
    await fetcher.init(session)
    event_urls = pjsk.Constant.get_srcs_url(
        lang, ['haruki', 'sekai.best'], 'master', 'events'
    )

    events_json = await util.fetch_url_json_simple(
        event_urls,
        fetcher,
        append_save_path=pjsk.Fetch.url_to_apd_path_master(event_urls[0], 'cn'),
    )

    if timestamp13 is None:
        timestamp13 = int(time.time() * 1000)
    time_lookup = util.DictLookup(events_json, 'startAt')
    newest_index = time_lookup.find_max_le_index(timestamp13)

    newest_event_id = events_json[newest_index]['id']
    if is_jp:
        newest_event_id += 1

    return newest_event_id


async def get_newest_contents(
    event_getter: pjsk.Event_story_getter,
    card_getter: pjsk.Card_story_getter,
    area_getter: pjsk.Area_talk_getter,
    quantity: int = 10,
    timestamp13: int | None = None,
    is_jp: bool = False,
) -> None:
    newest_event_id = await find_newest_event(
        event_getter.reader.lang, event_getter.session, timestamp13, is_jp
    )

    tasks = []

    for i in range(newest_event_id - (quantity - 1), newest_event_id + 1):
        tasks.append(event_getter.get(i))
        tasks.append(card_getter.get_event(i))
        tasks.append(area_getter.get(i))

    await asyncio.gather(*tasks)
