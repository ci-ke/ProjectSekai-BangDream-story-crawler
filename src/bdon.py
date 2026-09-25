import os, asyncio, json, logging
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
URLS: dict[str, str] = CONFIG['urls_bdon']['bdon.moe']

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
    PlayVideo = 26             # 【推断】videoID 93%
    StopVideo = 27             # 【推断】videoID 50%
    Monologue = 28             # 【实测】带 advTextID + 说话人、无语音（705 行）；推断为内心独白类对话变体
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


class Bdon_fetcher(util.Base_fetcher):
    @staticmethod
    def __url_to_save_path(url: str) -> str:
        # URL 路径过长，仿 pjsk 拆成两个短存盘根：
        # bdon-master/（master 表）、bdon-assets/Adv/Episode/（剧本表，保留源桶路径层级）
        if '/master/' in url:
            return os.path.join('bdon-master', url[url.rindex('/') + 1 :])
        return os.path.join('bdon-assets', 'Adv', 'Episode', url[url.rindex('/') + 1 :])

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
        self.story_episodes = {
            row['advId']: row for row in rows['MasterStoryEpisode']
        }
        self.friendship_episodes = {
            row['advId']: row for row in rows['MasterStoryFriendshipEpisode']
        }
        self.friendships = {
            row['id']: row for row in rows['MasterCharacterFriendship']
        }
        self.live_result_episodes = {
            row['advId']: row for row in rows['MasterStoryLiveResultEpisode']
        }
        self.home_talk_episodes = {
            row['advId']: row for row in rows['MasterStoryHomeSpotTapTalkEpisode']
        }
        self.home_spots = {row['id']: row for row in rows['MasterHomeSpot']}
        self.home_spots_by_adv = {
            row['advId']: row for row in rows['MasterHomeSpot'] if row.get('advId')
        }
        # 被各剧情主表引用的 advId（归属判定时引用优先于脚本名前缀）
        self.referenced_advs: set[int] = (
            set(self.story_episodes)
            | set(self.friendship_episodes)
            | set(self.live_result_episodes)
            | set(self.home_talk_episodes)
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
        """台词文本：缺失时按回落链取值并在行尾标注实际语言。"""
        text, field = self.localize_row(text_row, lang)
        if text is None:
            return ''
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

    def read_script(
        self,
        episode_json: dict[str, Any] | str,
        text_json: dict[str, Any] | str,
        lang: str,
        mark_lang: str,
    ) -> str:
        if isinstance(episode_json, str):
            return episode_json
        if isinstance(text_json, str):
            return text_json

        episode_rows = normalize_rows(episode_json)
        text_lookup = {str(row['id']): row for row in normalize_rows(text_json)}

        body = ''
        telop_pending = False  # Telop 之后的下一条输出需先补一个空行（Telop 独立段落、上下恰好各一空行）
        last_marker = ''  # 上一条输出的标记身份（bg:/still: 前缀 + 资源名）；仅相邻同资源名的标记去重，台词输出后清空
        last_chat_line = ''  # 上一条手机消息行：相邻完全相同的消息重发行（渲染对）只出一次

        # 遍历 Episode 指令流（数组顺序即剧本顺序，勿用 _index 当行号）
        for row in episode_rows:
            raw_command: Any = row.get('command')
            try:
                command = AdvCommand(raw_command)
            except ValueError:
                command = raw_command  # 新版本新增指令：退回裸数值
            adv_text_id = row.get('advTextID')

            if adv_text_id:
                # 凡 _advTextID 非空即有文本输出（Talk / Telop / ChatMessage / ChatMessageEx /
                # Monologue 均可携带），不按 command 白名单筛选，否则会丢聊天气泡与独白内容
                text = self.get_text_marked(
                    text_lookup.get(str(adv_text_id)), lang, mark_lang
                ).replace('\n', ' ')

                if command is AdvCommand.Telop:  # 场景字幕，独立段落（pjsk Telop 样式：上下恰好各一空行，不叠加）
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
                    target_ids = row.get('targetTextIDs') or []
                    speaker_id = (
                        target_ids[0] if target_ids else (row.get('targetName') or '')
                    )
                    speaker_row = (
                        text_lookup.get(str(speaker_id)) if speaker_id else None
                    )
                    speaker = (
                        self.get_text_marked(speaker_row, lang, mark_lang)
                        if speaker_row
                        else ''
                    )
                    speaker = (speaker or speaker_id).replace('\n', ' ')
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
                # 仅相邻同资源的背景切换去重；不同资源的连续背景切换各自保留
                if last_marker != f'bg:{bg_asset}':
                    if telop_pending:
                        body += '\n'
                        telop_pending = False
                    body += Mark_multi_lang['background'][mark_lang] + '\n'
                    last_marker = f'bg:{bg_asset}'
                    last_chat_line = ''
            elif command is AdvCommand.ShowStill:  # 过场大图
                asset = str(row.get('targetAssetName') or '').replace('\\', '/').strip('/')
                dir_name, still_name = asset.split('/')[0], asset.rsplit('/', 1)[-1]
                # 仅相邻同资源的过场大图去重（显示/隐藏对导致的相邻重发只出一次），非相邻的重现照常输出
                if last_marker != f'still:{asset}':
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
                    last_marker = f'still:{asset}'
                    last_chat_line = ''
                    prev_is_text = False
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

    def all_ids(self) -> list[int]:
        """该类别全部脚本 advId，升序。"""
        raise NotImplementedError

    async def get_id(self, adv_id: int, langs: Iterable[tuple[str, str]]) -> None:
        raise NotImplementedError

    async def get(
        self,
        langs: Iterable[tuple[str, str]] = LANGS,
        id_range: Iterable[int] | None = None,
    ) -> None:
        ids = self.all_ids()
        if id_range is not None:
            id_set = set(id_range)
            ids = [i for i in ids if i in id_set]

        await asyncio.gather(*[self.get_id(adv_id, langs) for adv_id in ids])

    async def get_newest(
        self,
        langs: Iterable[tuple[str, str]] = LANGS,
        quantity: int = 1,
    ) -> None:
        '''
        增量抓取最新的 quantity 个脚本（advId 单调递增且目前连续无空洞）；quantity 0 = 全部
        '''
        ids = self.all_ids()
        if quantity > 0:
            ids = ids[-quantity:]

        await asyncio.gather(*[self.get_id(adv_id, langs) for adv_id in ids])

    async def fetch_script(self, script: str) -> tuple[Any, Any]:
        return await asyncio.gather(
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
        episode_json, text_json = await self.fetch_script(script)

        if not self.parse:
            logging.info(f'fetch bdon script {script} done (assets only).')
            return

        if isinstance(episode_json, str) or isinstance(text_json, str):
            # 'ERROR: ...'（抓取失败）或 'Missing asset'（离线且本地缺失）
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
                    self.reader.read_script(episode_json, text_json, lang, mark_lang)
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
        maxlen_episodeNumber: int = 2,
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
        self.maxlen_episodeNumber = maxlen_episodeNumber

    def all_ids(self) -> list[int]:
        return sorted(self.reader.story_episodes)

    async def get_id(self, adv_id: int, langs: Iterable[tuple[str, str]]) -> None:
        reader = self.reader
        episode = reader.story_episodes[adv_id]
        script: str = reader.advs[adv_id]['advEpisodeAsset']
        band_id = next(
            chapter['bandId']
            for chapter in reader.story_chapters
            if chapter['id'] == episode['chapterId']
        )
        ep_number: int = episode['episodeNumber']
        is_another: bool = bool(episode['isAnotherEpisode'])
        is_extra: bool = bool(episode['isExtraEpisode'])
        chara_id = episode.get('characterId')
        description_id = episode.get('descriptionTextId')

        def filename(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            # 视角故事（another story）的 episodeNumber 1..5 与正篇重叠，用 another- 前缀并附角色名；
            # 番外（extra）的 episodeNumber 为 21..23，用 extra- 前缀；编号均为主表原值
            if is_another:
                return util.valid_filename(
                    f'another-{ep_number:0{self.maxlen_episodeNumber}d} {reader.get_chara_name(chara_id, lang, short=True)} {title}'
                    + '.txt'
                )
            if is_extra:
                return util.valid_filename(f'extra-{ep_number:0{self.maxlen_episodeNumber}d} {title}' + '.txt')
            return util.valid_filename(f'{ep_number:0{self.maxlen_episodeNumber}d} {title}' + '.txt')

        def path_of(lang: str) -> str:
            folder = util.valid_filename(
                f'{band_id:02d} {reader.get_band_name(band_id, lang)}', True
            )
            return os.path.join(self.save_dir.format(lang=lang), folder, filename(lang))

        def title_of(lang: str) -> str:
            return reader.get_adv_title(adv_id, lang)

        def synopsis_of(lang: str) -> str | None:
            return reader.get_master_text(description_id, lang)

        await self.write_script(
            adv_id, script, langs, r'(another-\d+|extra-\d+|\d+) ', path_of, title_of, synopsis_of
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

    def all_ids(self) -> list[int]:
        return sorted(self.reader.friendship_episodes)

    async def get_id(self, adv_id: int, langs: Iterable[tuple[str, str]]) -> None:
        reader = self.reader
        episode = reader.friendship_episodes[adv_id]
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
        maxlen_spotIndex: int = 2,
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
        self.maxlen_spotIndex = maxlen_spotIndex

    def all_ids(self) -> list[int]:
        # 首页 spot 点触对话 + 场景自带开场白，合并为 home 类
        entries: set[int] = set(self.reader.home_talk_episodes)
        entries |= set(self.reader.home_spots_by_adv)
        return sorted(entries)

    def __spot_of(self, adv_id: int) -> int | None:
        episode = self.reader.home_talk_episodes.get(adv_id)
        if episode is not None:
            return episode['spotId']
        spot = self.reader.home_spots_by_adv.get(adv_id)
        return spot['id'] if spot else None

    async def get_id(self, adv_id: int, langs: Iterable[tuple[str, str]]) -> None:
        reader = self.reader
        adv = reader.advs.get(adv_id)
        script: str = adv['advEpisodeAsset'] if adv else f'adv_{adv_id}'
        spot_id = self.__spot_of(adv_id)
        spot = reader.home_spots.get(spot_id) if spot_id is not None else None
        episode = reader.home_talk_episodes.get(adv_id)
        spot_index = sorted(reader.home_spots).index(spot_id) + 1 if spot_id is not None else 0

        def title_of(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            if title:
                return title
            if episode is not None and episode.get('characterId'):
                return reader.get_chara_name(episode['characterId'], lang)
            if spot is not None:
                return reader.get_master_text(spot.get('advNameTextId'), lang) or ''
            return ''

        def path_of(lang: str) -> str:
            spot_name = (
                reader.get_master_text(spot.get('nameTextId'), lang) if spot else None
            )
            folder = (
                util.valid_filename(
                    f'{spot_index:0{self.maxlen_spotIndex}d} {spot_name}', True
                )
                if spot_name
                else f'spot_{spot_index:0{self.maxlen_spotIndex}d}'
            )
            return os.path.join(self.save_dir.format(lang=lang), folder, filename(lang))

        def filename(lang: str) -> str:
            title = title_of(lang)
            return util.valid_filename(f'{adv_id} {title}'.strip() + '.txt')

        def synopsis_of(lang: str) -> str | None:
            return None

        await self.write_script(adv_id, script, langs, r'(\d+)', path_of, title_of, synopsis_of)


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

    def all_ids(self) -> list[int]:
        return sorted(self.reader.live_result_episodes)

    async def get_id(self, adv_id: int, langs: Iterable[tuple[str, str]]) -> None:
        reader = self.reader
        episode = reader.live_result_episodes[adv_id]
        script: str = reader.advs[adv_id]['advEpisodeAsset']
        episode_id: int = episode['id']  # MasterStoryLiveResultEpisode._id（1..325，master 原值）
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

    def all_ids(self) -> list[int]:
        # 教程本不被任何剧情主表引用，仅能按脚本名前缀识别
        return sorted(
            adv_id
            for adv_id, adv in self.reader.advs.items()
            if adv_id not in self.reader.referenced_advs
            and str(adv.get('advEpisodeAsset', '')).lower().startswith(
                'adv_script_tutorial_'
            )
        )

    async def get_id(self, adv_id: int, langs: Iterable[tuple[str, str]]) -> None:
        reader = self.reader
        script: str = reader.advs[adv_id]['advEpisodeAsset']

        def path_of(lang: str) -> str:
            return os.path.join(self.save_dir.format(lang=lang), filename(lang))

        def filename(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            return util.valid_filename(f'{script} {title}'.strip() + '.txt')

        def title_of(lang: str) -> str:
            return reader.get_adv_title(adv_id, lang)

        def synopsis_of(lang: str) -> str | None:
            return None

        await self.write_script(adv_id, script, langs, r'(adv_script_\w+)', path_of, title_of, synopsis_of)


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

        tasks.append(band_getter.get())
        tasks.append(friendship_getter.get())
        tasks.append(home_getter.get())
        tasks.append(live_result_getter.get())
        tasks.append(tutorial_getter.get())

        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
