import os, math, asyncio, json, re, logging
from pathlib import Path
from asyncio import Semaphore
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any, Callable, Optional, TypedDict, cast

from aiohttp import ClientSession, TCPConnector

from . import util
from .util import Mark_multi_lang


class Constant:
    unit_code_abbr = {
        'light_sound': 'Ln',
        'idol': 'MMJ',
        'street': 'VBS',
        'theme_park': 'WxS',
        'school_refusal': 'N25',
        'piapro': 'VS',
        'none': 'none',
        'mix': 'Mix',
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

    urls: dict[str, dict[str, Any]] = json.load(
        open(Path(__file__).parent / 'config.json', encoding='utf8')
    )['urls_pjsk']

    @staticmethod
    def get_srcs_url(
        lang: str, srcs: list[str], file_type: str, file: str
    ) -> list[util.UrlSpec]:
        '''
        lang: cn jp tw

        file_type: master or asset

        返回的 note 是 config 中的 key（asset 的 note 用于查对应 *_ext_replace）。
        '''
        base_urls: list[util.UrlSpec] = []
        for src in srcs:
            if lang not in Constant.urls[src]['master_lang']:
                continue
            if file_type == 'master':
                base_url: str = Constant.urls[src]['master']
                base_urls.append(
                    util.UrlSpec(
                        base_url.format(
                            lang=Constant.urls[src]['master_lang'][lang], file=file
                        ),
                        note=file,
                    )
                )
            else:
                sp_key = f'{file}_asset_{lang}'
                if not sp_key in Constant.urls[src]:
                    if f'{file}_asset' in Constant.urls[src]:
                        base_url = Constant.urls[src][f'{file}_asset']
                        base_urls.append(
                            util.UrlSpec(
                                base_url.format(
                                    lang=Constant.urls[src]['asset_lang'][lang]
                                ),
                                note=f'{file}_asset',
                            )
                        )
                else:
                    base_urls.append(
                        util.UrlSpec(Constant.urls[src][sp_key], note=sp_key)
                    )
        assert len(base_urls) > 0
        return base_urls


class Pjsk_fetcher(util.Base_fetcher):
    @staticmethod
    def __url_to_save_path(url: str, lang: str, note: str) -> str:
        '''按各源 config 的 save_roots 把 URL 映射为缓存相对路径。

        基址模板里的 {master_lang}/{asset_lang} 用剧本语言对应的站内语言填充；
        存盘根模板里的 {lang} 始终是剧本语言（如 tw 在 sekai.best 取 tc 资产，
        缓存仍落 pjsk-tw-assets）。note 是 get_srcs_url 给出的 config key，
        asset 组据此查对应的 *_ext_replace。
        '''
        for src in Constant.urls.values():
            master_lang = cast(dict[str, str], src['master_lang'])
            asset_lang = cast(dict[str, str], src['asset_lang'])
            if lang not in master_lang or lang not in asset_lang:
                continue
            url_langs: dict[str, str] = {
                'master_lang': master_lang[lang],
                'asset_lang': asset_lang[lang],
            }
            save_roots = cast(dict[str, dict[str, str]], src['save_roots'])
            for file_type, roots in save_roots.items():
                for base_tmpl, root_tmpl in roots.items():
                    base = base_tmpl.format(**url_langs)
                    if not url.startswith(base):
                        continue
                    rel_path = url[len(base) :]
                    if file_type == 'asset':
                        ext_replace = cast(
                            dict[str, str], src.get(f'{note}_ext_replace', {})
                        )
                        for old_ext, new_ext in ext_replace.items():
                            if rel_path.endswith(old_ext):
                                rel_path = rel_path[: -len(old_ext)] + new_ext
                                break
                    return os.path.normpath(
                        os.path.join(root_tmpl.format(lang=lang), rel_path)
                    )
        raise RuntimeError(url)

    async def fetch_url_json(
        self,
        url: util.UrlParam,
        extra_record_msg: str = '',
        print_done: bool = False,
        append_save_path: str | None = None,
        compress: bool = False,
        force_online: bool = False,
        force_local: bool = False,
        skip_read: bool = False,
        content_save_edit: Callable | None = None,
        format: str = 'json',
        bypass_urls: frozenset[str] | None = None,
        lang_for_path: str | None = None,
    ) -> Any:
        assert append_save_path is None

        lang_for_path = (
            lang_for_path
            or getattr(getattr(self, 'reader', None), 'lang', None)
            or getattr(self, 'lang', None)
        )
        assert lang_for_path is not None

        urls = util.normalize_urls(url)
        append_save_path = Pjsk_fetcher.__url_to_save_path(
            urls[0].url, lang_for_path, urls[0].note
        )

        return await super().fetch_url_json(
            urls,
            extra_record_msg,
            print_done,
            append_save_path=append_save_path,
            compress=compress,
            force_online=force_online,
            force_local=force_local,
            skip_read=skip_read,
            content_save_edit=content_save_edit,
            format=format,
            bypass_urls=bypass_urls,
        )


class Pjsk_getter(Pjsk_fetcher, util.Base_getter):
    pass


class Story_reader(Pjsk_fetcher):
    def __init__(
        self,
        lang: str = 'cn',
        src: list[str] = ['sekai.best'],
        assets_save_dir: str = '.',
        online: bool = True,
        save_assets: bool = True,
        missing_download: bool = True,
        mark_lang: str = 'cn',
        debug_parse: bool = False,
        cg_add_link: bool = True,
        force_master_online: bool = False,
        **args,
    ) -> None:
        util.warn_extra_args(self, args)
        super().__init__(
            assets_save_dir,
            online,
            save_assets,
            missing_download,
            False,
            force_master_online,
        )

        self.lang = lang
        self.mark_lang = mark_lang
        self.debug_parse = debug_parse
        self.cg_add_link = cg_add_link

        #self.cg_link = f'https://sekai-assets-bdf29c81.seiunx.net/{self.lang}-assets/ondemand/scenario/background/{{pic_name}}/{{pic_name}}.png'
        self.cg_link = 'https://storage.sekai.best/sekai-jp-assets/scenario/background/{pic_name}/{pic_name}.webp'

        self.gameCharacters_url = Constant.get_srcs_url(
            lang, src, 'master', 'gameCharacters'
        )
        self.character2ds_url = Constant.get_srcs_url(
            lang, src, 'master', 'character2ds'
        )
        self.gameCharacterUnits_url = Constant.get_srcs_url(
            lang, src, 'master', 'gameCharacterUnits'
        )
        self.events_url = Constant.get_srcs_url(lang, src, 'master', 'events')

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore)

        (
            self.gameCharacters,
            self.character2ds,
            self.gameCharacterUnits,
            self.events_json,
        ) = await asyncio.gather(
            self.fetch_url_json(
                self.gameCharacters_url, force_online=self.force_master_online
            ),
            self.fetch_url_json(
                self.character2ds_url, force_online=self.force_master_online
            ),
            self.fetch_url_json(
                self.gameCharacterUnits_url, force_online=self.force_master_online
            ),
            self.fetch_url_json(self.events_url, force_online=self.force_master_online),
        )

        self.gameCharacters_lookup = util.DictLookup(self.gameCharacters, 'id')
        self.character2ds_lookup = util.DictLookup(self.character2ds, 'id')

    def get_chara_unitAbbr_names(self, chara_id: int) -> tuple[str, str, str]:
        profile_index = self.gameCharacters_lookup.find_index(chara_id)
        assert profile_index != -1
        profile: dict[str, Any] = self.gameCharacters[profile_index]
        first_name = profile.get('firstName')
        givenName: str = profile['givenName']
        unit_abbr = Constant.unit_code_abbr[profile['unit']]
        if self.lang != 'en':
            full_name: str = (
                (first_name + givenName) if first_name is not None else givenName
            )
        else:
            if unit_abbr == 'VS':
                full_name = (
                    (first_name + ' ' + givenName)
                    if first_name is not None
                    else givenName
                )
            else:
                full_name = (
                    (givenName + ' ' + first_name)
                    if first_name is not None
                    else givenName
                )

        return (unit_abbr, full_name.strip(), givenName.strip())

    def get_chara2d_unitAbbr_names_isVS(
        self, chara2dId: int
    ) -> tuple[str, str, str, bool]:
        chara2d = self.character2ds[self.character2ds_lookup.find_index(chara2dId)]
        if chara2d['characterType'] != 'game_character':
            return '', '', '', False
        actual_unit = chara2d['unit']
        chara_id = chara2d['characterId']
        chara_unit, fullname, givenname = self.get_chara_unitAbbr_names(chara_id)
        if chara_unit != 'VS':
            return chara_unit, fullname, givenname, False
        else:
            return Constant.unit_code_abbr[actual_unit], fullname, givenname, True

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
            if chara2d['characterType'] == 'game_character':
                chara_id.add(chara2d['characterId'])
        chara_id_list = sorted(chara_id)

        if len(chara_id_list) > 0:
            ret0 = (
                Mark_multi_lang['characters'][self.mark_lang]
                + Mark_multi_lang[','][self.mark_lang].join(
                    [self.get_chara_unitAbbr_names(id)[1] for id in chara_id_list]
                )
                + Mark_multi_lang[')'][self.mark_lang]
            )
        else:
            ret0 = ''

        snippets = json_data['Snippets']
        next_talk_need_newline = True

        ret = ''
        for snippet in snippets:
            snippet_index = snippet['Index']
            if self.debug_parse:
                ret += f"{snippet_index},{snippet['ReferenceIndex']},"

            if snippet['Action'] == util.SnippetAction.SpecialEffect:
                specialEffect = specialEffects[snippet['ReferenceIndex']]
                if specialEffect['EffectType'] == util.SpecialEffectType.Telop:
                    ret += (
                        '\n'
                        + Mark_multi_lang['['][self.mark_lang]
                        + specialEffect['StringVal']
                        + Mark_multi_lang[']'][self.mark_lang]
                        + '\n'
                    )
                    next_talk_need_newline = True
                elif specialEffect['EffectType'] == util.SpecialEffectType.PlaceInfo:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += f"{Mark_multi_lang['place'][self.mark_lang]}{specialEffect['StringVal']}{Mark_multi_lang[')'][self.mark_lang]}\n"
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType'] == util.SpecialEffectType.FullScreenText
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += (
                        Mark_multi_lang['fullscreen text'][self.mark_lang]
                        + util.newlines_to_spaces(specialEffect['StringVal'])
                        + '\n'
                    )
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType']
                    == util.SpecialEffectType.SimpleSelectable
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += f"{Mark_multi_lang['selection'][self.mark_lang]}{specialEffect['StringVal']}{Mark_multi_lang[')'][self.mark_lang]}\n"
                    next_talk_need_newline = False
                elif specialEffect['EffectType'] == util.SpecialEffectType.Movie:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += f"{Mark_multi_lang['video'][self.mark_lang]}{specialEffect['StringVal']}{Mark_multi_lang[')'][self.mark_lang]}\n"
                    next_talk_need_newline = False
                elif specialEffect['EffectType'] == util.SpecialEffectType.PlayMV:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += f"{Mark_multi_lang['mv'][self.mark_lang]}{specialEffect['IntVal']}{Mark_multi_lang[')'][self.mark_lang]}\n"
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType']
                    == util.SpecialEffectType.ChangeBackground
                ):
                    if next_talk_need_newline:
                        ret += '\n'
                    pic_name = specialEffect['StringVal']
                    if Constant.is_cg(pic_name):
                        if not self.cg_add_link:
                            ret += f"{Mark_multi_lang['cg'][self.mark_lang]}{pic_name}{Mark_multi_lang[')'][self.mark_lang]}\n"
                        else:
                            ret += f"{Mark_multi_lang['cg'][self.mark_lang]}{self.cg_link.format(pic_name=pic_name)}{Mark_multi_lang[')'][self.mark_lang]}\n"
                    else:
                        ret += (
                            Mark_multi_lang['background'][self.mark_lang]
                            + (f': {pic_name}' if self.debug_parse else '')
                            + '\n'
                        )
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType']
                    == util.SpecialEffectType.ChangeCardStill
                ):
                    # 卡面立绘全屏插入，按插入 CG 输出（与 bang.py 同步；注意 pjsk 字段为
                    # 大写驼峰。当前 ProSeka 语料无此特效，为枚举语义完备而保留）
                    if next_talk_need_newline:
                        ret += '\n'
                    pic = specialEffect['StringVal']
                    if specialEffect.get('StringValSub'):
                        # 分隔符统一用英文逗号，不随标记语言本地化
                        pic += ', ' + specialEffect['StringValSub']
                    ret += f"{Mark_multi_lang['cg'][self.mark_lang]}{pic}{Mark_multi_lang[')'][self.mark_lang]}\n"
                    next_talk_need_newline = False
                elif (
                    specialEffect['EffectType']
                    == util.SpecialEffectType.ChangeBackgroundStill
                ):
                    # 静止图背景切换，以 ：Still 后缀与 7 号普通背景区分（与 bang.py 同步；
                    # 当前 ProSeka 语料无此特效，为枚举语义完备而保留）
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += (
                        Mark_multi_lang['background'][self.mark_lang]
                        + Mark_multi_lang[':'][self.mark_lang]
                        + 'Still'
                        + '\n'
                    )
                    next_talk_need_newline = False
                elif specialEffect['EffectType'] == util.SpecialEffectType.FlashbackIn:
                    ret += '\n' + Mark_multi_lang['memory in'][self.mark_lang] + '\n'
                    next_talk_need_newline = True
                elif specialEffect['EffectType'] == util.SpecialEffectType.FlashbackOut:
                    ret += '\n' + Mark_multi_lang['memory out'][self.mark_lang] + '\n'
                    next_talk_need_newline = True
                elif specialEffect['EffectType'] == util.SpecialEffectType.BlackOut:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += Mark_multi_lang['black out'][self.mark_lang] + '\n'
                    next_talk_need_newline = False
                elif specialEffect['EffectType'] == util.SpecialEffectType.WhiteOut:
                    if next_talk_need_newline:
                        ret += '\n'
                    ret += Mark_multi_lang['white out'][self.mark_lang] + '\n'
                    next_talk_need_newline = False
                else:
                    if self.debug_parse:
                        try:
                            effect_name = util.SpecialEffectType(
                                specialEffect['EffectType']
                            ).name
                        except ValueError:
                            effect_name = specialEffect['EffectType']
                        ret += f"SpecialEffect-{effect_name}: {specialEffect}\n"

            elif snippet['Action'] == util.SnippetAction.Talk:
                talk = talks[snippet['ReferenceIndex']]

                talk_chara2did = talk['TalkCharacters'][0]['Character2dId']
                unit, speaker_fullname, speaker_shortname, isVS = (
                    self.get_chara2d_unitAbbr_names_isVS(talk_chara2did)
                )
                if isVS and unit not in (
                    'VS',
                    'none',
                ):  # none for some VS in chara2D, like card 335
                    need_unit_annotation = True
                else:
                    need_unit_annotation = False

                displayname = util.newlines_to_spaces(talk['WindowDisplayName'])

                if len(speaker_fullname) > 0 and (
                    displayname not in (speaker_fullname, speaker_shortname)
                ):
                    name = (
                        displayname
                        + util.Mark_multi_lang['('][self.mark_lang]
                        + speaker_shortname
                        + (f'-{unit}' if need_unit_annotation else '')
                        + util.Mark_multi_lang[')'][self.mark_lang]
                    )
                else:
                    name = displayname + (
                        (
                            util.Mark_multi_lang['('][self.mark_lang]
                            + unit
                            + util.Mark_multi_lang[')'][self.mark_lang]
                        )
                        if need_unit_annotation
                        else ''
                    )

                if next_talk_need_newline:
                    ret += '\n'
                ret += (
                    name
                    + Mark_multi_lang[':'][self.mark_lang]
                    + util.newlines_to_spaces(talk['Body'])
                    + '\n'
                )
                next_talk_need_newline = False
            else:
                if self.debug_parse:
                    try:
                        snippet_name = util.SnippetAction(snippet['Action']).name
                    except ValueError:
                        snippet_name = snippet['Action']
                    ret += f"{snippet_name}\n"

        return (ret0 + '\n\n' + ret.strip()).strip()


