# https://github.com/ci-ke/ProjectSekai-BangDream-story-crawler

import bisect, os, json, threading
from urllib.request import pathname2url
from enum import Enum
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed, Future

import requests  # type: ignore


### CONFIG
BASE_SAVE_DIR = r'.'

EVENT_SAVE_DIR = BASE_SAVE_DIR + r'\event_story'
UNIT_SAVE_DIR = BASE_SAVE_DIR + r'\unit_story'
CARD_SAVE_DIR = BASE_SAVE_DIR + r'\card_story'

ASSET_SAVE_DIR = BASE_SAVE_DIR + r'\assets'

PROXY = None
# PROXY = {'http': 'http://127.0.0.1:10808', 'https': 'http://127.0.0.1:10808'}

### CONSTANT
UNIT_ID_NAME = {
    1: '虚拟歌手',
    2: 'Leo/need',
    3: 'MORE MORE JUMP！',
    4: 'Vivid BAD SQUAD',
    5: 'Wonderlands×Showtime',
    6: '25点，Nightcord见。',
}

UNIT_CODE_NAME = {
    'light_sound': 'LN',
    'idol': 'MMJ',
    'street': 'VBS',
    'theme_park': 'WS',
    'school_refusal': '25时',
    'piapro': '虚拟歌手',
}

