import asyncio

from aiohttp import ClientSession, TCPConnector

import src.util as util

from .all_pjsk import (
    create_getters,
    Getters_type,
    TaskList_type,
    init_getters,
    NET_CONNECT_LIMIT,
    TIMESTAMP13,
)

INIT_NAMES = ('event_getter', 'card_getter', 'area_getter')  # reader 由 init_getters 先 init


def add_timestamp_tasks(
    tasks: TaskList_type,
    getters: Getters_type,
    timestamp13: int | None = util.LATE_TIMESTAMP13,
) -> None:
    tasks.append(
        getters['event_getter'].get_newest(
            2, area_getter=getters['area_getter'], timestamp13=timestamp13
        )
    )
    tasks.append(getters['card_getter'].get_newest(10, timestamp13=timestamp13))


async def main() -> None:
    lang_getters: dict[str, Getters_type] = {
        'cn': create_getters('cn', use_parent_save_dir=True),
        'tw': create_getters('tw', use_parent_save_dir=True),
        'jp': create_getters(
            'jp',
            mark_lang='en',
            use_parent_save_dir=True,
            args={'src': ['haruki', 'sekai.best', 'pjsk.moe']},
        ),
        'en': create_getters('en', mark_lang='en', use_parent_save_dir=True),
    }

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await init_getters(lang_getters, session, INIT_NAMES)

        tasks: TaskList_type = []
        add_timestamp_tasks(tasks, lang_getters['jp'])
        for lang in ('cn', 'tw', 'en'):
            add_timestamp_tasks(tasks, lang_getters[lang], TIMESTAMP13)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
