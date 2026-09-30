import asyncio
from typing import Any
from collections.abc import Coroutine

from aiohttp import ClientSession, TCPConnector

import src.bdon as bdon

NET_CONNECT_LIMIT = 20

# 维护者不认识韩语，为确保质量，CI 不产出韩语目录
# （bdon.SIDE_LANGS 的国际服面默认含 kr，供本地手动选用）
CI_LANGS: dict[str, tuple[tuple[str, str], ...]] = {
    'en': (('cn', 'cn'), ('tw', 'cn'), ('en', 'en')),
    'jp': (('jp', 'en'),),
}

TaskList_type = list[Coroutine[Any, Any, Any]]


def add_all_tasks(
    tasks: TaskList_type,
    getters: bdon.Getters_type,
    langs: tuple[tuple[str, str], ...],
) -> None:
    # 各数据面遍历各自 master 的 tell_ids；剧本表按面取自对应服务器的发布段
    for getter in (
        getters['band_getter'],
        getters['friendship_getter'],
        getters['home_getter'],
        getters['live_result_getter'],
        getters['tutorial_getter'],
    ):
        for master_id in getter.tell_ids():
            tasks.append(getter.get(master_id, langs=langs))


async def main() -> None:

    args = {'online': False, 'missing_download': True}

    side_getters = {
        side: bdon.Run.create_getters(save_dir='..', args=args, side=side)
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
            add_all_tasks(tasks, getters, CI_LANGS[side])
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
