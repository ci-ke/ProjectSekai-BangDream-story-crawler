import sys, asyncio
from pathlib import Path
from typing import Any

import aiofiles
from aiohttp import ClientSession

sys.path.insert(0, str(Path(__file__).parents[1]))

import get_story_util as util


class Event_tranlation_getter(util.Base_fetcher):
    def __init__(
        self,
        event_base_path: str = 'story_event',
        event_id_maxlen: int = 3,
        mark_lang: str = 'en',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        missing_download: bool = True,
    ):
        super().__init__(assets_save_dir, online, save_assets, missing_download)

        self.event_base_path = event_base_path
        self.event_id_maxlen = event_id_maxlen
        self.mark_lang = mark_lang

        self.translate_title_url = (
            'https://translation.exmeaning.com/translation/events.json'
        )
        self.translate_url = (
            'https://translation.exmeaning.com/translation/eventStory/event_{}.json'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: asyncio.Semaphore | None = None,
        file_semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.translate_title_json = await util.fetch_url_json_simple(
            self.translate_title_url, self
        )

    async def get(self, event_id: int) -> None:
        for event_dir in Path(self.event_base_path).iterdir():
            if event_dir.stem.startswith(f'jp-{event_id:0{self.event_id_maxlen}}'):

                translate_json: dict = await util.fetch_url_json_simple(
                    self.translate_url.format(event_id), self
                )
                try:
                    source = 'pjsk.moe: ' + translate_json['meta']['source']
                except KeyError:
                    source = 'pjsk.moe'

                event_name = ' '.join(event_dir.stem.split(' ')[1:-1])
                banner_name = event_dir.stem.split(' ')[-1]

                trans_event_name = self.translate_title_json['name'].get(
                    event_name, event_name
                )

                new_event_dir = event_dir.parent / Path(
                    f'cn-{event_id:0{self.event_id_maxlen}} 翻译 {trans_event_name} {banner_name}'
                )
                new_event_dir.mkdir(exist_ok=True)

                index_episode: dict[str, dict[str, Any]] = translate_json.get(
                    'episodes', translate_json
                )
                format_index_talk: dict[str, dict[str, str]] = {}
                for index_str in index_episode:
                    raw_talk: dict[str, str] = index_episode[index_str]['talkData']
                    format_index_talk[index_str] = {}
                    for raw_sentence, raw_translate in raw_talk.items():
                        format_index_talk[index_str][
                            raw_sentence.replace('\n', ' ')
                        ] = raw_translate.replace('\n', ' ')

                tasks = []
                for episode_file in event_dir.iterdir():
                    tasks.append(
                        self.__get_episode(
                            source,
                            new_event_dir,
                            episode_file,
                            index_episode,
                            format_index_talk,
                        )
                    )
                await asyncio.gather(*tasks)
                break

    async def __get_episode(
        self,
        source: str,
        new_event_dir: Path,
        episode_file: Path,
        index_episode: dict[str, dict[str, Any]],
        format_index_talk: dict[str, dict[str, str]],
    ) -> None:
        episode_index = str(int(episode_file.stem.split(' ')[0].split('-')[1]))
        episode_name = episode_file.stem[episode_file.stem.index(' ') + 1 :]

        last_part = episode_file.stem.split(' ')[-1]
        if last_part.startswith('(') and last_part.endswith(')'):
            is_wl = True
        else:
            is_wl = False

        translate_epi_name = index_episode[episode_index].get('title', episode_name)

        new_epi_file = new_event_dir / Path(
            util.valid_filename(
                episode_file.stem[: episode_file.stem.index(' ') + 1]
                + translate_epi_name
                + ((' ' + last_part) if is_wl else '')
                + '.txt'
            )
        )

        async with self.file_semaphore:
            async with aiofiles.open(
                new_epi_file, 'w', encoding='utf8'
            ) as wf, aiofiles.open(episode_file, encoding='utf8') as rf:
                await wf.write(source + '; ')

                async for line in rf:
                    name, *sentence_list = line.rstrip('\n').split(
                        util.Mark_multi_lang[':'][self.mark_lang]
                    )
                    sentence = util.Mark_multi_lang[':'][self.mark_lang].join(
                        sentence_list
                    )

                    trans_name = format_index_talk[episode_index].get(name, name)
                    trans_sentence = format_index_talk[episode_index].get(
                        sentence, sentence
                    )

                    if trans_sentence:
                        trans_sentence = (
                            util.Mark_multi_lang[':'][self.mark_lang] + trans_sentence
                        )

                    await wf.write(trans_name + trans_sentence + '\n')

        print(f'get {new_epi_file.stem} done.')


async def main():

    online = False

    event_trans_getter = Event_tranlation_getter(online=online)

    async with ClientSession(trust_env=True) as session:
        await event_trans_getter.init(session)

        await event_trans_getter.get(1)


if __name__ == '__main__':
    asyncio.run(main())