class Event_story_getter(Pjsk_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: list[str] = ['sekai.best'],
        save_dir: str = '.',
        assets_save_dir: str = '.',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_eventId_episode: tuple[int, int] = (3, 2),
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        util.warn_extra_args(self, args)
        super().__init__(
            os.path.join(save_dir, 'story_{lang}', 'event'),
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )

        self.reader = reader
        self.save_dir = self.save_dir.format(lang=self.reader.lang)

        self.maxlen_eventId_episode = maxlen_eventId_episode

        self.eventStories_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'eventStories'
        )
        self.event_asset_url = Constant.get_srcs_url(
            self.reader.lang, src, 'asset', 'event'
        )

        self.actionSets_jp_url = Constant.get_srcs_url(
            'jp', src, 'master', 'actionSets'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore)

        self.eventStories_json, actionSets_jp = await asyncio.gather(
            self.fetch_url_json(
                self.eventStories_url, force_online=self.force_master_online
            ),
            self.fetch_url_json(
                self.actionSets_jp_url,
                lang_for_path='jp',
                force_online=self.force_master_online,
            ),
        )

        util.apply_patches(self.eventStories_json, 'pjsk_eventStories')

        self.events_json = self.reader.events_json

        self.gameCharacterUnits = self.reader.gameCharacterUnits

        self.events_lookup = util.DictLookup(self.events_json, 'id')
        self.eventStories_lookup = util.DictLookup(self.eventStories_json, 'eventId')
        self.gameCharacterUnits_lookup = util.DictLookup(self.gameCharacterUnits, 'id')

        event_type_map_base = {
            1: 'band',
            2: 'night',
            3: 'wonder',
            4: 'shuffle',
            5: 'idol',
            6: 'street',
            7: 'shuffle',
            8: 'wonder',
            9: 'shuffle',
            10: 'band',
            11: 'idol',
            12: 'street',
            13: 'shuffle',
            14: 'night',
            15: 'wonder',
            16: 'shuffle',
            17: 'idol',
            18: 'shuffle',
            19: 'night',
            20: 'band',
            21: 'street',
            22: 'shuffle',
            23: 'idol',
            24: 'shuffle',
            25: 'wonder',
            26: 'night',
            27: 'band',
            28: 'street',
            29: 'shuffle',
            30: 'shuffle',
            31: 'idol',
            32: 'wonder',
            33: 'shuffle',
            34: 'band',
            35: 'night',
            36: 'shuffle',
            37: 'street',
            38: 'wonder',
            39: 'night',
            40: 'band',
            41: 'shuffle',
            42: 'shuffle',
            43: 'idol',
            44: 'street',
            45: 'shuffle',
            46: 'wonder',
            47: 'night',
            48: 'shuffle',
            49: 'street',
            50: 'band',
            51: 'shuffle',
            52: 'idol',
            53: 'night',
            54: 'shuffle',
            55: 'wonder',
            56: 'band',
            57: 'idol',
            58: 'shuffle',
            59: 'street',
            60: 'shuffle',
            61: 'night',
            62: 'wonder',
            63: 'shuffle',
            64: 'street',
            65: 'band',
            66: 'shuffle',
            67: 'idol',
            68: 'night',
            69: 'band',
            70: 'shuffle',
            71: 'street',
            72: 'shuffle',
            73: 'idol',
            74: 'wonder',
            75: 'shuffle',
            76: 'band',
            77: 'night',
            78: 'idol',
            79: 'street',
            80: 'shuffle',
            81: 'shuffle',
            82: 'wonder',
            83: 'band',
            84: 'shuffle',
            85: 'idol',
            86: 'street',
            87: 'shuffle',
            88: 'wonder',
            89: 'night',
            90: 'shuffle',
            91: 'band',
            92: 'idol',
            93: 'night',
            94: 'shuffle',
            95: 'wonder',
            96: 'shuffle',
            97: 'street',
            98: 'idol',
            99: 'shuffle',
            100: 'night',
            101: 'band',
            102: 'shuffle',
            103: 'street',
            104: 'wonder',
            105: 'shuffle',
            106: 'shuffle',
            107: 'shuffle',
            108: 'shuffle',
            109: 'street',
            110: 'band',
            111: 'idol',
            112: 'night',
            113: 'wonder',
            114: 'shuffle',
            115: 'shuffle',
            116: 'night',
            117: 'shuffle',
            118: 'street',
            119: 'wonder',
            120: 'shuffle',
            121: 'band',
            122: 'idol',
            123: 'shuffle',
            124: 'wonder',
            125: 'street',
            126: 'shuffle',
            127: 'night',
            128: 'band',
            129: 'street',
            130: 'idol',
            131: 'wonder',
            132: 'shuffle',
            133: 'idol',
            134: 'night',
            135: 'street',
            136: 'wonder',
            137: 'band',
            138: 'idol',
            139: 'shuffle',
            140: 'piapro',
            141: 'shuffle',
            142: 'shuffle',
            143: 'band',
            144: 'shuffle',
            145: 'night',
            146: 'street',
            147: 'band',
            148: 'shuffle',
            149: 'wonder',
            150: 'night',
            151: 'idol',
            152: 'shuffle',
            153: 'shuffle',
            154: 'street',
            155: 'shuffle',
            156: 'shuffle',
            157: 'idol',
            158: 'shuffle',
            159: 'shuffle',
            160: 'shuffle',
            161: 'night',
            162: 'band',
            163: 'street',
            164: 'wonder',
            165: 'night',
            167: 'wonder',
            168: 'idol',
            169: 'street',
            170: 'night',
            171: 'band',
            172: 'wonder',
            173: 'band',
            174: 'idol',
            175: 'street',
            176: 'idol',
            177: 'night',
            178: 'wonder',
            179: 'piapro',
            180: 'finale',
            181: 'shuffle',
            182: 'band',
            183: 'idol',
            184: 'night',
            185: 'wonder',
            187: 'street',
            188: 'band',
            189: 'shuffle',
            190: 'idol',
            191: 'shuffle',
            192: 'night',
            193: 'street',
            194: 'shuffle',
            195: 'band',
            196: 'wonder',
            197: 'shuffle',
            198: 'idol',
            199: 'night',
            200: 'wonder',
            201: 'street',
            202: 'shuffle',
            203: 'band',
            204: 'street',
            205: 'shuffle',
            206: 'shuffle',
            207: 'shuffle',
            208: 'wonder',
            209: 'idol',
            210: 'night',
            211: 'shuffle',
            212: 'band',
            213: 'idol',
            214: 'shuffle',
            215: 'shuffle',
            216: 'street',
            217: 'wonder',
            218: 'finale',
            219: 'shuffle',
            220: 'band',
        }

        event_type_map_update = Event_story_getter.__get_event_type_map(actionSets_jp)

        self.event_type_map = event_type_map_update | event_type_map_base

    @staticmethod
    def __get_event_type_map(actionSets: list[dict[str, Any]]) -> dict[int, str]:
        ret = {}

        ret[1] = 'band'
        ret[5] = 'idol'
        ret[6] = 'street'
        ret[9] = 'shuffle'

        ret[16] = 'shuffle'  # areatalk_ev_wonder_03_006 is 101508(=16)

        for action in actionSets:
            releaseConditionId = str(action['releaseConditionId'])
            is_event = (
                ('scenarioId' in action)
                and (
                    'areatalk_ev' in action['scenarioId']
                    or 'areatalk_wl' in action['scenarioId']
                )
                and (len(releaseConditionId) == 6)
                and (releaseConditionId[0] == '1')
            )
            if is_event:
                event_id = int(releaseConditionId[1:4]) + 1
                scenarioId: str = action['scenarioId']
                event_type = scenarioId.split('_')[2]
                is_wl = scenarioId.split('_')[1] == 'wl'
                if event_id not in ret:
                    if False and is_wl:
                        ret[event_id] = event_type + '_' + 'wl'
                    else:
                        ret[event_id] = event_type
        return ret

    __type_str_code_map = {
        'band': 'light_sound',
        'idol': 'idol',
        'street': 'street',
        'wonder': 'theme_park',
        'night': 'school_refusal',
        'piapro': 'piapro',
    }

    def get_event_unit_abbr(self, event_id: int) -> str:
        try:
            type_str = self.event_type_map[event_id]
        except KeyError:
            return ''
        return Constant.unit_code_abbr[
            Event_story_getter.__type_str_code_map.get(type_str, 'mix')
        ]

    async def get(
        self, event_id: int, timestamp13: int | None = util.LATE_TIMESTAMP13
    ) -> None:
        '''
        timestamp13: 只抓 startAt <= timestamp13 的 event
        （None 为不过滤；默认 util.LATE_TIMESTAMP13 = now + 365 天：
        未来一年内纳入，超远未来（一年以上）不抓）
        '''
        event_index = self.events_lookup.find_index(event_id)
        eventStory_index = self.eventStories_lookup.find_index(event_id)

        if (event_index == -1) or (eventStory_index == -1):
            logging.info(f'event {event_id} does not exist.')
            return

        event = self.events_json[event_index]
        if timestamp13 is not None and event['startAt'] > timestamp13:
            logging.info(f'event {event_id} does not exist.')
            return

        eventStory: dict[str, Any] = self.eventStories_json[eventStory_index]

        event_name = event['name']
        event_type = event['eventType']
        # event_unit = event['unit']
        assetbundleName = event['assetbundleName']
        banner_chara_unit_id = eventStory.get('bannerGameCharacterUnitId')
        event_outline = util.newlines_to_spaces(eventStory['outline'])

        event_unit_abbr = self.get_event_unit_abbr(event_id)

        if event_unit_abbr != '':
            if event_type == 'world_bloom':
                banner_name = f'{event_unit_abbr}_WL'
            else:
                assert banner_chara_unit_id is not None
                banner_chara_unit_index = self.gameCharacterUnits_lookup.find_index(
                    banner_chara_unit_id
                )
                assert banner_chara_unit_index != -1
                chara_unit, banner_chara_name, _ = self.reader.get_chara_unitAbbr_names(
                    self.gameCharacterUnits[banner_chara_unit_index]['gameCharacterId']
                )
                if chara_unit == 'VS':
                    banner_chara_name += (
                        '-'
                        + Constant.unit_code_abbr[
                            self.gameCharacterUnits[banner_chara_unit_index]['unit']
                        ]
                    )
                banner_name = f'{event_unit_abbr}_{banner_chara_name}'

            save_folder_name = util.valid_filename(
                f'{event_id:0{self.maxlen_eventId_episode[0]}} {event_name} ({banner_name})',
                True,
            )
        else:
            save_folder_name = util.valid_filename(
                f'{event_id:0{self.maxlen_eventId_episode[0]}} {event_name}', True
            )

        event_save_dir = os.path.join(self.save_dir, save_folder_name)
        if self.parse:
            os.makedirs(Path(event_save_dir).parent, exist_ok=True)
            util.remove_olds_or_rename_old(event_save_dir, r'(\d+) ')
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
            + '.txt'
        )

        if event_type == 'world_bloom':
            gameCharacterId = episode.get('gameCharacterId', -1)
            if gameCharacterId != -1:
                chara_name = self.reader.get_chara_unitAbbr_names(gameCharacterId)[1]
                episode_name += f" ({chara_name})"
                episode_save_name = util.valid_filename(
                    episode_save_name[:-4] + f" ({chara_name})" + '.txt'
                )

        scenarioId = episode['scenarioId']

        story_json: dict[str, Any] = await self.fetch_url_json(
            [
                url.format(assetbundleName=assetbundleName, scenarioId=scenarioId)
                for url in self.event_asset_url
            ],
            episode_name,
            compress=self.compress_assets,
            skip_read=not self.parse,
        )

        if self.parse and not util.judge_need_skip(story_json):
            text = self.reader.read_story_in_json(story_json)

            file_path = os.path.join(event_save_dir, episode_save_name)
            util.remove_olds_or_rename_old(file_path, r'(\d+-\d+) ')
            with open(file_path, 'w', encoding='utf8') as f:
                if episode['episodeNo'] == 1:
                    f.write(event_outline + '\n\n')
                f.write(episode_name + '\n\n')
                f.write(text + '\n')

        logging.info(f'get event {event_id} {event_name} {episode_name} done.')

    async def get_newest(
        self,
        quantity: int = 1,
        timestamp13: int | None = util.LATE_TIMESTAMP13,
        area_getter: Optional['Area_talk_getter'] = None,
        exclude_new: int | None = None,
    ) -> None:
        '''
        quantity 0 = all
        '''
        old_events: list[tuple[int, int]] = []

        for event in self.events_json:
            if timestamp13 is None or event['startAt'] <= timestamp13:
                old_events.append((event['startAt'], event['id']))

        new_events = sorted(old_events)[-quantity:]
        new_eventids = [x[1] for x in new_events]

        if exclude_new:
            new_eventids = new_eventids[:-exclude_new]

        tasks = []
        for i in new_eventids:
            # id 层已按 timestamp13 筛过，get 内过滤传 None 关闭
            tasks.append(self.get(i, timestamp13=None))
            if area_getter is not None:
                tasks.append(area_getter.get(i, timestamp13=timestamp13))
        await asyncio.gather(*tasks)

    def tell_ids(self, timestamp13: int | None = None) -> list[int]:
        '''timestamp13: 只返回 startAt <= timestamp13 的事件 id（None 为全部）'''
        ret = []
        for event in self.events_json:
            if timestamp13 is None or event['startAt'] <= timestamp13:
                ret.append(event['id'])
        return ret


