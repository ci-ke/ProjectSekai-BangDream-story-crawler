# https://github.com/ci-ke/ProjectSekai-BangDream-story-crawler

import bisect, os, math, asyncio, json
from asyncio import Semaphore
from typing import Any

from aiohttp import ClientSession, TCPConnector  # type: ignore

import get_story_util as util

URLS: dict[str, dict[str, dict[str, str]]] = json.load(
    open('urls_pjsk.json', encoding='utf8')
)


class Constant:
    unit_id_name = {
        1: '虚拟歌手',
        2: 'Leo/need',
        3: 'MORE MORE JUMP！',
        4: 'Vivid BAD SQUAD',
        5: 'Wonderlands×Showtime',
        6: '25点，Nightcord见。',
    }

    unit_code_name = {
        'light_sound': 'LN',
        'idol': 'MMJ',
        'street': 'VBS',
        'theme_park': 'WS',
        'school_refusal': '25时',
        'piapro': '虚拟歌手',
    }

    chara_id_unit_and_name = {
        1: 'LN_星乃一歌',
        2: 'LN_天马咲希',
        3: 'LN_望月穗波',
        4: 'LN_日野森志步',
        5: 'MMJ_花里实乃理',
        6: 'MMJ_桐谷遥',
        7: 'MMJ_桃井爱莉',
        8: 'MMJ_日野森雫',
        9: 'VBS_小豆泽心羽',
        10: 'VBS_白石杏',
        11: 'VBS_东云彰人',
        12: 'VBS_青柳冬弥',
        13: 'WS_天马司',
        14: 'WS_凤笑梦',
        15: 'WS_草薙宁宁',
        16: 'WS_神代类',
        17: '25时_宵崎奏',
        18: '25时_朝比奈真冬',
        19: '25时_东云绘名',
        20: '25时_晓山瑞希',
        21: '虚拟歌手_初音未来',
        22: '虚拟歌手_镜音铃',
        23: '虚拟歌手_镜音连',
        24: '虚拟歌手_巡音流歌',
        25: '虚拟歌手_MEIKO',
        26: '虚拟歌手_KAITO',
    }

    extra_chara_id_unit_and_name_for_banner = {
        27: '虚拟歌手_初音未来（LN）',
        28: '虚拟歌手_初音未来（MMJ）',
        29: '虚拟歌手_初音未来（VBS）',
        30: '虚拟歌手_初音未来（WS）',
        31: '虚拟歌手_初音未来（25时）',
    }

    rarity_name = {
        'rarity_1': '一星',
        'rarity_2': '二星',
        'rarity_3': '三星',
        'rarity_4': '四星',
        'rarity_birthday': '生日',
    }

    @staticmethod
    def is_cg(pic_name: str) -> bool:
        if pic_name[:4] == 'bg_a' and (1 <= int(pic_name[4:]) <= 99):
            return True
        elif pic_name[:4] == 'bg_s':
            return True
        else:
            return False


class Story_reader:
    def __init__(
        self,
        lang: str = 'cn',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        missing_download: bool = True,
        debug_parse: bool = False,
    ) -> None:

        self.lang = lang
        self.assets_save_dir = assets_save_dir

        self.online = online
        self.save_assets = save_assets
        self.missing_download = missing_download

        self.debug_parse = debug_parse

        if lang == 'cn':
            self.character2ds_url = URLS['cn']['sekai.best']['character2ds']
        elif lang == 'jp':
            self.character2ds_url = URLS['jp']['sekai.best']['character2ds']
        elif lang == 'tw':
            self.character2ds_url = URLS['tw']['sekai.best']['character2ds']
        else:
            raise NotImplementedError

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        self.session = session
        self.network_semaphore = network_semaphore
        self.file_semaphore = file_semaphore

        self.character2ds: list[dict[str, Any]] = await util.fetch_url_json(
            self.character2ds_url,
            self.online,
            self.save_assets,
            self.assets_save_dir,
            self.missing_download,
            session=self.session,
            network_semaphore=self.network_semaphore,
            file_semaphore=self.file_semaphore,
        )

        self.character2ds_lookup = DictLookup(self.character2ds, 'id')

    def read_story_in_json(self, json_data: str | dict[str, Any]) -> str:
        if isinstance(json_data, str):
            return json_data

        ret = ''

        talks = json_data['TalkData']
        specialEffects = json_data['SpecialEffectData']

        appearCharacters = json_data['AppearCharacters']
        chara_id = set()

        have_mob = False
        for chara in appearCharacters:
            chara2dId = chara['Character2dId']
            chara2d = self.character2ds[self.character2ds_lookup.find_index(chara2dId)]
            if chara2d['characterId'] in Constant.chara_id_unit_and_name:
                chara_id.add(chara2d['characterId'])
            else:
                have_mob = True
        chara_id_list = sorted(chara_id)

        if len(chara_id_list) > 0:
            ret += (
                '（登场角色：'
                + '、'.join(
                    [
                        Constant.chara_id_unit_and_name[id].split('_')[1]
                        for id in chara_id_list
                    ]
                )
                # + ('、配角' if have_mob else '')
                + '）\n\n'
            )

        snippets = json_data['Snippets']
        next_talk_need_newline = True

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

        return ret[:-1]


