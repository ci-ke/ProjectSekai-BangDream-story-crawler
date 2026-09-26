import os, asyncio, json, logging, re
from pathlib import Path
from collections.abc import Iterable
from enum import Enum
from typing import Any, Callable
from asyncio import Semaphore

from aiohttp import ClientSession, TCPConnector

from . import util
from .util import Mark_multi_lang

CONFIG: dict[str, Any] = json.load(
    open(Path(__file__).parent / 'config.json', encoding='utf8')
)
URLS: dict[str, Any] = CONFIG['urls_bdon']['bdon.moe']
_SAVE_ROOTS: dict[str, str] = URLS['save_roots']  # 服务基址 → 存盘根

# 输出语言列表：(输出语言, 标记语言)。剧本 Text 表自带 5 语言，
# 每个脚本只需抓一次即可输出全部语言目录；按需增删此表即可。
LANGS: tuple[tuple[str, str], ...] = (
    ('cn', 'cn'),
    ('tw', 'cn'),
    ('jp', 'en'),
    ('en', 'en'),
    ('kr', 'en'),
)


class Constant:
    # 输出语言 → 剧本 Text 表的多语言字段名
    text_field = {
        'jp': 'japanese',
        'en': 'english',
        'tw': 'traditionalChinese',
        'cn': 'simplifiedChinese',
        'kr': 'korean',
    }

    # 目标语言缺失时的回落链（同 bdon.moe 站点 localizeMasterText，zh 取简中）
    fallback_chain = {
        'cn': (
            'simplifiedChinese',
            'traditionalChinese',
            'japanese',
            'english',
            'korean',
        ),
        'tw': (
            'traditionalChinese',
            'simplifiedChinese',
            'japanese',
            'english',
            'korean',
        ),
        'jp': ('japanese', 'english', 'simplifiedChinese', 'korean'),
        'kr': ('korean', 'english', 'japanese', 'simplifiedChinese'),
        'en': ('english', 'japanese', 'simplifiedChinese', 'korean'),
    }

    # 回落时行尾标注实际使用的语言（键为 Text 表字段名；与目标语言一致时不标注）
    fallback_mark = {
        'japanese': {'cn': '〔日文〕', 'en': '[ja]'},
        'english': {'cn': '〔英文〕', 'en': '[en]'},
        'traditionalChinese': {'cn': '〔繁中〕', 'en': '[zh-Hant]'},
        'simplifiedChinese': {'cn': '〔简中〕', 'en': '[zh-Hans]'},
        'korean': {'cn': '〔韩文〕', 'en': '[ko]'},
    }

    band_id_name = {
        1: 'mygo',
        2: 'mujica',
        3: 'yumemita',
        4: 'millsage',
        5: 'kadan',
    }


