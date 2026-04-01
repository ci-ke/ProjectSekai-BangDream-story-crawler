# for github action

import asyncio

from aiohttp import ClientSession, TCPConnector

import src.bang as bang

reader = bang.Story_reader()
event_getter = bang.Event_story_getter(reader, save_dir='../story_event')
card_getter = bang.Card_story_getter(reader, save_dir='../story_card')

net_connect_limit = 10


async def main():
    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=net_connect_limit)
    ) as session:
        await asyncio.gather(
            reader.init(session),
            event_getter.init(session),
            card_getter.init(session),
        )

        tasks = []

        tasks.append(event_getter.get_newest('cn', quantity=10))
        tasks.append(event_getter.get_newest('jp', 'en', quantity=10))

        tasks.append(
            card_getter.get_newest('cn', quantity=50, exclude=[1992, 2034, 2100, 2163])
        )
        tasks.append(
            card_getter.get_newest(
                'jp', 'en', quantity=50, exclude=[1992, 2034, 2100, 2163]
            )
        )

        await asyncio.gather(*tasks)


asyncio.run(main())
