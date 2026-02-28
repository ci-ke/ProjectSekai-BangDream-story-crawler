# https://github.com/ci-ke/ProjectSekai-BangDream-story-crawler

import os, math, asyncio, json
from asyncio import Semaphore
from typing import Any, cast

import aiofiles  # type: ignore
from aiohttp import ClientSession, TCPConnector  # type: ignore

import get_story_util as util


class Constant:
    unit_code_abbr = {
        'light_sound': 'L/n',
        'idol': 'MMJ',
        'street': 'VBS',
        'theme_park': 'WxS',
        'school_refusal': 'N25',
        'piapro': 'VS',
    }

    rarity_name = {
        'rarity_1': 'R1',
        'rarity_2': 'R2',
        'rarity_3': 'R3',
        'rarity_4': 'R4',
        'rarity_birthday': 'RB',
    }

    @staticmethod
    def is_cg(pic_name: str) -> bool:
        if pic_name[:4] == 'bg_a' and (1 <= int(pic_name[4:]) <= 99):
            return True
        elif pic_name[:4] == 'bg_s':
            return True
        else:
            return False

    urls: dict[str, dict[str, Any]] = json.load(open('urls_pjsk.json', encoding='utf8'))

    @staticmethod
    def get_src_url(lang: str, src: str, file_type: str, file: str) -> str:
        '''
        lang: cn jp tw

        file_type: master or asset
        '''
        if file_type == 'master':
            base_url: str = Constant.urls[src]['master']
            return base_url.format(
                lang=Constant.urls[src]['master_lang'][lang], file=file
            )
        else:
            base_url = Constant.urls[src][f'{file}_asset']
            return base_url.format(lang=Constant.urls[src]['asset_lang'][lang])


