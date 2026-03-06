import asyncio
from pathlib import Path
from typing import Any

import aiofiles
from aiohttp import ClientSession

import get_story_util as util

translate_src_url = 'https://pjsk.moe/data/translations/eventStory/event_{}.json'


async def get_translate(
    event_id: int,
    event_base_path: str = 'story_event',
    event_id_maxlen: int = 3,
    mark_lang: str = 'en',
    assets_save_dir: str = './assets',
    online: bool = True,
    save_assets: bool = True,
    missing_download: bool = True,
    session: ClientSession | None = None,
) -> None:
    for event_dir in Path(event_base_path).iterdir():
        if event_dir.stem.startswith(f'jp-{event_id:0{event_id_maxlen}}'):

            translate_json: dict = await util.fetch_url_json(
                translate_src_url.format(event_id),
                online,
                save_assets,
                assets_save_dir,
                missing_download,
                session=session,
            )
            try:
                source = 'pjsk.moe: ' + translate_json['meta']['source']
            except KeyError:
                source = 'pjsk.moe'
            raw_content: dict[str, dict[str, Any]] = translate_json.get(
                'episodes', translate_json
            )
            format_index_talk: dict[str, dict[str, str]] = {}
            for index_str in raw_content:
                raw_talk: dict[str, str] = raw_content[index_str]['talkData']
                format_index_talk[index_str] = {}
                for raw_sentence, raw_translate in raw_talk.items():
                    format_index_talk[index_str][raw_sentence.replace('\n', ' ')] = (
                        raw_translate.replace('\n', ' ')
                    )

            tasks = []
            for episode_file in event_dir.iterdir():
                tasks.append(
                    _get_translate_episode(
                        source,
                        event_dir,
                        episode_file,
                        raw_content,
                        format_index_talk,
                        event_id,
                        event_id_maxlen,
                        mark_lang,
                    )
                )
            await asyncio.gather(*tasks)
            break


async def _get_translate_episode(
    source: str,
    event_dir: Path,
    episode_file: Path,
    raw_content: dict[str, dict[str, Any]],
    format_index_talk: dict[str, dict[str, str]],
    event_id: int,
    event_id_maxlen: int,
    mark_lang: str,
) -> None:
    episode_index = str(int(episode_file.stem.split(' ')[0].split('-')[1]))
    episode_name = episode_file.stem[episode_file.stem.index(' ') + 1 :]

    last_part = episode_file.stem.split(' ')[-1]
    if last_part.startswith('(') and last_part.endswith(')'):
        is_wl = True
    else:
        is_wl = False

    translate_epi_name = raw_content[episode_index].get('title', episode_name)

    new_event_dir = event_dir.parent / Path(
        f'cn-{event_id:0{event_id_maxlen}} 翻译 {event_dir.stem[event_dir.stem.index(' ')+1:]}'
    )

    new_event_dir.mkdir(exist_ok=True)

    new_epi_file = new_event_dir / Path(
        util.valid_filename(
            episode_file.stem[: episode_file.stem.index(' ') + 1]
            + translate_epi_name
            + ((' ' + last_part) if is_wl else '')
            + '.txt'
        )
    )

    async with util._file_semaphore:
        async with aiofiles.open(
            new_epi_file, 'w', encoding='utf8'
        ) as wf, aiofiles.open(episode_file, encoding='utf8') as rf:
            await wf.write(source + '; ')

            async for line in rf:
                name, *sentence_list = line.split(util.Mark_multi_lang[':'][mark_lang])
                name = name.strip()
                sentence = ''.join(sentence_list).strip()

                trans_name = format_index_talk[episode_index].get(name, name)
                trans_sentence = format_index_talk[episode_index].get(
                    sentence, sentence
                )

                if trans_sentence:
                    trans_sentence = (
                        util.Mark_multi_lang[':'][mark_lang] + trans_sentence
                    )

                await wf.write(trans_name + trans_sentence + '\n')

    print(f'get {new_epi_file.stem} done.')


async def main():
    async with ClientSession(trust_env=True) as session:
        await get_translate(197, online=False, session=session)


if __name__ == '__main__':
    asyncio.run(main())
