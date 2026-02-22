# https://github.com/ci-ke/ProjectSekai-BangDream-story-crawler

import os
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any

import request_story_util as util


class Constant:
    lang_index = {'jp': 0, 'en': 1, 'tw': 2, 'cn': 3, 'kr': 4}

    band_id_name = {
        1: 'Poppin\'Party',
        2: 'Afterglow',
        3: 'Hello, Happy World!',
        4: 'Pastel＊Palettes',
        5: 'Roselia',
        18: 'RAISE A SUILEN',
        21: 'Morfonica',
        45: 'MyGO!!!!!',
    }

    chara_id_band_and_name = {
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


def read_story_in_json(
    json_data: str | dict[str, dict[str, Any]], debug_parse: bool = False
) -> str:
    if isinstance(json_data, str):
        return json_data

    ret = ''

    talks = json_data['Base']['talkData']
    specialEffects = json_data['Base']['specialEffectData']

    snippets = json_data['Base']['snippets']
    next_talk_need_newline = True

    index = -1
    for snippet in snippets:
        index += 1
        if snippet['actionType'] == util.SnippetAction.SpecialEffect:
            specialEffect = specialEffects[snippet['referenceIndex']]
            if specialEffect['effectType'] == util.SpecialEffectType.Telop:
                ret += '\n【' + specialEffect['stringVal'] + '】\n'
                next_talk_need_newline = True
            elif specialEffect['effectType'] == util.SpecialEffectType.ChangeBackground:
                if next_talk_need_newline:
                    ret += '\n'
                ret += "（背景切换）\n"
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
                if debug_parse:
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
            if debug_parse:
                try:
                    snippet_name = util.SnippetAction(snippet['actionType']).name
                except ValueError:
                    snippet_name = snippet['actionType']
                ret += f'SnippetAction: {snippet_name}, {index}\n'

    return ret[:-1]


class Event_story_getter:

    event_is_main = [217]
    event_no_story = [248]

    def __init__(
        self,
        save_dir: str = './event_story',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        debug_parse: bool = False,
    ) -> None:

        self.save_dir = save_dir
        self.assets_save_dir = assets_save_dir
        self.debug_parse = debug_parse

        self.online = online
        self.save_assets = save_assets
        self.parse = parse
        self.missing_download = missing_download

        self.info_url = 'https://bestdori.com/api/events/{event_id}.json'
        self.story_url = 'https://bestdori.com/assets/{lang}/scenario/eventstory/event{event_id}_rip/Scenario{id}.asset'

    def get(self, event_id: int, lang: str = 'cn') -> None:

        info_json: dict[str, Any] = util.get_url_json(
            self.info_url.format(event_id=event_id),
            self.online,
            self.save_assets,
            self.assets_save_dir,
            self.missing_download,
        )

        event_name = info_json['eventName'][Constant.lang_index[lang]]
        if event_name is None:
            print(f'event {event_id} has no {lang.upper()}.')
            return

        event_filename = util.valid_filename(event_name)

        save_folder_name = f'{event_id} {event_filename}'

        if lang != 'cn':
            save_folder_name = lang + '-' + save_folder_name

        event_save_dir = os.path.join(self.save_dir, save_folder_name)

        if self.parse:
            os.makedirs(event_save_dir, exist_ok=True)

            if event_id in Event_story_getter.event_no_story:
                with open(
                    os.path.join(event_save_dir, '无剧情.txt'), 'w', encoding='utf8'
                ) as f:
                    f.write('本活动没有活动剧情\n')
                return

        for story in info_json['stories']:
            name = f"{story['scenarioId']} {story['caption'][Constant.lang_index[lang]]} {story['title'][Constant.lang_index[lang]]}"

            synopsis: str | None = story['synopsis'][Constant.lang_index[lang]]
            if synopsis is not None:  # for 13 20 23, jp meta lost
                synopsis = synopsis.replace('\n', ' ')

            id = story['scenarioId']

            filename = util.valid_filename(name)

            if ('bandStoryId' not in story) and (
                event_id not in Event_story_getter.event_is_main
            ):
                story_json: dict[str, dict[str, Any]] = util.get_url_json(
                    self.story_url.format(lang=lang, event_id=event_id, id=id),
                    self.online,
                    self.save_assets,
                    self.assets_save_dir,
                    self.missing_download,
                    filename,
                )

                if self.parse:
                    text = read_story_in_json(story_json, self.debug_parse)
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
        save_dir: str = './band_story',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        debug_parse: bool = False,
    ) -> None:

        self.save_dir = save_dir
        self.assets_save_dir = assets_save_dir
        self.debug_parse = debug_parse

        self.online = online
        self.save_assets = save_assets
        self.parse = parse
        self.missing_download = missing_download

        self.info_url = 'https://bestdori.com/api/misc/bandstories.5.json'
        self.story_url = 'https://bestdori.com/assets/{lang}/scenario/band/{band_id:03}_rip/Scenario{id}.asset'

    def get(
        self,
        want_band_id: int | None = None,
        want_chapter_number: int | None = None,
        lang: str = 'cn',
    ) -> None:
        if want_band_id is not None:
            assert want_band_id in Constant.band_id_name

        info_json: dict[str, dict[str, Any]] = util.get_url_json(
            self.info_url,
            self.online,
            self.save_assets,
            self.assets_save_dir,
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

            band_name = Constant.band_id_name[band_id]

            if band_story['mainTitle'][Constant.lang_index[lang]] == None:
                print(
                    f'band story {band_name} {band_story["mainTitle"][0]} {band_story["subTitle"][0]} has no {lang.upper()}.'
                )
                continue

            save_folder_name = util.valid_filename(
                f'{band_story["mainTitle"][Constant.lang_index[lang]]} {band_story["subTitle"][Constant.lang_index[lang]]}'
            )
            if lang != 'cn':
                save_folder_name = lang + '-' + save_folder_name

            band_save_dir = os.path.join(self.save_dir, band_name, save_folder_name)
            if self.parse:
                os.makedirs(band_save_dir, exist_ok=True)

            for story in band_story['stories'].values():
                name = f"{story['scenarioId']} {story['caption'][Constant.lang_index[lang]]} {story['title'][Constant.lang_index[lang]]}"
                synopsis = story['synopsis'][Constant.lang_index[lang]].replace(
                    '\n', ' '
                )
                id = story['scenarioId']

                filename = util.valid_filename(name)

                story_json: dict[str, dict[str, Any]] = util.get_url_json(
                    self.story_url.format(lang=lang, band_id=band_id, id=id),
                    self.online,
                    self.save_assets,
                    self.assets_save_dir,
                    self.missing_download,
                    filename,
                )

                if self.parse:
                    text = read_story_in_json(story_json, self.debug_parse)

                    with open(
                        os.path.join(band_save_dir, filename) + '.txt',
                        'w',
                        encoding='utf8',
                    ) as f:
                        f.write(name + '\n\n')
                        f.write(synopsis + '\n\n')
                        f.write(text + '\n')

                print(
                    f'get band story {band_name} {band_story["mainTitle"][Constant.lang_index[lang]]} {name} done.'
                )


class Main_story_getter:
    def __init__(
        self,
        save_dir: str = './main_story',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        debug_parse: bool = False,
    ) -> None:

        self.save_dir = save_dir
        self.assets_save_dir = assets_save_dir
        self.debug_parse = debug_parse

        self.online = online
        self.save_assets = save_assets
        self.parse = parse
        self.missing_download = missing_download

        self.info_url = 'https://bestdori.com/api/misc/mainstories.5.json'
        self.story_url = (
            'https://bestdori.com/assets/{lang}/scenario/main_rip/Scenario{id}.asset'
        )

    def get(self, id_range: list[int] | None = None, lang: str = 'cn') -> None:
        info_json: dict[str, dict[str, Any]] = util.get_url_json(
            self.info_url,
            self.online,
            self.save_assets,
            self.assets_save_dir,
            self.missing_download,
        )

        if self.parse:
            os.makedirs(self.save_dir, exist_ok=True)

        for strId, main_story in info_json.items():
            if id_range is not None and int(strId) not in id_range:
                continue

            if main_story['title'][Constant.lang_index[lang]] == None:
                print(
                    f'main story {main_story["caption"][0]} {main_story["title"][0]} has no {lang.upper()}.'
                )
                continue

            name = f"{main_story['scenarioId']} {main_story['caption'][Constant.lang_index[lang]]} {main_story['title'][Constant.lang_index[lang]]}"

            if lang != 'cn':
                name = lang + '-' + name

            filename = util.valid_filename(name)

            synopsis = main_story['synopsis'][Constant.lang_index[lang]].replace(
                '\n', ' '
            )
            id = main_story['scenarioId']

            story_json: dict[str, dict[str, Any]] = util.get_url_json(
                self.story_url.format(lang=lang, id=id),
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
                filename,
            )

            if self.parse:
                text = read_story_in_json(story_json, self.debug_parse)

                with open(
                    os.path.join(self.save_dir, filename) + '.txt', 'w', encoding='utf8'
                ) as f:
                    f.write(name + '\n\n')
                    f.write(synopsis + '\n\n')
                    f.write(text + '\n')

            print(f'get main story {name} done.')


class Card_story_getter:
    def __init__(
        self,
        save_dir: str = './card_story',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        debug_parse: bool = False,
    ) -> None:

        self.save_dir = save_dir
        self.assets_save_dir = assets_save_dir
        self.debug_parse = debug_parse

        self.online = online
        self.save_assets = save_assets
        self.parse = parse
        self.missing_download = missing_download

        self.all_cards_list_url = 'https://bestdori.com/api/cards/all.0.json'
        self.info_url = 'https://bestdori.com/api/cards/{id}.json'
        self.story_url = 'https://bestdori.com/assets/{lang}/characters/resourceset/{res_id}_rip/Scenario{scenarioId}.asset'

        self.cards_ids: list[int] = [
            int(id)
            for id in util.get_url_json(
                self.all_cards_list_url,
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
            ).keys()
        ]

    def get(self, card_id: int, lang: str = 'cn') -> None:
        if card_id not in self.cards_ids:
            print(f'card {card_id} does not exist.')
            return

        card = util.get_url_json(
            self.info_url.format(id=card_id),
            self.online,
            self.save_assets,
            self.assets_save_dir,
            self.missing_download,
        )

        chara_band_and_name = Constant.chara_id_band_and_name[card['characterId']]
        chara_name = chara_band_and_name.split('_')[1]
        cardRarityType = card['rarity']
        card_name = card['prefix'][Constant.lang_index[lang]]

        if card_name is None:
            print(f'card {card_id} has no {lang.upper()}.')
            return

        resourceSetName: str = card['resourceSetName']

        card_story_filename = util.valid_filename(
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
                story_1_json: str | dict[str, dict[str, Any]] = util.get_url_json(
                    self.story_url.format(
                        lang=lang, res_id=resourceSetName, scenarioId=scenarioId_1
                    ),
                    self.online,
                    self.save_assets,
                    self.assets_save_dir,
                    self.missing_download,
                    card_story_filename,
                )
            else:
                story_1_json = '动画故事'

            scenarioId_2 = card['episodes']['entries'][1]['scenarioId']
            story_2_json: dict[str, dict[str, Any]] = util.get_url_json(
                self.story_url.format(
                    lang=lang, res_id=resourceSetName, scenarioId=scenarioId_2
                ),
                self.online,
                self.save_assets,
                self.assets_save_dir,
                self.missing_download,
                card_story_filename,
            )

            if self.parse:
                text_1 = read_story_in_json(story_1_json, self.debug_parse)
                text_2 = read_story_in_json(story_2_json, self.debug_parse)
            else:
                text_1 = ''
                text_2 = ''

        if self.parse:
            card_save_dir = os.path.join(self.save_dir, chara_band_and_name)

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


if __name__ == '__main__':

    online = True

    main_getter = Main_story_getter(online=online)
    band_getter = Band_story_getter(online=online)
    event_getter = Event_story_getter(online=online)
    card_getter = Card_story_getter(online=online)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures: list[Future[None]] = []

        # futures.append(executor.submit(main_getter.get, None, 'cn'))
        # futures.append(executor.submit(main_getter.get, None, 'jp'))

        # for i in Constant.band_id_name:
        #     futures.append(executor.submit(band_getter.get, i, None, 'cn'))
        # for i in Constant.band_id_name:
        #     futures.append(executor.submit(band_getter.get, i, None, 'jp'))

        # for i in list(range(1, 301)) + [312, 313]:
        #     futures.append(executor.submit(event_getter.get, i, 'cn'))
        # for i in range(1, 323):
        #     futures.append(executor.submit(event_getter.get, i, 'jp'))

        # for i in range(1, 2253):
        #     futures.append(executor.submit(card_getter.get, i, 'cn'))
        # for i in range(1, 2403):
        #     futures.append(executor.submit(card_getter.get, i, 'jp'))

        wait(futures)
        for future in futures:
            try:
                future.result()
            except Exception as e:
                print(f"Exception: {e}")
