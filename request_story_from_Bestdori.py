# https://github.com/ci-ke/ProjectSekai-BangDream-story-crawler

import os, json, threading
from urllib.request import pathname2url
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any, Dict, Optional, Sequence

import requests  # type: ignore

### CONFIG
BASE_SAVE_DIR = r'.'

EVENT_SAVE_DIR = BASE_SAVE_DIR + r'\event_story'
BAND_SAVE_DIR = BASE_SAVE_DIR + r'\band_story'
MAIN_SAVE_DIR = BASE_SAVE_DIR + r'\main_story'
CARD_SAVE_DIR = BASE_SAVE_DIR + r'\card_story'

ASSET_SAVE_DIR = BASE_SAVE_DIR + r'\assets'

PROXY = None
# PROXY = {'http': 'http://127.0.0.1:10808', 'https': 'http://127.0.0.1:10808'}


### CONSTANT
LANG_INDEX = {'jp': 0, 'en': 1, 'tw': 2, 'cn': 3, 'kr': 4}

BAND_ID_NAME = {
    1: 'Poppin\'Party',
    2: 'Afterglow',
    3: 'Hello, Happy World!',
    4: 'Pastel＊Palettes',
    5: 'Roselia',
    18: 'RAISE A SUILEN',
    21: 'Morfonica',
    45: 'MyGO!!!!!',
}

CHARA_ID_BAND_AND_NAME = {
    1: 'PPP_户山香澄',
    2: 'PPP_花园多惠',
    3: 'PPP_牛込里美',
    4: 'PPP_山吹沙绫',
    5: 'PPP_市谷有咲',
    6: 'AG_美竹兰',
    7: 'AG_青叶摩卡',
    8: 'AG_上原绯玛丽',
    9: 'AG_宇田川巴',
    10: 'AG_羽泽鸫',
    11: 'HHW_弦卷心',
    12: 'HHW_濑田薰',
    13: 'HHW_北泽育美',
    14: 'HHW_松原花音',
    15: 'HHW_奥泽美咲-米歇尔',
    16: 'PP_丸山彩',
    17: 'PP_冰川日菜',
    18: 'PP_白鹭千圣',
    19: 'PP_大和麻弥',
    20: 'PP_若宫伊芙',
    21: 'Ro_凑友希那',
    22: 'Ro_冰川纱夜',
    23: 'Ro_今井莉莎',
    24: 'Ro_宇田川亚子',
    25: 'Ro_白金燐子',
    26: 'Mor_仓田真白',
    27: 'Mor_桐谷透子',
    28: 'Mor_广町七深',
    29: 'Mor_二叶筑紫',
    30: 'Mor_八潮瑠唯',
    31: 'RAS_和奏瑞依-LAYER',
    32: 'RAS_朝日六花-LOCK',
    33: 'RAS_佐藤益木-MASKING',
    34: 'RAS_鳰原令王那-PAREO',
    35: 'RAS_珠手知由-CHU²',
    36: 'Mygo_高松灯',
    37: 'Mygo_千早爱音',
    38: 'Mygo_要乐奈',
    39: 'Mygo_长崎爽世',
    40: 'Mygo_椎名立希',
}


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