# Episode 表 _command 列的枚举（游戏内类型名 AdvCommand，见剧本表 _header 列定义）。
# 游戏 2026-09-24 才上线、无公开枚举对照，以下语义由全量 946 个 Episode 表（约 13 万行）
# 的字段关联审计推导（2026-09-25）：【实测】= 站点解析器行为或资源名/字段自证；
# 【推断】= 仅由字段相关性得出，命名未必与游戏内部一致，待后续修正。
# 审计中未出现的值（8/22/40/41/42/45/55/58）不收录；新版本新增值在解析时退回裸数值。
class AdvCommand(int, Enum):
    CharacterIn = 0            # 【推断】targetName=角色名 + positionType 100% + duration 91%，角色移入/入场
    CharacterOut = 1           # 【推断】同 0 但 duration 56%、positionType 23%，角色移出/退场
    Talk = 2                   # 【实测】对话：说话人 + 文本 + 语音（站点解析器）
    Wait = 3                   # 【实测】等待 duration 秒（duration 100%）
    WaitParam = 4              # 【推断】duration 100% + parameter1 99%，带参数的条件等待？
    TransitionIn = 5           # 【推断】转场，少量携带 adv_transition_*，与 6 成对、方向未定
    TransitionOut = 6          # 【推断】转场，同上
    MoveCamera = 7             # 【实测】cameraDistance 93% + positionType 99%，相机移动到目标站位
    Op9 = 9                    # positionType 100%，仅 74 行
    Op10 = 10                  # positionType 96%，仅 72 行
    Op11 = 11                  # duration 71%，仅 112 行
    Op12 = 12                  # parameter1 100% + positionType 22%
    Op13 = 13                  # positionType 100% + parameter1 100%
    Op14 = 14                  # 同 13
    PlayBgm = 15               # 【实测】bgmID 52%（PlayBgm 指令，报告推断）
    Op16 = 16                  # duration 66% + parameter1 100%
    SetExpression = 17         # 【实测】expressionName 100%，切换表情
    Op18 = 18                  # targetName 99%（角色相关）
    Op19 = 19                  # targetName 100%（角色相关）
    Telop = 20                 # 【实测】场景字幕（地点/时间标题卡；全量 573 条均无句读，等价 pjsk 的 Telop，站点误作 narration）
    CharacterMotion = 21       # 【实测】motionName 96% + expressionName 99%，角色动作+表情同步（行数与对话同量级）
    LoadCharacterModel = 23    # 【推断】targetName + targetAssetName 100%（Live2D 模型路径），登场/换装
    Op24 = 24                  # targetName 100%（角色相关）
    ChangeBackground = 25      # 【实测】targetAssetName 100% = adv_bkg_*（站点解析器 + 资源名自证）
    Clip = 26                  # 【实测】带 videoID = 播放视频（14 行；1 行无 videoID，站点解析器忽略）
    SkippableClip = 27         # 【实测】双语义：带 videoID = 播放视频（24 行）；无 videoID 且
                               # parameter3 = SkipClipTarget = 视频结束/跳过恢复点（24 行）
    ClipLine = 28              # 【实测】视频字幕行：454 行全部位于视频段内（916 个无视频脚本 0 行），
                               # 其中 406 行带 targetName（模型名），48 行无说话人
    Op29 = 29                  # 仅 12 行
    ShowStill = 30             # 【实测】targetAssetName 100% = adv_still_*（站点解析器 + 资源名自证）
    PlaySe = 31                # 【实测】seID 99%
    Op32 = 32                  # targetName 100% + parameter1 100%
    Op33 = 33                  # 仅 1 行
    Op34 = 34                  # duration 54% + parameter1 100%
    ChangeTalkWindow = 35      # 【实测】targetAssetName = UICenterTalkWindow / UIDefaultTalkWindow
    ChatOpen = 36              # 【推断】说话人 + targetTextIDs + targetChatID，无文本，打开聊天窗口
    ChatMessage = 37           # 【实测】聊天气泡（带文本 + targetChatID，站点解析器遗漏）
    ChatStamp = 38             # 【实测】聊天贴图（adv_data_chat_*_stamp + System）
    Op39 = 39                  # 仅 1 行
    PostEffect = 43            # 【实测】targetAssetName = adv_effect_posteffect_*（含 reminiscence 回忆滤镜）
    FrameOverlay = 44          # 【实测】targetAssetName = adv_frame_*（遮幅/相框/速度线等）
    CharacterTransform1 = 46   # 【推断】targetName 100% + parameter1 93% + duration 64%，角色变形/位移
    CharacterTransform2 = 47   # 【推断】parameter1 100%
    CharacterTransform3 = 48   # 【推断】parameter1 100%
    CharacterTransform4 = 49   # 【推断】parameter1 100% + positionType 76%
    Op50 = 50                  # duration 19% + parameter1 99%
    Op51 = 51                  # duration 48%
    PlayVoice = 52             # 【实测】voiceIDs 100%（仅 7 行）
    Op53 = 53                  # duration 76% + parameter1 100%
    StageEffect = 54           # 【实测】targetAssetName = adv_effect_spotlight / adv_effect_stage_*
    Op56 = 56                  # 仅 57 行
    Op57 = 57                  # parameter1 100%
    Op59 = 59                  # 仅 688 行
    Op60 = 60                  # positionType 100%
    Op61 = 61                  # positionType 100%
    Op62 = 62                  # positionType 100%
    Op63 = 63                  # positionType 100%
    Op64 = 64                  # positionType 100%
    ChatMessageEx = 65         # 【实测】聊天气泡变体（带文本，站点解析器遗漏）
    CharacterMoveTo = 66       # 【推断】targetName 100% + positionType 100% + duration 75%，与 0 近似
    Op67 = 67                  # duration 85% + parameter1 100%
    Op68 = 68                  # motionName 57%，仅 14 行
    Op69 = 69                  # targetName 100%，仅 65 行


def normalize_rows(table_json: Any) -> list[dict[str, Any]]:
    """剥离 master/剧本表 _allData 行字段的前导下划线；抓取失败（字符串）时返回空。"""
    if isinstance(table_json, str):
        return []
    return [
        {k[1:] if k.startswith('_') else k: v for k, v in row.items()}
        for row in table_json.get('_allData', [])
    ]


# TextMeshPro 富文本标签全集（与站点解析器一致）：纯文本输出时剥除，未知标签原样保留
RICH_TAGS = frozenset((
    'align', 'alpha', 'b', 'br', 'color', 'cspace', 'font', 'font-weight', 'gradient', 'i',
    'indent', 'line-height', 'line-indent', 'link', 'lowercase', 'margin', 'mark', 'mspace',
    'nobr', 'noparse', 'page', 'pos', 'r', 'rotate', 'ruby', 's', 'size', 'smallcaps', 'space',
    'sprite', 'strikethrough', 'style', 'sub', 'sup', 'u', 'uppercase', 'voffset', 'width',
))
RICH_TAG = re.compile(r'<(/?)([a-zA-Z][a-zA-Z-]*)(?:\s*=\s*"?[^">]*"?)?\s*>')


def strip_rich_text(text: str) -> str:
    """剥除 TextMeshPro 富文本标签；<br> 转换行，标签外的正文保留。"""
    def replace(match: re.Match[str]) -> str:
        name = match.group(2).lower()
        if name not in RICH_TAGS:
            return match.group(0)
        return '\n' if name == 'br' else ''

    return RICH_TAG.sub(replace, text)


