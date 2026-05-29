import asyncio, sys
from typing import cast, Any

from aiohttp import ClientSession, TCPConnector

import src.pjsk as pjsk

from .all_pjsk import (
    create_getters,
    Getters_type,
    TaskList_type,
    add_common_tasks,
    add_timestamp_tasks,
    NET_CONNECT_LIMIT,
    TIMESTAMP13,
)


async def main() -> None:
    assert sys.argv[1] in ('full', 'incremental')
    online = sys.argv[1] == 'full'

    args: dict[str, Any] = {
        'online': online,
        'parse': False,
        'assets_save_dir': '../assets',
        'compress_assets': True,
        'force_master_online': True,
    }

    lang_getters: dict[str, Getters_type] = {
        'cn': create_getters('cn', args=args),
        'tw': create_getters('tw', args=args),
        'jp': create_getters('jp', mark_lang='en', args=args),
        'en': create_getters('en', mark_lang='en', args=args),
    }

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await asyncio.gather(
            *[
                cast(pjsk.Pjsk_fetcher, obj).init(session)
                for getters in lang_getters.values()
                for obj in getters.values()
            ]
        )

        tasks: TaskList_type = []
        add_common_tasks(tasks, lang_getters)
        add_timestamp_tasks(tasks, lang_getters['jp'])
        for lang in ('cn', 'tw', 'en'):
            add_timestamp_tasks(tasks, lang_getters[lang], TIMESTAMP13)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
