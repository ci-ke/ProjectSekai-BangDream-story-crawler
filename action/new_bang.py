import asyncio

from aiohttp import ClientSession, TCPConnector

from .all_bang import (
    create_getters,
    Getters_type,
    TaskList_type,
    LANGS,
    NET_CONNECT_LIMIT,
)

INIT_NAMES = ('reader', 'event_getter', 'card_getter')


def add_new_tasks(tasks: TaskList_type, getters: Getters_type) -> None:
    for lang, mark_lang in LANGS:
        tasks.append(getters['event_getter'].get_newest(lang, mark_lang, quantity=10))
        tasks.append(getters['card_getter'].get_newest(lang, mark_lang, quantity=50))


async def main() -> None:
    getters = create_getters(use_parent_save_dir=True)

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await asyncio.gather(
            *[
                getters[name].init(session)  # type: ignore[literal-required]
                for name in INIT_NAMES
            ]
        )

        tasks: TaskList_type = []
        add_new_tasks(tasks, getters)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
