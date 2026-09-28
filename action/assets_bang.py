import asyncio, sys
from typing import Any

from aiohttp import ClientSession, TCPConnector

import src.bang as bang

from .all_bang import (
    TaskList_type,
    add_all_tasks,
    NET_CONNECT_LIMIT,
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

    getters = bang.Run.create_getters(assets_save_dir='..', args=args)

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await bang.Run.init_getters(getters, session)

        tasks: TaskList_type = []
        add_all_tasks(tasks, getters)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