def read_story_in_json(json_data: str | Dict[str, Dict[str, Any]]) -> str:
    if isinstance(json_data, str):
        return json_data

    ret = ''

    talks = json_data['Base']['talkData']
    specialEffects = json_data['Base']['specialEffectData']

    snippets = json_data['Base']['snippets']
    next_talk_need_newline = True

    for snippet in snippets:
        if snippet['actionType'] == SnippetAction.SpecialEffect:
            specialEffect = specialEffects[snippet['referenceIndex']]
            if specialEffect['effectType'] == SpecialEffectType.Telop:
                ret += '\n【' + specialEffect['stringVal'] + '】\n'
                next_talk_need_newline = True
            elif specialEffect['effectType'] == SpecialEffectType.FullScreenText:
                if next_talk_need_newline:
                    ret += '\n'
                ret += (
                    '（全屏幕文字）：'
                    + specialEffect['stringVal'].replace('\n', ' ')
                    + '\n'
                )
                next_talk_need_newline = False
            elif specialEffect['effectType'] == SpecialEffectType.SimpleSelectable:
                if next_talk_need_newline:
                    ret += '\n'
                ret += (
                    '（选项）：' + specialEffect['stringVal'].replace('\n', ' ') + '\n'
                )
                next_talk_need_newline = False
            elif specialEffect['effectType'] == SpecialEffectType.Movie:
                if next_talk_need_newline:
                    ret += '\n'
                ret += '（播放视频）\n'
                next_talk_need_newline = False
            elif specialEffect['effectType'] == SpecialEffectType.ChangeBackground:
                if next_talk_need_newline:
                    ret += '\n'
                ret += '（背景切换）\n'
                next_talk_need_newline = False
            elif specialEffect['effectType'] == SpecialEffectType.FlashbackIn:
                ret += '\n（回忆切入 ↓）\n'
                next_talk_need_newline = True
            elif specialEffect['effectType'] == SpecialEffectType.FlashbackOut:
                ret += '\n（回忆切出 ↑）\n'
                next_talk_need_newline = True
            elif specialEffect['effectType'] == SpecialEffectType.BlackOut:
                if next_talk_need_newline:
                    ret += '\n'
                ret += '（黑屏转场）\n'
                next_talk_need_newline = False
            elif specialEffect['effectType'] == SpecialEffectType.WhiteOut:
                if next_talk_need_newline:
                    ret += '\n'
                ret += '（白屏转场）\n'
                next_talk_need_newline = False
        elif snippet['actionType'] == SnippetAction.Talk:
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

    return ret[:-1]


class Event_story_getter:

    event_is_main = [217]
    event_no_story = [248]

    def __init__(
        self,
        online: bool = True,
        save: bool = False,
        parse: bool = True,
        missing_download: bool = True,
    ) -> None:

        self.online = online
        self.save = save
        self.parse = parse
        self.missing_download = missing_download

        self.info_url = 'https://bestdori.com/api/events/{event_id}.json'
        self.story_url = 'https://bestdori.com/assets/{lang}/scenario/eventstory/event{event_id}_rip/Scenario{id}.asset'

    def get(self, event_id: int, lang: str = 'cn') -> None:

        info_json: Dict[str, Any] = Util.get_url_json(
            self.info_url.format(event_id=event_id),
            self.online,
            self.save,
            self.missing_download,
        )

        event_name = info_json['eventName'][LANG_INDEX[lang]]
        if event_name is None:
            print(f'event {event_id} has no {lang.upper()}.')
            return

        event_filename = Util.valid_filename(event_name)

        save_folder_name = f'{event_id} {event_filename}'

        if lang != 'cn':
            save_folder_name = lang + '-' + save_folder_name

        event_save_dir = os.path.join(EVENT_SAVE_DIR, save_folder_name)

        if self.parse:
            os.makedirs(event_save_dir, exist_ok=True)

            if event_id in Event_story_getter.event_no_story:
                with open(
                    os.path.join(event_save_dir, '无剧情.txt'), 'w', encoding='utf8'
                ) as f:
                    f.write('本活动没有活动剧情\n')
                return

        for story in info_json['stories']:
            name = f"{story['scenarioId']} {story['caption'][LANG_INDEX[lang]]} {story['title'][LANG_INDEX[lang]]}"

            synopsis: str | None = story['synopsis'][LANG_INDEX[lang]]
            if synopsis is not None:  # for 13 20 23, jp meta lost
                synopsis = synopsis.replace('\n', ' ')

            id = story['scenarioId']

            filename = Util.valid_filename(name)

            if ('bandStoryId' not in story) and (
                event_id not in Event_story_getter.event_is_main
            ):
                story_json: Dict[str, Dict[str, Any]] = Util.get_url_json(
                    self.story_url.format(lang=lang, event_id=event_id, id=id),
                    self.online,
                    self.save,
                    self.missing_download,
                    filename,
                )

                if self.parse:
                    text = read_story_in_json(story_json)
                else:
                    text = ''
            elif event_id in Event_story_getter.event_is_main:
                text = '见主线故事'
            else:
                text = '见乐队故事'

            if self.parse:
                with open(
                    os.path.join(event_save_dir, filename) + '.txt',
                    'w',
                    encoding='utf8',
                ) as f:
                    f.write(name + '\n\n')
                    f.write(f'{synopsis}' + '\n\n')
                    f.write(text + '\n')

            print(f'get event {event_id} {event_name} {name} done.')


