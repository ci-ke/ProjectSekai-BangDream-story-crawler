import asyncio
from typing import Any
from collections.abc import Coroutine

from aiohttp import ClientSession, TCPConnector

import src.bdon as bdon

NET_CONNECT_LIMIT = 20

# CI 的 story_jp 由国际服面的 en-jp 合成语言（国际服 dump 的日语列）产出，存储目录经
# lang_dir 接管仍写 story_jp。日服面（side='jp'，日服 master + ja 段剧本表）待其剧本表
# 在发布服务稳定可用后再启用：bdon.Run.create_getters(..., side='jp')。
# 维护者不认识韩语，为确保质量，CI 不产出韩语目录（bdon.SIDE_LANGS 的国际服面默认含 kr）。
CI_LANGS: tuple[tuple[str, str], ...] = (
    ('cn', 'cn'),
    ('tw', 'cn'),
    ('en-jp', 'en'),
    ('en', 'en'),
)

TaskList_type = list[Coroutine[Any, Any, Any]]


def add_all_tasks(
    tasks: TaskList_type,
    getters: bdon.Getters_type,
    langs: tuple[tuple[str, str], ...],
) -> None:
    # 剧本表按数据面取自对应服务器的发布段
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

    getters = bdon.Run.create_getters(
        save_dir='..', args=args, side='en', lang_dir={'en-jp': 'jp'}
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