class Unit_story_getter(Pjsk_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: list[str] = ['sekai.best'],
        save_dir: str = '.',
        assets_save_dir: str = '.',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_unitId: int = 1,
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        util.warn_extra_args(self, args)
        super().__init__(
            os.path.join(save_dir, 'story_{lang}', 'main'),
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )

        self.reader = reader
        self.save_dir = self.save_dir.format(lang=self.reader.lang)
        self.maxlen_unitId = maxlen_unitId

        self.unitProfiles_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'unitProfiles'
        )

        self.unitStoryEpisodeGroups_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'unitStoryEpisodeGroups'
        )

        self.unitStories_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'unitStories'
        )
        self.unit_asset_url = Constant.get_srcs_url(
            self.reader.lang, src, 'asset', 'unit'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore)

        (
            self.unitProfiles_json,
            self.unitStoryEpisodeGroups_json,
            self.unitStories_json,
        ) = await asyncio.gather(
            self.fetch_url_json(
                self.unitProfiles_url, force_online=self.force_master_online
            ),
            self.fetch_url_json(
                self.unitStoryEpisodeGroups_url, force_online=self.force_master_online
            ),
            self.fetch_url_json(
                self.unitStories_url, force_online=self.force_master_online
            ),
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
            logging.info(f'unit {unit_id} does not exist.')
            return

        for unitStory in self.unitStories_json:
            if unitStory['seq'] == unit_id:
                assetbundleName = unitStory['chapters'][0]['assetbundleName']
                episodes = unitStory['chapters'][0]['episodes']
                break
        else:
            logging.info(f'unit {unit_id} does not exist.')
            return

        save_folder_name = util.valid_filename(
            f'{unit_id:0{self.maxlen_unitId}} {unitName}', True
        )

        unit_save_dir = os.path.join(self.save_dir, save_folder_name)
        if self.parse:
            os.makedirs(Path(unit_save_dir).parent, exist_ok=True)
            util.remove_olds_or_rename_old(unit_save_dir, r'(\d+) ')
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
            unit_outline = util.newlines_to_spaces(
                self.unitStoryEpisodeGroups_json[
                    self.unitStoryEpisodeGroups_lookup.find_index(
                        unitStoryEpisodeGroupId
                    )
                ]['outline']
            )
        else:
            unit_outline = None

        episode_save_name = util.valid_filename(episode_name + '.txt')

        story_json: dict[str, Any] = await self.fetch_url_json(
            [
                url.format(assetbundleName=assetbundleName, scenarioId=scenarioId)
                for url in self.unit_asset_url
            ],
            episode_name,
            compress=self.compress_assets,
            skip_read=not self.parse,
        )

        if self.parse and not util.judge_need_skip(story_json):
            text = self.reader.read_story_in_json(story_json)

            file_path = os.path.join(unit_save_dir, episode_save_name)
            util.remove_olds_or_rename_old(file_path, r'([^\s]+) ')
            with open(file_path, 'w', encoding='utf8') as f:
                if unit_outline is not None:
                    f.write(unit_outline + '\n\n')
                f.write(episode_name + '\n\n')
                f.write(text + '\n')

        logging.info(f'get unit {unit_id} {unitName} {episode_name} done.')

    def tell_ids(self) -> list[int]:
        ret = []
        for unitProfile in self.unitProfiles_json:
            ret.append(unitProfile['seq'])
        return ret


class Card_story_getter(Pjsk_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: list[str] = ['sekai.best'],
        save_dir: str = '.',
        assets_save_dir: str = '.',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_charaId_cardId: tuple[int, int] = (2, 4),
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        util.warn_extra_args(self, args)
        super().__init__(
            os.path.join(save_dir, 'story_{lang}', 'card'),
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )

        self.reader = reader
        self.save_dir = self.save_dir.format(lang=self.reader.lang)
        self.maxlen_charaId_cardId = maxlen_charaId_cardId

        self.cards_url = Constant.get_srcs_url(self.reader.lang, src, 'master', 'cards')
        self.cardEpisodes_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'cardEpisodes'
        )
        self.eventCards_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'eventCards'
        )
        self.card_asset_url = Constant.get_srcs_url(
            self.reader.lang, src, 'asset', 'card'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore)

        self.cards_json, self.cardEpisodes_json, ori_eventCards_json = (
            await asyncio.gather(
                self.fetch_url_json(
                    self.cards_url, force_online=self.force_master_online
                ),
                self.fetch_url_json(
                    self.cardEpisodes_url, force_online=self.force_master_online
                ),
                self.fetch_url_json(
                    self.eventCards_url, force_online=self.force_master_online
                ),
            )
        )

        self.eventCards_json: list[dict[str, Any]] = []
        for item in ori_eventCards_json:
            if item['isDisplayCardStory']:
                self.eventCards_json.append(item)

        self.cards_lookup = util.DictLookup(self.cards_json, 'id')
        self.cardEpisodes_lookup = util.DictLookup(self.cardEpisodes_json, 'cardId')
        self.eventCards_lookup = util.DictLookup(self.eventCards_json, 'cardId')

    async def get(
        self, card_id: int, timestamp13: int | None = util.LATE_TIMESTAMP13
    ) -> None:
        '''
        timestamp13: 只抓 releaseAt <= timestamp13 的卡片
        （None 为不过滤；默认 util.LATE_TIMESTAMP13 = now + 365 天：
        未来一年内纳入，超远未来（一年以上）不抓）
        '''
        card_index = self.cards_lookup.find_index(card_id)
        cardEpisode_index = self.cardEpisodes_lookup.find_index(card_id)

        if (card_index == -1) or (cardEpisode_index == -1):
            logging.info(f'card {card_id} does not exist.')
            return

        card: dict[str, Any] = self.cards_json[card_index]
        if timestamp13 is not None and card['releaseAt'] > timestamp13:
            logging.info(f'card {card_id} does not exist.')
            return

        cardEpisode_1 = self.cardEpisodes_json[cardEpisode_index]
        cardEpisode_2 = self.cardEpisodes_json[cardEpisode_index + 1]

        chara_unit_and_name = '_'.join(
            self.reader.get_chara_unitAbbr_names(card['characterId'])[:2]
        )
        chara_name = self.reader.get_chara_unitAbbr_names(card['characterId'])[1]
        cardRarityType = Constant.rarity_name[card['cardRarityType']]
        card_name = card['prefix']
        skill_name = card['cardSkillName']
        special_skill_name = card.get('specialTrainingSkillName', None)
        card_gachaPhrase = card.get('gachaPhrase', '-').replace(
            '\n', ' '
        )  # some have no gachaPhrase in tw
        sub_unit = card['supportUnit']
        assetbundleName: str = card['assetbundleName']

        story_1_name = cardEpisode_1['title']
        story_2_name = cardEpisode_2['title']
        story_1_scenarioId = cardEpisode_1['scenarioId']
        story_2_scenarioId = cardEpisode_2['scenarioId']

        card_save_dir = os.path.join(
            self.save_dir,
            util.valid_filename(
                f"{card['characterId']:0{self.maxlen_charaId_cardId[0]}} {chara_unit_and_name}",
                True,
            ),
        )

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
            f'{card_id:0{self.maxlen_charaId_cardId[1]}}_{chara_name}{sub_unit_name}_{cardRarityType} {card_name}{belong_event}'
            + '.txt'
        )

        story_1_json, story_2_json = await asyncio.gather(
            self.fetch_url_json(
                [
                    url.format(
                        assetbundleName=assetbundleName, scenarioId=story_1_scenarioId
                    )
                    for url in self.card_asset_url
                ],
                card_story_name + ' part1',
                compress=self.compress_assets,
                skip_read=not self.parse,
            ),
            self.fetch_url_json(
                [
                    url.format(
                        assetbundleName=assetbundleName, scenarioId=story_2_scenarioId
                    )
                    for url in self.card_asset_url
                ],
                card_story_name + ' part2',
                compress=self.compress_assets,
                skip_read=not self.parse,
            ),
        )

        if self.parse and not util.judge_need_skip(story_1_json, story_2_json):
            os.makedirs(Path(card_save_dir).parent, exist_ok=True)
            util.remove_olds_or_rename_old(card_save_dir, r'(\d+) ')
            os.makedirs(card_save_dir, exist_ok=True)

            text_1 = self.reader.read_story_in_json(story_1_json)
            text_2 = self.reader.read_story_in_json(story_2_json)

            file_path = os.path.join(card_save_dir, card_story_filename)
            util.remove_olds_or_rename_old(file_path, r'(\d+)_')
            with open(file_path, 'w', encoding='utf8') as f:
                f.write(card_story_name + '\n\n')
                f.write(
                    Mark_multi_lang['skill name'][self.reader.mark_lang] + skill_name
                )
                if special_skill_name:
                    f.write(' / ' + special_skill_name)
                if card_gachaPhrase != '-':
                    f.write(
                        '\n'
                        + Mark_multi_lang['gacha phrase'][self.reader.mark_lang]
                        + card_gachaPhrase
                    )
                f.write(
                    '\n\n'
                    + Mark_multi_lang['<'][self.reader.mark_lang]
                    + story_1_name
                    + Mark_multi_lang['>'][self.reader.mark_lang]
                    + '\n\n'
                )
                f.write(text_1 + '\n\n\n')
                f.write(
                    Mark_multi_lang['<'][self.reader.mark_lang]
                    + story_2_name
                    + Mark_multi_lang['>'][self.reader.mark_lang]
                    + '\n\n'
                )
                f.write(text_2 + '\n')

        logging.info(f'get card {card_story_name} done.')

    async def get_event(self, event_id: int) -> None:
        newest_event_id = self.eventCards_json[-1]['eventId']
        if event_id > newest_event_id + 1:
            return

        if event_id == 0:
            start_cardid = 1
            end_cardid = self.eventCards_json[0]['cardId'] - 1
        elif event_id == 1:
            event_cardids = [
                card['cardId']
                for card in self.eventCards_json
                if card['eventId'] == event_id
            ]
            start_cardid = event_cardids[0]
            end_cardid = event_cardids[-1]
        elif event_id == newest_event_id + 1:
            start_cardid = self.eventCards_json[-1]['cardId'] + 1
            end_cardid = self.cardEpisodes_json[-1]['cardId']
        else:
            last_event_cardids: list[int] = []
            forward_i = 1
            while len(last_event_cardids) == 0 and (event_id - forward_i > 0):
                last_event_cardids = [
                    card['cardId']
                    for card in self.eventCards_json
                    if card['eventId'] == event_id - forward_i
                ]
                forward_i += 1
            start_cardid = last_event_cardids[-1] + 1

            event_cardids = [
                card['cardId']
                for card in self.eventCards_json
                if card['eventId'] == event_id
            ]

            if len(event_cardids) > 0:
                end_cardid = event_cardids[-1]
            else:
                return

        tasks = []
        for i in range(start_cardid, end_cardid + 1):
            tasks.append(self.get(i))
        await asyncio.gather(*tasks)

    async def get_newest(
        self,
        quantity: int = 1,
        timestamp13: int | None = util.LATE_TIMESTAMP13,
        exclude_new: int | None = None,
    ) -> None:
        '''
        quantity 0 = all
        '''
        old_cards: list[tuple[int, int]] = []

        for card in self.cards_json:
            if timestamp13 is None or card['releaseAt'] <= timestamp13:
                old_cards.append((card['releaseAt'], card['id']))

        new_cards = sorted(old_cards)[-quantity:]
        new_cardids = [x[1] for x in new_cards]

        if exclude_new:
            new_cardids = new_cardids[:-exclude_new]

        tasks = []
        for i in new_cardids:
            # id 层已按 timestamp13 筛过，get 内过滤传 None 关闭
            tasks.append(self.get(i, timestamp13=None))
        await asyncio.gather(*tasks)

    def tell_ids(self, timestamp13: int | None = None) -> list[int]:
        '''timestamp13: 只返回 releaseAt <= timestamp13 的卡片 id（None 为全部）'''
        ret = []
        for card in self.cards_json:
            if timestamp13 is None or card['releaseAt'] <= timestamp13:
                ret.append(card['id'])
        return ret


