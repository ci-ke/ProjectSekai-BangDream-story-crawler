# https://github.com/ci-ke/ProjectSekai-BangDream-story-crawler

import os, asyncio, json
from typing import Any
from asyncio import Semaphore

import aiofiles  # type: ignore
from aiohttp import ClientSession, TCPConnector  # type: ignore

import get_story_util as util

URLS: dict[str, dict[str, str]] = json.load(open('urls_bandori.json', encoding='utf8'))


class Constant:
    lang_index = {'jp': 0, 'en': 1, 'tw': 2, 'cn': 3, 'kr': 4}

    band_id_abbr = {
        1: 'PPP',
        2: 'Ag',
        3: 'HHW',
        4: 'P＊P',
        5: 'Ro',
        18: 'RAS',
        21: 'Mor',
        45: 'MyGO',
    }


class Story_reader(util.Base_fetcher):
    def __init__(
        self,
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        missing_download: bool = True,
        debug_parse: bool = False,
    ) -> None:
        super().__init__(assets_save_dir, online, save_assets, missing_download)

        self.debug_parse = debug_parse

        self.characters_main_url = URLS['bestdori.com']['characters_main_3']
        self.bands_main_url = URLS['bestdori.com']['bands_main_1']

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.characters_json, self.bands_json = await asyncio.gather(
            util.fetch_url_json_simple(self.characters_main_url, self),
            util.fetch_url_json_simple(self.bands_main_url, self),
        )

    def get_band_name(self, band_id: int, lang: str) -> str:
        return self.bands_json[str(band_id)]['bandName'][Constant.lang_index[lang]]

    def get_chara_bandAbbr_and_name(self, chara_id: int, lang: str) -> tuple[str, str]:
        name = self.characters_json[str(chara_id)]['characterName'][
            Constant.lang_index[lang]
        ].replace(' ', '')
        band_id = self.characters_json[str(chara_id)]['bandId']
        band_abbr = Constant.band_id_abbr[band_id]
        return band_abbr, name

    def read_story_in_json(
        self, json_data: str | dict[str, dict[str, Any]], lang: str
    ) -> str:
        if isinstance(json_data, str):
            return json_data

        talks = json_data['Base']['talkData']
        specialEffects = json_data['Base']['specialEffectData']

        appearCharacters = json_data['Base']['appearCharacters']
        chara_id = set()
        for chara in appearCharacters:
            if str(chara['characterId']) in self.characters_json:
                chara_id.add(chara['characterId'])
        chara_id_list = sorted(chara_id)

        if len(chara_id_list) > 0:
            ret0 = (
                '（登场角色：'
                + '、'.join(
                    [
                        self.get_chara_bandAbbr_and_name(id, lang)[1]
                        for id in chara_id_list
                    ]
                )
                + '）\n'
            )
        else:
            ret0 = ''

        snippets = json_data['Base']['snippets']
        next_talk_need_newline = True

        ret = ''
        index = -1
        for snippet in snippets:
            index += 1
            if snippet['actionType'] == util.SnippetAction.SpecialEffect:
                specialEffect = specialEffects[snippet['referenceIndex']]
                if specialEffect['effectType'] == util.SpecialEffectType.Telop:
                    ret += '\n【' + specialEffect['stringVal'] + '】\n'
                    next_talk_need_newline = True
                elif (
                    specialEffect['effectType']
                    == util.SpecialEffectType.ChangeBackground
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += (
                        '（背景切换）'
                        + (
                            f"：{specialEffect['stringVal']}, {specialEffect['stringValSub']}"
                            if self.debug_parse
                            else ''
                        )
                        + '\n'
                    )
                    next_talk_need_newline = False
                elif specialEffect['effectType'] == util.SpecialEffectType.FlashbackIn:
                    ret += '\n（回忆切入 ↓）\n'
                    next_talk_need_newline = True
                elif specialEffect['effectType'] == util.SpecialEffectType.FlashbackOut:
                    ret += '\n（回忆切出 ↑）\n'
                    next_talk_need_newline = True
                elif specialEffect['effectType'] == util.SpecialEffectType.BlackOut:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += '（黑屏转场）\n'
                    next_talk_need_newline = False
                elif specialEffect['effectType'] == util.SpecialEffectType.WhiteOut:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += '（白屏转场）\n'
                    next_talk_need_newline = False
                else:
                    if self.debug_parse:
                        try:
                            effect_name = util.SpecialEffectType(
                                specialEffect['effectType']
                            ).name
                        except ValueError:
                            effect_name = specialEffect['effectType']
                        ret += f"SpecialEffectType: {effect_name}, {index}, {specialEffect['stringVal']}\n"
            elif snippet['actionType'] == util.SnippetAction.Talk:
                talk = talks[snippet['referenceIndex']]
                if next_talk_need_newline:
                    ret += '\n'
                ret += (
                    talk['windowDisplayName']
                    + '：'
                    + talk['body'].replace('\n', ' ')
                    + '\n'
                )
                next_talk_need_newline = False
            else:
                if self.debug_parse:
                    try:
                        snippet_name = util.SnippetAction(snippet['actionType']).name
                    except ValueError:
                        snippet_name = snippet['actionType']
                    ret += f'SnippetAction: {snippet_name}, {index}\n'

        return (ret0 + '\n' + ret.strip()).strip()


class Event_story_getter(util.Base_getter):

    event_is_main = [217]
    event_no_story = [248]

    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_event',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_eventId: int = 3,
    ) -> None:
        super().__init__(
            save_dir, assets_save_dir, online, save_assets, parse, missing_download
        )

        self.reader = reader
        self.maxlen_eventId = maxlen_eventId

        self.events_id_url = URLS['bestdori.com']['events_id']
        self.event_asset_url = URLS['bestdori.com']['event_asset']

    async def get(self, event_id: int, lang: str = 'cn') -> None:

        info_json: dict[str, Any] = await util.fetch_url_json_simple(
            self.events_id_url.format(event_id=event_id), self
        )

        event_name = info_json['eventName'][Constant.lang_index[lang]]
        if event_name is None:
            print(f'event {event_id} has no {lang.upper()}.')
            return

        event_filename = util.valid_filename(event_name)

        save_folder_name = f'{event_id:0{self.maxlen_eventId}} {event_filename}'

        save_folder_name = lang + '-' + save_folder_name

        event_save_dir = os.path.join(self.save_dir, save_folder_name)

        if self.parse:
            os.makedirs(event_save_dir, exist_ok=True)

            if event_id in Event_story_getter.event_no_story:
                async with self.file_semaphore:
                    async with aiofiles.open(
                        os.path.join(event_save_dir, '无剧情.txt'), 'w', encoding='utf8'
                    ) as f:
                        await f.write('本活动没有活动剧情\n')
                    return

        tasks = []
        for story in info_json['stories']:
            tasks.append(
                self.__get_story(story, lang, event_id, event_save_dir, event_name)
            )
        await asyncio.gather(*tasks)

    async def __get_story(
        self,
        story: dict[str, Any],
        lang: str,
        event_id: int,
        event_save_dir: str,
        event_name: str,
    ):
        name = f"{story['scenarioId']} {story['caption'][Constant.lang_index[lang]]} {story['title'][Constant.lang_index[lang]]}"

        synopsis: str | None = story['synopsis'][Constant.lang_index[lang]]
        if synopsis is not None:  # for 13 20 23, jp meta lost
            synopsis = synopsis.replace('\n', ' ')

        id = story['scenarioId']

        filename = util.valid_filename(name)

        if ('bandStoryId' not in story) and (
            event_id not in Event_story_getter.event_is_main
        ):
            story_json: dict[str, dict[str, Any]] = await util.fetch_url_json_simple(
                self.event_asset_url.format(lang=lang, event_id=event_id, id=id),
                self,
                filename,
            )

            if self.parse:
                text = self.reader.read_story_in_json(story_json, lang)
            else:
                text = ''
        elif event_id in Event_story_getter.event_is_main:
            text = '见主线故事'
        else:
            text = '见乐队故事'

        if self.parse:
            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(event_save_dir, filename) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    await f.write(name + '\n\n')
                    await f.write(f'{synopsis}' + '\n\n')
                    await f.write(text + '\n')

        print(f'get event {event_id} {event_name} {name} done.')


