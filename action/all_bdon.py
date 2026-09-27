import asyncio, inspect
from typing import Any, TypedDict
from collections.abc import Coroutine

from aiohttp import ClientSession, TCPConnector

import src.bdon as bdon

NET_CONNECT_LIMIT = 20

# 维护者不认识韩语，CI 不产出韩语目录（bdon 模块级 LANGS 默认仍含 kr，供本地手动选用）
LANGS: tuple[tuple[str, str], ...] = (
    ('cn', 'cn'),
    ('tw', 'cn'),
    ('jp', 'en'),
    ('en', 'en'),
)

TaskList_type = list[Coroutine[Any, Any, Any]]


class Getters_type(TypedDict):
    reader: bdon.Story_reader
    band_getter: bdon.Band_story_getter
    friendship_getter: bdon.Friendship_story_getter
    home_getter: bdon.Home_talk_getter
    live_result_getter: bdon.Live_result_story_getter
    tutorial_getter: bdon.Tutorial_story_getter


def create_getters(
    use_parent_save_dir: bool = False,
    args: dict[str, Any] | None = None,
) -> Getters_type:
    if args is None:
        args = {}
    reader = bdon.Story_reader(**args)

    def get_save_dir(getter_cls) -> str:
        default = inspect.signature(getter_cls.__init__).parameters['save_dir'].default
        return ('.' if use_parent_save_dir else '') + default

    return {
        'reader': reader,
        'band_getter': bdon.Band_story_getter(
            reader, save_dir=get_save_dir(bdon.Band_story_getter), **args
        ),
        'friendship_getter': bdon.Friendship_story_getter(
            reader, save_dir=get_save_dir(bdon.Friendship_story_getter), **args
        ),
        'home_getter': bdon.Home_talk_getter(
            reader, save_dir=get_save_dir(bdon.Home_talk_getter), **args
        ),
        'live_result_getter': bdon.Live_result_story_getter(
            reader, save_dir=get_save_dir(bdon.Live_result_story_getter), **args
        ),
        'tutorial_getter': bdon.Tutorial_story_getter(
            reader, save_dir=get_save_dir(bdon.Tutorial_story_getter), **args
        ),
    }


def add_all_tasks(tasks: TaskList_type, getters: Getters_type) -> None:
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


async def init_getters(
    getters: Getters_type,
    session: ClientSession,
    init_names: tuple[str, ...] | None = None,
) -> None:
    '''
    reader 最先 init：getter 使用的 master 数据（如 story_episodes / advs）由
    reader 的 init 赋值；其余 getter 并发 init。
    init_names 为 None 时 init 除 reader 外的全部 getter。
    '''
    await getters['reader'].init(session)

    if init_names is None:
        init_names = tuple(name for name in getters.keys() if name != 'reader')

    await asyncio.gather(
        *[getters[name].init(session) for name in init_names]  # type: ignore[literal-required]
    )


async def main() -> None:

    args = {'online': False, 'missing_download': True}

    getters = create_getters(use_parent_save_dir=True, args=args)

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await init_getters(getters, session)

        tasks: TaskList_type = []
        add_all_tasks(tasks, getters)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