class Band_story_getter:
    def __init__(
        self,
        online: bool = True,
        save: bool = False,
        parse: bool = True,
        missing_download: bool = True,
    ) -> None:

        self.online = online
        self.save = save
        self.parse = parse
        self.missing_download = missing_download

        self.info_url = 'https://bestdori.com/api/misc/bandstories.5.json'
        self.story_url = 'https://bestdori.com/assets/{lang}/scenario/band/{band_id:03}_rip/Scenario{id}.asset'

    def get(
        self,
        want_band_id: Optional[int] = None,
        want_chapter_number: Optional[int] = None,
        lang: str = 'cn',
    ) -> None:
        if want_band_id is not None:
            assert want_band_id in BAND_ID_NAME

        info_json: Dict[str, Dict[str, Any]] = Util.get_url_json(
            self.info_url,
            self.online,
            self.save,
            self.missing_download,
        )

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

            band_name = BAND_ID_NAME[band_id]

            if band_story['mainTitle'][LANG_INDEX[lang]] == None:
                print(
                    f'band story {band_name} {band_story["mainTitle"][0]} {band_story["subTitle"][0]} has no {lang.upper()}.'
                )
                continue

            save_folder_name = Util.valid_filename(
                f'{band_story["mainTitle"][LANG_INDEX[lang]]} {band_story["subTitle"][LANG_INDEX[lang]]}'
            )
            if lang != 'cn':
                save_folder_name = lang + '-' + save_folder_name

            band_save_dir = os.path.join(BAND_SAVE_DIR, band_name, save_folder_name)
            if self.parse:
                os.makedirs(band_save_dir, exist_ok=True)

            for story in band_story['stories'].values():
                name = f"{story['scenarioId']} {story['caption'][LANG_INDEX[lang]]} {story['title'][LANG_INDEX[lang]]}"
                synopsis = story['synopsis'][LANG_INDEX[lang]].replace('\n', ' ')
                id = story['scenarioId']

                filename = Util.valid_filename(name)

                story_json: Dict[str, Dict[str, Any]] = Util.get_url_json(
                    self.story_url.format(lang=lang, band_id=band_id, id=id),
                    self.online,
                    self.save,
                    self.missing_download,
                    filename,
                )

                if self.parse:
                    text = read_story_in_json(story_json)

                    with open(
                        os.path.join(band_save_dir, filename) + '.txt',
                        'w',
                        encoding='utf8',
                    ) as f:
                        f.write(name + '\n\n')
                        f.write(synopsis + '\n\n')
                        f.write(text + '\n')

                print(
                    f'get band story {band_name} {band_story["mainTitle"][LANG_INDEX[lang]]} {name} done.'
                )