class Band_story_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_band',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
    ) -> None:
        super().__init__(
            save_dir, assets_save_dir, online, save_assets, parse, missing_download
        )

        self.reader = reader

        self.bandstories_5_url = URLS['bestdori.com']['bandstories_5']
        self.band_asset_url = URLS['bestdori.com']['band_asset']

    async def get(
        self,
        want_band_id: int | None = None,
        want_chapter_number: int | None = None,
        lang: str = 'cn',
    ) -> None:
        if want_band_id is not None:
            assert str(want_band_id) in self.reader.bands_json

        info_json: dict[str, dict[str, Any]] = await util.fetch_url_json_simple(
            self.bandstories_5_url, self
        )

        tasks = []
        for band_story in info_json.values():
            band_id = band_story['bandId']
            try:
                chapterNumber = band_story['chapterNumber']
            except KeyError:
                continue

            if want_band_id is not None:
                if want_band_id != band_id:
                    continue
            if want_chapter_number is not None:
                if want_chapter_number != chapterNumber:
                    continue

            band_name = self.reader.get_band_name(band_id, lang)

            if band_story['mainTitle'][Constant.lang_index[lang]] == None:
                print(
                    f'band story {band_name} {band_story["mainTitle"][0]} {band_story["subTitle"][0]} has no {lang.upper()}.'
                )
                continue

            save_folder_name = util.valid_filename(
                f'{band_story["mainTitle"][Constant.lang_index[lang]]} {band_story["subTitle"][Constant.lang_index[lang]]}'
            )

            band_save_dir = os.path.join(
                self.save_dir, lang + '-' + band_name, save_folder_name
            )
            if self.parse:
                os.makedirs(band_save_dir, exist_ok=True)

            for story in band_story['stories'].values():
                tasks.append(
                    self.__get_story(
                        story, lang, band_id, band_save_dir, band_name, band_story
                    )
                )
        await asyncio.gather(*tasks)

    async def __get_story(
        self,
        story: dict[str, Any],
        lang: str,
        band_id: int,
        band_save_dir: str,
        band_name: str,
        band_story: dict[str, Any],
    ):
        name = f"{story['scenarioId']} {story['caption'][Constant.lang_index[lang]]} {story['title'][Constant.lang_index[lang]]}"
        synopsis = story['synopsis'][Constant.lang_index[lang]].replace('\n', ' ')
        id = story['scenarioId']

        filename = util.valid_filename(name)

        story_json: dict[str, dict[str, Any]] = await util.fetch_url_json_simple(
            self.band_asset_url.format(lang=lang, band_id=band_id, id=id),
            self,
            filename,
        )

        if self.parse:
            text = self.reader.read_story_in_json(story_json, lang)

            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(band_save_dir, filename) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    await f.write(name + '\n\n')
                    await f.write(synopsis + '\n\n')
                    await f.write(text + '\n')

        print(
            f'get band story {band_name} {band_story["mainTitle"][Constant.lang_index[lang]]} {name} done.'
        )