class Area_talk_getter(Pjsk_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: list[str] = ['sekai.best'],
        save_dir: str = '.',
        assets_save_dir: str = '.',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_eventId_areaID: tuple[int, int] = (3, 2),
        print_fetch_detial: bool = False,
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        util.warn_extra_args(self, args)
        super().__init__(
            os.path.join(save_dir, 'story_{lang}', 'area'),
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )

        self.reader = reader
        self.save_dir = self.save_dir.format(lang=self.reader.lang)
        self.maxlen_eventId_areaID = maxlen_eventId_areaID
        self.print_fetch_detial = print_fetch_detial

        self.areas_url = Constant.get_srcs_url(self.reader.lang, src, 'master', 'areas')
        self.actionSets_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'actionSets'
        )
        self.talk_asset_url = Constant.get_srcs_url(
            self.reader.lang, src, 'asset', 'talk'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore)

        self.area_name_json, self.actionSets_json = await asyncio.gather(
            self.fetch_url_json(self.areas_url, force_online=self.force_master_online),
            self.fetch_url_json(
                self.actionSets_url, force_online=self.force_master_online
            ),
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
            and (action.get("actionSetType") == "limited")
            and ('aprilfool' not in action['scenarioId'])
        ):
            return f"limited_{action['areaId']}"
        elif ('scenarioId' in action) and ('aprilfool' in action['scenarioId']):
            talk_name: str = action['scenarioId']
            return talk_name.split('_')[1]
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
            2000000 <= action["releaseConditionId"] <= 2000036
        ):  # cn and jp have diff
            return 'theater'
        else:
            assert 'scenarioId' not in action or action['scenarioId'] == 'op_02area'
            return ''

    async def get(
        self, target: int | str, timestamp13: int | None = util.LATE_TIMESTAMP13
    ) -> None:
        '''
        target: int: event_id; str: grade1, grade2, theater, limited_{area_id}, aprilfool2022+

        timestamp13: 只抓 archivePublishedAt <= timestamp13 的 talk
        （None 为不过滤；默认 util.LATE_TIMESTAMP13 = now + 365 天：
        未来一年内纳入，超远未来（一年以上）不抓）
        '''
        if target == 38 and self.reader.lang == 'en':  # special case of EN
            logging.info(f'talk {target} does not exist.')
            return

        actions = [
            action
            for action in self.actionSets_json
            if self.__get_category(action) == target
        ]

        if timestamp13 is not None:
            # archivePublishedAt 结构上可选：仅特例 id=2373（mzk5）
            # 缺失该键，缺失视为最早，必通过过滤
            actions = [
                action
                for action in actions
                if (
                    action['archivePublishedAt']
                    if 'archivePublishedAt' in action
                    else 0
                )
                <= timestamp13
            ]

        if len(actions) == 0:
            logging.info(f'talk {target} does not exist.')
            return

        tasks = []
        for action in actions:
            tasks.append(
                self.fetch_url_json(
                    [
                        url.format(
                            group=math.floor(action['id'] / 100),
                            scenarioId=action['scenarioId'],
                        )
                        for url in self.talk_asset_url
                    ],
                    str(target),
                    print_done=self.print_fetch_detial,
                    compress=self.compress_assets,
                    skip_read=not self.parse,
                )
            )

        talk_jsons = await asyncio.gather(*tasks)

        if self.parse and not util.judge_need_skip(*talk_jsons):
            os.makedirs(self.save_dir, exist_ok=True)

            texts = [
                self.reader.read_story_in_json(talk_json) for talk_json in talk_jsons
            ]

            if isinstance(target, int):  # event id
                filename = f'talk_event_{target:0{self.maxlen_eventId_areaID[0]}}'
            elif target.startswith('limited_'):
                filename = f'talk_{target.split('_')[0]}_{target.split('_')[1]:0{self.maxlen_eventId_areaID[1]}}'

                area_name_index = self.area_name_lookup.find_index(action['areaId'])
                area_name = self.area_name_json[area_name_index]['name']

                filename += ' ' + area_name
            else:
                filename = f'talk_{target}'

            filename = util.valid_filename(filename + '.txt')

            filepath = os.path.join(self.save_dir, filename)
            util.remove_olds_or_rename_old(filepath, r'([^\s\.]+)')
            with open(filepath, 'w', encoding='utf8') as f:
                left = Mark_multi_lang['['][self.reader.mark_lang]
                right = Mark_multi_lang[']'][self.reader.mark_lang]

                for index, (action, text) in enumerate(zip(actions, texts)):
                    area_name_index = self.area_name_lookup.find_index(action['areaId'])
                    area_name = self.area_name_json[area_name_index]['name']
                    sub_name = self.area_name_json[area_name_index].get('subName')
                    if sub_name is not None:
                        area_name += ' - ' + sub_name

                    f.write(
                        f"{index+1} {action['id']}:{action['scenarioId']}\n\n{left}{area_name}{right}\n\n"
                    )
                    if index != len(actions) - 1:
                        f.write(text + '\n\n\n')
                    else:
                        f.write(text + '\n')

        logging.info(f'get talk {target} done.')

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
            logging.info(f'talk {talk_id} does not exist.')
            return

        actionSet = self.actionSets_json[actionSets_index]

        cate = self.__get_category(actionSet)

        if 'scenarioId' not in actionSet:
            logging.info(f'talk {talk_id} does have content.')
            return

        if self.parse:
            os.makedirs(self.save_dir, exist_ok=True)

        talk_json = await self.fetch_url_json(
            [
                url.format(
                    group=math.floor(talk_id / 100), scenarioId=actionSet['scenarioId']
                )
                for url in self.talk_asset_url
            ],
            compress=self.compress_assets,
            skip_read=not self.parse,
        )

        if self.parse and not util.judge_need_skip(talk_json):
            text = self.reader.read_story_in_json(talk_json)

            filename = f'talk_{talk_id}'

            area_name_index = self.area_name_lookup.find_index(actionSet['areaId'])
            area_name = self.area_name_json[area_name_index]['name']
            sub_name = self.area_name_json[area_name_index].get('subName')
            if sub_name is not None:
                area_name += ' - ' + sub_name

            with open(
                os.path.join(self.save_dir, filename) + '.txt',
                'w',
                encoding='utf8',
            ) as f:
                left = Mark_multi_lang['['][self.reader.mark_lang]
                right = Mark_multi_lang[']'][self.reader.mark_lang]
                f.write(
                    f"{actionSet['id']}:{actionSet['scenarioId']} {cate}\n\n{left}{area_name}{right}\n\n"
                )
                f.write(text + '\n')

        logging.info(f'get talk {talk_id} done.')

    def tell_categories(self, timestamp13: int | None = None) -> set[str | int]:
        '''timestamp13: 只返回存在 archivePublishedAt <= timestamp13 的
        talk 的类别（None 为全部类别）'''
        ret = set()
        for actionSet in self.actionSets_json:
            if timestamp13 is not None:
                # archivePublishedAt 结构上可选：仅特例 id=2373（mzk5）
                # 缺失该键，缺失视为最早，必通过过滤
                archive_published_at = (
                    actionSet['archivePublishedAt']
                    if 'archivePublishedAt' in actionSet
                    else 0
                )
                if archive_published_at > timestamp13:
                    continue
            cate = self.__get_category(actionSet)
            if cate != '':
                ret.add(cate)
        return ret


class Self_intro_getter(Pjsk_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: list[str] = ['sekai.best'],
        save_dir: str = '.',
        assets_save_dir: str = '.',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_charaId: int = 2,
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ):
        util.warn_extra_args(self, args)
        super().__init__(
            os.path.join(save_dir, 'story_{lang}', 'self'),
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )

        self.reader = reader
        self.save_dir = self.save_dir.format(lang=self.reader.lang)
        self.maxlen_charaId = maxlen_charaId

        self.characterProfiles_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'characterProfiles'
        )
        self.self_asset_url = Constant.get_srcs_url(
            self.reader.lang, src, 'asset', 'self'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore)

        self.characterProfiles_json: list[dict[str, Any]] = await self.fetch_url_json(
            self.characterProfiles_url, force_online=self.force_master_online
        )

        self.characterProfiles_lookup = util.DictLookup(
            self.characterProfiles_json, 'characterId'
        )

    async def get(self, chara_id: int) -> None:
        profile_index = self.characterProfiles_lookup.find_index(chara_id)
        if profile_index == -1:
            logging.info(f'character {chara_id} does not exist.')
            return

        chara_unit_name = '_'.join(self.reader.get_chara_unitAbbr_names(chara_id)[:2])

        filename = util.valid_filename(
            f'{chara_id:0{self.maxlen_charaId}} {chara_unit_name}' + '.txt'
        )

        profile = self.characterProfiles_json[profile_index]
        scenarioId: str = profile['scenarioId']

        scenarioId_common = scenarioId[: scenarioId.rindex('_')]
        scenarioId_2nd = scenarioId_common + '_2nd'

        grade1_json, grade2_json = await asyncio.gather(
            self.fetch_url_json(
                [
                    url.format(scenarioId=scenarioId_common)
                    for url in self.self_asset_url
                ],
                chara_unit_name,
                compress=self.compress_assets,
                skip_read=not self.parse,
            ),
            self.fetch_url_json(
                [url.format(scenarioId=scenarioId_2nd) for url in self.self_asset_url],
                chara_unit_name,
                compress=self.compress_assets,
                skip_read=not self.parse,
            ),
        )

        if self.parse and not util.judge_need_skip(grade1_json, grade2_json):
            os.makedirs(self.save_dir, exist_ok=True)

            text_1 = self.reader.read_story_in_json(grade1_json)
            text_2 = self.reader.read_story_in_json(grade2_json)

            file_path = os.path.join(self.save_dir, filename)
            util.remove_olds_or_rename_old(file_path, r'(\d+) ')
            with open(file_path, 'w', encoding='utf8') as f:
                f.write(
                    f"{Mark_multi_lang['self intro'][self.reader.mark_lang]}{self.reader.get_chara_unitAbbr_names(chara_id)[1]}\n\n"
                )
                f.write(
                    Mark_multi_lang['<'][self.reader.mark_lang]
                    + 'YEAR 1'
                    + Mark_multi_lang['>'][self.reader.mark_lang]
                    + '\n\n'
                )
                f.write(text_1 + '\n\n\n')
                f.write(
                    Mark_multi_lang['<'][self.reader.mark_lang]
                    + 'YEAR 2'
                    + Mark_multi_lang['>'][self.reader.mark_lang]
                    + '\n\n'
                )
                f.write(text_2 + '\n')

        logging.info(f'get self intro {filename} done.')

    def tell_ids(self) -> list[int]:
        ret = []
        for chara in self.characterProfiles_json:
            ret.append(chara['characterId'])
        return ret


class Special_story_getter(Pjsk_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: list[str] = ['sekai.best'],
        save_dir: str = '.',
        assets_save_dir: str = '.',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_sp: int = 3,
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ):
        util.warn_extra_args(self, args)
        super().__init__(
            os.path.join(save_dir, 'story_{lang}', 'special'),
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )

        self.reader = reader
        self.save_dir = self.save_dir.format(lang=self.reader.lang)
        self.maxlen_sp = maxlen_sp

        self.specialStories_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'specialStories'
        )
        self.special_asset_url = Constant.get_srcs_url(
            self.reader.lang, src, 'asset', 'special'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore)

        self.specialStories_json: list[dict[str, Any]] = await self.fetch_url_json(
            self.specialStories_url, force_online=self.force_master_online
        )

        self.specialStories_lookup = util.DictLookup(self.specialStories_json, 'id')

    async def get(
        self, id: int, timestamp13: int | None = util.LATE_TIMESTAMP13
    ) -> None:
        '''
        timestamp13: 只抓 startAt <= timestamp13 的 special story
        （None 为不过滤；默认 util.LATE_TIMESTAMP13 = now + 365 天：
        未来一年内纳入，超远未来（一年以上）不抓）
        '''
        story_index = self.specialStories_lookup.find_index(id)
        if story_index == -1 or id == 2:  # special case id2
            logging.info(f'special story {id} does not exist.')
            return

        story = self.specialStories_json[story_index]
        if timestamp13 is not None and story['startAt'] > timestamp13:
            logging.info(f'special story {id} does not exist.')
            return

        episodes = story['episodes']

        tasks = []
        for episode in episodes:
            tasks.append(
                self.fetch_url_json(
                    [
                        url.format(
                            assetbundleName=episode['assetbundleName'],
                            scenarioId=episode['scenarioId'],
                        )
                        for url in self.special_asset_url
                    ],
                    f"sp{id}-{episode['episodeNo']}",
                    compress=self.compress_assets,
                    skip_read=not self.parse,
                )
            )
        episode_story_jsons = await asyncio.gather(*tasks)

        if self.parse and not util.judge_need_skip(*episode_story_jsons):
            os.makedirs(self.save_dir, exist_ok=True)

            texts = [
                self.reader.read_story_in_json(episode_story_json)
                for episode_story_json in episode_story_jsons
            ]

            story_name = f"sp{id} {episodes[0]['title']} ({episodes[0]['scenarioId']})"
            filename = util.valid_filename(
                f"sp{id:0{self.maxlen_sp}} {episodes[0]['title']}" + '.txt'
            )

            file_path = os.path.join(self.save_dir, filename)
            util.remove_olds_or_rename_old(file_path, r'sp(\d+) ')
            with open(file_path, 'w', encoding='utf8') as f:
                f.write(story_name + '\n\n')
                if len(episodes) == 1:
                    f.write(texts[0] + '\n')
                else:
                    for episode, text in zip(episodes, texts):
                        f.write(
                            f"{episode['episodeNo']} {episode['title']} ({episode['scenarioId']})\n\n"
                        )
                        f.write(text + '\n\n\n')

            logging.info(f'get special {filename} done.')

    def tell_ids(self, timestamp13: int | None = None) -> list[int]:
        '''timestamp13: 只返回 startAt <= timestamp13 的 special id（None 为全部）'''
        ret = []
        for sp in self.specialStories_json:
            if timestamp13 is None or sp['startAt'] <= timestamp13:
                ret.append(sp['id'])
        return ret


