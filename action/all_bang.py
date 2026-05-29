import asyncio, inspect
from typing import cast, Any, TypedDict
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone

from aiohttp import ClientSession, TCPConnector

import src.bang as bang
import src.util as util

NET_CONNECT_LIMIT = 20

LANGS: tuple[tuple[str, str], ...] = (
    ('cn', 'cn'),
    ('tw', 'cn'),
    ('jp', 'en'),
    ('en', 'en'),
)

TaskList_type = list[Coroutine[Any, Any, Any]]


class Getters_type(TypedDict):
    reader: bang.Story_reader
    main_getter: bang.Main_story_getter
    band_getter: bang.Band_story_getter
    event_getter: bang.Event_story_getter
    card_getter: bang.Card_story_getter
    area_getter: bang.Area_talk_getter


def create_getters(
    use_parent_save_dir: bool = False,
    args: dict[str, Any] | None = None,
) -> Getters_type:
    if args is None:
        args = {}
    reader = bang.Story_reader(**args)

    def get_save_dir(getter_cls) -> str:
        default = inspect.signature(getter_cls.__init__).parameters['save_dir'].default
        return ('.' if use_parent_save_dir else '') + default

    return {
        'reader': reader,
        'main_getter': bang.Main_story_getter(
            reader, save_dir=get_save_dir(bang.Main_story_getter), **args
        ),
        'band_getter': bang.Band_story_getter(
            reader, save_dir=get_save_dir(bang.Band_story_getter), **args
        ),
        'event_getter': bang.Event_story_getter(
            reader, save_dir=get_save_dir(bang.Event_story_getter), **args
        ),
        'card_getter': bang.Card_story_getter(
            reader, save_dir=get_save_dir(bang.Card_story_getter), **args
        ),
        'area_getter': bang.Area_talk_getter(
            reader, save_dir=get_save_dir(bang.Area_talk_getter), **args
        ),
    }


def add_all_tasks(tasks: TaskList_type, getters: Getters_type) -> None:
    for lang, mark_lang in LANGS:
        tasks.append(getters['main_getter'].get(None, lang, mark_lang))
        tasks.append(getters['band_getter'].get(None, None, lang, mark_lang))
        tasks.append(getters['event_getter'].get_newest(lang, mark_lang, quantity=0))
        tasks.append(getters['card_getter'].get_newest(lang, mark_lang, quantity=0))
        for area_id in (area_getter := getters['area_getter']).tell_area_ids():
            for talk_type in area_getter.types:
                tasks.append(area_getter.get(area_id, talk_type, lang, mark_lang))


async def main() -> None:

    getters = create_getters(use_parent_save_dir=True)

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await asyncio.gather(
            *[cast(util.Base_fetcher, obj).init(session) for obj in getters.values()]
        )

        tasks: TaskList_type = []
        add_all_tasks(tasks, getters)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
