import asyncio

from aiohttp import ClientSession, TCPConnector

import src.bang as bang

from .all_bang import TaskList_type, LANGS, NET_CONNECT_LIMIT

INIT_NAMES = (
    'event_getter',
    'card_getter',
)  # reader 由 init_getters 先 init


def add_new_tasks(tasks: TaskList_type, getters: bang.Getters_type) -> None:
    for lang, mark_lang in LANGS:
        tasks.append(getters['event_getter'].get_newest(lang, mark_lang, quantity=1))
        tasks.append(getters['card_getter'].get_newest(lang, mark_lang, quantity=10))


async def main() -> None:
    getters = bang.Run.create_getters(save_dir='..')

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await bang.Run.init_getters(getters, session, INIT_NAMES)

        tasks: TaskList_type = []
        add_new_tasks(tasks, getters)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
