import asyncio, sys
from typing import Any

from aiohttp import ClientSession, TCPConnector

import src.bdon as bdon

from .all_bdon import (
    CI_LANGS,
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

    getters = bdon.Run.create_getters(
        assets_save_dir='..', args=args, side='en', lang_dir={'en-jp': 'jp'}
    )

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await bdon.Run.init_getters(getters, session)

        tasks: TaskList_type = []
        add_all_tasks(tasks, getters, CI_LANGS)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