class Event_story_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: str = 'sekai.best',
        save_dir: str = './event_story',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
    ) -> None:
        '''
        src: sekai.best or pjsk.moe
        '''

        super().__init__(
            save_dir, assets_save_dir, online, save_assets, parse, missing_download
        )

        self.reader = reader

        if reader.lang == 'cn':
            self.events_url = URLS['cn']['sekai.best']['events']
            self.eventStories_url = URLS['cn']['sekai.best']['eventStories']
            self.event_asset_url = URLS['cn']['sekai.best']['event_asset']
        elif reader.lang == 'jp':
            if src == 'sekai.best':
                self.events_url = URLS['jp']['sekai.best']['events']
                self.eventStories_url = URLS['jp']['sekai.best']['eventStories']
                self.event_asset_url = URLS['jp']['sekai.best']['event_asset']
            elif src == 'pjsk.moe':
                self.events_url = URLS['jp']['pjsk.moe']['events']
                self.eventStories_url = URLS['jp']['pjsk.moe']['eventStories']
                self.event_asset_url = URLS['jp']['pjsk.moe']['event_asset']
            else:
                raise NotImplementedError
        elif reader.lang == 'tw':
            self.events_url = URLS['tw']['sekai.best']['events']
            self.eventStories_url = URLS['tw']['sekai.best']['eventStories']
            self.event_asset_url = URLS['tw']['sekai.best']['event_asset']
        else:
            raise NotImplementedError

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.events_json, self.eventStories_json = await asyncio.gather(
            util.fetch_url_json(
                self.events_url,
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
                session=self.session,
                network_semaphore=self.network_semaphore,
                file_semaphore=self.file_semaphore,
            ),
            util.fetch_url_json(
                self.eventStories_url,
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
                session=self.session,
                network_semaphore=self.network_semaphore,
                file_semaphore=self.file_semaphore,
            ),
        )

        self.events_lookup = DictLookup(self.events_json, 'id')
        self.eventStories_lookup = DictLookup(self.eventStories_json, 'eventId')

    async def get(self, event_id: int) -> None:

        event_index = self.events_lookup.find_index(event_id)
        eventStory_index = self.eventStories_lookup.find_index(event_id)

        if (event_index == -1) or (eventStory_index == -1):
            print(f'event {event_id} does not exist.')
            return

        event = self.events_json[event_index]
        eventStory = self.eventStories_json[eventStory_index]

        event_name = event['name']
        event_type = event['eventType']
        event_unit = event['unit']
        assetbundleName = event['assetbundleName']
        banner_chara_id = eventStory.get('bannerGameCharacterUnitId', None)
        event_outline = eventStory['outline'].replace('\n', ' ')

        if event_type == 'world_bloom':
            if event_unit != 'none':
                banner_name = f'{Constant.unit_code_name[event_unit]}_WL'
            else:
                banner_name = 'WL'
        else:
            assert banner_chara_id is not None
            banner_name = (
                Constant.chara_id_unit_and_name
                | Constant.extra_chara_id_unit_and_name_for_banner
            )[banner_chara_id]

        event_filename = util.valid_filename(event_name)
        save_folder_name = f'{event_id} {event_filename}（{banner_name}）'

        if self.reader.lang != 'cn':
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
        if event_type == 'world_bloom':
            gameCharacterId = episode.get('gameCharacterId', -1)
            if gameCharacterId != -1:
                chara_name = Constant.chara_id_unit_and_name[gameCharacterId].split(
                    '_'
                )[1]
                episode_name += f"（{chara_name}）"

        scenarioId = episode['scenarioId']

        filename = util.valid_filename(episode_name)

        story_json: dict[str, Any] = await util.fetch_url_json(
            self.event_asset_url.format(
                assetbundleName=assetbundleName, scenarioId=scenarioId
            ),
            self.online,
            self.save_assets,
            self.assets_save_dir,
            self.missing_download,
            filename,
            session=self.session,
            network_semaphore=self.network_semaphore,
            file_semaphore=self.file_semaphore,
        )

        if self.parse:
            text = self.reader.read_story_in_json(story_json)

            with open(
                os.path.join(event_save_dir, filename) + '.txt',
                'w',
                encoding='utf8',
            ) as f:
                if episode['episodeNo'] == 1:
                    f.write(event_outline + '\n\n')
                f.write(episode_name + '\n\n')
                f.write(text + '\n')

        print(f'get event {event_id} {event_name} {episode_name} done.')


