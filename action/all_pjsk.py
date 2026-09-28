import asyncio
from typing import Any
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone

from aiohttp import ClientSession, TCPConnector

import src.pjsk as pjsk
import src.util as util

NET_CONNECT_LIMIT = 20
TIMESTAMP13 = int(
    (cn_time := (datetime.now(timezone.utc) + timedelta(hours=36))).timestamp() * 1000
)
TIMESTAMP13_EN = int((cn_time + timedelta(hours=15)).timestamp() * 1000)

TaskList_type = list[Coroutine[Any, Any, Any]]


def add_common_tasks(
    tasks: TaskList_type, lang_getters: dict[str, pjsk.Getters_type]
) -> None:
    for getters in lang_getters.values():
        unit_getter = getters['unit_getter']
        tasks.extend(unit_getter.get(story_id) for story_id in unit_getter.tell_ids())
        self_getter = getters['self_getter']
        tasks.extend(self_getter.get(story_id) for story_id in self_getter.tell_ids())
        mysekai_getter = getters['mysekai_getter']
        tasks.extend(
            mysekai_getter.get(chara_unit_id)
            for chara_unit_id in mysekai_getter.tell_ids()
        )


def add_timestamp_tasks(
    tasks: TaskList_type,
    getters: pjsk.Getters_type,
    timestamp13: int | None = util.LATE_TIMESTAMP13,
) -> None:
    tasks.append(getters['event_getter'].get_newest(0, timestamp13=timestamp13))
    tasks.append(getters['card_getter'].get_newest(0, timestamp13=timestamp13))
    tasks.append(getters['special_getter'].get_newest(0, timestamp13=timestamp13))
    tasks.append(getters['virtual_getter'].get_newest(0, timestamp13=timestamp13))
    area_getter = getters['area_getter']
    tasks.extend(
        area_getter.get(category, timestamp13=timestamp13)
        for category in area_getter.tell_categories()
    )


async def main() -> None:

    args = {'online': False, 'missing_download': True}

    lang_getters = pjsk.Run.create_getters(
        (
            ('cn', 'cn'),
            ('tw', 'cn'),
            ('jp', 'en'),
            ('en', 'en'),
        ),
        save_dir='..',
        args=args,
    )

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await pjsk.Run.init_getters(lang_getters, session)

        tasks: TaskList_type = []
        add_common_tasks(tasks, lang_getters)
        add_timestamp_tasks(tasks, lang_getters['jp'])
        for lang in ('cn', 'tw'):
            add_timestamp_tasks(tasks, lang_getters[lang], TIMESTAMP13)
        add_timestamp_tasks(tasks, lang_getters['en'], TIMESTAMP13_EN)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
