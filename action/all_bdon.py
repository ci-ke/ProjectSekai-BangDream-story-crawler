import asyncio
from typing import Any
from collections.abc import Coroutine

from aiohttp import ClientSession, TCPConnector

import src.bdon as bdon

NET_CONNECT_LIMIT = 20

# 维护者不认识韩语，为确保质量，CI 不产出韩语目录（bdon 模块级 LANGS 默认仍含 kr，供本地手动选用）
LANGS: tuple[tuple[str, str], ...] = (
    ('cn', 'cn'),
    ('tw', 'cn'),
    ('jp', 'en'),
    ('en', 'en'),
)

TaskList_type = list[Coroutine[Any, Any, Any]]


def add_all_tasks(tasks: TaskList_type, getters: bdon.Getters_type) -> None:
    # 剧本 Text 表自带全部语言，每脚本一次抓取；按 pjsk/bang 惯例遍历各自 master 的 tell_ids
    for getter in (
        getters['band_getter'],
        getters['friendship_getter'],
        getters['home_getter'],
        getters['live_result_getter'],
        getters['tutorial_getter'],
    ):
        for master_id in getter.tell_ids():
            tasks.append(getter.get(master_id, langs=LANGS))


async def main() -> None:

    args = {'online': False, 'missing_download': True}

    getters = bdon.Run.create_getters(save_dir='..', args=args)

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await bdon.Run.init_getters(getters, session)

        tasks: TaskList_type = []
        add_all_tasks(tasks, getters)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