class Unit_story_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './unit_story',
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

        if reader.lang == 'cn':
            self.unitProfiles_url = URLS['cn']['sekai.best']['unitProfiles']
            self.unitStories_url = URLS['cn']['sekai.best']['unitStories']
            self.unit_asset_url = URLS['cn']['sekai.best']['unit_asset']
        elif reader.lang == 'jp':
            self.unitProfiles_url = URLS['jp']['sekai.best']['unitProfiles']
            self.unitStories_url = URLS['jp']['sekai.best']['unitStories']
            self.unit_asset_url = URLS['jp']['sekai.best']['unit_asset']
        elif reader.lang == 'tw':
            self.unitProfiles_url = URLS['tw']['sekai.best']['unitProfiles']
            self.unitStories_url = URLS['tw']['sekai.best']['unitStories']
            self.unit_asset_url = URLS['tw']['sekai.best']['unit_asset']
        else:
            raise NotImplementedError

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.unitProfiles_json, self.unitStories_json = await asyncio.gather(
            util.fetch_url_json(
                self.unitProfiles_url,
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
                session=self.session,
                network_semaphore=self.network_semaphore,
                file_semaphore=self.file_semaphore,
            ),
            util.fetch_url_json(
                self.unitStories_url,
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
                session=self.session,
                network_semaphore=self.network_semaphore,
                file_semaphore=self.file_semaphore,
            ),
        )

    async def get(self, unit_id: int) -> None:
        for unitProfile in self.unitProfiles_json:
            if unitProfile['seq'] == unit_id:
                unitName = unitProfile['unitName']
                # unitCode = unitProfile['unit']
                unit_outline = unitProfile['profileSentence']
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

        unit_filename = util.valid_filename(unitName)
        save_folder_name = f'{unit_id} {unit_filename}'

        if self.reader.lang != 'cn':
            save_folder_name = self.reader.lang + '-' + save_folder_name

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
                    unit_outline,
                    unit_id,
                    unitName,
                )
            )
        await asyncio.gather(*tasks)

    async def __get_episode(
        self,
        episode: dict[str, Any],
        assetbundleName: str,
        unit_save_dir: str,
        unit_outline: str,
        unit_id: int,
        unitName: str,
    ) -> None:
        scenarioId = episode['scenarioId']
        episode_name = f"{scenarioId} {episode['title']}"

        filename = util.valid_filename(episode_name)

        story_json: dict[str, Any] = await util.fetch_url_json(
            self.unit_asset_url.format(
                assetbundleName=assetbundleName, scenarioId=scenarioId
            ),
            self.online,
            self.save_assets,
            self.assets_save_dir,
            self.missing_download,
            filename,
            session=self.session,
            network_semaphore=self.network_semaphore,
            file_semaphore=self.file_semaphore,
        )

        if self.parse:
            text = self.reader.read_story_in_json(story_json)

            with open(
                os.path.join(unit_save_dir, filename) + '.txt', 'w', encoding='utf8'
            ) as f:
                if episode['episodeNo'] == 1:
                    f.write(unit_outline + '\n\n')
                f.write(episode_name + '\n\n')
                f.write(text + '\n')

        print(f'get unit {unit_id} {unitName} {episode_name} done.')


