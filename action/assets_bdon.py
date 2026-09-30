import asyncio, sys
from typing import Any

from aiohttp import ClientSession, TCPConnector

import src.bdon as bdon

from .all_bdon import (
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

    side_getters = {
        side: bdon.Run.create_getters(assets_save_dir='..', args=args, side=side)
        for side in bdon.SIDES
    }

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await asyncio.gather(
            *[
                bdon.Run.init_getters(getters, session)
                for getters in side_getters.values()
            ]
        )

        tasks: TaskList_type = []
        for side, getters in side_getters.items():
            add_all_tasks(tasks, getters, bdon.SIDE_LANGS[side])
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