class Mysekai_talk_getter(Pjsk_getter):
    def __init__(
        self,
        reader: Story_reader,
        src: list[str] = ['haruki', 'pjsk.moe', 'sekai.best'],
        save_dir: str = '.',
        assets_save_dir: str = '.',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_charaId: int = 2,
        print_fetch_detial: bool = False,
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        util.warn_extra_args(self, args)
        super().__init__(
            os.path.join(save_dir, 'story_{lang}', 'mysekai'),
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )

        self.reader = reader
        self.save_dir = self.save_dir.format(lang=self.reader.lang)
        self.maxlen_charaId = maxlen_charaId
        self.print_fetch_detial = print_fetch_detial

        # Master JSON URLs
        self.mysekaiCharacterTalks_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'mysekaiCharacterTalks'
        )
        self.mysekaiTutorialTalks_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'mysekaiTutorialTalks'
        )
        self.mysekaiGameCharacterUnitGroups_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'mysekaiGameCharacterUnitGroups'
        )
        self.mysekaiCharacterTalkConditionGroups_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'mysekaiCharacterTalkConditionGroups'
        )
        self.mysekaiCharacterTalkConditions_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'mysekaiCharacterTalkConditions'
        )
        self.mysekaiPhenomenas_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'mysekaiPhenomenas'
        )
        self.mysekaiFixtures_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'mysekaiFixtures'
        )
        self.releaseConditions_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'releaseConditions'
        )

        # Asset URL
        self.talk_asset_url = Constant.get_srcs_url(
            self.reader.lang, src, 'asset', 'mysekai_talk'
        )

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore)

        (
            self.mysekaiCharacterTalks_json,
            self.mysekaiGameCharacterUnitGroups_json,
            self.mysekaiCharacterTalkConditionGroups_json,
            self.mysekaiCharacterTalkConditions_json,
            self.mysekaiPhenomenas_json,
            self.mysekaiFixtures_json,
            self.releaseConditions_json,
        ) = await asyncio.gather(
            self.fetch_url_json(
                self.mysekaiCharacterTalks_url, force_online=self.force_master_online
            ),
            self.fetch_url_json(
                self.mysekaiGameCharacterUnitGroups_url,
                force_online=self.force_master_online,
            ),
            self.fetch_url_json(
                self.mysekaiCharacterTalkConditionGroups_url,
                force_online=self.force_master_online,
            ),
            self.fetch_url_json(
                self.mysekaiCharacterTalkConditions_url,
                force_online=self.force_master_online,
            ),
            self.fetch_url_json(
                self.mysekaiPhenomenas_url, force_online=self.force_master_online
            ),
            self.fetch_url_json(
                self.mysekaiFixtures_url, force_online=self.force_master_online
            ),
            self.fetch_url_json(
                self.releaseConditions_url, force_online=self.force_master_online
            ),
        )

        self.gameCharacterUnits_json = self.reader.gameCharacterUnits

        # Build lookups
        self.mysekaiGameCharacterUnitGroups_lookup = util.DictLookup(
            self.mysekaiGameCharacterUnitGroups_json, 'id'
        )
        self.gameCharacterUnits_lookup = util.DictLookup(
            self.gameCharacterUnits_json, 'id'
        )
        self.mysekaiCharacterTalkConditions_lookup = util.DictLookup(
            self.mysekaiCharacterTalkConditions_json, 'id'
        )
        self.mysekaiPhenomenas_lookup = util.DictLookup(
            self.mysekaiPhenomenas_json, 'id'
        )
        self.mysekaiFixtures_lookup = util.DictLookup(self.mysekaiFixtures_json, 'id')

        # Group condition IDs by groupId
        self.group_conditions_map: dict[int, list[int]] = {}
        for cg in self.mysekaiCharacterTalkConditionGroups_json:
            gid = cg['groupId']
            cid = cg['mysekaiCharacterTalkConditionId']
            if gid not in self.group_conditions_map:
                self.group_conditions_map[gid] = []
            self.group_conditions_map[gid].append(cid)

        # Build release condition sentence map for read_event_story_episode_id
        # 注意：master 里偶有 event_story 条件缺 releaseConditionTypeId（新活动的数据
        # 未补全时上游会漏该字段，如 7.1.0.35 的 id=122120），无法映射到任何
        # read_event_story_episode_id 值，跳过即可，不能让 init 直接崩。
        self.release_cond_eventID_map: dict[int, int] = {}
        for rc in self.releaseConditions_json:
            if rc['releaseConditionType'] != 'event_story':
                continue
            type_id = rc.get('releaseConditionTypeId')
            if type_id is None:
                logging.warning(
                    f'releaseCondition {rc["id"]} (event_story) has no '
                    f'releaseConditionTypeId, skipped: {rc.get("sentence")}'
                )
                continue
            self.release_cond_eventID_map[type_id] = int(str(rc['id'])[1:4]) + 1

    def _get_chara_info(self, gameCharacterUnitId: int) -> tuple[int, str, str]:
        """Return (gameCharacterId, unit_abbr, full_name)."""
        gcu_index = self.gameCharacterUnits_lookup.find_index(gameCharacterUnitId)
        assert gcu_index != -1, f'gameCharacterUnitId {gameCharacterUnitId} not found'
        gcu = self.gameCharacterUnits_json[gcu_index]
        gameCharacterId = gcu['gameCharacterId']
        unit = gcu['unit']
        unit_abbr = Constant.unit_code_abbr[unit]

        _, fullname, _ = self.reader.get_chara_unitAbbr_names(gameCharacterId)

        return gameCharacterId, unit_abbr, fullname

    def _get_conditions_str(self, conditionGroupId: int) -> str:
        """Return human-readable conditions string for a given condition group."""
        cond_ids = self.group_conditions_map.get(conditionGroupId, [])
        parts: list[str] = []
        for cid in cond_ids:
            cond_index = self.mysekaiCharacterTalkConditions_lookup.find_index(cid)
            assert cond_index != -1
            cond = self.mysekaiCharacterTalkConditions_json[cond_index]
            cond_type = cond['mysekaiCharacterTalkConditionType']
            cond_value = cond['mysekaiCharacterTalkConditionTypeValue']

            if cond_type == 'mysekai_phenomena_id':
                p_index = self.mysekaiPhenomenas_lookup.find_index(cond_value)
                assert p_index != -1
                parts.append(
                    'phenomena-' + self.mysekaiPhenomenas_json[p_index]['name']
                )
            elif cond_type == 'mysekai_character_visit_count':
                parts.append(f'character_visit_count-{cond_value}')
            elif cond_type == 'read_event_story_episode_id':
                # 未被 releaseConditions 收录的 episode（上游字段缺失）兜底，
                # 保留原始 episode id 以便人工排查
                eventID = self.release_cond_eventID_map.get(cond_value)
                if eventID is None:
                    logging.warning(
                        f'read_event_story_episode_id {cond_value} not found '
                        'in releaseConditions.'
                    )
                    parts.append(f'read_event_story-unknown-{cond_value}')
                else:
                    parts.append(f'read_event_story-{eventID}')
            elif cond_type == 'mysekai_fixture_id':
                fix_index = self.mysekaiFixtures_lookup.find_index(cond_value)
                assert fix_index != -1
                parts.append(self.mysekaiFixtures_json[fix_index]['name'])
        return ', '.join(parts)

    def _parse_lua_talk(self, lua_text: str) -> str:
        """Parse Lua talk script to formatted dialogue text."""
        # Find all label and text calls in order by position
        combined_pattern = re.compile(
            r'label\("(?P<label>[^"]*)"\)|text\("(?P<text>(?:[^"\\]|\\.)*)"\)'
        )

        events: list[tuple[int, str, str]] = []  # (pos, type, content)
        for m in combined_pattern.finditer(lua_text):
            if m.group('label') is not None:
                events.append((m.start(), 'label', m.group('label')))
            elif m.group('text') is not None:
                raw = m.group('text')
                content = (
                    raw.replace('\\n', ' ').replace('\\"', '"').replace('\\\\', '\\')
                )
                events.append((m.start(), 'text', content))

        events.sort(key=lambda x: x[0])

        lines: list[str] = []
        current_label: str | None = None
        for _, ev_type, ev_content in events:
            if ev_type == 'label':
                current_label = ev_content
            elif ev_type == 'text' and current_label is not None:
                lines.append(
                    f"{current_label}{util.Mark_multi_lang[':'][self.reader.mark_lang]}{ev_content}"
                )

        return '\n'.join(lines)

    def _get_talk_meta(self, talk: dict) -> dict:
        """Extract metadata for one mysekaiCharacterTalk entry.
        Returns dict with talk_id, archive_group_id, conditions_str, chara_names,
        gameCharacterUnitIds, lua_name, assetbundleName; or None if group missing.
        """
        talk_id = talk['id']
        group_id = talk['mysekaiGameCharacterUnitGroupId']
        condition_group_id = talk['mysekaiCharacterTalkConditionGroupId']
        archive_group_id = talk['characterArchiveMysekaiCharacterTalkGroupId']
        assetbundleName = talk['assetbundleName']
        lua_name = talk['lua']

        # Conditions
        conditions_str = self._get_conditions_str(condition_group_id)

        # Character group
        group_index = self.mysekaiGameCharacterUnitGroups_lookup.find_index(group_id)
        assert group_index != -1
        chara_group: dict[str, int] = self.mysekaiGameCharacterUnitGroups_json[
            group_index
        ]

        chara_unit_ids: list[int] = []
        chara_names: list[str] = []
        for key_name in [f'gameCharacterUnitId{i}' for i in range(1, 6)]:
            chara_unit_id = chara_group.get(key_name)
            if chara_unit_id is None:
                continue
            _, _, fullname = self._get_chara_info(chara_unit_id)
            chara_unit_ids.append(chara_unit_id)
            chara_names.append(fullname)

        return {
            'talk_id': talk_id,
            'archive_group_id': archive_group_id,
            'conditions_str': conditions_str,
            'chara_names': chara_names,
            'gameCharacterUnitIds': chara_unit_ids,
            'lua_name': lua_name,
            'assetbundleName': assetbundleName,
        }

    async def _fetch_lua_map(
        self, lua_keys: list[tuple[str, str]]
    ) -> tuple[dict[tuple[str, str], str], list[Any]]:
        """Fetch unique lua files concurrently.

        Returns (result_map, raw_results) where raw_results is the list of
        raw return values from fetch_url_json (for judge_need_skip).
        """
        if not lua_keys:
            return {}, []
        lua_tasks = [
            self.fetch_url_json(
                [url.format(assetbundleName=ab, lua=ln) for url in self.talk_asset_url],
                ln,
                compress=self.compress_assets,
                skip_read=not self.parse,
                format='text',
                print_done=self.print_fetch_detial,
            )
            for ab, ln in lua_keys
        ]
        lua_results = await asyncio.gather(*lua_tasks)
        result_map: dict[tuple[str, str], str] = {}
        for key, result in zip(lua_keys, lua_results):
            result_map[key] = result
        return result_map, lua_results

    def _write_entries(
        self,
        filepath: str,
        entries: list[tuple[int, int, str, str, str, str]],
        lua_map: dict[tuple[str, str], str],
        is_first_group_id: dict[int, bool] | None = None,
    ) -> None:
        """Write formatted talk entries to a file."""
        right = Mark_multi_lang[')'][self.reader.mark_lang]
        chara_prefix = Mark_multi_lang['characters'][self.reader.mark_lang]

        with open(filepath, 'w', encoding='utf8') as f:
            for idx, (
                talk_id,
                archive_group_id,
                conditions_str,
                chara_names_str,
                lua_name,
                ab,
            ) in enumerate(entries, 1):
                repeat_mark = ''
                if is_first_group_id is not None and not is_first_group_id[talk_id]:
                    repeat_mark = '~'

                lua_text = lua_map.get((ab, lua_name))
                f.write(
                    f'{idx} {talk_id}:{archive_group_id}{repeat_mark} {conditions_str}\n'
                )
                if chara_names_str:
                    f.write(f'\n{chara_prefix}{chara_names_str}{right}\n')
                if lua_text is not None:
                    f.write(f'\n{self._parse_lua_talk(lua_text)}\n')
                else:
                    f.write('\n')
                if idx != len(entries):
                    f.write('\n\n')

    # --- Public methods ---

    async def get_id(self, talk_id: int) -> None:
        """Debug: fetch one mysekai talk by id, save to mysekai_talk_id.txt."""
        talk = None
        for t in self.mysekaiCharacterTalks_json:
            if t['id'] == talk_id:
                talk = t
                break
        if talk is None:
            logging.error(f'talk_id {talk_id} not found in mysekaiCharacterTalks')
            return

        meta = self._get_talk_meta(talk)
        if meta is None:
            logging.error(f'talk {talk_id}: group not found')
            return

        comma = Mark_multi_lang[','][self.reader.mark_lang]
        entries = [
            (
                meta['talk_id'],
                meta['archive_group_id'],
                meta['conditions_str'],
                comma.join(meta['chara_names']),
                meta['lua_name'],
                meta['assetbundleName'],
            )
        ]

        lua_map, lua_results = await self._fetch_lua_map(
            [(meta['assetbundleName'], meta['lua_name'])]
        )

        if self.parse and not util.judge_need_skip(*lua_results):
            os.makedirs(self.save_dir, exist_ok=True)
            filepath = os.path.join(self.save_dir, f'mysekai_talk_{talk_id}.txt')
            self._write_entries(filepath, entries, lua_map)

        logging.info(f'get mysekai talk {talk_id} done.')

    async def get(self, gameCharacterUnitId: int) -> None:
        """Fetch all mysekai talks for one character (by gameCharacterUnitId),
        save to {chara_key}.txt.
        """

        # Build chara key
        _, unit_abbr, fullname = self._get_chara_info(gameCharacterUnitId)
        chara_key = (
            f'{gameCharacterUnitId:0{self.maxlen_charaId}} {unit_abbr}_{fullname}'
        )

        # Collect talks involving this character
        comma = Mark_multi_lang[','][self.reader.mark_lang]
        entries: list[tuple[int, int, str, str, str, str]] = []
        lua_keys: list[tuple[str, str]] = []
        seen_lua: set[tuple[str, str]] = set()

        is_first_group_id: dict[int, bool] = {}
        seen_talk_group_id: set[int] = set()

        for talk in self.mysekaiCharacterTalks_json:
            meta = self._get_talk_meta(talk)
            if meta is None:
                continue
            if gameCharacterUnitId not in meta['gameCharacterUnitIds']:
                continue

            entries.append(
                (
                    meta['talk_id'],
                    meta['archive_group_id'],
                    meta['conditions_str'],
                    comma.join(meta['chara_names']),
                    meta['lua_name'],
                    meta['assetbundleName'],
                )
            )

            tid = meta['talk_id']
            gid = meta['archive_group_id']
            if gid not in seen_talk_group_id:
                is_first_group_id[tid] = True
            else:
                is_first_group_id[tid] = False
            seen_talk_group_id.add(gid)

            lua_key = (meta['assetbundleName'], meta['lua_name'])
            if lua_key not in seen_lua:
                seen_lua.add(lua_key)
                lua_keys.append(lua_key)

        if not entries:
            logging.info(f'no talks found for {chara_key}')
            return

        lua_map, lua_results = await self._fetch_lua_map(lua_keys)

        if self.parse and not util.judge_need_skip(*lua_results):
            os.makedirs(self.save_dir, exist_ok=True)
            filename = util.valid_filename(chara_key + '.txt')
            filepath = os.path.join(self.save_dir, filename)
            util.remove_olds_or_rename_old(filepath, r'(\d+) ')
            self._write_entries(filepath, entries, lua_map, is_first_group_id)

        logging.info(f'get mysekai talk of character {gameCharacterUnitId} done.')

    async def get_tutorial(self) -> None:
        """Fetch all mysekai tutorial talks, save to _tutorial.txt."""

        ttalk_list = await self.fetch_url_json(
            self.mysekaiTutorialTalks_url, force_online=self.force_master_online
        )
        if isinstance(ttalk_list, str):
            # 'ERROR: ...'（抓取失败）或 'Missing asset'（离线且本地缺失）：
            # 无法枚举教程对话，跳过不写，避免把字符串当列表迭代
            logging.warning(f'skip mysekai tutorial talks ({ttalk_list}).')
            return
        if not ttalk_list:
            logging.info('no tutorial talks.')
            return

        lua_keys: list[tuple[str, str]] = []
        for tt in ttalk_list:
            key = (tt['assetbundleName'], tt['lua'])
            if key not in lua_keys:
                lua_keys.append(key)

        lua_map, lua_results = await self._fetch_lua_map(lua_keys)

        if self.parse and not util.judge_need_skip(*lua_results):
            parts: list[str] = []
            for tt in ttalk_list:
                ttalk_id = tt['id']
                lua_name = tt['lua']
                ab = tt['assetbundleName']
                lua_text = lua_map.get((ab, lua_name))
                if lua_text is not None:
                    parsed = self._parse_lua_talk(lua_text)
                    parts.append(f'{ttalk_id}:{lua_name}\n\n{parsed}\n')
                else:
                    parts.append(f'{ttalk_id}:{lua_name}\n\n')

            os.makedirs(self.save_dir, exist_ok=True)
            filepath = os.path.join(
                self.save_dir, f'{0:0{self.maxlen_charaId}} tutorial.txt'
            )
            with open(filepath, 'w', encoding='utf8') as f:
                f.write('\n'.join(parts) + '\n')

        logging.info('get mysekai talk tutorial done.')

    def tell_ids(self) -> list[int]:
        """Return gameCharacterUnitIds for mysekai talks.
        Fixed list: 20 original characters + 5 Miku variants + 5 VS group variants.
        """
        return sorted(
            [
                # 原创角色 (gameCharacterId 1~20)
                1,
                2,
                3,
                4,
                5,
                6,
                7,
                8,
                9,
                10,
                11,
                12,
                13,
                14,
                15,
                16,
                17,
                18,
                19,
                20,
                # 初音未来 5 variants (charaId=21)
                27,  # light_sound (Leo/need)
                28,  # idol (MMJ)
                29,  # street (VBS)
                30,  # theme_park (WxS)
                31,  # school_refusal (25ji)
                # VS in groups
                33,  # Rin (MMJ)
                39,  # Len (VBS)
                42,  # Luka (Leo/need)
                49,  # MEIKO (VBS)
                55,  # KAITO (WxS)
            ]
        )