class Card_story_getter(util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './card_story',
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

        if reader.lang == 'cn':
            self.cards_url = URLS['cn']['sekai.best']['cards']
            self.cardEpisodes_url = URLS['cn']['sekai.best']['cardEpisodes']
            self.eventCards_url = URLS['cn']['sekai.best']['eventCards']
            self.card_asset_url = URLS['cn']['sekai.best']['card_asset']
        elif reader.lang == 'jp':
            self.cards_url = URLS['jp']['sekai.best']['cards']
            self.cardEpisodes_url = URLS['jp']['sekai.best']['cardEpisodes']
            self.eventCards_url = URLS['jp']['sekai.best']['eventCards']
            self.card_asset_url = URLS['jp']['sekai.best']['card_asset']
        elif reader.lang == 'tw':
            self.cards_url = URLS['tw']['sekai.best']['cards']
            self.cardEpisodes_url = URLS['tw']['sekai.best']['cardEpisodes']
            self.eventCards_url = URLS['tw']['sekai.best']['eventCards']
            self.card_asset_url = URLS['tw']['sekai.best']['card_asset']
        else:
            raise NotImplementedError

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.cards_json, self.cardEpisodes_json, ori_eventCards_json = (
            await asyncio.gather(
                util.fetch_url_json(
                    self.cards_url,
                    self.online,
                    self.save_assets,
                    self.assets_save_dir,
                    self.missing_download,
                    session=self.session,
                    network_semaphore=self.network_semaphore,
                    file_semaphore=self.file_semaphore,
                ),
                util.fetch_url_json(
                    self.cardEpisodes_url,
                    self.online,
                    self.save_assets,
                    self.assets_save_dir,
                    self.missing_download,
                    session=self.session,
                    network_semaphore=self.network_semaphore,
                    file_semaphore=self.file_semaphore,
                ),
                util.fetch_url_json(
                    self.eventCards_url,
                    self.online,
                    self.save_assets,
                    self.assets_save_dir,
                    self.missing_download,
                    session=self.session,
                    network_semaphore=self.network_semaphore,
                    file_semaphore=self.file_semaphore,
                ),
            )
        )

        self.eventCards_json: list[dict[str, Any]] = []
        for item in ori_eventCards_json:
            if item['isDisplayCardStory']:
                self.eventCards_json.append(item)

        self.cards_lookup = DictLookup(self.cards_json, 'id')
        self.cardEpisodes_lookup = DictLookup(self.cardEpisodes_json, 'cardId')
        self.eventCards_lookup = DictLookup(self.eventCards_json, 'cardId')

    async def get(self, card_id: int) -> None:
        card_index = self.cards_lookup.find_index(card_id)
        cardEpisode_index = self.cardEpisodes_lookup.find_index(card_id)

        if (card_index == -1) or (cardEpisode_index == -1):
            print(f'card {card_id} does not exist.')
            return

        card = self.cards_json[card_index]
        cardEpisode_1 = self.cardEpisodes_json[cardEpisode_index]
        cardEpisode_2 = self.cardEpisodes_json[cardEpisode_index + 1]

        chara_unit_and_name = Constant.chara_id_unit_and_name[card['characterId']]
        chara_name = chara_unit_and_name.split('_')[1]
        cardRarityType = Constant.rarity_name[card['cardRarityType']]
        card_name = card['prefix']
        sub_unit = card['supportUnit']
        assetbundleName: str = card['assetbundleName']
        card_id_for_chara = int(assetbundleName.split('_')[1][2:])

        story_1_name = cardEpisode_1['title']
        story_2_name = cardEpisode_2['title']
        story_1_scenarioId = cardEpisode_1['scenarioId']
        story_2_scenarioId = cardEpisode_2['scenarioId']

        card_save_dir = os.path.join(self.save_dir, chara_unit_and_name)
        if self.parse:
            os.makedirs(card_save_dir, exist_ok=True)

        if sub_unit != 'none':
            sub_unit_name = f'（{Constant.unit_code_name[sub_unit]}）'
        else:
            sub_unit_name = ''

        card_event_index = self.eventCards_lookup.find_index(card_id)
        if card_event_index == -1:
            belong_event = ''
        else:
            belong_event = (
                f"（event-{self.eventCards_json[card_event_index]['eventId']}）"
            )

        card_story_filename = util.valid_filename(
            f'{card_id}_{chara_name}{sub_unit_name}_{card_id_for_chara}_{cardRarityType} {card_name}{belong_event}'
        )

        if self.reader.lang != 'cn':
            card_story_filename = self.reader.lang + '-' + card_story_filename

        story_1_json, story_2_json = await asyncio.gather(
            util.fetch_url_json(
                self.card_asset_url.format(
                    assetbundleName=assetbundleName, scenarioId=story_1_scenarioId
                ),
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
                card_story_filename + ' 上篇',
                session=self.session,
                network_semaphore=self.network_semaphore,
                file_semaphore=self.file_semaphore,
            ),
            util.fetch_url_json(
                self.card_asset_url.format(
                    assetbundleName=assetbundleName, scenarioId=story_2_scenarioId
                ),
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
                card_story_filename + ' 下篇',
                session=self.session,
                network_semaphore=self.network_semaphore,
                file_semaphore=self.file_semaphore,
            ),
        )

        if self.parse:
            text_1 = self.reader.read_story_in_json(story_1_json)
            text_2 = self.reader.read_story_in_json(story_2_json)

            with open(
                os.path.join(card_save_dir, card_story_filename) + '.txt',
                'w',
                encoding='utf8',
            ) as f:
                f.write(
                    f'{chara_name}{sub_unit_name}-{card_id_for_chara} {card_name}{belong_event}\n\n\n'
                )
                f.write(story_1_name + '\n\n')
                f.write(text_1 + '\n\n\n')
                f.write(story_2_name + '\n\n')
                f.write(text_2 + '\n')

        print(f'get card {card_story_filename} done.')


class Area_talk_getter((util.Base_getter)):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './area_talk',
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

        if reader.lang == 'cn':
            self.areas_url = URLS['cn']['sekai.best']['areas']
            self.actionSets_url = URLS['cn']['sekai.best']['actionSets']
            self.talk_asset_url = URLS['cn']['sekai.best']['talk_asset']
        elif reader.lang == 'jp':
            self.areas_url = URLS['jp']['sekai.best']['areas']
            self.actionSets_url = URLS['jp']['sekai.best']['actionSets']
            self.talk_asset_url = URLS['jp']['sekai.best']['talk_asset']
        elif reader.lang == 'tw':
            self.areas_url = URLS['tw']['sekai.best']['areas']
            self.actionSets_url = URLS['tw']['sekai.best']['actionSets']
            self.talk_asset_url = URLS['tw']['sekai.best']['talk_asset']
        else:
            raise NotImplementedError

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore, file_semaphore)

        self.area_name_json, self.info_json = await asyncio.gather(
            util.fetch_url_json(
                self.areas_url,
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
                session=self.session,
                network_semaphore=self.network_semaphore,
                file_semaphore=self.file_semaphore,
            ),
            util.fetch_url_json(
                self.actionSets_url,
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
                session=self.session,
                network_semaphore=self.network_semaphore,
                file_semaphore=self.file_semaphore,
            ),
        )

        self.area_name_lookup = DictLookup(self.area_name_json, 'id')
        self.info_json_lookup = DictLookup(self.info_json, 'id')

    async def get(self, target: int | str) -> None:
        '''
        target: int: event_id; str: grade1, grade2, theater, limited-{area_id}, aprilfool2022-
        '''
        if isinstance(target, int):  # event id
            talk_infos = [
                talk
                for talk in self.info_json
                if ('scenarioId' in talk)
                and (len(cond := str(talk['releaseConditionId'])) == 6)
                and (cond[0] == '1')
                and (int(cond[1:4]) == target - 1)
            ]
            if target == 145:
                talk_info_index = self.info_json_lookup.find_index(
                    2373
                )  # special for mzk5
                talk_infos.append(self.info_json[talk_info_index])
        elif target == 'grade1':
            talk_infos = [
                talk
                for talk in self.info_json
                if ('scenarioId' in talk)
                and (talk.get("actionSetType") == "normal")
                and (talk["isNextGrade"] == False)
                and (talk["releaseConditionId"] == 1)
            ]
        elif target == 'grade2':
            talk_infos = [
                talk
                for talk in self.info_json
                if ('scenarioId' in talk)
                and (talk.get("actionSetType") == "normal")
                and (talk["isNextGrade"] == True)
                and (talk["releaseConditionId"] == 1)
            ]
        elif target == 'theater':
            talk_infos = [
                talk
                for talk in self.info_json
                if ('scenarioId' in talk) and (talk["releaseConditionId"] >= 2000000)
            ]
        elif target.startswith('limited-'):
            area_id = int(target.split('-')[1])
            talk_infos = [
                talk
                for talk in self.info_json
                if ('scenarioId' in talk)
                and (talk.get("actionSetType") == "limited")
                and (talk['areaId'] == area_id)
                and ('aprilfool' not in talk['scenarioId'])
            ]
        elif target.startswith('aprilfool'):
            assert len(target) == 9 + 4
            talk_infos = [
                talk
                for talk in self.info_json
                if ('scenarioId' in talk)
                and (talk.get("actionSetType") == "limited")
                and ((target in talk['scenarioId']))
            ]
        else:
            raise NotImplementedError

        if len(talk_infos) == 0:
            print(f'talk {target} does not exist.')
            return

        if self.parse:
            os.makedirs(self.save_dir, exist_ok=True)

        tasks = []
        for talk_info in talk_infos:
            tasks.append(
                util.fetch_url_json(
                    self.talk_asset_url.format(
                        group=math.floor(talk_info['id'] / 100),
                        scenarioId=talk_info['scenarioId'],
                    ),
                    self.online,
                    self.save_assets,
                    self.assets_save_dir,
                    self.missing_download,
                    print_done=True,
                    session=self.session,
                    network_semaphore=self.network_semaphore,
                    file_semaphore=self.file_semaphore,
                )
            )

        talk_jsons = await asyncio.gather(*tasks)

        if self.parse:
            texts: list[str] = []
            for talk_json in talk_jsons:
                texts.append(self.reader.read_story_in_json(talk_json))

            if isinstance(target, int):  # event id
                filename = f'talk_event_{target}'
            else:
                filename = f'talk_{target}'

            if self.reader.lang != 'cn':
                filename = self.reader.lang + '-' + filename

            with open(
                os.path.join(self.save_dir, filename) + '.txt',
                'w',
                encoding='utf8',
            ) as f:
                for index, (talk_info, text) in enumerate(zip(talk_infos, texts)):
                    area_name_index = self.area_name_lookup.find_index(
                        talk_info['areaId']
                    )
                    area_name = self.area_name_json[area_name_index]['name']
                    sub_name = self.area_name_json[area_name_index].get('subName')
                    if sub_name is not None:
                        area_name += ' - ' + sub_name
                    f.write(f"{index+1}: {talk_info['id']} 【{area_name}】\n\n")
                    f.write(text + '\n\n\n')

        print(f'get talk {filename} done.')

    # for debug
    async def get_id(self, talk_id: int) -> None:
        talk_info_index = self.info_json_lookup.find_index(talk_id)
        if talk_info_index == -1:
            print(f'talk {talk_id} does not exist.')
            return

        talk_info = self.info_json[talk_info_index]

        if 'scenarioId' not in talk_info:
            print(f'talk {talk_id} does have content.')
            return

        if self.parse:
            os.makedirs(self.save_dir, exist_ok=True)

        talk_json = await util.fetch_url_json(
            self.talk_asset_url.format(
                group=math.floor(talk_id / 100), scenarioId=talk_info['scenarioId']
            ),
            self.online,
            self.save_assets,
            self.assets_save_dir,
            self.missing_download,
            session=self.session,
            network_semaphore=self.network_semaphore,
            file_semaphore=self.file_semaphore,
        )

        if self.parse:
            text = self.reader.read_story_in_json(talk_json)

            filename = f'talk_{talk_id}'
            if self.reader.lang != 'cn':
                filename = self.reader.lang + '-' + filename

            area_name_index = self.area_name_lookup.find_index(talk_info['areaId'])
            area_name = self.area_name_json[area_name_index]['name']
            sub_name = self.area_name_json[area_name_index].get('subName')
            if sub_name is not None:
                area_name += ' - ' + sub_name

            with open(
                os.path.join(self.save_dir, filename) + '.txt',
                'w',
                encoding='utf8',
            ) as f:
                f.write(f"{talk_info['id']} 【{area_name}】\n\n")
                f.write(text + '\n')

        print(f'get talk {talk_id} done.')


class DictLookup:
    def __init__(self, data: list[dict[str, Any]], attr_name: str):
        self.data = data
        self.ids = [int(d[attr_name]) for d in data]

    def find_index(self, target_id: int) -> int:
        left_index = bisect.bisect_left(self.ids, target_id)
        if left_index < len(self.ids) and self.ids[left_index] == target_id:
            return left_index
        return -1


if __name__ == '__main__':

    net_connect_limit = 20

    online = False

    reader = Story_reader('tw', online=online)
    unit_getter = Unit_story_getter(reader, online=online)
    event_getter = Event_story_getter(reader, online=online)
    card_getter = Card_story_getter(reader, online=online)
    area_getter = Area_talk_getter(reader, online=online)

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
            )

            tasks = []
            for i in range(1, 3):
                tasks.append(unit_getter.get(i))
            for i in range(1, 11):
                tasks.append(event_getter.get(i))
            for i in range(1, 11):
                tasks.append(card_getter.get(i))
            for i in range(1, 11):
                tasks.append(area_getter.get(i))

            await asyncio.gather(*tasks)

    asyncio.run(main())
