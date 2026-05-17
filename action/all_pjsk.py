import asyncio, inspect
from typing import cast, Any, TypedDict
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone

from aiohttp import ClientSession, TCPConnector

import src.pjsk as pjsk

NET_CONNECT_LIMIT = 20
TIMESTAMP13 = int((datetime.now(timezone.utc) + timedelta(hours=36)).timestamp() * 1000)

TaskList_type = list[Coroutine[Any, Any, Any]]


class Getters_type(TypedDict):
    reader: pjsk.Story_reader
    event_getter: pjsk.Event_story_getter
    card_getter: pjsk.Card_story_getter
    area_getter: pjsk.Area_talk_getter
    unit_getter: pjsk.Unit_story_getter
    self_getter: pjsk.Self_intro_getter
    special_getter: pjsk.Special_story_getter


def create_getters(
    lang: str = 'cn',
    mark_lang: str | None = None,
    use_parent_save_dir: bool = False,
    args: dict[str, Any] | None = None,
) -> Getters_type:
    if args is None:
        args = {}

    if mark_lang is not None:
        reader = pjsk.Story_reader(lang=lang, mark_lang=mark_lang, **args)
    else:
        reader = pjsk.Story_reader(lang=lang, **args)

    def get_save_dir(getter_cls) -> str:
        default = inspect.signature(getter_cls.__init__).parameters['save_dir'].default
        return ('.' if use_parent_save_dir else '') + default

    return {
        'reader': reader,
        'event_getter': pjsk.Event_story_getter(
            reader, save_dir=get_save_dir(pjsk.Event_story_getter), **args
        ),
        'card_getter': pjsk.Card_story_getter(
            reader, save_dir=get_save_dir(pjsk.Card_story_getter), **args
        ),
        'area_getter': pjsk.Area_talk_getter(
            reader, save_dir=get_save_dir(pjsk.Area_talk_getter), **args
        ),
        'unit_getter': pjsk.Unit_story_getter(
            reader, save_dir=get_save_dir(pjsk.Unit_story_getter), **args
        ),
        'self_getter': pjsk.Self_intro_getter(
            reader, save_dir=get_save_dir(pjsk.Self_intro_getter), **args
        ),
        'special_getter': pjsk.Special_story_getter(
            reader, save_dir=get_save_dir(pjsk.Special_story_getter), **args
        ),
    }


def add_common_tasks(
    tasks: TaskList_type, lang_getters: dict[str, Getters_type]
) -> None:
    """unit / self / special: 所有语言统一走 tell_ids"""
    for getters in lang_getters.values():
        unit_getter = getters['unit_getter']
        tasks.extend(unit_getter.get(story_id) for story_id in unit_getter.tell_ids())
        self_getter = getters['self_getter']
        tasks.extend(self_getter.get(story_id) for story_id in self_getter.tell_ids())
        special_getter = getters['special_getter']
        tasks.extend(
            special_getter.get(story_id) for story_id in special_getter.tell_ids()
        )


def add_jp_tasks(tasks: TaskList_type, lang_getters: dict[str, Getters_type]) -> None:
    """JP 模式: event/card 走 tell_ids, area 不过滤 int"""
    getters = lang_getters['jp']
    event_getter = getters['event_getter']
    card_getter = getters['card_getter']
    area_getter = getters['area_getter']

    tasks.extend(event_getter.get(story_id) for story_id in event_getter.tell_ids())
    tasks.extend(card_getter.get(story_id) for story_id in card_getter.tell_ids())
    tasks.extend(
        area_getter.get(category) for category in area_getter.tell_categories()
    )


def add_nonjp_tasks(
    tasks: TaskList_type,
    lang_getters: dict[str, Getters_type],
    timestamp13: int | None = None,
) -> None:
    """非 JP 模式: event/card 走 get_newest, area 过滤 int"""
    for lang in ('cn', 'tw', 'en'):
        getters = lang_getters[lang]
        event_getter = getters['event_getter']
        card_getter = getters['card_getter']
        area_getter = getters['area_getter']

        tasks.append(
            event_getter.get_newest(0, area_getter=area_getter, timestamp13=timestamp13)
        )
        tasks.append(card_getter.get_newest(0, timestamp13=timestamp13))
        tasks.extend(
            area_getter.get(category)
            for category in area_getter.tell_categories()
            if not isinstance(category, int)
        )


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
                cast(pjsk.Pjsk_fetcher, obj).init(session)
                for getters in lang_getters.values()
                for obj in getters.values()
            ]
        )

        tasks: TaskList_type = []
        add_common_tasks(tasks, lang_getters)
        add_jp_tasks(tasks, lang_getters)
        add_nonjp_tasks(tasks, lang_getters, TIMESTAMP13)
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