class Virtual_live_getter(Pjsk_getter):
    # CueName 末尾的罗马音 → characterId（voice_mc_xxx_11_90_minori 这类合唱行的后缀）。
    # 无后缀时末尾数字本身就是 characterId（_13 司 / _21 Miku / _26 KAITO），故只列后缀表。
    # 仅用于「多人同说一句」时的归属消歧，缺项会自动退回按场次顺序配对。
    _cue_romaji_character: dict[str, int] = {
        'ichika': 1,
        'saki': 2,
        'honami': 3,
        'shiho': 4,
        'minori': 5,
        'haruka': 6,
        'airi': 7,
        'shizuku': 8,
        'kohane': 9,
        'an': 10,
        'akito': 11,
        'toya': 12,
        'tsukasa': 13,
        'emu': 14,
        'nene': 15,
        'rui': 16,
        'kanade': 17,
        'mafuyu': 18,
        'ena': 19,
        'mizuki': 20,
        'miku': 21,
        'rin': 22,
        'len': 23,
        'luka': 24,
        'meiko': 25,
        'kaito': 26,
    }

    def __init__(
        self,
        reader: Story_reader,
        src: list[str] = ['sekai.best'],
        save_dir: str = '.',
        assets_save_dir: str = '.',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_id: int = 3,
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        util.warn_extra_args(self, args)
        super().__init__(
            os.path.join(save_dir, 'story_{lang}', 'virtual_live'),
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )

        self.reader = reader
        self.save_dir = self.save_dir.format(lang=self.reader.lang)
        self.maxlen_id = maxlen_id

        self.virtualLives_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'virtualLives'
        )
        self.character3ds_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'character3ds'
        )
        self.musics_url = Constant.get_srcs_url(
            self.reader.lang, src, 'master', 'musics'
        )
        # timeline 类型（mc_timeline / virtual_message）的两种上游格式：
        # - sekai.best 的 .playable 带上游预解析的 __timelineParse，直接可用；
        # - haruki / pjsk.moe 是整包对象转储（container + objects），对象自身没有
        #   PathID，轨道 clip 的 m_Asset.m_PathID 指不到台词对象，只能拿 clip 的
        #   m_DisplayName（日文）去比文本。cn / tw 包的 m_DisplayName 保留日文，
        #   所以需要同 bundle 的 jp 包当对照（jp 的 Serif 就是日文本体）。
        # 按源分成一组组 URL：一个源要「本语言包 + jp 包」都拿到才算可用，
        # 缺一个就整段换下一个源（见 _fetch_mc）。各源扩展名不同（.playable /
        # .asset / .json），由 config 里的模板决定，格式化时统一带上 file_type。
        self.virtual_live_src_urls: list[
            tuple[str, list[util.UrlSpec], list[util.UrlSpec]]
        ] = []
        for src_name in src:
            urls = Constant.get_srcs_url(self.reader.lang, [src_name], 'asset', 'virtual_live')
            if not urls:
                continue
            # 只有转储格式的源才有「jp 对照包」；sekai.best 自带预解析，不需要
            jp_urls = (
                Constant.get_srcs_url('jp', [src_name], 'asset', 'virtual_live')
                if src_name in ('haruki', 'pjsk.moe')
                else []
            )
            self.virtual_live_src_urls.append((src_name, urls, jp_urls))

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore)

        self.virtualLives_json, self.character3ds_json, self.musics_json = (
            await asyncio.gather(
                self.fetch_url_json(
                    self.virtualLives_url, force_online=self.force_master_online
                ),
                self.fetch_url_json(
                    self.character3ds_url, force_online=self.force_master_online
                ),
                self.fetch_url_json(
                    self.musics_url, force_online=self.force_master_online
                ),
            )
        )

        self.events_json = self.reader.events_json

        # virtualLiveId → event id 映射（events.json 数据，一对一）
        self.virtual_live_event_map: dict[int, int] = {}
        for event in self.events_json:
            if 'virtualLiveId' in event:
                self.virtual_live_event_map[event['virtualLiveId']] = event['id']

        self.virtualLives_lookup = util.DictLookup(self.virtualLives_json, 'id')
        self.character3ds_lookup = util.DictLookup(self.character3ds_json, 'id')
        self.musics_lookup = util.DictLookup(self.musics_json, 'id')

    def _get_chara_name(self, character3dId: int | None) -> str:
        '''character3ds id → characterId → 服务器语言角色名（gameCharacters givenName）。'''
        if character3dId is None:
            return ''
        index = self.character3ds_lookup.find_index(character3dId)
        if index == -1:
            return ''
        chara3d = self.character3ds_json[index]
        # reader 的 gameCharacters 已按服务器语言加载
        return self.reader.get_chara_unitAbbr_names(chara3d['characterId'])[2]

    def get_chara3d_unitAbbr_names_isVS(
        self, character3dId: int | None
    ) -> tuple[str, str, str, bool]:
        '''仿 get_chara2d_unitAbbr_names_isVS：character3ds id →
        (实际组合缩写, 全名, 短名, 是否为 VS 角色)。

        character3ds 无 characterType 字段，直接按角色 unit 判断；
        VS 角色的 3d 模型可能属于其它组合（如 N25），此时返回其实际组合缩写。
        '''
        if character3dId is None:
            return '', '', '', False
        index = self.character3ds_lookup.find_index(character3dId)
        if index == -1:
            return '', '', '', False
        chara3d = self.character3ds_json[index]
        actual_unit = chara3d['unit']
        chara_id = chara3d['characterId']
        chara_unit, fullname, givenname = self.reader.get_chara_unitAbbr_names(chara_id)
        if chara_unit != 'VS':
            return chara_unit, fullname, givenname, False
        else:
            return Constant.unit_code_abbr[actual_unit], fullname, givenname, True

    def _annotate_vs_unit(
        self, chara_name: str, character3dId: int | None, style: str
    ) -> str:
        '''VS 角色在名字后追加实际组合缩写注释（非 VS 角色原样返回）：
        style='paren' 说话人用括号（同 story reader 的解析），
        style='dash' 登场/退场用短横（外层已有括号包裹）。'''
        unit, _, _, isVS = self.get_chara3d_unitAbbr_names_isVS(character3dId)
        if not isVS or unit in ('VS', 'none'):
            return chara_name
        if style == 'dash':
            return f'{chara_name}-{unit}'
        lparen = Mark_multi_lang['('][self.reader.mark_lang]
        rparen = Mark_multi_lang[')'][self.reader.mark_lang]
        return f'{chara_name}{lparen}{unit}{rparen}'

    def parse_mc_scenario(self, mc_asset: dict[str, Any]) -> str:
        '''解析 mc 类型（.asset，scenario 目录）的对话。

        talk / spawn / unspawn 事件的 Id 属于同一计数空间，
        合并后按 Id 排序即可获得演出顺序。
        '''
        events: list[tuple[str, dict[str, Any]]] = []
        for ev_type, key in (
            ('talk', 'characterTalkEvents'),
            ('spawn', 'characterSpawnEvents'),
            ('unspawn', 'characterUnspawnEvents'),
        ):
            for ev in mc_asset[key]:
                events.append((ev_type, ev))
        events.sort(key=lambda t: t[1]['Id'])

        mark_lang = self.reader.mark_lang
        lines: list[str] = []
        for ev_type, ev in events:
            if ev_type == 'talk':
                serif = re.sub(r'\r\n|\r|\n', ' ', ev['Serif']).strip()
                if not serif:
                    continue
                chara_name = self._annotate_vs_unit(
                    self._get_chara_name(ev['Character3dId']),
                    ev['Character3dId'],
                    'paren',
                )
                lines.append(f'{chara_name}{Mark_multi_lang[":"][mark_lang]}{serif}')
            else:  # spawn / unspawn: 登场 / 退场
                chara_name = self._annotate_vs_unit(
                    self._get_chara_name(ev['Character3dId']),
                    ev['Character3dId'],
                    'dash',
                )
                lines.append(
                    f'{Mark_multi_lang[ev_type][mark_lang]}{chara_name}'
                    f'{Mark_multi_lang[")"][mark_lang]}'
                )
        return '\n'.join(lines)

    def _event_chara_name(
        self, ev: dict[str, Any], chara3d_map: dict[str, list[int]]
    ) -> tuple[str, int | None]:
        '''事件角色名 → (服务器语言角色名, character3dId)。

        meta.characters 里的 name 不可靠：同一场里可能有两个 3d 模型共用一个显示名
        （如 countdown 的 1786 实际是 KAITO，却被标成「レン」）。talk 事件的 cueName
        末段数字才是精确的 characterId，先用它把候选 id 收敛，再取本地化名字。
        '''
        raw_name: str = ev['character']
        own = ev.get('character3dId')
        if own is not None:
            return self._get_chara_name(own) or raw_name, own
        cands = chara3d_map[raw_name]
        want = self._cue_character(ev.get('cueName') or '')
        if want is not None:
            for cid in cands:
                if self._chara3d_character_id(cid) == want:
                    return self._get_chara_name(cid) or raw_name, cid
        for cid in cands:
            localized = self._get_chara_name(cid)
            if localized:
                return localized, cid
        return raw_name, None

    def parse_mc_timeline(
        self, payload: dict[str, Any], jp_payload: dict[str, Any] | None = None
    ) -> str:
        '''解析 mc_timeline / virtual_message 类型（.playable）的对话。

        按内容自动判别格式（无需调用方指定）：
        - sekai.best：文件里带上游预解析的 __timelineParse，直接转事件表；
        - haruki / pjsk.moe：整包对象转储（container + objects），走
          _timeline_events_from_container（cn/tw 需 jp 包当外键）。
        '''
        payload_format = self._timeline_format(payload)
        if payload_format == 'parsed':
            events = self._timeline_events_from_parse(payload)
        elif payload_format == 'container':
            events = self._timeline_events_from_container(payload, jp_payload)
        else:
            logging.warning(
                f"{payload.get('m_Name', payload.get('container', '?'))}: "
                'unknown timeline format, skipped this segment.'
            )
            return ''
        return self._render_timeline_events(events)

    def _timeline_events_from_parse(
        self, playable: dict[str, Any]
    ) -> list[dict[str, Any]]:
        '''sekai.best 的 __timelineParse → 统一事件表。'''
        timeline = playable['__timelineParse']

        # talk 事件只带角色名文本，不带 3d id；用带 character3dId 的事件
        # （spawn）及 meta.characters 建立「角色名文本 → character3dId」映射
        chara3d_map: dict[str, list[int]] = defaultdict(list)
        for chara in timeline['meta']['characters']:
            chara3d_map[chara['name']].append(chara['character3dId'])
        for ev in timeline['events']:
            if 'character3dId' in ev:
                chara3d_map[ev['character']].append(ev['character3dId'])

        events: list[dict[str, Any]] = []
        for ev in timeline['events']:
            ev_type: str = ev['type']
            if ev_type not in ('talk', 'spawn', 'unspawn'):
                continue
            chara_name, cid = self._event_chara_name(ev, chara3d_map)
            events.append(
                {
                    'type': ev_type,
                    'start': ev['start'],
                    'character3dId': cid,
                    'name': chara_name,
                    'serif': ev.get('serif', '') if ev_type == 'talk' else '',
                }
            )
        return events

    def _chara3d_character_id(self, character3dId: int | None) -> int | None:
        '''character3dId → characterId（cue 里的人物编号是后者）。'''
        if character3dId is None:
            return None
        index = self.character3ds_lookup.find_index(character3dId)
        if index == -1:
            return None
        characterId: int = self.character3ds_json[index]['characterId']
        return characterId

    @staticmethod
    def _cue_number(cue: str) -> int:
        '''cue 里的场次序号（voice_mc_xxx_29_14 → 29），用于同组内排序。'''
        match = re.search(r'_(\d+)_(\d+)(?:_[a-z]+)?$', cue)
        return int(match.group(1)) if match else -1

    def _cue_character(self, cue: str) -> int | None:
        '''cue 里的人物：末尾数字即 characterId（_29_14 → 14、_64_26_piapro → 26）；
        合唱行的 90 是占位符，真人在后缀（_90_meiko → 25）。行号可能带字母
        （_14a_90_kaito），所以只从末尾取一段，不做整串匹配。
        '''
        match = re.search(r'_(\d+)(?:_([a-z]+))?$', cue)
        if match is None:
            return None
        number = int(match.group(1))
        if number == 90:
            return self._cue_romaji_character.get(match.group(2) or '')
        return number if 1 <= number <= 26 else None

    # 临时登场角色（只在中途露一面的客串）的台词/登场/退场不放在 <角色>_Talk 轨道，
    # 而是落在这三条通用轨道上，角色由轨道自身的 CharacterId 指定。
    _generic_track_kind: dict[str, str] = {
        'MC Timeline Character Talk Track': 'talk',
        'MC Timeline Character Spawn Track': 'spawn',
        'MC Timeline Character Un Spawn Track': 'unspawn',
    }

    @classmethod
    def _container_timeline_clips(
        cls, container: dict[str, Any]
    ) -> list[dict[str, Any]]:
        '''container 转储里的角色轨道 clip（_Talk / _入場 / _退場 + 三条通用轨道）。

        子轨道自带 CharacterId（即 character3dId），时间与日文原文（m_DisplayName）
        都在 clip 上，唯一缺的是「这个 clip 用哪条台词对象」——见 _match_talk_cues。
        '''
        clips: list[dict[str, Any]] = []
        for obj in container['objects']:
            data = obj['data']
            # Unity 复制轨道会带 ' (1)' 之类的后缀（如 '穂波_Talk (1)'），先剥掉再判类型
            track = re.sub(r' \(\d+\)$', '', data.get('m_Name', ''))
            track_clips = data.get('m_Clips')
            if track_clips is None:
                continue
            if track.endswith('_Talk'):
                kind, name = 'talk', track[: -len('_Talk')]
            elif track.endswith('_入場'):
                kind, name = 'spawn', track[: -len('_入場')]
            elif track.endswith('_退場'):
                kind, name = 'unspawn', track[: -len('_退場')]
            elif track in cls._generic_track_kind:
                kind, name = cls._generic_track_kind[track], ''
            else:
                continue
            for clip in track_clips:
                clips.append(
                    {
                        'type': kind,
                        'start': clip['m_Start'],
                        'display': clip.get('m_DisplayName') or '',
                        'pid': clip['m_Asset']['m_PathID'],
                        'character3dId': data.get('CharacterId'),
                        'track': track,  # 归一化后的轨道名，跨语言一致，用于结构配对
                        'chara_name': name,  # 名字查不到时的兜底显示名（通用轨道为空）
                    }
                )
        return clips

    @staticmethod
    def _container_texts(container: dict[str, Any]) -> list[dict[str, Any]]:
        '''container 转储里的台词对象（CharacterTalkClip：Serif + CueName）。'''
        return [obj['data'] for obj in container['objects'] if 'Serif' in obj['data']]

    def _is_self_describing(
        self, talks: list[dict[str, Any]], texts: list[dict[str, Any]]
    ) -> bool:
        '''这个语言的包是否自带本地化台词（jp / en 是，cn / tw 不是）。

        判据：clip 的 m_DisplayName 能否在本包的 Serif 里找到。jp/en 的
        m_DisplayName 就是本地化文本，命中率 ~100%；cn/tw 保留日文，命中率 0。
        '''
        if not talks:
            return True
        serifs = {text.get('Serif') or '' for text in texts}
        hit = sum(1 for t in talks if t['display'] and t['display'] in serifs)
        return hit >= 0.9 * len(talks)

    @staticmethod
    def _text_key(text: str) -> str:
        '''文本比对键：去掉所有空白（同一条台词在 cn / jp 包里换行、空格可能不同）。'''
        return re.sub(r'\s+', '', text or '')

    def _match_by_text(
        self,
        clips: list[dict[str, Any]],
        texts: list[dict[str, Any]],
        used: set[str] | None = None,
    ) -> dict[int, str]:
        '''按文本把 clip 对到台词对象，返回 pid → CueName（used 里的 cue 不参与）。

        只有两种可判的情形才建立对应：文本唯一命中；或同文多角色但 cue 里的人物
        编号与轨道 CharacterId 一致。仍歧义（如 _90_wonder 全组合唱）就不建立——
        宁可留空，也不按序号猜一个。
        '''
        if used is None:
            used = set()
        pool_by_text: dict[str, list[tuple[int, int | None, str]]] = defaultdict(list)
        for text in texts:
            cue = text.get('CueName') or ''
            pool_by_text[self._text_key(text.get('Serif') or '')].append(
                (self._cue_number(cue), self._cue_character(cue), cue)
            )
        for cands in pool_by_text.values():
            cands.sort(key=lambda c: (c[0], c[1] or 0))

        def candidates(clip: dict[str, Any]) -> list[tuple[int, int | None, str]]:
            return [
                c
                for c in pool_by_text.get(self._text_key(clip['display']), [])
                if c[2] not in used
            ]

        cue_of: dict[int, str] = {}
        # 第一轮：文本唯一可判
        for clip in clips:
            if not clip['display'].strip():
                continue  # 空显示名没有信息量，交给排名对齐
            cands = candidates(clip)
            if len(cands) == 1:
                cue_of[clip['pid']] = cands[0][2]
                used.add(cands[0][2])
        # 第二轮：同文多角色，用人物编号消歧
        for clip in clips:
            if clip['pid'] in cue_of or not clip['display'].strip():
                continue
            character_id = self._chara3d_character_id(clip['character3dId'])
            cands = [
                c
                for c in candidates(clip)
                if c[1] is not None and c[1] == character_id
            ]
            if len(cands) == 1:
                cue_of[clip['pid']] = cands[0][2]
                used.add(cands[0][2])
        return cue_of

    def _rank_mapping(
        self,
        clips: list[dict[str, Any]],
        texts: list[dict[str, Any]],
    ) -> dict[int, str] | None:
        '''按「pid 升序 ↔ 台词对象在转储里的出现顺序」建立对应，自检不过就返回 None。

        这是同一份文件内部的结构关系：Unity 的 m_Asset.m_PathID 与对象落盘顺序同源，
        实测 jp 403/415、en 210/220 个 bundle 严格成立。自检用「display 就在本包
        Serif 集合里」的 clip 当锚点——它们本可以按文本直接定，若按排名得到的 cue
        与之不符，说明这个包的顺序被打乱（如 CharacterTalkClip(Clone) 混排），整体弃用。
        '''
        if not clips or len(clips) != len(texts):
            return None
        ordered = sorted(clips, key=lambda c: c['pid'])
        mapping = {
            clip['pid']: texts[i].get('CueName') or '' for i, clip in enumerate(ordered)
        }
        serif_of = {t.get('CueName') or '': t.get('Serif') or '' for t in texts}
        domain = {t.get('Serif') or '' for t in texts}
        checked = 0
        for clip in clips:
            display = clip['display']
            if not display.strip() or display not in domain:
                continue
            checked += 1
            if serif_of.get(mapping[clip['pid']]) != display:
                return None
        return mapping if checked else None

    def _match_talk_cues(
        self,
        talks: list[dict[str, Any]],
        pool_clips: list[dict[str, Any]],
        pool_texts: list[dict[str, Any]],
    ) -> dict[int, str]:
        '''本语言 talk clip ↔ 台词对象配对，返回 pid → CueName。

        台词对象没有自身 PathID（haruki / pjsk.moe 的转储把它剥掉了），只能间接配，
        且每一步都必须有据可依：
        1) 参考包（jp）内部：文本唯一命中 / cue 人物编号消歧；仍歧义就交给第 2 步；
        2) 参考包内部：pid 排名（_rank_mapping，带锚点自检）——专治 display 与正文
           措辞不一致的行（如显示名「あなたは」、正文「君は」）；
        3) 跨语言：本语言 clip 按「轨道名 + 开始时间」对到参考包同名 clip，继承 cue；
        4) 时间对不上的，再退回文本比对（忽略空白）。
        四步都不成立的行不输出（宁可留空，也不按场次序号猜）。
        '''
        pool_cue = self._match_by_text(pool_clips, pool_texts)

        ranked = self._rank_mapping(pool_clips, pool_texts)
        if ranked is not None:
            pool_used = set(pool_cue.values())
            for clip in pool_clips:
                if clip['pid'] in pool_cue:
                    continue
                cue = ranked[clip['pid']]
                if cue in pool_used:
                    continue
                pool_cue[clip['pid']] = cue
                pool_used.add(cue)

        by_track: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for clip in pool_clips:
            pooled = pool_cue.get(clip['pid'])
            if pooled:
                by_track[clip['track']].append((clip['start'], pooled))

        cue_of: dict[int, str] = {}
        used: set[str] = set()
        for talk in sorted(talks, key=lambda t: t['start']):
            best: tuple[float, str] | None = None
            for start, cue in by_track.get(talk['track'], []):
                if cue in used or abs(start - talk['start']) > 0.05:
                    continue
                if best is None or abs(start - talk['start']) < abs(best[0] - talk['start']):
                    best = (start, cue)
            if best is not None:
                cue_of[talk['pid']] = best[1]
                used.add(best[1])

        leftover = [t for t in talks if t['pid'] not in cue_of]
        if leftover:
            cue_of.update(self._match_by_text(leftover, pool_texts, used))
        return cue_of

    def _timeline_events_from_container(
        self, container: dict[str, Any], jp_container: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        '''haruki / pjsk.moe 的 container 转储 → 统一事件表。'''
        clips = self._container_timeline_clips(container)
        talks = [c for c in clips if c['type'] == 'talk']
        texts = self._container_texts(container)

        if self._is_self_describing(talks, texts):
            # jp / en：m_DisplayName 就是本地化台词，逐条精确，无需配对
            for talk in talks:
                talk['serif'] = talk['display']
            # 例外：个别 clip 的 display 与正文措辞不一致（编辑器标签没同步改）。
            # 这些行用 pid 排名补正文——排名的自检覆盖整个包，通过才采纳。
            domain = {t.get('Serif') or '' for t in texts}
            drifted = [
                t for t in talks if not t['display'].strip() or t['display'] not in domain
            ]
            if drifted:
                ranked = self._rank_mapping(talks, texts)
                if ranked is not None:
                    serif_of = {
                        t.get('CueName') or '': t.get('Serif') or '' for t in texts
                    }
                    for talk in drifted:
                        text = serif_of.get(ranked.get(talk['pid'], ''), '')
                        if text.strip():
                            talk['serif'] = text
        else:
            # cn / tw：本地化文本只在 Serif 里，回填靠 jp 包的 cue 对齐
            jp_clips = self._container_timeline_clips(jp_container) if jp_container else []
            jp_texts = self._container_texts(jp_container) if jp_container else []
            if jp_container is None:
                logging.warning(
                    f"{container.get('container', '?')}: missing jp reference "
                    'bundle, talk lines of this segment cannot be resolved.'
                )
            cue_of = self._match_talk_cues(
                talks, [c for c in jp_clips if c['type'] == 'talk'], jp_texts
            )
            cue2serif = {t.get('CueName') or '': t.get('Serif') or '' for t in texts}
            for talk in talks:
                talk['serif'] = cue2serif.get(cue_of.get(talk['pid'], ''), '')

        events: list[dict[str, Any]] = []
        for clip in clips:
            character3dId = clip['character3dId']
            # 名字优先用服务器语言角色名，查不到（character3ds 缺项）时回退轨道名前缀
            events.append(
                {
                    'type': clip['type'],
                    'start': clip['start'],
                    'character3dId': character3dId,
                    'name': self._get_chara_name(character3dId) or clip['chara_name'],
                    'serif': clip.get('serif', ''),
                }
            )
        return events

    def _render_timeline_events(self, events: list[dict[str, Any]]) -> str:
        '''事件表 → 文本（按时间排列；talk 输出「人名：台词」，其余登场/退场）。'''
        mark_lang = self.reader.mark_lang
        lines: list[str] = []
        for ev in sorted(events, key=lambda e: e['start']):
            ev_type: str = ev['type']
            chara_name: str = ev['name']
            if ev_type == 'talk':
                serif = re.sub(r'\r\n|\r|\n', ' ', ev['serif']).strip()
                if not serif:
                    continue
                chara_name = self._annotate_vs_unit(
                    chara_name, ev['character3dId'], 'paren'
                )
                lines.append(f'{chara_name}{Mark_multi_lang[":"][mark_lang]}{serif}')
            else:
                # 登场 / 退场
                chara_name = self._annotate_vs_unit(
                    chara_name, ev['character3dId'], 'dash'
                )
                lines.append(
                    f'{Mark_multi_lang[ev_type][mark_lang]}{chara_name}'
                    f'{Mark_multi_lang[")"][mark_lang]}'
                )
        return '\n'.join(lines)

    @staticmethod
    def _timeline_format(payload: dict[str, Any]) -> str:
        '''自动判别 timeline 资产格式：sekai.best 的预解析 / haruki、pjsk.moe 的转储。'''
        if '__timelineParse' in payload:
            return 'parsed'
        if 'objects' in payload and 'container' in payload:
            return 'container'
        return 'unknown'

    @staticmethod
    def _is_skip_read(payload: Any) -> bool:
        '''assets 模式（parse=False）读缓存时 util 返回的占位串，不是取包失败。'''
        return isinstance(payload, str) and payload.startswith('ERROR: skip read')

    @staticmethod
    def _brief_error(payload: str) -> str:
        '''错误串只取首段。

        完整错误（含 URL、异常类型）util 的 fetch_url_json 已经打过一条日志，
        这里只补「哪个 record、哪个源」这层上下文，不重复 URL。
        '''
        return payload.split(' || ', 1)[0].removeprefix('ERROR: ')

    async def _fetch_mc(
        self,
        mc_type: str,
        file_type: str,
        assetbundleName: str,
        record: str,
    ) -> tuple[Any, dict[str, Any] | None]:
        '''按 src 顺序取一段 MC 资产，返回 (本语言 payload, jp 对照 payload)。

        一个源必须「本语言包 +（cn/tw 的 timeline 还要）jp 对照包」都拿到才算可用，
        任一缺失（404 等）就整段换下一个源；全失败时返回最后一个错误串。
        各源扩展名不同（.playable / .asset / .json），由 config 模板决定，
        格式化时统一带 file_type，本函数不关心具体后缀。
        '''
        last_error: Any = ''

        def format_urls(urls: list[util.UrlSpec]) -> list[util.UrlSpec]:
            return [
                url.format(
                    mc_type=mc_type,
                    assetbundleName=assetbundleName,
                    file_type=file_type,
                )
                for url in urls
            ]

        for src_name, urls, jp_urls in self.virtual_live_src_urls:
            payload = await self.fetch_url_json(
                format_urls(urls),
                record,
                compress=self.compress_assets,
                skip_read=not self.parse,
            )
            if isinstance(payload, str):
                if self._is_skip_read(payload):
                    return payload, None
                # 换源会静默改变数据来源（尤其离线时可能落到别的源的旧缓存），
                # 这里明确记一条，便于在日志里发现；只报这个源失败，不预告换源。
                logging.warning(
                    f'{record}: {src_name} failed: {self._brief_error(payload)}'
                )
                last_error = payload
                continue

            # 只有「本包没有本地化台词」的语言才需要 jp 对照包，按数据判断：
            # jp / en 的 m_DisplayName 就是本地化文本（自描述），cn / tw / kr 保留日文。
            # 这样新语言不用改代码；sekai.best 的预解析格式也不需要对照。
            need_jp = (
                mc_type == 'timeline'
                and bool(jp_urls)
                and self._timeline_format(payload) == 'container'
            )
            if need_jp:
                talks = [
                    c
                    for c in self._container_timeline_clips(payload)
                    if c['type'] == 'talk'
                ]
                need_jp = not self._is_self_describing(
                    talks, self._container_texts(payload)
                )
            if not need_jp:
                return payload, None

            jp_payload = await self.fetch_url_json(
                format_urls(jp_urls),
                f'{record}:jp',
                compress=self.compress_assets,
                skip_read=not self.parse,
                lang_for_path='jp',
            )
            if isinstance(jp_payload, str):
                if self._is_skip_read(jp_payload):
                    return payload, None
                logging.warning(
                    f'{record}: {src_name} has no jp reference bundle: '
                    f'{self._brief_error(jp_payload)}'
                )
                last_error = jp_payload
                continue
            return payload, jp_payload

        return last_error, None

    def _music_title(self, music_id: int | None) -> str:
        if music_id is None:
            return '?'
        index = self.musics_lookup.find_index(music_id)
        if index == -1:
            return '?'
        return self.musics_json[index]['title']

    async def get(
        self, target: int, timestamp13: int | None = util.LATE_TIMESTAMP13
    ) -> None:
        '''target: virtualLiveId，抓取整场 live 的全部 setlists（MC 台词 + 音乐列表）。

        timestamp13: 只抓 startAt <= timestamp13 的 live
        （None 为不过滤；默认 util.LATE_TIMESTAMP13 = now + 365 天：
        未来一年内纳入，超远未来（一年以上）不抓）
        '''
        if target >= 10000:
            logging.info(f'virtual live {target} does not exist.')
            return
        vl_index = self.virtualLives_lookup.find_index(target)
        if vl_index == -1:
            logging.info(f'virtual live {target} does not exist.')
            return

        vl = self.virtualLives_json[vl_index]
        if timestamp13 is not None and vl['startAt'] > timestamp13:
            logging.info(f'virtual live {target} does not exist.')
            return

        setlists = sorted(vl['virtualLiveSetlists'], key=lambda sl: sl['seq'])

        # 没有台词环节（mc / mc_timeline / virtual_message）的 live 视为不存在
        if not any(
            sl['virtualLiveSetlistType'] in ('mc', 'mc_timeline', 'virtual_message')
            for sl in setlists
        ):
            logging.info(f'virtual live {target} has no talk segments.')
            return

        # 按 seq 顺序组装每一段的输出；MC 类段先发起 fetch
        entries: list[str] = []
        is_mc_block: list[bool] = []  # 与 entries 平行，标记是否为 MC 类块
        pending: list[tuple[dict[str, Any], Any]] = []  # (setlist, fetch result)

        for sl in setlists:
            stype: str = sl['virtualLiveSetlistType']

            if stype == 'music':
                music_id = sl['musicId']
                title = self._music_title(music_id)
                entries.append(f"{sl['seq']} [MUSIC] {music_id}: {title}")
                is_mc_block.append(False)
                continue

            if stype == 'mc':
                mc_type, file_type = 'scenario', 'asset'
            elif stype in ('mc_timeline', 'virtual_message'):
                mc_type, file_type = 'timeline', 'playable'
            else:
                raise ValueError(f'unknown virtualLiveSetlistType: {stype}')

            assetbundleName: str = sl['assetbundleName']

            entry_index = len(entries)
            entries.append(
                f"{sl['seq']} [{stype}] {assetbundleName}"
            )  # 占位，内容稍后替换
            is_mc_block.append(True)
            pending.append(
                (
                    {
                        'entry_index': entry_index,
                        'mc_type': mc_type,
                        'assetbundleName': assetbundleName,
                        'setlist': sl,
                    },
                    self._fetch_mc(
                        mc_type,
                        file_type,
                        assetbundleName,
                        f"vl{target}:{sl['seq']}:{stype}:{assetbundleName}",
                    ),
                )
            )

        results = await asyncio.gather(*[task for _, task in pending]) if pending else []
        pending_results = [payload for payload, _ in results]
        jp_payloads = {
            i: jp for i, (_, jp) in enumerate(results) if isinstance(jp, dict)
        }

        if self.parse and not util.judge_need_skip(*pending_results):
            os.makedirs(self.save_dir, exist_ok=True)

            for i, ((meta, _), result) in enumerate(zip(pending, pending_results)):
                if isinstance(result, str):  # ERROR / Missing asset
                    entries[meta['entry_index']] += f"\n\n{result}"
                    continue
                if meta['mc_type'] == 'timeline':
                    text = self.parse_mc_timeline(result, jp_payloads.get(i))
                else:
                    text = self.parse_mc_scenario(result)
                entries[meta['entry_index']] += f"\n\n{text}" if text else ''

            # 关联活动（events.json 的 virtualLiveId）时在名字后附加 (event_xx)
            event_suffix = ''
            if target in self.virtual_live_event_map:
                event_suffix = f" (event_{self.virtual_live_event_map[target]})"

            filename = util.valid_filename(
                f"{target:0{self.maxlen_id}} {vl['name']}{event_suffix}" + '.txt'
            )
            filepath = os.path.join(self.save_dir, filename)
            util.remove_olds_or_rename_old(filepath, r'(\d+) ')
            with open(filepath, 'w', encoding='utf8') as f:
                # 块内：标题后空一行（\n\n）；块间：MC 块结束后空两行
                # （\n\n\n），music 块后维持一个空行（\n\n）
                out: list[str] = []
                for i, entry in enumerate(entries):
                    if i > 0:
                        out.append('\n\n\n' if is_mc_block[i - 1] else '\n\n')
                    out.append(entry)
                f.write(f"{target} {vl['name']}{event_suffix}\n\n")
                f.write(''.join(out) + '\n')

        logging.info(f'get virtual live {target} done.')

    def tell_ids(self, timestamp13: int | None = None) -> list[int]:
        '''timestamp13: 只返回 startAt <= timestamp13 的 live id（None 为全部）'''
        ret = []
        for vl in self.virtualLives_json:
            if timestamp13 is None or vl['startAt'] <= timestamp13:
                ret.append(vl['id'])
        return ret


class Getters_type(TypedDict):
    reader: Story_reader
    event_getter: Event_story_getter
    card_getter: Card_story_getter
    area_getter: Area_talk_getter
    unit_getter: Unit_story_getter
    self_getter: Self_intro_getter
    special_getter: Special_story_getter
    mysekai_getter: Mysekai_talk_getter
    virtual_getter: Virtual_live_getter


class Run:
    '''一套 getter 的创建与初始化，供 action 与本地 main 复用。'''

    @staticmethod
    def create_getters(
        langs: Iterable[tuple[str, str]] = (('cn', 'cn'),),
        save_dir: str = '.',
        assets_save_dir: str = '.',
        args: dict[str, Any] | None = None,
    ) -> dict[str, Getters_type]:
        '''langs 为 (lang, mark_lang) 元组列表，每语言各建一套 getter，返回值按 lang 为键。'''
        args = {
            **(args or {}),
            'save_dir': save_dir,
            'assets_save_dir': assets_save_dir,
        }

        lang_getters: dict[str, Getters_type] = {}
        for lang, mark_lang in langs:
            reader = Story_reader(lang=lang, mark_lang=mark_lang, **args)
            lang_getters[lang] = {
                'reader': reader,
                'event_getter': Event_story_getter(reader, **args),
                'card_getter': Card_story_getter(reader, **args),
                'area_getter': Area_talk_getter(reader, **args),
                'unit_getter': Unit_story_getter(reader, **args),
                'self_getter': Self_intro_getter(reader, **args),
                'special_getter': Special_story_getter(reader, **args),
                'mysekai_getter': Mysekai_talk_getter(reader, **args),
                'virtual_getter': Virtual_live_getter(reader, **args),
            }
        return lang_getters

    @staticmethod
    async def init_getters(
        lang_getters: dict[str, Getters_type],
        session: ClientSession,
        init_names: Sequence[str] | None = None,
    ) -> None:
        '''
        reader 最先 init：各 getter 的 init 依赖 reader 的 master 数据
        （如 events_json / gameCharacterUnits）；其余 getter 并发 init。
        init_names 为 None 时 init 除 reader 外的全部 getter；多语言逐套迭代该
        参数（每套一遍），需可重复迭代故标 Sequence 而非 Iterable。
        '''
        await asyncio.gather(
            *[
                cast(Pjsk_fetcher, getters['reader']).init(session)
                for getters in lang_getters.values()
            ]
        )

        if init_names is None:
            sample = next(iter(lang_getters.values()))
            init_names = tuple(name for name in sample.keys() if name != 'reader')

        await asyncio.gather(
            *[
                cast(Pjsk_fetcher, getters[name]).init(session)  # type: ignore[literal-required]
                for getters in lang_getters.values()
                for name in init_names
            ]
        )


async def main():

    logging.basicConfig(level=logging.INFO)

    net_connect_limit = 20

    online = False

    text_lang = 'cn'
    mark_lang = 'cn'

    lang_getters = Run.create_getters(
        ((text_lang, mark_lang),), args={'online': online}
    )
    getters = lang_getters[text_lang]

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=net_connect_limit)
    ) as session:
        await Run.init_getters(lang_getters, session)

        tasks = []

        for i in range(1, 3):
            tasks.append(getters['unit_getter'].get(i))
        for i in range(1, 4):
            tasks.append(getters['event_getter'].get(i))
        for i in range(1, 4):
            tasks.append(getters['card_getter'].get(i))
        for i in range(1, 4):
            tasks.append(getters['area_getter'].get(i))
        for i in range(1, 3):
            tasks.append(getters['self_getter'].get(i))
        for i in range(1, 5):
            tasks.append(getters['special_getter'].get(i))
        for i in range(1, 5):
            tasks.append(getters['mysekai_getter'].get_id(i))
        for i in range(1, 4):
            tasks.append(getters['virtual_getter'].get(i))

        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
