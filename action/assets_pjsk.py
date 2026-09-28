import asyncio, sys
from typing import Any

from aiohttp import ClientSession, TCPConnector

import src.pjsk as pjsk

from .all_pjsk import (
    TaskList_type,
    add_common_tasks,
    add_timestamp_tasks,
    NET_CONNECT_LIMIT,
    TIMESTAMP13,
    TIMESTAMP13_EN,
)


async def main() -> None:
    assert sys.argv[1] in ('full', 'incremental')
    online = sys.argv[1] == 'full'

    args: dict[str, Any] = {
        'online': online,
        'parse': False,
        'compress_assets': True,
        'force_master_online': True,
    }

    lang_getters = pjsk.Run.create_getters(
        (
            ('cn', 'cn'),
            ('tw', 'cn'),
            ('jp', 'en'),
            ('en', 'en'),
        ),
        assets_save_dir='..',
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