CHARA_ID_UNIT_AND_NAME = {
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

EXTRA_CHARA_ID_UNIT_AND_NAME_FOR_BANNER = {
    27: '虚拟歌手_初音未来（LN）',
    28: '虚拟歌手_初音未来（MMJ）',
    29: '虚拟歌手_初音未来（VBS）',
    30: '虚拟歌手_初音未来（WS）',
    31: '虚拟歌手_初音未来（25时）',
}

RARITY_NAME = {
    'rarity_1': '一星',
    'rarity_2': '二星',
    'rarity_3': '三星',
    'rarity_4': '四星',
    'rarity_birthday': '生日',
}


class Story_reader:

    # https://github.com/EternalFlower/Project-Sekai-Story-Parser/blob/main/PJSekai%20Story%20parser.py
    class SnippetAction(int, Enum):
        NoAction = 0
        Talk = 1
        CharacterLayout = 2
        InputName = 3
        CharacterMotion = 4
        Selectable = 5
        SpecialEffect = 6
        Sound = 7

    class SpecialEffectType(int, Enum):
        NoEffect = 0
        BlackIn = 1
        BlackOut = 2
        WhiteIn = 3
        WhiteOut = 4
        ShakeScreen = 5
        ShakeWindow = 6
        ChangeBackground = 7
        Telop = 8
        FlashbackIn = 9
        FlashbackOut = 10
        ChangeCardStill = 11
        AmbientColorNormal = 12
        AmbientColorEvening = 13
        AmbientColorNight = 14
        PlayScenarioEffect = 15
        StopScenarioEffect = 16
        ChangeBackgroundStill = 17
        PlaceInfo = 18
        Movie = 19
        SekaiIn = 20
        SekaiOut = 21
        AttachCharacterShader = 22
        SimpleSelectable = 23
        FullScreenText = 24
        StopShakeScreen = 25
        StopShakeWindow = 26

    def __init__(
        self,
        lang: str = 'cn',
        online: bool = True,
        save: bool = False,
        missing_download: bool = True,
    ) -> None:

        self.online = online
        self.save = save
        self.missing_download = missing_download

        self.lang = lang
        if lang == 'cn':
            character2ds_url = 'https://sekai-world.github.io/sekai-master-db-cn-diff/character2ds.json'
        elif lang == 'jp':
            character2ds_url = (
                'https://sekai-world.github.io/sekai-master-db-diff/character2ds.json'
            )
        elif lang == 'tw':
            character2ds_url = 'https://sekai-world.github.io/sekai-master-db-tc-diff/character2ds.json'
        else:
            raise NotImplementedError

        self.character2ds: list[dict[str, Any]] = Util.get_url_json(
            character2ds_url, self.online, self.save, self.missing_download
        )

        self.character2ds_lookup = DictLookup(self.character2ds, 'id')

    def read_story_in_json(self, json_data: dict[str, Any]) -> str:
        ret = ''

        talks = json_data['TalkData']
        specialEffects = json_data['SpecialEffectData']

        appearCharacters = json_data['AppearCharacters']
        chara_id = set()
        for chara in appearCharacters:
            chara2dId = chara['Character2dId']
            chara2d = self.character2ds[self.character2ds_lookup.find_index(chara2dId)]
            if chara2d['characterId'] in CHARA_ID_UNIT_AND_NAME:
                chara_id.add(chara2d['characterId'])
        chara_id_list = sorted(chara_id)

        if len(chara_id_list) > 0:
            ret += (
                '（登场角色：'
                + '、'.join(
                    [CHARA_ID_UNIT_AND_NAME[id].split('_')[1] for id in chara_id_list]
                )
                + '）\n\n'
            )

        snippets = json_data['Snippets']
        next_talk_need_newline = True

        for snippet in snippets:
            if snippet['Action'] == Story_reader.SnippetAction.SpecialEffect:
                specialEffect = specialEffects[snippet['ReferenceIndex']]
                if specialEffect['EffectType'] == Story_reader.SpecialEffectType.Telop:
                    ret += '\n【' + specialEffect['StringVal'] + '】\n'
                    next_talk_need_newline = True
                elif (
                    specialEffect['EffectType']
                    == Story_reader.SpecialEffectType.FullScreenText
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
                    == Story_reader.SpecialEffectType.SimpleSelectable
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += (
                        '（选项）：'
                        + specialEffect['StringVal'].replace('\n', ' ')
                        + '\n'
                    )
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType'] == Story_reader.SpecialEffectType.Movie
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += '（播放视频）\n'
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType']
                    == Story_reader.SpecialEffectType.ChangeBackground
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += '（背景切换）\n'
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType']
                    == Story_reader.SpecialEffectType.FlashbackIn
                ):
                    ret += '\n（回忆切入 ↓）\n'
                    next_talk_need_newline = True
                elif (
                    specialEffect['EffectType']
                    == Story_reader.SpecialEffectType.FlashbackOut
                ):
                    ret += '\n（回忆切出 ↑）\n'
                    next_talk_need_newline = True
                elif (
                    specialEffect['EffectType']
                    == Story_reader.SpecialEffectType.BlackOut
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += '（黑屏转场）\n'
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType']
                    == Story_reader.SpecialEffectType.WhiteOut
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += '（白屏转场）\n'
                    next_talk_need_newline = False
            elif snippet['Action'] == Story_reader.SnippetAction.Talk:
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

        return ret[:-1]


class Event_story_getter:
    def __init__(
        self,
        reader: Story_reader,
        src: str = 'sekai.best',
        online: bool = True,
        save: bool = False,
        parse: bool = True,
        missing_download: bool = True,
    ) -> None:
        '''
        src: sekai.best or snowy
        '''

        self.online = online
        self.save = save
        self.parse = parse
        self.missing_download = missing_download

        if reader.lang == 'cn':
            events_url = (
                'https://sekai-world.github.io/sekai-master-db-cn-diff/events.json'
            )
            eventStories_url = 'https://sekai-world.github.io/sekai-master-db-cn-diff/eventStories.json'
            self.asset_url = 'https://storage.sekai.best/sekai-cn-assets/event_story/{assetbundleName}/scenario/{scenarioId}.asset'
        elif reader.lang == 'jp':
            if src == 'sekai.best':
                events_url = (
                    'https://sekai-world.github.io/sekai-master-db-diff/events.json'
                )
                eventStories_url = 'https://sekai-world.github.io/sekai-master-db-diff/eventStories.json'
                self.asset_url = 'https://storage.sekai.best/sekai-jp-assets/event_story/{assetbundleName}/scenario/{scenarioId}.asset'
            elif src == 'snowy':
                events_url = 'https://sekaimaster.exmeaning.com/master/events.json'
                eventStories_url = (
                    'https://sekaimaster.exmeaning.com/master/eventStories.json'
                )
                self.asset_url = 'https://snowyassets.exmeaning.com/ondemand/event_story/{assetbundleName}/scenario/{scenarioId}.json'
            else:
                raise NotImplementedError
        elif reader.lang == 'tw':
            events_url = (
                'https://sekai-world.github.io/sekai-master-db-tc-diff/events.json'
            )
            eventStories_url = 'https://sekai-world.github.io/sekai-master-db-tc-diff/eventStories.json'
            self.asset_url = 'https://storage.sekai.best/sekai-tc-assets/event_story/{assetbundleName}/scenario/{scenarioId}.asset'
        else:
            raise NotImplementedError

        self.events_json: list[dict[str, Any]] = Util.get_url_json(
            events_url, self.online, self.save, self.missing_download
        )
        self.eventStories_json: list[dict[str, Any]] = Util.get_url_json(
            eventStories_url, self.online, self.save, self.missing_download
        )

        self.events_lookup = DictLookup(self.events_json, 'id')
        self.eventStories_lookup = DictLookup(self.eventStories_json, 'eventId')

        self.reader = reader

    def get(self, event_id: int) -> None:

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
                banner_name = f'{UNIT_CODE_NAME[event_unit]}_WL'
            else:
                banner_name = 'WL'
        else:
            assert banner_chara_id is not None
            banner_name = (
                CHARA_ID_UNIT_AND_NAME | EXTRA_CHARA_ID_UNIT_AND_NAME_FOR_BANNER
            )[banner_chara_id]

        event_filename = Util.valid_filename(event_name)
        save_folder_name = f'{event_id} {event_filename}（{banner_name}）'

        if self.reader.lang != 'cn':
            save_folder_name = self.reader.lang + '-' + save_folder_name

        event_save_dir = os.path.join(EVENT_SAVE_DIR, save_folder_name)
        if self.parse:
            os.makedirs(event_save_dir, exist_ok=True)

        for episode in eventStory['eventStoryEpisodes']:
            episode_name = (
                f"{episode['eventStoryId']}-{episode['episodeNo']} {episode['title']}"
            )
            if event_type == 'world_bloom':
                gameCharacterId = episode.get('gameCharacterId', -1)
                if gameCharacterId != -1:
                    chara_name = CHARA_ID_UNIT_AND_NAME[gameCharacterId].split('_')[1]
                    episode_name += f"（{chara_name}）"

            scenarioId = episode['scenarioId']

            filename = Util.valid_filename(episode_name)

            story_json: dict[str, Any] = Util.get_url_json(
                self.asset_url.format(
                    assetbundleName=assetbundleName, scenarioId=scenarioId
                ),
                self.online,
                self.save,
                self.missing_download,
                filename,
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


class Unit_story_getter:
    def __init__(
        self,
        reader: Story_reader,
        online: bool = True,
        save: bool = False,
        parse: bool = True,
        missing_download: bool = True,
    ) -> None:

        self.online = online
        self.save = save
        self.parse = parse
        self.missing_download = missing_download

        if reader.lang == 'cn':
            unitProfiles_url = 'https://sekai-world.github.io/sekai-master-db-cn-diff/unitProfiles.json'
            unitStories_url = (
                'https://sekai-world.github.io/sekai-master-db-cn-diff/unitStories.json'
            )
            self.asset_url = 'https://storage.sekai.best/sekai-cn-assets/scenario/unitstory/{assetbundleName}/{scenarioId}.asset'
        elif reader.lang == 'jp':
            unitProfiles_url = (
                'https://sekai-world.github.io/sekai-master-db-diff/unitProfiles.json'
            )
            unitStories_url = (
                'https://sekai-world.github.io/sekai-master-db-diff/unitStories.json'
            )
            self.asset_url = 'https://storage.sekai.best/sekai-jp-assets/scenario/unitstory/{assetbundleName}/{scenarioId}.asset'
        elif reader.lang == 'tw':
            unitProfiles_url = 'https://sekai-world.github.io/sekai-master-db-tc-diff/unitProfiles.json'
            unitStories_url = (
                'https://sekai-world.github.io/sekai-master-db-tc-diff/unitStories.json'
            )
            self.asset_url = 'https://storage.sekai.best/sekai-tc-assets/scenario/unitstory/{assetbundleName}/{scenarioId}.asset'
        else:
            raise NotImplementedError

        self.unitProfiles_json: list[dict[str, Any]] = Util.get_url_json(
            unitProfiles_url, self.online, self.save, self.missing_download
        )
        self.unitStories_json: list[dict[str, Any]] = Util.get_url_json(
            unitStories_url, self.online, self.save, self.missing_download
        )

        self.reader = reader

    def get(self, unit_id: int) -> None:
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

        unit_filename = Util.valid_filename(unitName)
        save_folder_name = f'{unit_id} {unit_filename}'

        if self.reader.lang != 'cn':
            save_folder_name = self.reader.lang + '-' + save_folder_name

        unit_save_dir = os.path.join(UNIT_SAVE_DIR, save_folder_name)
        if self.parse:
            os.makedirs(unit_save_dir, exist_ok=True)

        for episode in episodes:
            scenarioId = episode['scenarioId']
            episode_name = f"{scenarioId} {episode['title']}"

            filename = Util.valid_filename(episode_name)

            story_json: dict[str, Any] = Util.get_url_json(
                self.asset_url.format(
                    assetbundleName=assetbundleName, scenarioId=scenarioId
                ),
                self.online,
                self.save,
                self.missing_download,
                filename,
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


class Card_story_getter:
    def __init__(
        self,
        reader: Story_reader,
        online: bool = True,
        save: bool = False,
        parse: bool = True,
        missing_download: bool = True,
    ) -> None:

        self.online = online
        self.save = save
        self.parse = parse
        self.missing_download = missing_download

        if reader.lang == 'cn':
            cards_url = (
                'https://sekai-world.github.io/sekai-master-db-cn-diff/cards.json'
            )
            cardEpisodes_url = 'https://sekai-world.github.io/sekai-master-db-cn-diff/cardEpisodes.json'
            eventCards_url = (
                'https://sekai-world.github.io/sekai-master-db-cn-diff/eventCards.json'
            )
            self.asset_url = 'https://storage.sekai.best/sekai-cn-assets/character/member/{assetbundleName}/{scenarioId}.asset'
        elif reader.lang == 'jp':
            cards_url = 'https://sekai-world.github.io/sekai-master-db-diff/cards.json'
            cardEpisodes_url = (
                'https://sekai-world.github.io/sekai-master-db-diff/cardEpisodes.json'
            )
            eventCards_url = (
                'https://sekai-world.github.io/sekai-master-db-diff/eventCards.json'
            )
            self.asset_url = 'https://storage.sekai.best/sekai-jp-assets/character/member/{assetbundleName}/{scenarioId}.asset'
        elif reader.lang == 'tw':
            cards_url = (
                'https://sekai-world.github.io/sekai-master-db-tc-diff/cards.json'
            )
            cardEpisodes_url = 'https://sekai-world.github.io/sekai-master-db-tc-diff/cardEpisodes.json'
            eventCards_url = (
                'https://sekai-world.github.io/sekai-master-db-tc-diff/eventCards.json'
            )
            self.asset_url = 'https://storage.sekai.best/sekai-tc-assets/character/member/{assetbundleName}/{scenarioId}.asset'
        else:
            raise NotImplementedError

        self.cards_json: list[dict[str, Any]] = Util.get_url_json(
            cards_url, self.online, self.save, self.missing_download
        )
        self.cardEpisodes_json: list[dict[str, Any]] = Util.get_url_json(
            cardEpisodes_url, self.online, self.save, self.missing_download
        )
        ori_eventCards_json: list[dict[str, Any]] = Util.get_url_json(
            eventCards_url, self.online, self.save, self.missing_download
        )

        self.eventCards_json: list[dict[str, Any]] = []
        for item in ori_eventCards_json:
            if item['isDisplayCardStory']:
                self.eventCards_json.append(item)

        self.cards_lookup = DictLookup(self.cards_json, 'id')
        self.cardEpisodes_lookup = DictLookup(self.cardEpisodes_json, 'cardId')
        self.eventCards_lookup = DictLookup(self.eventCards_json, 'cardId')

        self.reader = reader

    def get(self, card_id: int) -> None:
        card_index = self.cards_lookup.find_index(card_id)
        cardEpisode_index = self.cardEpisodes_lookup.find_index(card_id)

        if (card_index == -1) or (cardEpisode_index == -1):
            print(f'card {card_id} does not exist.')
            return

        card = self.cards_json[card_index]
        cardEpisode_1 = self.cardEpisodes_json[cardEpisode_index]
        cardEpisode_2 = self.cardEpisodes_json[cardEpisode_index + 1]

        chara_unit_and_name = CHARA_ID_UNIT_AND_NAME[card['characterId']]
        chara_name = chara_unit_and_name.split('_')[1]
        cardRarityType = RARITY_NAME[card['cardRarityType']]
        card_name = card['prefix']
        sub_unit = card['supportUnit']
        assetbundleName: str = card['assetbundleName']
        card_id_for_chara = int(assetbundleName.split('_')[1][2:])

        story_1_name = cardEpisode_1['title']
        story_2_name = cardEpisode_2['title']
        story_1_scenarioId = cardEpisode_1['scenarioId']
        story_2_scenarioId = cardEpisode_2['scenarioId']

        card_save_dir = os.path.join(CARD_SAVE_DIR, chara_unit_and_name)
        if self.parse:
            os.makedirs(card_save_dir, exist_ok=True)

        if sub_unit != 'none':
            sub_unit_name = f'（{UNIT_CODE_NAME[sub_unit]}）'
        else:
            sub_unit_name = ''

        card_event_index = self.eventCards_lookup.find_index(card_id)
        if card_event_index == -1:
            belong_event = ''
        else:
            belong_event = (
                f"（event-{self.eventCards_json[card_event_index]['eventId']}）"
            )

        card_story_filename = Util.valid_filename(
            f'{card_id}_{chara_name}{sub_unit_name}_{card_id_for_chara}_{cardRarityType} {card_name}{belong_event}'
        )

        if self.reader.lang != 'cn':
            card_story_filename = self.reader.lang + '-' + card_story_filename

        story_1_json: dict[str, Any] = Util.get_url_json(
            self.asset_url.format(
                assetbundleName=assetbundleName, scenarioId=story_1_scenarioId
            ),
            self.online,
            self.save,
            self.missing_download,
            card_story_filename + ' 上篇',
        )
        story_2_json: dict[str, Any] = Util.get_url_json(
            self.asset_url.format(
                assetbundleName=assetbundleName, scenarioId=story_2_scenarioId
            ),
            self.online,
            self.save,
            self.missing_download,
            card_story_filename + ' 下篇',
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


class DictLookup:
    def __init__(self, data: list[dict[str, Any]], attr_name: str):
        self.data = data
        self.ids = [int(d[attr_name]) for d in data]

    def find_index(self, target_id: int) -> int:
        left_index = bisect.bisect_left(self.ids, target_id)
        if left_index < len(self.ids) and self.ids[left_index] == target_id:
            return left_index
        return -1


class Util:

    missing_assets_file = 'missing_assets.txt'

    @staticmethod
    def valid_filename(filename: str) -> str:
        return (
            filename.strip()
            .replace('*', '＊')
            .replace(':', '：')
            .replace('/', '／')
            .replace('?', '？')
            .replace('"', "''")
            .replace('\n', ' ')
        )

    @staticmethod
    def url_to_path(url: str) -> str:
        url_path = url[url.index('//') + 2 :]
        return os.path.normpath(os.path.join(ASSET_SAVE_DIR, url_path))

    @staticmethod
    def path_to_url(path: str) -> str:
        path_url = pathname2url(path)
        base_path = os.path.normpath(os.path.join(BASE_SAVE_DIR, ASSET_SAVE_DIR))
        return 'https:/' + path_url[path_url.index(base_path) + len(base_path) :]

    @staticmethod
    def save_json_to_url(url: str, content: Any) -> None:
        path = Util.url_to_path(url)
        os.makedirs(os.path.split(path)[0], exist_ok=True)
        with open(path, 'w', encoding='utf8') as f:
            json.dump(content, f, ensure_ascii=False)

    @staticmethod
    def read_json_from_url(
        url: str, auto_donwload: bool, record_missing: bool, extra_missing_msg: str
    ) -> Any:
        path = Util.url_to_path(url)
        if os.path.exists(path):
            with open(path, encoding='utf8') as f:
                return json.load(f)
        else:
            if auto_donwload:
                res = requests.get(url, proxies=PROXY)
                res.raise_for_status()
                json_content = res.json()
                Util.save_json_to_url(url, json_content)
                return json_content
            else:
                if record_missing:
                    if extra_missing_msg:
                        Util.write_to_file(
                            Util.missing_assets_file, f'{extra_missing_msg}：{url}'
                        )
                    else:
                        Util.write_to_file('missing_assets.txt', url)
                return None

    file_lock = threading.Lock()

    @staticmethod
    def write_to_file(file_path: str, content: str) -> None:
        with Util.file_lock:
            with open(file_path, 'a', encoding='utf-8', newline='') as f:
                f.write(f"{content}\n")
                f.flush()

    @staticmethod
    def get_url_json(
        url: str,
        online: bool,
        save: bool,
        missing_download: bool,
        extra_missing_msg: str = '',
    ) -> Any:
        if online:
            res = requests.get(url, proxies=PROXY)
            res.raise_for_status()
            json_content = res.json()
            if save:
                Util.save_json_to_url(url, json_content)
        else:
            json_content = Util.read_json_from_url(
                url,
                missing_download,
                record_missing=True,
                extra_missing_msg=extra_missing_msg,
            )

        return json_content


if __name__ == '__main__':

    online = True
    save = True
    parse = True

    reader = Story_reader('cn', online=online, save=save)

    unit_getter = Unit_story_getter(reader, online=online, save=save, parse=parse)
    event_getter = Event_story_getter(reader, online=online, save=save, parse=parse)
    card_getter = Card_story_getter(reader, online=online, save=save, parse=parse)

    with ThreadPoolExecutor(max_workers=20) as executor:

        futures: list[Future[None]] = []
        future: Future[None]

        # for i in range(1, 7):
        #     future = executor.submit(unit_getter.get, i)
        #     futures.append(future)
        # for i in range(1, 196):
        #     future = executor.submit(event_getter.get, i)
        #     futures.append(future)
        # # 1-107 initial card, 724-759 2nd grade card
        # for i in range(1, 1339):
        #     future = executor.submit(card_getter.get, i)

        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                print(f"Exception: {e}")