class Main_story_getter:
    def __init__(
        self,
        online: bool = True,
        save: bool = False,
        parse: bool = True,
        missing_download: bool = True,
    ) -> None:

        self.online = online
        self.save = save
        self.parse = parse
        self.missing_download = missing_download

        self.info_url = 'https://bestdori.com/api/misc/mainstories.5.json'
        self.story_url = (
            'https://bestdori.com/assets/{lang}/scenario/main_rip/Scenario{id}.asset'
        )

    def get(self, id_range: Optional[Sequence[int]] = None, lang: str = 'cn') -> None:
        info_json: Dict[str, Dict[str, Any]] = Util.get_url_json(
            self.info_url,
            self.online,
            self.save,
            self.missing_download,
        )

        if self.parse:
            os.makedirs(MAIN_SAVE_DIR, exist_ok=True)

        for strId, main_story in info_json.items():
            if id_range is not None and int(strId) not in id_range:
                continue

            if main_story['title'][LANG_INDEX[lang]] == None:
                print(
                    f'main story {main_story["caption"][0]} {main_story["title"][0]} has no {lang.upper()}.'
                )
                continue

            name = f"{main_story['scenarioId']} {main_story['caption'][LANG_INDEX[lang]]} {main_story['title'][LANG_INDEX[lang]]}"

            if lang != 'cn':
                name = lang + '-' + name

            filename = Util.valid_filename(name)

            synopsis = main_story['synopsis'][LANG_INDEX[lang]].replace('\n', ' ')
            id = main_story['scenarioId']

            story_json: Dict[str, Dict[str, Any]] = Util.get_url_json(
                self.story_url.format(lang=lang, id=id),
                self.online,
                self.save,
                self.missing_download,
                filename,
            )

            if self.parse:
                text = read_story_in_json(story_json)

                with open(
                    os.path.join(MAIN_SAVE_DIR, filename) + '.txt', 'w', encoding='utf8'
                ) as f:
                    f.write(name + '\n\n')
                    f.write(synopsis + '\n\n')
                    f.write(text + '\n')

            print(f'get main story {name} done.')


class Card_story_getter:
    def __init__(
        self,
        online: bool = True,
        save: bool = False,
        parse: bool = True,
        missing_download: bool = True,
    ) -> None:

        self.online = online
        self.save = save
        self.parse = parse
        self.missing_download = missing_download

        self.all_cards_list_url = 'https://bestdori.com/api/cards/all.0.json'
        self.info_url = 'https://bestdori.com/api/cards/{id}.json'
        self.story_url = 'https://bestdori.com/assets/{lang}/characters/resourceset/{res_id}_rip/Scenario{scenarioId}.asset'

        self.cards_ids: list[int] = [
            int(id)
            for id in Util.get_url_json(
                self.all_cards_list_url,
                self.online,
                self.save,
                self.missing_download,
            ).keys()
        ]

    def get(self, card_id: int, lang: str = 'cn') -> None:
        if card_id not in self.cards_ids:
            print(f'card {card_id} does not exist.')
            return

        card = Util.get_url_json(
            self.info_url.format(id=card_id),
            self.online,
            self.save,
            self.missing_download,
        )

        chara_band_and_name = CHARA_ID_BAND_AND_NAME[card['characterId']]
        chara_name = chara_band_and_name.split('_')[1]
        cardRarityType = card['rarity']
        card_name = card['prefix'][LANG_INDEX[lang]]

        if card_name is None:
            print(f'card {card_id} has no {lang.upper()}.')
            return

        resourceSetName: str = card['resourceSetName']

        card_story_filename = Util.valid_filename(
            f'{card_id}_{chara_name}_{cardRarityType}星 {card_name}'
        )

        if lang != 'cn':
            card_story_filename = lang + '-' + card_story_filename

        if 'episodes' not in card:
            card_has_story = False
            text_1 = ''
            text_2 = ''
        else:
            card_has_story = True

            story_1_name = card['episodes']['entries'][0]['title'][LANG_INDEX[lang]]
            story_2_name = card['episodes']['entries'][1]['title'][LANG_INDEX[lang]]

            story_1_type = card['episodes']['entries'][0]['episodeType']
            story_2_type = card['episodes']['entries'][1]['episodeType']

            if story_1_type != 'animation':
                scenarioId_1 = card['episodes']['entries'][0]['scenarioId']
                story_1_json: str | Dict[str, Dict[str, Any]] = Util.get_url_json(
                    self.story_url.format(
                        lang=lang, res_id=resourceSetName, scenarioId=scenarioId_1
                    ),
                    self.online,
                    self.save,
                    self.missing_download,
                    card_story_filename,
                )
            else:
                story_1_json = '动画故事'

            scenarioId_2 = card['episodes']['entries'][1]['scenarioId']
            story_2_json: Dict[str, Dict[str, Any]] = Util.get_url_json(
                self.story_url.format(
                    lang=lang, res_id=resourceSetName, scenarioId=scenarioId_2
                ),
                self.online,
                self.save,
                self.missing_download,
                card_story_filename,
            )

            if self.parse:
                text_1 = read_story_in_json(story_1_json)
                text_2 = read_story_in_json(story_2_json)
            else:
                text_1 = ''
                text_2 = ''

        if self.parse:
            card_save_dir = os.path.join(CARD_SAVE_DIR, chara_band_and_name)

            os.makedirs(card_save_dir, exist_ok=True)

            with open(
                os.path.join(card_save_dir, card_story_filename) + '.txt',
                'w',
                encoding='utf8',
            ) as f:
                if card_has_story:
                    f.write(f'{chara_name} {card_name}\n\n\n')
                    f.write(f'《{story_1_name}》' + '\n\n')
                    f.write(text_1 + '\n\n\n')
                    f.write(f'《{story_2_name}》' + '\n\n')
                    f.write(text_2 + '\n')
                else:
                    f.write('本卡面没有剧情\n')

        print(f'get card {card_story_filename} done.')