class Bdon_fetcher(util.Base_fetcher):
    @staticmethod
    def __url_to_save_path(url: str) -> str:
        # 存盘路径 = 剥掉基址（config 的 save_roots：基址 → 存盘根）后的资源路径
        for base, root in _SAVE_ROOTS.items():
            if url.startswith(base):
                return os.path.join(root, url[len(base) :])
        raise RuntimeError(url)

    async def fetch_url_json(
        self,
        url: str | list[str],
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
    ) -> Any:
        assert append_save_path is None

        urls = [url] if isinstance(url, str) else url
        append_save_path = Bdon_fetcher.__url_to_save_path(urls[0])

        return await super().fetch_url_json(
            url,
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


class Story_reader(Bdon_fetcher):
    def __init__(
        self,
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        missing_download: bool = True,
        debug_parse: bool = False,
        cg_add_link: bool = True,
        force_master_online: bool = False,
        **args,
    ) -> None:
        super().__init__(
            assets_save_dir,
            online,
            save_assets,
            missing_download,
            False,
            force_master_online,
        )

        self.debug_parse = debug_parse
        self.cg_add_link = cg_add_link

        # 过场大图（cmd 30）链接：assets.bdon.moe 发布服务；图片语言固定 zh-Hans，与站点行为一致。
        # 注意比 legacy 桶 S3 key 多一层 <name>/ 段且为 .webp；全量 333 张中 21 张上游未导出（死链不可避免）。
        self.cg_link = 'https://assets.bdon.moe/zh-Hans/Adv/Still/{dir}/{name}/data/{name}/{name}.webp'
        # 视频（cmd 26/27）链接：Video 表 assetName → Cri/Video/<path>/<name>.mp4，语言段同样固定 zh-Hans。
        self.video_link = 'https://assets.bdon.moe/zh-Hans/Cri/Video/{path}/{name}.mp4'

    async def init(
        self,
        session: ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
    ) -> None:
        await super().init(session, network_semaphore)

        master_tables = (
            'MasterAdv',
            'MasterText',
            'MasterCharacter',
            'MasterBand',
            'MasterStoryChapter',
            'MasterStoryEpisode',
            'MasterStoryFriendshipEpisode',
            'MasterCharacterFriendship',
            'MasterStoryLiveResultEpisode',
            'MasterStoryHomeSpotTapTalkEpisode',
            'MasterHomeSpot',
            'MasterBiliAnimeStillSubTitle',
        )
        jsons = await asyncio.gather(
            *[
                self.fetch_url_json(
                    URLS['master'].format(table=table),
                    force_online=self.force_master_online,
                )
                for table in master_tables
            ]
        )
        rows = {
            table: normalize_rows(json) for table, json in zip(master_tables, jsons)
        }

        # 注意：Master 表字段大小写不统一，MasterCharacter/MasterBand 为 nameTextID（大写 ID），
        # 其余多为 nameTextId/advId（小写 d）；剧本 Episode 表为 advTextID（大写 ID）。
        self.master_text = {str(row['id']): row for row in rows['MasterText']}
        self.advs = {row['id']: row for row in rows['MasterAdv']}
        self.characters = {row['id']: row for row in rows['MasterCharacter']}
        self.bands = {row['id']: row for row in rows['MasterBand']}
        self.story_chapters = rows['MasterStoryChapter']
        # 剧情表各自以本表 _id 为键（getter 的入口 id），行内 advId 用于定位脚本
        self.story_episodes = {row['id']: row for row in rows['MasterStoryEpisode']}
        self.friendship_episodes = {
            row['id']: row for row in rows['MasterStoryFriendshipEpisode']
        }
        self.live_result_episodes = {
            row['id']: row for row in rows['MasterStoryLiveResultEpisode']
        }
        self.home_talk_episodes = {
            row['id']: row for row in rows['MasterStoryHomeSpotTapTalkEpisode']
        }
        self.friendships = {
            row['id']: row for row in rows['MasterCharacterFriendship']
        }
        self.home_spots = {row['id']: row for row in rows['MasterHomeSpot']}
        # 动画 still 内嵌文字的翻译（站点用 MasterBiliAnimeStillSubTitle 叠加显示字幕）：
        # asset 名 → [(episodeIndexOpen, episodeIndexClose, textID)]
        self.still_captions: dict[str, list[tuple[int, int, str]]] = {}
        for row in rows['MasterBiliAnimeStillSubTitle']:
            asset = str(row.get('episodeAssetName') or '')
            if asset and row.get('textID'):
                self.still_captions.setdefault(asset, []).append(
                    (
                        int(row.get('episodeIndexOpen') or 0),
                        int(row.get('episodeIndexClose') or 0),
                        str(row['textID']),
                    )
                )
        self.home_spots_by_adv = {
            row['advId']: row for row in rows['MasterHomeSpot'] if row.get('advId')
        }
        # 被各剧情主表引用的 advId（归属判定时引用优先于脚本名前缀）
        self.referenced_advs: set[int] = (
            {row['advId'] for row in self.story_episodes.values()}
            | {row['advId'] for row in self.friendship_episodes.values()}
            | {row['advId'] for row in self.live_result_episodes.values()}
            | {row['advId'] for row in self.home_talk_episodes.values()}
            | set(self.home_spots_by_adv)
        )

    def localize_row(
        self, text_row: dict[str, Any] | None, lang: str
    ) -> tuple[str | None, str | None]:
        """按回落链取目标语言文本，返回 (文本, 实际使用的字段名)。"""
        if text_row is None:
            return None, None
        for field in Constant.fallback_chain[lang]:
            value = text_row.get(field)
            if value:
                return value, field
        return None, None

    def get_text_marked(
        self, text_row: dict[str, Any] | None, lang: str, mark_lang: str
    ) -> str:
        """台词文本：剥除富文本标签；缺失时按回落链取值并在行尾标注实际语言。"""
        text, field = self.localize_row(text_row, lang)
        if text is None:
            return ''
        text = strip_rich_text(text)
        if field and field != Constant.text_field[lang]:
            text += Constant.fallback_mark[field][mark_lang]
        return text

    def get_master_text(self, text_id: Any, lang: str) -> str | None:
        """MasterText 文案（标题/章节/角色名等），不附回落标注。"""
        if not text_id:
            return None
        text, _ = self.localize_row(self.master_text.get(str(text_id)), lang)
        return text

    def get_adv_title(self, adv_id: int, lang: str) -> str:
        adv = self.advs.get(adv_id)
        if adv is None:
            return ''
        return self.get_master_text(adv.get('titleTextId'), lang) or ''

    def get_chara_name(self, chara_id: Any, lang: str, short: bool = False) -> str:
        chara = self.characters.get(chara_id)
        if chara is None:
            return ''
        key = 'shortNameTextID' if short else 'nameTextID'
        return self.get_master_text(chara.get(key), lang) or ''

    def get_band_name(self, band_id: Any, lang: str) -> str:
        band = self.bands.get(band_id)
        if band is None:
            return Constant.band_id_name.get(band_id, '')
        return (
            self.get_master_text(band.get('nameTextID'), lang)
            or Constant.band_id_name.get(band_id, '')
        )

    def get_still_caption(self, asset: str, index: Any, lang: str) -> str:
        """动画 still 图内文字（站点由 MasterBiliAnimeStillSubTitle 叠加显示）。
        行号需落在条目区间内；日文列是图内文字的原文转录，jp 直接取用（为空则无，
        不回落其他语言），其余语言按回落链取翻译。不在显示区间内的重现不配说明。"""
        if index is None:
            return ''
        try:
            position = int(index)
        except (TypeError, ValueError):
            return ''
        for open_, close_, text_id in self.still_captions.get(asset, ()):
            if open_ <= position <= close_:
                row = self.master_text.get(str(text_id))
                if lang == 'jp':
                    caption = (row or {}).get('japanese') or ''
                else:
                    caption = self.get_master_text(text_id, lang) or ''
                return re.sub(r'\s*\n+\s*', ' ', strip_rich_text(caption)).strip()
        return ''

    def read_script(
        self,
        episode_json: dict[str, Any] | str,
        text_json: dict[str, Any] | str,
        video_json: dict[str, Any] | str,
        lang: str,
        mark_lang: str,
    ) -> str:
        if isinstance(episode_json, str):
            return episode_json
        if isinstance(text_json, str):
            return text_json

        episode_rows = normalize_rows(episode_json)
        text_lookup = {str(row['id']): row for row in normalize_rows(text_json)}
        video_rows = {
            int(row['id']): row
            for row in normalize_rows(video_json)
            if row.get('id') is not None
        }

        body = ''
        telop_pending = False  # Telop 之后的下一条输出需先补一个空行（Telop 独立段落、上下恰好各一空行）
        last_marker = ''  # 上一条输出的背景标记资源名；仅相邻同资源的背景切换去重，台词输出后清空
        last_chat_line = ''  # 上一条手机消息行：相邻完全相同的消息重发行（渲染对）只出一次
        shown_still: str | None = None  # 当前显示中的过场大图（站点同款语义：再次点名 = 隐藏）
        last_still: str | None = None  # 最近一次输出过的大图资源；背景切换后允许再次输出

        # 遍历 Episode 指令流（数组顺序即剧本顺序，勿用 _index 当行号）
        in_clip = False  # 视频播放中：26/27 带 videoID 开始，27 带 SkipClipTarget 参数结束
        for row in episode_rows:
            raw_command: Any = row.get('command')
            try:
                command = AdvCommand(raw_command)
            except ValueError:
                command = raw_command  # 新版本新增指令：退回裸数值
            if command in (AdvCommand.Clip, AdvCommand.SkippableClip):
                video_id = row.get('videoID')
                video_row = video_rows.get(int(video_id)) if video_id else None
                if video_row and video_row.get('assetName'):
                    # 视频段开始：输出视频链接与 Video 表的场景说明（note 为官方日文原文）
                    in_clip = True
                    if telop_pending:
                        body += '\n'
                        telop_pending = False
                    path = str(video_row['assetName']).replace('\\', '/').strip('/')
                    body += (
                        Mark_multi_lang['video'][mark_lang]
                        + self.video_link.format(path=path, name=path.rsplit('/', 1)[-1])
                        + Mark_multi_lang[')'][mark_lang]
                        + '\n'
                    )
                    note = str(video_row.get('note') or '').replace('\n', ' ').strip()
                    if note:
                        body += Mark_multi_lang['still caption'][mark_lang] + note + '\n'
                    last_marker = ''
                    last_chat_line = ''
                elif row.get('parameter3') == 'SkipClipTarget':
                    in_clip = False
            adv_text_id = row.get('advTextID')

            if adv_text_id:
                # 凡 _advTextID 非空即有文本输出（Talk / Telop / ChatMessage / ChatMessageEx /
                # ClipLine 均可携带），不按 command 白名单筛选，否则会丢聊天气泡与视频字幕
                text = self.get_text_marked(
                    text_lookup.get(str(adv_text_id)), lang, mark_lang
                ).replace('\n', ' ')
                if not text.strip():
                    continue  # 文本缺失/全空的行不输出（站点同样跳过），避免孤立的"说话人："

                if command is AdvCommand.ClipLine and in_clip:
                    # 视频字幕行（全语料仅存在于视频段内）：带 targetName（模型名）时附在标记后
                    if telop_pending:
                        body += '\n'
                        telop_pending = False
                    subtitle_name = row.get('targetName') or ''
                    if subtitle_name and mark_lang != 'cn':
                        subtitle_name = ' ' + subtitle_name  # 英文标记与名字间补空格
                    body += (
                        Mark_multi_lang['subtitle'][mark_lang]
                        + subtitle_name
                        + Mark_multi_lang[':'][mark_lang]
                        + text
                        + '\n'
                    )
                    last_marker = ''
                    last_chat_line = ''
                elif command is AdvCommand.Telop:  # 场景字幕，独立段落（pjsk Telop 样式：上下恰好各一空行，不叠加）
                    if body and not body.endswith('\n\n'):
                        body += '\n'
                    body += (
                        Mark_multi_lang['['][mark_lang]
                        + text
                        + Mark_multi_lang[']'][mark_lang]
                        + '\n'
                    )
                    telop_pending = True
                    last_marker = ''
                    last_chat_line = ''
                else:
                    # 说话人可多人（_targetTextIDs 列表），逐个解析后用英文 " & " 连接
                    names = []
                    for target_id in row.get('targetTextIDs') or []:
                        speaker_row = text_lookup.get(str(target_id))
                        name = (
                            self.get_text_marked(speaker_row, lang, mark_lang)
                            if speaker_row
                            else ''
                        )
                        names.append((name or target_id).replace('\n', ' '))
                    speaker = (
                        ' & '.join(names) if names else (row.get('targetName') or '')
                    )
                    line = f"{speaker}{Mark_multi_lang[':'][mark_lang]}{text}\n"
                    if command is AdvCommand.ChatMessage or command is AdvCommand.ChatMessageEx:
                        # 手机消息（聊天窗气泡）：行前加（消息）标记；相邻完全相同的消息重发行只出一次
                        line = Mark_multi_lang['message'][mark_lang] + line
                        if line != last_chat_line:
                            if telop_pending:
                                body += '\n'
                                telop_pending = False
                            body += line
                            last_chat_line = line
                    else:
                        if telop_pending:
                            body += '\n'
                            telop_pending = False
                        body += line
                        last_chat_line = ''
                    last_marker = ''
            elif command is AdvCommand.ChangeBackground:  # 切换背景（背景图仅在 legacy 桶，此处只留标记）
                bg_asset = str(row.get('targetAssetName') or '')
                if not bg_asset:
                    continue  # 无资源的背景指令：站点忽略
                # 仅相邻同资源的背景切换去重；不同资源的连续背景切换各自保留
                if last_marker != f'bg:{bg_asset}':
                    if telop_pending:
                        body += '\n'
                        telop_pending = False
                    body += Mark_multi_lang['background'][mark_lang] + '\n'
                    last_marker = f'bg:{bg_asset}'
                    last_chat_line = ''
                    last_still = None  # 场景已切换：同一张大图可在新场景中重现
            elif command is AdvCommand.ShowStill:  # 过场大图（站点同款状态机）
                asset = str(row.get('targetAssetName') or '').replace('\\', '/').strip('/')
                if not asset:
                    continue
                if asset == shown_still:
                    shown_still = None  # 再次点名当前显示中的大图 = 隐藏，不输出
                else:
                    shown_still = asset
                    # 背景未切换时同一张大图只输出一次；切换后重现（新场景）照常输出
                    if asset != last_still:
                        last_still = asset
                        dir_name, still_name = (
                            asset.split('/')[0],
                            asset.rsplit('/', 1)[-1],
                        )
                        if telop_pending:
                            body += '\n'
                            telop_pending = False
                        if self.cg_add_link:  # 仿 pjsk：链接替换资源名
                            cg_text = self.cg_link.format(dir=dir_name, name=still_name)
                        else:
                            cg_text = still_name
                        body += (
                            Mark_multi_lang['cg'][mark_lang]
                            + cg_text
                            + Mark_multi_lang[')'][mark_lang]
                            + '\n'
                        )
                        caption = self.get_still_caption(asset, row.get('index'), lang)
                        if caption:
                            body += (
                                Mark_multi_lang['still caption'][mark_lang]
                                + caption
                                + '\n'
                            )
                        last_marker = ''
                        last_chat_line = ''
            elif self.debug_parse:
                body += f"cmd-{command}: {row.get('targetName')}\n"

        return body.strip()


class Bdon_getter(Bdon_fetcher, util.Base_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str,
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        super().__init__(
            save_dir,
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )

        self.reader = reader

    def tell_ids(self) -> list[int]:
        """该类别各自 master 表的全部 id，升序。"""
        raise NotImplementedError

    async def get(self, master_id: int, langs: Iterable[tuple[str, str]] = LANGS) -> None:
        raise NotImplementedError

    async def fetch_script(self, script: str) -> tuple[Any, Any, Any]:
        episode_json, text_json = await asyncio.gather(
            self.fetch_url_json(
                URLS['episode_asset'].format(script=script),
                script,
                compress=self.compress_assets,
                skip_read=not self.parse,
            ),
            self.fetch_url_json(
                URLS['text_asset'].format(script=script),
                script,
                compress=self.compress_assets,
                skip_read=not self.parse,
            ),
        )
        # 仅引用了视频的脚本（全语料 30 个）才抓 Video 表（含视频 URL 的 assetName 与场景说明 note）
        video_json: Any = ''
        if isinstance(episode_json, dict) and any(
            row.get('_videoID') for row in episode_json.get('_allData', [])
        ):
            video_json = await self.fetch_url_json(
                URLS['video_asset'].format(script=script),
                script,
                compress=self.compress_assets,
                skip_read=not self.parse,
            )
        return episode_json, text_json, video_json

    async def write_script(
        self,
        adv_id: int,
        script: str,
        langs: Iterable[tuple[str, str]],
        index_regex: str,
        path_of: Callable[[str], str],
        title_of: Callable[[str], str],
        synopsis_of: Callable[[str], str | None],
    ) -> None:
        """抓取剧本两表并向各语言目录写出；文件头首行固定 `advId:脚本名 标题`
        （advId = MasterAdv._id，对应站点 /story/<advId>）。
        index_regex 匹配文件名中稳定的首段索引用于改名/清理。"""
        episode_json, text_json, video_json = await self.fetch_script(script)

        if not self.parse:
            logging.info(f'fetch bdon script {script} done (assets only).')
            return

        if (
            isinstance(episode_json, str)
            or isinstance(text_json, str)
            or (isinstance(video_json, str) and video_json)
        ):
            # 'ERROR: ...'（抓取失败）或 'Missing asset'（离线且本地缺失）；
            # video_json 非空串的 str 同为失败（无视频的脚本为空串，放行）
            logging.warning(f'skip bdon script {script} (fetch failed).')
            return

        for lang, mark_lang in langs:
            file_path = path_of(lang)
            os.makedirs(os.path.split(file_path)[0], exist_ok=True)
            util.remove_olds_or_rename_old(file_path, index_regex)
            title = title_of(lang)
            name = f'{adv_id}:{script} {title}'.strip() if title else f'{adv_id}:{script}'
            with open(file_path, 'w', encoding='utf8') as f:
                f.write(name + '\n\n')
                synopsis = synopsis_of(lang)
                if synopsis:
                    f.write(synopsis.replace('\n', ' ') + '\n\n')
                f.write(
                    self.reader.read_script(
                        episode_json, text_json, video_json, lang, mark_lang
                    )
                    + '\n'
                )

        logging.info(f'get bdon script {script} done.')


class Band_story_getter(Bdon_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_{lang}/band',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_chapterId_episodeNumber: tuple[int, int] = (2, 2),
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        super().__init__(
            reader,
            save_dir,
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )
        self.maxlen_chapterId_episodeNumber = maxlen_chapterId_episodeNumber

    def tell_ids(self) -> list[int]:
        return sorted(self.reader.story_episodes)  # MasterStoryEpisode._id

    async def get(self, episode_id: int, langs: Iterable[tuple[str, str]] = LANGS) -> None:
        reader = self.reader
        episode = reader.story_episodes[episode_id]
        adv_id: int = episode['advId']
        script: str = reader.advs[adv_id]['advEpisodeAsset']
        chapter = next(
            c for c in reader.story_chapters if c['id'] == episode['chapterId']
        )
        band_id = chapter['bandId']
        chapter_id: int = chapter['id']
        ep_number: int = episode['episodeNumber']
        is_another: bool = bool(episode['isAnotherEpisode'])
        is_extra: bool = bool(episode['isExtraEpisode'])
        chara_id = episode.get('characterId')
        description_id = episode.get('descriptionTextId')

        def filename(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            # 编号 = 章节-话（均为主表原值）：视角故事（another story）的 episodeNumber 1..5 与正篇重叠，
            # 用 another- 前缀并附角色名；番外（extra）的 episodeNumber 为 21..23，用 extra- 前缀
            chapter_episode = (
                f'{chapter_id:0{self.maxlen_chapterId_episodeNumber[0]}d}'
                + f'-{ep_number:0{self.maxlen_chapterId_episodeNumber[1]}d}'
            )
            prefix = 'another-' if is_another else 'extra-' if is_extra else ''
            return util.valid_filename(f'{prefix}{chapter_episode} {title_of(lang)}' + '.txt')

        def path_of(lang: str) -> str:
            chapter_name = reader.get_master_text(chapter['nameTextId'], lang)
            folder = util.valid_filename(
                f'{band_id:02d} {reader.get_band_name(band_id, lang)}'
                + (f'：{chapter_name}' if chapter_name else ''),
                True,
            )
            return os.path.join(self.save_dir.format(lang=lang), folder, filename(lang))

        def title_of(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            # 视角故事标题后附角色短名（文件名与文件头一致）
            if is_another:
                chara_name = reader.get_chara_name(chara_id, lang, short=True)
                if chara_name:
                    title = f'{title} ({chara_name})' if title else chara_name
            return title

        def synopsis_of(lang: str) -> str | None:
            return reader.get_master_text(description_id, lang)

        await self.write_script(
            adv_id,
            script,
            langs,
            r'(another-\d+-\d+|extra-\d+-\d+|\d+-\d+) ',
            path_of,
            title_of,
            synopsis_of,
        )


class Friendship_story_getter(Bdon_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_{lang}/friendship',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_friendshipId_episodeNumber: tuple[int, int] = (4, 2),
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        super().__init__(
            reader,
            save_dir,
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )
        self.maxlen_friendshipId_episodeNumber = maxlen_friendshipId_episodeNumber

    def tell_ids(self) -> list[int]:
        return sorted(self.reader.friendship_episodes)  # MasterStoryFriendshipEpisode._id

    async def get(self, episode_id: int, langs: Iterable[tuple[str, str]] = LANGS) -> None:
        reader = self.reader
        episode = reader.friendship_episodes[episode_id]
        adv_id: int = episode['advId']
        script: str = reader.advs[adv_id]['advEpisodeAsset']
        pair = reader.friendships[episode['characterFriendshipId']]
        id_a, id_b = pair['masterCharacterIdA'], pair['masterCharacterIdB']
        # 组合编号直接用 master 的 friendshipId（角色A id + 角色B id 拼接码，如 102=灯×爱音），
        # 不连续但稳定；补零到 4 位保证目录按数值排序
        friendship_id: int = pair['id']
        ep_number: int = episode['episodeNumber']

        def path_of(lang: str) -> str:
            folder = util.valid_filename(
                f'{friendship_id:0{self.maxlen_friendshipId_episodeNumber[0]}d} '
                + f'{reader.get_chara_name(id_a, lang)}×{reader.get_chara_name(id_b, lang)}',
                True,
            )
            return os.path.join(self.save_dir.format(lang=lang), folder, filename(lang))

        def filename(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            # 文件名带完整编号 friendshipId-话号（如 0102-01），全局唯一
            return util.valid_filename(
                f'{friendship_id:0{self.maxlen_friendshipId_episodeNumber[0]}d}'
                + f'-{ep_number:0{self.maxlen_friendshipId_episodeNumber[1]}d} {title}'
                + '.txt'
            )

        def title_of(lang: str) -> str:
            return reader.get_adv_title(adv_id, lang)

        def synopsis_of(lang: str) -> str | None:
            return None  # 羁绊话主表无简介字段

        await self.write_script(adv_id, script, langs, r'(\d+-\d+) ', path_of, title_of, synopsis_of)


class Home_talk_getter(Bdon_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_{lang}/home',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_spotId: int = 5,
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        super().__init__(
            reader,
            save_dir,
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )
        self.maxlen_spotId = maxlen_spotId

    def tell_ids(self) -> list[int]:
        # 入口 id = HomeSpot._id：一个 spot 一个合并文件（场景开场 + 全部点触对话）
        return sorted(self.reader.home_spots)

    async def get(self, spot_id: int, langs: Iterable[tuple[str, str]] = LANGS) -> None:
        reader = self.reader
        spot = reader.home_spots[spot_id]

        # 该 spot 的全部脚本：场景开场在前，点触对话按 TapTalk._id 升序
        segments: list[tuple[int, dict[str, Any] | None]] = []
        if spot.get('advId'):
            segments.append((spot['advId'], None))
        segments.extend(
            (episode['advId'], episode)
            for tid, episode in sorted(self.reader.home_talk_episodes.items())
            if episode['spotId'] == spot_id
        )
        if not segments:
            logging.info(f'home spot {spot_id} has no scripts.')
            return

        fetched = await asyncio.gather(
            *[
                self.fetch_script(reader.advs[adv_id]['advEpisodeAsset'])
                for adv_id, _ in segments
            ]
        )

        if not self.parse:
            logging.info(f'fetch bdon home spot {spot_id} done (assets only).')
            return

        def segment_title(adv_id: int, episode: dict[str, Any] | None, lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            if title:
                return title
            if episode is not None and episode.get('characterId'):
                return reader.get_chara_name(episode['characterId'], lang)
            return reader.get_master_text(spot.get('advNameTextId'), lang) or ''

        for lang, mark_lang in langs:
            parts = []
            for i, (
                (adv_id, episode),
                (episode_json, text_json, video_json),
            ) in enumerate(zip(segments, fetched), 1):
                if (
                    isinstance(episode_json, str)
                    or isinstance(text_json, str)
                    or (isinstance(video_json, str) and video_json)
                ):
                    logging.warning(f'skip home segment {adv_id} (fetch failed).')
                    continue
                title = segment_title(adv_id, episode, lang)
                script = reader.advs[adv_id]['advEpisodeAsset']
                head = f'{i} {adv_id}:{script} {title}'.strip()
                text = reader.read_script(
                    episode_json, text_json, video_json, lang, mark_lang
                )
                parts.append(f'{head}\n\n{text}\n')

            spot_name = reader.get_master_text(spot.get('nameTextId'), lang)
            # 文件名 = MasterHomeSpot._id + spot 名（master 原值，5 位补零保证排序）
            file_name = (
                util.valid_filename(
                    f'{spot_id:0{self.maxlen_spotId}d} {spot_name}', False
                )
                if spot_name
                else f'spot_{spot_id:0{self.maxlen_spotId}d}'
            )
            file_path = os.path.join(
                self.save_dir.format(lang=lang), file_name + '.txt'
            )
            os.makedirs(self.save_dir.format(lang=lang), exist_ok=True)
            util.remove_olds_or_rename_old(file_path, r'(\d+)')
            with open(file_path, 'w', encoding='utf8') as f:
                f.write('\n\n'.join(parts))

        logging.info(f'get bdon home spot {spot_id} done.')


class Live_result_story_getter(Bdon_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_{lang}/live_result',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        maxlen_episodeId: int = 3,
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        super().__init__(
            reader,
            save_dir,
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )
        self.maxlen_episodeId = maxlen_episodeId

    def tell_ids(self) -> list[int]:
        return sorted(self.reader.live_result_episodes)  # MasterStoryLiveResultEpisode._id（1..325）

    async def get(self, episode_id: int, langs: Iterable[tuple[str, str]] = LANGS) -> None:
        reader = self.reader
        episode = reader.live_result_episodes[episode_id]
        adv_id: int = episode['advId']
        script: str = reader.advs[adv_id]['advEpisodeAsset']
        chara_ids = episode.get('characterIds') or []

        def title_of(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            if title:
                return title
            # 演出后对话通常无标题，用出场角色名兜底
            sep = '、' if lang in ('cn', 'tw') else ', '
            return sep.join(reader.get_chara_name(cid, lang) for cid in chara_ids)

        def path_of(lang: str) -> str:
            return os.path.join(
                self.save_dir.format(lang=lang), filename(lang)
            )

        def filename(lang: str) -> str:
            title = title_of(lang)
            return util.valid_filename(
                f'{episode_id:0{self.maxlen_episodeId}d} {title}'.strip() + '.txt'
            )

        def synopsis_of(lang: str) -> str | None:
            return None

        await self.write_script(adv_id, script, langs, r'(\d+)', path_of, title_of, synopsis_of)


class Tutorial_story_getter(Bdon_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_{lang}/tutorial',
        assets_save_dir: str = './assets',
        online: bool = True,
        save_assets: bool = True,
        parse: bool = True,
        missing_download: bool = True,
        compress_assets: bool = False,
        force_master_online: bool = False,
        **args,
    ) -> None:
        super().__init__(
            reader,
            save_dir,
            assets_save_dir,
            online,
            save_assets,
            parse,
            missing_download,
            compress_assets,
            force_master_online,
        )

    def tell_ids(self) -> list[int]:
        # 教程本不被任何剧情主表引用，仅能按脚本名前缀识别；入口 id 只能是 MasterAdv._id
        return sorted(
            adv_id
            for adv_id, adv in self.reader.advs.items()
            if adv_id not in self.reader.referenced_advs
            and str(adv.get('advEpisodeAsset', '')).lower().startswith(
                'adv_script_tutorial_'
            )
        )

    async def get(self, adv_id: int, langs: Iterable[tuple[str, str]] = LANGS) -> None:
        reader = self.reader
        script: str = reader.advs[adv_id]['advEpisodeAsset']

        def path_of(lang: str) -> str:
            return os.path.join(self.save_dir.format(lang=lang), filename(lang))

        def filename(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            return util.valid_filename(f'{adv_id} {title}'.strip() + '.txt')

        def title_of(lang: str) -> str:
            return reader.get_adv_title(adv_id, lang)

        def synopsis_of(lang: str) -> str | None:
            return None

        await self.write_script(adv_id, script, langs, r'(\d+)', path_of, title_of, synopsis_of)


async def main():

    logging.basicConfig(level=logging.INFO)

    net_connect_limit = 20

    online = False

    reader = Story_reader(online=online)
    band_getter = Band_story_getter(reader, online=online)
    friendship_getter = Friendship_story_getter(reader, online=online)
    home_getter = Home_talk_getter(reader, online=online)
    live_result_getter = Live_result_story_getter(reader, online=online)
    tutorial_getter = Tutorial_story_getter(reader, online=online)

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=net_connect_limit)
    ) as session:

        await asyncio.gather(
            reader.init(session),
            band_getter.init(session),
            friendship_getter.init(session),
            home_getter.init(session),
            live_result_getter.init(session),
            tutorial_getter.init(session),
        )

        tasks = []

        # 每类各抓少量各自 master 的 id，检测各功能可运行：
        # 正篇两乐队（mujica 含聊天气泡）+ 番外 + 视角（覆盖文件名各分支）、羁绊、首页点触、演出后、教程
        tasks.append(band_getter.get(101))  # 10000 MyGO 正篇
        tasks.append(band_getter.get(201))  # 10020 Ave Mujica 正篇（聊天气泡）
        tasks.append(band_getter.get(121))  # 10100 番外
        tasks.append(band_getter.get(124))  # 10434 视角
        tasks.append(friendship_getter.get(1))  # 10459 灯×爱音
        tasks.append(home_getter.get(1000101))  # 10611 首页点触
        tasks.append(live_result_getter.get(1))  # 10109 演出后
        tasks.append(tutorial_getter.get(10609))  # 教程（无主表，入口为 advId）

        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