class Main_story_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_main',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
    ) -> None:
        super().__init__(
            save_dir, assets_save_dir, online, save_assets, parse, missing_download
        )

        self.reader = reader

        self.mainstories_5_url = URLS['bestdori.com']['mainstories_5']
        self.main_asset_url = URLS['bestdori.com']['main_asset']

    async def get(self, id_range: list[int] | None = None, lang: str = 'cn') -> None:
        info_json: dict[str, dict[str, Any]] = await util.fetch_url_json_simple(
            self.mainstories_5_url, self
        )

        if self.parse:
            os.makedirs(self.save_dir, exist_ok=True)

        tasks = []
        for strId, main_story in info_json.items():
            if id_range is not None and int(strId) not in id_range:
                continue

            if main_story['title'][Constant.lang_index[lang]] == None:
                print(
                    f'main story {main_story["caption"][0]} {main_story["title"][0]} has no {lang.upper()}.'
                )
                continue

            name = f"{main_story['scenarioId']} {main_story['caption'][Constant.lang_index[lang]]} {main_story['title'][Constant.lang_index[lang]]}"

            filename = util.valid_filename(lang + '-' + name)

            synopsis = main_story['synopsis'][Constant.lang_index[lang]].replace(
                '\n', ' '
            )
            id = main_story['scenarioId']

            tasks.append(self.__get_story(lang, id, filename, name, synopsis))
        await asyncio.gather(*tasks)

    async def __get_story(
        self, lang: str, id: str, filename: str, name: str, synopsis: str
    ) -> None:
        story_json: dict[str, dict[str, Any]] = await util.fetch_url_json_simple(
            self.main_asset_url.format(lang=lang, id=id), self, filename
        )

        if self.parse:
            text = self.reader.read_story_in_json(story_json, lang)

            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(self.save_dir, filename) + '.txt', 'w', encoding='utf8'
                ) as f:
                    await f.write(name + '\n\n')
                    await f.write(synopsis + '\n\n')
                    await f.write(text + '\n')

        print(f'get main story {name} done.')


