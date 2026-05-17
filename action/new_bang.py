import asyncio

from aiohttp import ClientSession, TCPConnector

from .all_bang import (
    create_getters,
    Getters_type,
    TaskList_type,
    LANGS,
    NET_CONNECT_LIMIT,
    TIMESTAMP13,
)

INIT_NAMES = ('reader', 'event_getter', 'card_getter')


def add_new_tasks(
    tasks: TaskList_type, getters: Getters_type, timestamp13: int
) -> None:
    event_getter = getters['event_getter']
    card_getter = getters['card_getter']
    for lang, mark_lang in LANGS:
        tasks.append(
            event_getter.get_newest(
                lang, mark_lang, quantity=10, timestamp13=timestamp13
            )
        )
        tasks.append(
            card_getter.get_newest(
                lang, mark_lang, quantity=50, timestamp13=timestamp13
            )
        )


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
        add_new_tasks(tasks, getters, TIMESTAMP13)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
