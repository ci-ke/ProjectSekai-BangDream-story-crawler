import asyncio, sys
from typing import cast, Any

from aiohttp import ClientSession, TCPConnector

import src.util as util

from .all_bang import create_getters, TaskList_type, add_all_tasks, NET_CONNECT_LIMIT


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

    getters = create_getters(args=args)

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