class Util:

    error_assets_file = 'error_assets.txt'
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
        url: str,
        auto_donwload: bool,
        extra_record_msg: str,
        record_error: bool,
        record_missing: bool,
    ) -> Any:
        path = Util.url_to_path(url)
        if os.path.exists(path):
            with open(path, encoding='utf8') as f:
                return json.load(f)
        else:
            if auto_donwload:
                return Util.get_url_json(
                    url,
                    True,
                    True,
                    False,
                    extra_record_msg,
                    record_error,
                    record_missing,
                )
            else:
                if record_missing:
                    if extra_record_msg:
                        Util.write_to_file(
                            Util.missing_assets_file, f'{extra_record_msg}：{url}'
                        )
                    else:
                        Util.write_to_file(Util.missing_assets_file, url)
                return '未能读取到json文件'

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
        extra_record_msg: str = '',
        record_error: bool = True,
        record_missing: bool = True,
    ) -> Any:
        if online:
            res = requests.get(url, proxies=PROXY)
            res.raise_for_status()
            try:
                json_content = res.json()
                if save:
                    Util.save_json_to_url(url, json_content)
            except Exception as e:
                json_content = f'读取json出错：{e}'
                if record_error:
                    if extra_record_msg:
                        Util.write_to_file(
                            Util.error_assets_file, f'{extra_record_msg}：{url}'
                        )
                    else:
                        Util.write_to_file(Util.error_assets_file, url)
        else:
            json_content = Util.read_json_from_url(
                url, missing_download, extra_record_msg, record_error, record_missing
            )

        return json_content


if __name__ == '__main__':

    online = False
    save = True
    parse = True
    missing_download = True

    m = Main_story_getter(
        online=online, save=save, parse=parse, missing_download=missing_download
    )
    b = Band_story_getter(
        online=online, save=save, parse=parse, missing_download=missing_download
    )
    e = Event_story_getter(
        online=online, save=save, parse=parse, missing_download=missing_download
    )
    c = Card_story_getter(
        online=online, save=save, parse=parse, missing_download=missing_download
    )

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures: list[Future[None]] = []
        future: Future[None]

        # future = executor.submit(m.get, None, 'cn')
        # futures.append(future)

        # future = executor.submit(m.get, None, 'jp')
        # futures.append(future)

        # for i in BAND_ID_NAME:
        #     future = executor.submit(b.get, i, None, 'cn')
        #     futures.append(future)

        # for i in BAND_ID_NAME:
        #     future = executor.submit(b.get, i, None, 'jp')
        #     futures.append(future)

        # for i in list(range(1, 301)) + [312, 313]:
        #     future = executor.submit(e.get, i, 'cn')
        #     futures.append(future)

        # for i in range(1, 323):
        #     future = executor.submit(e.get, i, 'jp')
        #     futures.append(future)

        # for i in range(1, 2253):
        #     future = executor.submit(c.get, i, 'cn')
        #     futures.append(future)

        # for i in range(1, 2403):
        #     future = executor.submit(c.get, i, 'jp')
        #     futures.append(future)

        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                print(f"Exception: {e}")