class Story_reader(util.Base_fetcher):
    def __init__(
        self,
        lang: str = 'cn',
        src: str = 'sekai.best',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        missing_download: bool = True,
        debug_parse: bool = False,
    ) -> None:
        super().__init__(assets_save_dir, online, save_assets, missing_download)

        self.lang = lang
        self.debug_parse = debug_parse

        self.gameCharacters_url = Constant.get_src_url(
            lang, src, 'master', 'gameCharacters'
        )
        self.character2ds_url = Constant.get_src_url(
            lang, src, 'master', 'character2ds'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.gameCharacters, self.character2ds = await asyncio.gather(
            util.fetch_url_json_simple(self.gameCharacters_url, self),
            util.fetch_url_json_simple(self.character2ds_url, self),
        )

        self.gameCharacters_lookup = util.DictLookup(self.gameCharacters, 'id')
        self.character2ds_lookup = util.DictLookup(self.character2ds, 'id')

    def get_chara_unitAbbr_name(self, chara_id: int) -> tuple[str, str]:
        profile_index = self.gameCharacters_lookup.find_index(chara_id)
        assert profile_index != -1
        profile: dict[str, Any] = self.gameCharacters[profile_index]
        first_name = profile.get('firstName')
        givenName = profile['givenName']
        full_name = first_name + givenName if first_name is not None else givenName

        unit_abbr = Constant.unit_code_abbr[profile['unit']]
        return (unit_abbr, full_name)

    def read_story_in_json(self, json_data: str | dict[str, Any]) -> str:
        if isinstance(json_data, str):
            return json_data

        talks = json_data['TalkData']
        specialEffects = json_data['SpecialEffectData']

        appearCharacters = json_data['AppearCharacters']
        chara_id = set()

        for chara in appearCharacters:
            chara2dId = chara['Character2dId']
            chara2d = self.character2ds[self.character2ds_lookup.find_index(chara2dId)]
            if chara2d['characterId'] in self.gameCharacters_lookup.ids:
                chara_id.add(chara2d['characterId'])
        chara_id_list = sorted(chara_id)

        if len(chara_id_list) > 0:
            ret0 = (
                '（登场角色：'
                + '、'.join(
                    [self.get_chara_unitAbbr_name(id)[1] for id in chara_id_list]
                )
                + '）\n'
            )
        else:
            ret0 = ''

        snippets = json_data['Snippets']
        next_talk_need_newline = True

        ret = ''
        for snippet in snippets:
            snippet_index = snippet['Index']
            if snippet['Action'] == util.SnippetAction.SpecialEffect:
                specialEffect = specialEffects[snippet['ReferenceIndex']]
                if specialEffect['EffectType'] == util.SpecialEffectType.Telop:
                    ret += '\n【' + specialEffect['StringVal'] + '】\n'
                    next_talk_need_newline = True
                elif specialEffect['EffectType'] == util.SpecialEffectType.PlaceInfo:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += f"（地点）：{specialEffect['StringVal']}\n"
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType'] == util.SpecialEffectType.FullScreenText
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += (
                        '（全屏幕文字）：'
                        + specialEffect['StringVal'].replace('\n', ' ')
                        + '\n'
                    )
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType']
                    == util.SpecialEffectType.SimpleSelectable
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += f"（选项）：{specialEffect['StringVal']}\n"
                    next_talk_need_newline = False
                elif specialEffect['EffectType'] == util.SpecialEffectType.Movie:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += f"（播放视频）：{specialEffect['StringVal']}\n"
                    next_talk_need_newline = False
                elif specialEffect['EffectType'] == util.SpecialEffectType.PlayMV:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += f"（播放MV）：{specialEffect['IntVal']}\n"
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType']
                    == util.SpecialEffectType.ChangeBackground
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    pic_name = specialEffect['StringVal']
                    if Constant.is_cg(pic_name):
                        ret += f'（插入CG）：{pic_name}\n'
                    else:
                        ret += (
                            '（背景切换）'
                            + (f'：{pic_name}' if self.debug_parse else '')
                            + '\n'
                        )
                    next_talk_need_newline = False
                elif specialEffect['EffectType'] == util.SpecialEffectType.FlashbackIn:
                    ret += '\n（回忆切入 ↓）\n'
                    next_talk_need_newline = True
                elif specialEffect['EffectType'] == util.SpecialEffectType.FlashbackOut:
                    ret += '\n（回忆切出 ↑）\n'
                    next_talk_need_newline = True
                elif specialEffect['EffectType'] == util.SpecialEffectType.BlackOut:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += '（黑屏转场）\n'
                    next_talk_need_newline = False
                elif specialEffect['EffectType'] == util.SpecialEffectType.WhiteOut:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += '（白屏转场）\n'
                    next_talk_need_newline = False
                else:
                    if self.debug_parse:
                        try:
                            effect_name = util.SpecialEffectType(
                                specialEffect['EffectType']
                            ).name
                        except ValueError:
                            effect_name = specialEffect['EffectType']
                        ret += f"SpecialEffectType: {effect_name}, {snippet_index}, {specialEffect['StringVal']}\n"

            elif snippet['Action'] == util.SnippetAction.Talk:
                talk = talks[snippet['ReferenceIndex']]

                if next_talk_need_newline:
                    ret += '\n'
                ret += (
                    talk['WindowDisplayName']
                    + '：'
                    + talk['Body'].replace('\n', ' ')
                    + '\n'
                )
                next_talk_need_newline = False
            else:
                if self.debug_parse:
                    try:
                        snippet_name = util.SnippetAction(snippet['Action']).name
                    except ValueError:
                        snippet_name = snippet['Action']
                    ret += f"SnippetAction: {snippet_name}, {snippet_index}\n"

        return (ret0 + '\n' + ret.strip()).strip()


class Event_story_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: str = 'sekai.best',
        save_dir: str = './story_event',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_eventId_episode: tuple[int, int] = (3, 2),
    ) -> None:
        '''
        src: sekai.best or pjsk.moe
        '''

        super().__init__(
            save_dir, assets_save_dir, online, save_assets, parse, missing_download
        )

        self.reader = reader

        self.maxlen_eventId_episode = maxlen_eventId_episode

        self.events_url = Constant.get_src_url(
            self.reader.lang, src, 'master', 'events'
        )
        self.eventStories_url = Constant.get_src_url(
            self.reader.lang, src, 'master', 'eventStories'
        )
        self.gameCharacterUnits_url = Constant.get_src_url(
            self.reader.lang,
            src,
            'master',
            'gameCharacterUnits',
        )
        self.event_asset_url = Constant.get_src_url(
            self.reader.lang, src, 'asset', 'event'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.events_json, self.eventStories_json, self.gameCharacterUnits = (
            await asyncio.gather(
                util.fetch_url_json_simple(self.events_url, self),
                util.fetch_url_json_simple(self.eventStories_url, self),
                util.fetch_url_json_simple(self.gameCharacterUnits_url, self),
            )
        )

        self.events_lookup = util.DictLookup(self.events_json, 'id')
        self.eventStories_lookup = util.DictLookup(self.eventStories_json, 'eventId')
        self.gameCharacterUnits_lookup = util.DictLookup(self.gameCharacterUnits, 'id')

    async def get(self, event_id: int) -> None:

        event_index = self.events_lookup.find_index(event_id)
        eventStory_index = self.eventStories_lookup.find_index(event_id)

        if (event_index == -1) or (eventStory_index == -1):
            print(f'event {event_id} does not exist.')
            return

        event = self.events_json[event_index]
        eventStory: dict[str, Any] = self.eventStories_json[eventStory_index]

        event_name = event['name']
        event_type = event['eventType']
        event_unit = event['unit']
        assetbundleName = event['assetbundleName']
        banner_chara_unit_id = eventStory.get('bannerGameCharacterUnitId')
        event_outline = eventStory['outline'].replace('\n', ' ')

        if event_type == 'world_bloom':
            if event_unit != 'none':
                banner_name = f'{Constant.unit_code_abbr[event_unit]}_WL'
            else:
                banner_name = 'WL'
        else:
            assert banner_chara_unit_id is not None
            banner_chara_unit_index = self.gameCharacterUnits_lookup.find_index(
                banner_chara_unit_id
            )
            assert banner_chara_unit_index != -1
            banner_chara_unit = self.gameCharacterUnits[banner_chara_unit_index]['unit']
            unit_abbr = Constant.unit_code_abbr[banner_chara_unit]
            banner_chara_name = self.reader.get_chara_unitAbbr_name(
                self.gameCharacterUnits[banner_chara_unit_index]['gameCharacterId']
            )[1]
            banner_name = f'{unit_abbr}_{banner_chara_name}'

        save_folder_name = util.valid_filename(
            f'{event_id:0{self.maxlen_eventId_episode[0]}} {event_name} ({banner_name})'
        )

        save_folder_name = self.reader.lang + '-' + save_folder_name

        event_save_dir = os.path.join(self.save_dir, save_folder_name)
        if self.parse:
            os.makedirs(event_save_dir, exist_ok=True)

        tasks = []
        for episode in eventStory['eventStoryEpisodes']:
            tasks.append(
                self.__get_episode(
                    episode,
                    event_type,
                    assetbundleName,
                    event_save_dir,
                    event_outline,
                    event_id,
                    event_name,
                )
            )
        await asyncio.gather(*tasks)

    async def __get_episode(
        self,
        episode: dict[str, Any],
        event_type: str,
        assetbundleName: str,
        event_save_dir: str,
        event_outline: str,
        event_id: int,
        event_name: str,
    ) -> None:
        episode_name = (
            f"{episode['eventStoryId']}-{episode['episodeNo']} {episode['title']}"
        )
        episode_save_name = util.valid_filename(
            f"{episode['eventStoryId']:0{self.maxlen_eventId_episode[0]}}-{episode['episodeNo']:0{self.maxlen_eventId_episode[1]}} {episode['title']}"
        )

        if event_type == 'world_bloom':
            gameCharacterId = episode.get('gameCharacterId', -1)
            if gameCharacterId != -1:
                chara_name = self.reader.get_chara_unitAbbr_name(gameCharacterId)[1]
                episode_name += f" ({chara_name})"
                episode_save_name += util.valid_filename(f" ({chara_name})")

        scenarioId = episode['scenarioId']

        story_json: dict[str, Any] = await util.fetch_url_json_simple(
            self.event_asset_url.format(
                assetbundleName=assetbundleName, scenarioId=scenarioId
            ),
            self,
        )

        if self.parse:
            text = self.reader.read_story_in_json(story_json)

            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(event_save_dir, episode_save_name) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    if episode['episodeNo'] == 1:
                        await f.write(event_outline + '\n\n')
                    await f.write(episode_name + '\n\n')
                    await f.write(text + '\n')

        print(f'get event {event_id} {event_name} {episode_name} done.')


class Unit_story_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: str = 'sekai.best',
        save_dir: str = './story_unit',
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

        self.unitProfiles_url = Constant.get_src_url(
            self.reader.lang, src, 'master', 'unitProfiles'
        )

        self.unitStoryEpisodeGroups_url = Constant.get_src_url(
            self.reader.lang, src, 'master', 'unitStoryEpisodeGroups'
        )

        self.unitStories_url = Constant.get_src_url(
            self.reader.lang, src, 'master', 'unitStories'
        )
        self.unit_asset_url = Constant.get_src_url(
            self.reader.lang, src, 'asset', 'unit'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        (
            self.unitProfiles_json,
            self.unitStoryEpisodeGroups_json,
            self.unitStories_json,
        ) = await asyncio.gather(
            util.fetch_url_json_simple(self.unitProfiles_url, self),
            util.fetch_url_json_simple(self.unitStoryEpisodeGroups_url, self),
            util.fetch_url_json_simple(self.unitStories_url, self),
        )

        self.unitStoryEpisodeGroups_lookup = util.DictLookup(
            self.unitStoryEpisodeGroups_json, 'id'
        )

    async def get(self, unit_id: int) -> None:
        for unitProfile in self.unitProfiles_json:
            if unitProfile['seq'] == unit_id:
                unitName = unitProfile['unitName']
                unitCode = unitProfile['unit']
                break
        else:
            print(f'unit {unit_id} does not exist.')
            return

        for unitStory in self.unitStories_json:
            if unitStory['seq'] == unit_id:
                assetbundleName = unitStory['chapters'][0]['assetbundleName']
                episodes = unitStory['chapters'][0]['episodes']
                break
        else:
            print(f'unit {unit_id} does not exist.')
            return

        save_folder_name = util.valid_filename(
            self.reader.lang + '-' + f'{unit_id} {unitName}'
        )

        unit_save_dir = os.path.join(self.save_dir, save_folder_name)
        if self.parse:
            os.makedirs(unit_save_dir, exist_ok=True)

        tasks = []
        for episode in episodes:
            tasks.append(
                self.__get_episode(
                    episode,
                    assetbundleName,
                    unit_save_dir,
                    unit_id,
                    unitName,
                    unitCode,
                )
            )
        await asyncio.gather(*tasks)

    async def __get_episode(
        self,
        episode: dict[str, Any],
        assetbundleName: str,
        unit_save_dir: str,
        unit_id: int,
        unitName: str,
        unitCode: str,
    ) -> None:
        scenarioId: str = episode['scenarioId']
        episode_name = f"{scenarioId} {episode['title']}"

        if unitCode != 'piapro' and episode['episodeNo'] == 1:
            need_outline = True
        elif unitCode == 'piapro' and int(scenarioId.split('_')[-1]) == 1:
            need_outline = True
        else:
            need_outline = False

        if need_outline:
            unitStoryEpisodeGroupId = episode['unitStoryEpisodeGroupId']
            unit_outline = self.unitStoryEpisodeGroups_json[
                self.unitStoryEpisodeGroups_lookup.find_index(unitStoryEpisodeGroupId)
            ]['outline'].replace('\n', ' ')
        else:
            unit_outline = None

        episode_save_name = util.valid_filename(episode_name)

        story_json: dict[str, Any] = await util.fetch_url_json_simple(
            self.unit_asset_url.format(
                assetbundleName=assetbundleName, scenarioId=scenarioId
            ),
            self,
        )

        if self.parse:
            text = self.reader.read_story_in_json(story_json)

            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(unit_save_dir, episode_save_name) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    if unit_outline is not None:
                        await f.write(unit_outline + '\n\n')
                    await f.write(episode_name + '\n\n')
                    await f.write(text + '\n')

        print(f'get unit {unit_id} {unitName} {episode_name} done.')


class Card_story_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: str = 'sekai.best',
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

        self.cards_url = Constant.get_src_url(self.reader.lang, src, 'master', 'cards')
        self.cardEpisodes_url = Constant.get_src_url(
            self.reader.lang, src, 'master', 'cardEpisodes'
        )
        self.eventCards_url = Constant.get_src_url(
            self.reader.lang, src, 'master', 'eventCards'
        )
        self.card_asset_url = Constant.get_src_url(
            self.reader.lang, src, 'asset', 'card'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.cards_json, self.cardEpisodes_json, ori_eventCards_json = (
            await asyncio.gather(
                util.fetch_url_json_simple(self.cards_url, self),
                util.fetch_url_json_simple(self.cardEpisodes_url, self),
                util.fetch_url_json_simple(self.eventCards_url, self),
            )
        )

        self.eventCards_json: list[dict[str, Any]] = []
        for item in ori_eventCards_json:
            if item['isDisplayCardStory']:
                self.eventCards_json.append(item)

        self.cards_lookup = util.DictLookup(self.cards_json, 'id')
        self.cardEpisodes_lookup = util.DictLookup(self.cardEpisodes_json, 'cardId')
        self.eventCards_lookup = util.DictLookup(self.eventCards_json, 'cardId')

    async def get(self, card_id: int) -> None:
        card_index = self.cards_lookup.find_index(card_id)
        cardEpisode_index = self.cardEpisodes_lookup.find_index(card_id)

        if (card_index == -1) or (cardEpisode_index == -1):
            print(f'card {card_id} does not exist.')
            return

        card = self.cards_json[card_index]
        cardEpisode_1 = self.cardEpisodes_json[cardEpisode_index]
        cardEpisode_2 = self.cardEpisodes_json[cardEpisode_index + 1]

        chara_unit_and_name = '_'.join(
            self.reader.get_chara_unitAbbr_name(card['characterId'])
        )
        chara_name = self.reader.get_chara_unitAbbr_name(card['characterId'])[1]
        cardRarityType = Constant.rarity_name[card['cardRarityType']]
        card_name = card['prefix']
        sub_unit = card['supportUnit']
        assetbundleName: str = card['assetbundleName']

        story_1_name = cardEpisode_1['title']
        story_2_name = cardEpisode_2['title']
        story_1_scenarioId = cardEpisode_1['scenarioId']
        story_2_scenarioId = cardEpisode_2['scenarioId']

        card_save_dir = os.path.join(
            self.save_dir,
            util.valid_filename(self.reader.lang + '-' + chara_unit_and_name),
        )

        if self.parse:
            os.makedirs(card_save_dir, exist_ok=True)

        if sub_unit != 'none':
            sub_unit_name = f' ({Constant.unit_code_abbr[sub_unit]})'
        else:
            sub_unit_name = ''

        card_event_index = self.eventCards_lookup.find_index(card_id)
        if card_event_index == -1:
            belong_event = ''
        else:
            belong_event = (
                f" (event_{self.eventCards_json[card_event_index]['eventId']})"
            )

        card_story_name = f'{card_id}_{chara_name}{sub_unit_name}_{cardRarityType} {card_name}{belong_event}'

        card_story_filename = util.valid_filename(
            f'{card_id:0{self.maxlen_id}}_{chara_name}{sub_unit_name}_{cardRarityType} {card_name}{belong_event}'
        )

        story_1_json, story_2_json = await asyncio.gather(
            util.fetch_url_json_simple(
                self.card_asset_url.format(
                    assetbundleName=assetbundleName, scenarioId=story_1_scenarioId
                ),
                self,
                card_story_name + ' part1',
            ),
            util.fetch_url_json_simple(
                self.card_asset_url.format(
                    assetbundleName=assetbundleName, scenarioId=story_2_scenarioId
                ),
                self,
                card_story_name + ' part2',
            ),
        )

        if self.parse:
            text_1 = self.reader.read_story_in_json(story_1_json)
            text_2 = self.reader.read_story_in_json(story_2_json)

            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(card_save_dir, card_story_filename) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    await f.write(card_story_name + '\n\n')
                    await f.write(story_1_name + '\n\n')
                    await f.write(text_1 + '\n\n\n')
                    await f.write(story_2_name + '\n\n')
                    await f.write(text_2 + '\n')

        print(f'get card {card_story_name} done.')


class Area_talk_getter((util.Base_getter)):
    def __init__(
        self,
        reader: Story_reader,
        src: str = 'sekai.best',
        save_dir: str = './story_area',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_eventId_areaID: tuple[int, int] = (3, 2),
    ) -> None:

        super().__init__(
            save_dir, assets_save_dir, online, save_assets, parse, missing_download
        )

        self.reader = reader
        self.maxlen_eventId_areaID = maxlen_eventId_areaID

        self.areas_url = Constant.get_src_url(self.reader.lang, src, 'master', 'areas')
        self.actionSets_url = Constant.get_src_url(
            self.reader.lang, src, 'master', 'actionSets'
        )
        self.talk_asset_url = Constant.get_src_url(
            self.reader.lang, src, 'asset', 'talk'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.area_name_json, self.actionSets_json = await asyncio.gather(
            util.fetch_url_json_simple(self.areas_url, self),
            util.fetch_url_json_simple(self.actionSets_url, self),
        )

        self.area_name_lookup = util.DictLookup(self.area_name_json, 'id')
        self.actionSets_json_lookup = util.DictLookup(self.actionSets_json, 'id')

    def __get_category(self, action: dict[str, Any]) -> int | str:
        '''
        category: int: event_id; str: grade1, grade2, theater, limited_{area_id}, aprilfool2022+
        '''
        if (
            ('scenarioId' in action)
            and (len(cond := str(action['releaseConditionId'])) == 6)
            and (cond[0] == '1')
        ):
            return int(cond[1:4]) + 1
        elif action['id'] == 2373:  # special case for mzk5
            return 145
        elif (
            ('scenarioId' in action)
            and (action.get("actionSetType") == "normal")
            and (action["isNextGrade"] == False)
            and (action["releaseConditionId"] == 1)
        ):
            return 'grade1'
        elif (
            ('scenarioId' in action)
            and (action.get("actionSetType") == "normal")
            and (action["isNextGrade"] == True)
            and (action["releaseConditionId"] == 1)
        ):
            return 'grade2'
        elif ('scenarioId' in action) and (
            action["releaseConditionId"] >= 2000000
        ):  # cn and jp have diff
            return 'theater'
        elif (
            ('scenarioId' in action)
            and (action.get("actionSetType") == "limited")
            and ('aprilfool' not in action['scenarioId'])
        ):
            return f"limited_{action['areaId']}"
        elif (
            ('scenarioId' in action)
            and (action.get("actionSetType") == "limited")
            and (('aprilfool' in action['scenarioId']))
        ):
            talk_name: str = action['scenarioId']
            return talk_name.split('_')[1]
        else:
            return ''

    async def get(self, target: int | str) -> None:
        '''
        target: int: event_id; str: grade1, grade2, theater, limited_{area_id}, aprilfool2022+
        '''

        actions = [
            action
            for action in self.actionSets_json
            if self.__get_category(action) == target
        ]

        if len(actions) == 0:
            print(f'talk {target} does not exist.')
            return

        if self.parse:
            os.makedirs(self.save_dir, exist_ok=True)

        tasks = []
        for action in actions:
            tasks.append(
                util.fetch_url_json_simple(
                    self.talk_asset_url.format(
                        group=math.floor(action['id'] / 100),
                        scenarioId=action['scenarioId'],
                    ),
                    self,
                    print_done=True,
                )
            )

        talk_jsons = await asyncio.gather(*tasks)

        if self.parse:
            texts = [
                self.reader.read_story_in_json(talk_json) for talk_json in talk_jsons
            ]

            if isinstance(target, int):  # event id
                filename = f'talk_event_{target:0{self.maxlen_eventId_areaID[0]}}'
            elif target.startswith('limited_'):
                filename = f'talk_{target.split('_')[0]}_{target.split('_')[1]:0{self.maxlen_eventId_areaID[1]}}'
            else:
                filename = f'talk_{target}'

            filename = util.valid_filename(self.reader.lang + '-' + filename)

            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(self.save_dir, filename) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    for index, (action, text) in enumerate(zip(actions, texts)):
                        area_name_index = self.area_name_lookup.find_index(
                            action['areaId']
                        )
                        area_name = self.area_name_json[area_name_index]['name']
                        sub_name = self.area_name_json[area_name_index].get('subName')
                        if sub_name is not None:
                            area_name += ' - ' + sub_name

                        talk_type = ''
                        if isinstance(target, int):
                            if '_ev_' in action['scenarioId']:
                                talk_type = ' event'
                            elif '_wl_' in action['scenarioId']:
                                talk_type = ' wl'
                            elif '_monthly' in action['scenarioId']:
                                talk_type = ' monthly'
                            elif '_add_' in action['scenarioId']:
                                talk_type = ' add'
                            else:
                                assert action['id'] == 618  # special case

                        await f.write(
                            f"{index+1}: {action['id']}{talk_type} 【{area_name}】\n\n"
                        )
                        await f.write(text + '\n\n\n')

        print(f'get talk {filename} done.')

    # mainly for update new talk
    async def get_id_range(
        self, start: int | None = None, end: int | None = None
    ) -> None:
        if start is None:
            start = 1
        if end is None:
            end = cast(int, self.actionSets_json[-1]['id'] + 1)
        categories = set()
        for i in range(start, end):
            actionSets_index = self.actionSets_json_lookup.find_index(i)
            cate = self.__get_category(self.actionSets_json[actionSets_index])
            if cate != '':
                categories.add(cate)
        tasks = []
        for cate in categories:
            tasks.append(self.get(cate))
        await asyncio.gather(*tasks)

    # for debug
    async def get_id_to_single_file(self, talk_id: int) -> None:
        actionSets_index = self.actionSets_json_lookup.find_index(talk_id)
        if actionSets_index == -1:
            print(f'talk {talk_id} does not exist.')
            return

        actionSet = self.actionSets_json[actionSets_index]

        if 'scenarioId' not in actionSet:
            print(f'talk {talk_id} does have content.')
            return

        if self.parse:
            os.makedirs(self.save_dir, exist_ok=True)

        talk_json = await util.fetch_url_json_simple(
            self.talk_asset_url.format(
                group=math.floor(talk_id / 100), scenarioId=actionSet['scenarioId']
            ),
            self,
        )

        if self.parse:
            text = self.reader.read_story_in_json(talk_json)

            filename = f'talk_{talk_id}'
            filename = self.reader.lang + '-' + filename

            area_name_index = self.area_name_lookup.find_index(actionSet['areaId'])
            area_name = self.area_name_json[area_name_index]['name']
            sub_name = self.area_name_json[area_name_index].get('subName')
            if sub_name is not None:
                area_name += ' - ' + sub_name

            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(self.save_dir, filename) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    await f.write(f"{actionSet['id']} 【{area_name}】\n\n")
                    await f.write(text + '\n')

        print(f'get talk {talk_id} done.')


class Self_intro_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: str = 'sekai.best',
        save_dir: str = './story_self',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
    ):
        super().__init__(
            save_dir, assets_save_dir, online, save_assets, parse, missing_download
        )

        self.reader = reader

        self.characterProfiles_url = Constant.get_src_url(
            self.reader.lang, src, 'master', 'characterProfiles'
        )
        self.self_asset_url = Constant.get_src_url(
            self.reader.lang, src, 'asset', 'self'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.characterProfiles_json: list[dict[str, Any]] = (
            await util.fetch_url_json_simple(self.characterProfiles_url, self)
        )

        self.characterProfiles_lookup = util.DictLookup(
            self.characterProfiles_json, 'characterId'
        )

    async def get(self, chara_id: int) -> None:
        profile_index = self.characterProfiles_lookup.find_index(chara_id)
        if profile_index == -1:
            print(f'character {chara_id} does not exist.')
            return

        chara_unit_name = '_'.join(self.reader.get_chara_unitAbbr_name(chara_id))

        filename = util.valid_filename(self.reader.lang + '-' + chara_unit_name)

        profile = self.characterProfiles_json[profile_index]
        scenarioId: str = profile['scenarioId']

        scenarioId_common = scenarioId[: scenarioId.rindex('_')]

        grade1_json, grade2_json = await asyncio.gather(
            util.fetch_url_json_simple(
                self.self_asset_url.format(scenarioId=scenarioId_common), self
            ),
            util.fetch_url_json_simple(
                self.self_asset_url.format(scenarioId=scenarioId), self
            ),
        )

        if self.parse:
            os.makedirs(self.save_dir, exist_ok=True)

            text_1 = self.reader.read_story_in_json(grade1_json)
            text_2 = self.reader.read_story_in_json(grade2_json)

            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(self.save_dir, filename) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    await f.write(f'自我介绍：{chara_unit_name.split('_')[1]}\n\n')
                    await f.write('YEAR 1' + '\n\n')
                    await f.write(text_1 + '\n\n\n')
                    await f.write('YEAR 2' + '\n\n')
                    await f.write(text_2 + '\n')

        print(f'get self intro {filename} done.')


class Special_story_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: str = 'sekai.best',
        save_dir: str = './story_special',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_sp: int = 3,
    ):
        super().__init__(
            save_dir, assets_save_dir, online, save_assets, parse, missing_download
        )

        self.reader = reader
        self.maxlen_sp = maxlen_sp

        self.specialStories_url = Constant.get_src_url(
            self.reader.lang, src, 'master', 'specialStories'
        )
        self.special_asset_url = Constant.get_src_url(
            self.reader.lang, src, 'asset', 'special'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.specialStories_json: list[dict[str, Any]] = (
            await util.fetch_url_json_simple(self.specialStories_url, self)
        )

        self.specialStories_lookup = util.DictLookup(self.specialStories_json, 'id')

    async def get(self, id: int) -> None:
        story_index = self.specialStories_lookup.find_index(id)
        if story_index == -1 or id == 2:  # special case id2
            print(f'special story {id} does not exist.')
            return

        story = self.specialStories_json[story_index]
        episodes = story['episodes']
        title = story.get('title')

        if title is None:
            title = episodes[0]['title']

        story_name = f'sp{id}_{title}'

        filename = util.valid_filename(
            self.reader.lang + '-' f'sp{id:0{self.maxlen_sp}}_{title}'
        )

        episode_tasks = []
        for episode in episodes:
            episode_tasks.append(
                util.fetch_url_json_simple(
                    self.special_asset_url.format(
                        assetbundleName=episode['assetbundleName'],
                        scenarioId=episode['scenarioId'],
                    ),
                    self,
                    filename,
                )
            )
        episode_story_jsons = await asyncio.gather(*episode_tasks)

        if self.parse:
            os.makedirs(self.save_dir, exist_ok=True)

            texts = [
                self.reader.read_story_in_json(episode_story_json)
                for episode_story_json in episode_story_jsons
            ]

            if len(episodes) > 1:
                record_No = True
            else:
                record_No = False

            async with self.file_semaphore:
                async with aiofiles.open(
                    os.path.join(self.save_dir, filename) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    await f.write(story_name + '\n\n')
                    for episode, text in zip(episodes, texts):
                        if record_No:
                            await f.write(str(episode['episodeNo']) + ' ')
                        await f.write(episode['title'] + '\n\n')
                        await f.write(text + '\n\n\n')

        print(f'get special {filename} done.')


if __name__ == '__main__':

    net_connect_limit = 20

    online = False

    lang = 'cn'
    src = 'sekai.best'

    reader = Story_reader(lang, src=src, online=online)
    unit_getter = Unit_story_getter(reader, src=src, online=online)
    event_getter = Event_story_getter(reader, src=src, online=online)
    card_getter = Card_story_getter(reader, src=src, online=online)
    area_getter = Area_talk_getter(reader, src=src, online=online)
    self_getter = Self_intro_getter(reader, src=src, online=online)
    special_getter = Special_story_getter(reader, src=src, online=online)

    async def main():
        async with ClientSession(
            trust_env=True, connector=TCPConnector(limit=net_connect_limit)
        ) as session:
            await asyncio.gather(
                reader.init(session),
                unit_getter.init(session),
                event_getter.init(session),
                card_getter.init(session),
                area_getter.init(session),
                self_getter.init(session),
                special_getter.init(session),
            )

            tasks = []

            for i in range(1, 3):
                tasks.append(unit_getter.get(i))
            for i in range(1, 4):
                tasks.append(event_getter.get(i))
            for i in range(1, 4):
                tasks.append(card_getter.get(i))
            for i in range(1, 4):
                tasks.append(area_getter.get(i))
            for i in range(1, 3):
                tasks.append(self_getter.get(i))
            for i in range(1, 5):
                tasks.append(special_getter.get(i))

            await asyncio.gather(*tasks)

    asyncio.run(main())
