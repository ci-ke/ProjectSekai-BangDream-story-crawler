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


def add_special_tasks(
    tasks: TaskList_type, lang_getters: dict[str, Getters_type]
) -> None:
    """special: 所有语言统一走 tell_ids()[-5:]"""
    for getters in lang_getters.values():
        special_getter = getters['special_getter']
        tasks.extend(
            special_getter.get(story_id) for story_id in special_getter.tell_ids()[-5:]
        )


def add_jp_tasks(
    tasks: TaskList_type, lang_getters: dict[str, Getters_type], timestamp13: int
) -> None:
    """JP 模式: event tell_ids[-10:] + area, card tell_ids[-50:]"""
    getters = lang_getters['jp']
    event_getter = getters['event_getter']
    for event_id in event_getter.tell_ids()[-10:]:
        tasks.append(event_getter.get(event_id))
        tasks.append(getters['area_getter'].get(event_id))
    card_getter = getters['card_getter']
    tasks.extend(card_getter.get(story_id) for story_id in card_getter.tell_ids()[-50:])


def add_nonjp_tasks(
    tasks: TaskList_type, lang_getters: dict[str, Getters_type], timestamp13: int
) -> None:
    """非 JP 模式: event/card 走 get_newest"""
    for lang in ('cn', 'tw', 'en'):
        getters = lang_getters[lang]
        event_getter = getters['event_getter']
        tasks.append(
            event_getter.get_newest(
                10, area_getter=getters['area_getter'], timestamp13=timestamp13
            )
        )
        card_getter = getters['card_getter']
        tasks.append(card_getter.get_newest(50, timestamp13=timestamp13))


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
        add_special_tasks(tasks, lang_getters)
        add_jp_tasks(tasks, lang_getters, TIMESTAMP13)
        add_nonjp_tasks(tasks, lang_getters, TIMESTAMP13)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
