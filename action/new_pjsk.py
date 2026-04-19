import asyncio

from aiohttp import ClientSession, TCPConnector

from .all_pjsk import (
    reader,
    event_getter,
    card_getter,
    area_getter,
    reader_jp,
    event_getter_jp,
    card_getter_jp,
    area_getter_jp,
    net_connect_limit,
    timestamp13,
)


async def main():
    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=net_connect_limit)
    ) as session:
        await asyncio.gather(
            reader.init(session),
            event_getter.init(session),
            card_getter.init(session),
            area_getter.init(session),
            reader_jp.init(session),
            event_getter_jp.init(session),
            card_getter_jp.init(session),
            area_getter_jp.init(session),
        )

        tasks = []

        tasks.append(
            event_getter.get_newest(
                10, area_getter=area_getter, timestamp13=timestamp13
            )
        )
        for i in event_getter_jp.tell_ids()[-10:]:
            tasks.append(event_getter_jp.get(i))
            tasks.append(area_getter_jp.get(i))

        tasks.append(card_getter.get_newest(50, timestamp13=timestamp13))
        for i in card_getter_jp.tell_ids()[-50:]:
            tasks.append(card_getter_jp.get(i))

        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
