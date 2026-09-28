import asyncio
from typing import Any
from collections.abc import Coroutine

from aiohttp import ClientSession, TCPConnector

import src.bang as bang

NET_CONNECT_LIMIT = 20

LANGS: tuple[tuple[str, str], ...] = (
    ('cn', 'cn'),
    ('tw', 'cn'),
    ('jp', 'en'),
    ('en', 'en'),
)

TaskList_type = list[Coroutine[Any, Any, Any]]


def add_all_tasks(tasks: TaskList_type, getters: bang.Getters_type) -> None:
    for lang, mark_lang in LANGS:
        tasks.append(getters['main_getter'].get(None, lang, mark_lang))
        tasks.append(getters['band_getter'].get(None, None, lang, mark_lang))
        tasks.append(getters['event_getter'].get_newest(lang, mark_lang, quantity=0))
        tasks.append(getters['card_getter'].get_newest(lang, mark_lang, quantity=0))
        for area_id in (area_getter := getters['area_getter']).tell_area_ids():
            for talk_type in area_getter.types:
                tasks.append(area_getter.get(area_id, talk_type, lang, mark_lang))
        for talk_id in (after_live_getter := getters['after_live_getter']).tell_ids():
            tasks.append(after_live_getter.get(talk_id, lang, mark_lang))


async def main() -> None:

    args = {'online': False, 'missing_download': True}

    getters = bang.Run.create_getters(save_dir='..', args=args)

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await bang.Run.init_getters(getters, session)

        tasks: TaskList_type = []
        add_all_tasks(tasks, getters)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
