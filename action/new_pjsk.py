import asyncio

from aiohttp import ClientSession, TCPConnector

from .all_pjsk import (
    create_getters,
    Getters_type,
    TaskList_type,
    NET_CONNECT_LIMIT,
    TIMESTAMP13,
)

INIT_NAMES = ('reader', 'event_getter', 'card_getter', 'area_getter', 'special_getter')


def add_common_tasks(
    tasks: TaskList_type, lang_getters: dict[str, Getters_type]
) -> None:
    for getters in lang_getters.values():
        special_getter = getters['special_getter']
        tasks.extend(
            special_getter.get(story_id) for story_id in special_getter.tell_ids()[-5:]
        )


def add_timestamp_tasks(
    tasks: TaskList_type,
    getters: Getters_type,
    timestamp13: int | None = None,
) -> None:
    tasks.append(
        getters['event_getter'].get_newest(
            10, area_getter=getters['area_getter'], timestamp13=timestamp13
        )
    )
    tasks.append(getters['card_getter'].get_newest(50, timestamp13=timestamp13))


async def main() -> None:
    lang_getters: dict[str, Getters_type] = {
        'cn': create_getters('cn', use_parent_save_dir=True),
        'tw': create_getters('tw', use_parent_save_dir=True),
        'jp': create_getters('jp', mark_lang='en', use_parent_save_dir=True),
        'en': create_getters('en', mark_lang='en', use_parent_save_dir=True),
    }

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=NET_CONNECT_LIMIT)
    ) as session:
        await asyncio.gather(
            *[
                getters[name].init(session)  # type: ignore[literal-required]
                for getters in lang_getters.values()
                for name in INIT_NAMES
            ]
        )

        tasks: TaskList_type = []
        add_common_tasks(tasks, lang_getters)
        add_timestamp_tasks(tasks, lang_getters['jp'])
        for lang in ('cn', 'tw', 'en'):
            add_timestamp_tasks(tasks, lang_getters[lang], TIMESTAMP13)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
