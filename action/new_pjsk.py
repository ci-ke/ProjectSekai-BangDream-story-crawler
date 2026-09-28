import asyncio

from aiohttp import ClientSession, TCPConnector

import src.pjsk as pjsk
import src.util as util

from .all_pjsk import TaskList_type, NET_CONNECT_LIMIT

INIT_NAMES = (
    'event_getter',
    'card_getter',
    'area_getter',
)  # reader 由 init_getters 先 init


def add_timestamp_tasks(
    tasks: TaskList_type,
    getters: pjsk.Getters_type,
    timestamp13: int | None = util.LATE_TIMESTAMP13,
) -> None:
    tasks.append(
        getters['event_getter'].get_newest(
            1, area_getter=getters['area_getter'], timestamp13=timestamp13
        )
    )
    tasks.append(getters['card_getter'].get_newest(10, timestamp13=timestamp13))


async def main() -> None:
    lang_getters = pjsk.Run.create_getters(
        (('jp', 'en'),),
        save_dir='..',
        args={'src': ['haruki', 'sekai.best', 'pjsk.moe']},
    )
    # 启用其余语言往 langs 里补元组即可：('cn', 'cn'), ('tw', 'cn'), ('en', 'en')

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await pjsk.Run.init_getters(lang_getters, session, INIT_NAMES)

        tasks: TaskList_type = []
        add_timestamp_tasks(tasks, lang_getters['jp'])
        # for lang in ('cn', 'tw', 'en'):
        #     add_timestamp_tasks(tasks, lang_getters[lang], TIMESTAMP13)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