class Card_story_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_card',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_id: int = 4,
    ) -> None:
        super().__init__(
            save_dir, assets_save_dir, online, save_assets, parse, missing_download
        )

        self.reader = reader
        self.maxlen_id = maxlen_id

        self.cards_all_0_url = URLS['bestdori.com']['cards_all_0']
        self.cards_id_url = URLS['bestdori.com']['cards_id']
        self.card_asset_url = URLS['bestdori.com']['card_asset']

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        all_cards_list: dict[int, Any] = await util.fetch_url_json_simple(
            self.cards_all_0_url, self
        )

        self.cards_ids: list[int] = [int(id) for id in all_cards_list.keys()]

    async def get(self, card_id: int, lang: str = 'cn') -> None:
        if card_id not in self.cards_ids:
            print(f'card {card_id} does not exist.')
            return

        card = await util.fetch_url_json_simple(
            self.cards_id_url.format(id=card_id), self
        )

        chara_bandAbbr, chara_name = self.reader.get_chara_bandAbbr_and_name(
            card['characterId'], lang
        )
        chara_band_and_name = lang + '-' + '_'.join((chara_bandAbbr, chara_name))
        cardRarityType = card['rarity']
        card_name = card['prefix'][Constant.lang_index[lang]]

        if card_name is None:
            print(f'card {card_id} has no {lang.upper()}.')
            return

        resourceSetName: str = card['resourceSetName']

        card_story_name = f'{card_id}_{chara_name}_R{cardRarityType} {card_name}'

        card_story_filename = util.valid_filename(
            f'{card_id:0{self.maxlen_id}}_{chara_name}_R{cardRarityType} {card_name}'
        )

        if 'episodes' not in card:
            card_has_story = False
            text_1 = ''
            text_2 = ''
        else:
            card_has_story = True

            story_1_name = card['episodes']['entries'][0]['title'][
                Constant.lang_index[lang]
            ]
            story_2_name = card['episodes']['entries'][1]['title'][
                Constant.lang_index[lang]
            ]

            story_1_type = card['episodes']['entries'][0]['episodeType']
            story_2_type = card['episodes']['entries'][1]['episodeType']

            if story_1_type != 'animation':
                scenarioId_1 = card['episodes']['entries'][0]['scenarioId']
                story_1_json_task = util.fetch_url_json_simple(
                    self.card_asset_url.format(
                        lang=lang, res_id=resourceSetName, scenarioId=scenarioId_1
                    ),
                    self,
                    card_story_filename,
                )
            else:

                async def noop() -> str:
                    return '动画故事'

                story_1_json_task = noop()

            scenarioId_2 = card['episodes']['entries'][1]['scenarioId']

            story_2_json_task = util.fetch_url_json_simple(
                self.card_asset_url.format(
                    lang=lang, res_id=resourceSetName, scenarioId=scenarioId_2
                ),
                self,
                card_story_filename,
            )

            story_1_json, story_2_json = await asyncio.gather(
                story_1_json_task, story_2_json_task
            )

            if self.parse:
                text_1 = self.reader.read_story_in_json(story_1_json, lang)
                text_2 = self.reader.read_story_in_json(story_2_json, lang)
            else:
                text_1 = ''
                text_2 = ''

        if self.parse:
            card_save_dir = os.path.join(self.save_dir, chara_band_and_name)

            os.makedirs(card_save_dir, exist_ok=True)

            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(card_save_dir, card_story_filename) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    if card_has_story:
                        await f.write(card_story_name + '\n\n')
                        await f.write(f'《{story_1_name}》' + '\n\n')
                        await f.write(text_1 + '\n\n\n')
                        await f.write(f'《{story_2_name}》' + '\n\n')
                        await f.write(text_2 + '\n')
                    else:
                        await f.write('本卡面没有剧情\n')

        print(f'get card {card_story_filename} done.')


if __name__ == '__main__':

    net_connect_limit = 10

    online = False

    reader = Story_reader(online=online)
    main_getter = Main_story_getter(reader, online=online)
    band_getter = Band_story_getter(reader, online=online)
    event_getter = Event_story_getter(reader, online=online)
    card_getter = Card_story_getter(reader, online=online)

    async def main():
        async with ClientSession(
            trust_env=True, connector=TCPConnector(limit=net_connect_limit)
        ) as session:

            await asyncio.gather(
                reader.init(session),
                main_getter.init(session),
                band_getter.init(session),
                event_getter.init(session),
                card_getter.init(session),
            )

            tasks = []

            lang = 'cn'

            tasks.append(main_getter.get(list(range(1, 4)), lang))
            for i in [1, 2]:
                for j in [1]:
                    tasks.append(band_getter.get(i, j, lang))
            for i in range(1, 11):
                tasks.append(event_getter.get(i, lang))
            for i in range(1, 11):
                tasks.append(card_getter.get(i, lang))

            await asyncio.gather(*tasks)

    asyncio.run(main())
