# for github action

import asyncio
from datetime import datetime, timedelta, timezone

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

        now = datetime.now(timezone.utc)
        timestamp = now.timestamp()
        timestamp13 = int(timestamp * 1000)

        tasks = []

        tasks.append(
            event_getter.get_newest('cn', quantity=10, timestamp13=timestamp13)
        )
        tasks.append(
            event_getter.get_newest('jp', 'en', quantity=10, timestamp13=timestamp13)
        )

        tasks.append(
            card_getter.get_newest(
                'cn', quantity=50, timestamp13=timestamp13, exclude=[2163]
            )
        )
        tasks.append(
            card_getter.get_newest('jp', 'en', quantity=50, timestamp13=timestamp13)
        )

        await asyncio.gather(*tasks)


asyncio.run(main())
