import os, asyncio, json, logging
from pathlib import Path
from collections.abc import Iterable
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

    # 不计入（登场角色）的说话人 id
    narrator_ids = {'adv_storyteller'}


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

        speakers: list[str] = []
        speaker_seen: set[str] = set()
        body = ''
        prev_is_text = False

        # 遍历 Episode 指令流（数组顺序即剧本顺序，勿用 _index 当行号）
        for row in episode_rows:
            command = row.get('command')
            adv_text_id = row.get('advTextID')

            if adv_text_id:
                # 凡 _advTextID 非空即一行台词（2 对话 / 20 旁白 / 37 65 聊天气泡），
                # 不按 command 白名单筛选，否则会丢聊天气泡内容
                text = self.get_text_marked(
                    text_lookup.get(str(adv_text_id)), lang, mark_lang
                ).replace('\n', ' ')

                if command == 20:  # 旁白/独白，无说话人
                    body += text + '\n'
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
                    if (
                        speaker_id
                        and speaker_id not in Constant.narrator_ids
                        and speaker not in speaker_seen
                    ):
                        speaker_seen.add(speaker)
                        speakers.append(speaker)
                    body += f"{speaker}{Mark_multi_lang[':'][mark_lang]}{text}\n"
                prev_is_text = True
            elif command == 25:  # 切换背景（背景图仅在 legacy 桶，此处只留标记）
                if prev_is_text:
                    body += '\n'
                body += Mark_multi_lang['background'][mark_lang] + '\n'
                prev_is_text = False
            elif command == 30:  # 过场大图
                if prev_is_text:
                    body += '\n'
                asset_name = (
                    str(row.get('targetAssetName') or '')
                    .replace('\\', '/')
                    .strip('/')
                    .rsplit('/', 1)[-1]
                )
                body += (
                    Mark_multi_lang['cg'][mark_lang]
                    + asset_name
                    + Mark_multi_lang[')'][mark_lang]
                    + '\n'
                )
                prev_is_text = False
            elif self.debug_parse:
                body += f"cmd-{command}: {row.get('targetName')}\n"

        ret0 = ''
        if speakers:
            ret0 = (
                Mark_multi_lang['characters'][mark_lang]
                + Mark_multi_lang[','][mark_lang].join(speakers)
                + Mark_multi_lang[')'][mark_lang]
            )

        return (ret0 + '\n\n' + body).strip()


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
        script: str,
        langs: Iterable[tuple[str, str]],
        index_regex: str,
        path_of: Callable[[str], str],
        name_of: Callable[[str], str],
        synopsis_of: Callable[[str], str | None],
    ) -> None:
        """抓取剧本两表并向各语言目录写出；index_regex 匹配文件名中稳定的首段索引用于改名/清理。"""
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
            with open(file_path, 'w', encoding='utf8') as f:
                f.write(name_of(lang) + '\n\n')
                synopsis = synopsis_of(lang)
                if synopsis:
                    f.write(synopsis.replace('\n', ' ') + '\n\n')
                f.write(
                    self.reader.read_script(episode_json, text_json, lang, mark_lang)
                    + '\n'
                )

        logging.info(f'get bdon script {script} done.')


class Main_story_getter(Bdon_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_{lang}/main',
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
        chara_id = episode.get('characterId')
        description_id = episode.get('descriptionTextId')

        def filename(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            # 另一视角的 episodeNumber 与正篇重叠（1..5），加 a 后缀并附角色名区分
            if is_another:
                return util.valid_filename(
                    f'{ep_number:02d}a {reader.get_chara_name(chara_id, lang, short=True)} {title}'
                    + '.txt'
                )
            return util.valid_filename(f'{ep_number:02d} {title}' + '.txt')

        def path_of(lang: str) -> str:
            folder = util.valid_filename(
                f'{band_id:02d} {reader.get_band_name(band_id, lang)}', True
            )
            return os.path.join(self.save_dir.format(lang=lang), folder, filename(lang))

        def name_of(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            return f'{script} {title}'.strip() if title else script

        def synopsis_of(lang: str) -> str | None:
            return reader.get_master_text(description_id, lang)

        await self.write_script(script, langs, r'(\d+[ab]?) ', path_of, name_of, synopsis_of)


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
        return sorted(self.reader.friendship_episodes)

    async def get_id(self, adv_id: int, langs: Iterable[tuple[str, str]]) -> None:
        reader = self.reader
        episode = reader.friendship_episodes[adv_id]
        script: str = reader.advs[adv_id]['advEpisodeAsset']
        pair = reader.friendships[episode['characterFriendshipId']]
        id_a, id_b = pair['masterCharacterIdA'], pair['masterCharacterIdB']
        pair_index = sorted(reader.friendships).index(episode['characterFriendshipId']) + 1
        ep_number: int = episode['episodeNumber']

        def path_of(lang: str) -> str:
            folder = util.valid_filename(
                f'{pair_index:02d} '
                + f'{reader.get_chara_name(id_a, lang)}×{reader.get_chara_name(id_b, lang)}',
                True,
            )
            return os.path.join(self.save_dir.format(lang=lang), folder, filename(lang))

        def filename(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            return util.valid_filename(f'{ep_number:02d} {title}' + '.txt')

        def name_of(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            return f'{script} {title}'.strip() if title else script

        def synopsis_of(lang: str) -> str | None:
            return None  # 羁绊话主表无简介字段

        await self.write_script(script, langs, r'(\d+) ', path_of, name_of, synopsis_of)


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
                util.valid_filename(f'{spot_index:02d} {spot_name}', True)
                if spot_name
                else f'spot_{spot_index:02d}'
            )
            return os.path.join(self.save_dir.format(lang=lang), folder, filename(lang))

        def filename(lang: str) -> str:
            title = title_of(lang)
            return util.valid_filename(f'{adv_id} {title}'.strip() + '.txt')

        def name_of(lang: str) -> str:
            title = title_of(lang)
            return f'{script} {title}'.strip() if title else script

        def synopsis_of(lang: str) -> str | None:
            return None

        await self.write_script(script, langs, r'(\d+)', path_of, name_of, synopsis_of)


class Live_result_getter(Bdon_getter):
    def __init__(
        self,
        reader: Story_reader,
        save_dir: str = './story_{lang}/live',
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
        return sorted(self.reader.live_result_episodes)

    async def get_id(self, adv_id: int, langs: Iterable[tuple[str, str]]) -> None:
        reader = self.reader
        episode = reader.live_result_episodes[adv_id]
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
            return util.valid_filename(f'{adv_id} {title}'.strip() + '.txt')

        def name_of(lang: str) -> str:
            title = title_of(lang)
            return f'{script} {title}'.strip() if title else script

        def synopsis_of(lang: str) -> str | None:
            return None

        await self.write_script(script, langs, r'(\d+)', path_of, name_of, synopsis_of)


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

        def name_of(lang: str) -> str:
            title = reader.get_adv_title(adv_id, lang)
            return f'{script} {title}'.strip() if title else script

        def synopsis_of(lang: str) -> str | None:
            return None

        await self.write_script(script, langs, r'(adv_script_\w+)', path_of, name_of, synopsis_of)


async def main():

    logging.basicConfig(level=logging.INFO)

    net_connect_limit = 20

    online = False

    reader = Story_reader(online=online)
    main_getter = Main_story_getter(reader, online=online)
    friendship_getter = Friendship_story_getter(reader, online=online)
    home_getter = Home_talk_getter(reader, online=online)
    live_getter = Live_result_getter(reader, online=online)
    tutorial_getter = Tutorial_story_getter(reader, online=online)

    async with ClientSession(
        trust_env=True, connector=TCPConnector(limit=net_connect_limit)
    ) as session:

        await asyncio.gather(
            reader.init(session),
            main_getter.init(session),
            friendship_getter.init(session),
            home_getter.init(session),
            live_getter.init(session),
            tutorial_getter.init(session),
        )

        tasks = []

        tasks.append(main_getter.get())
        tasks.append(friendship_getter.get())
        tasks.append(home_getter.get())
        tasks.append(live_getter.get())
        tasks.append(tutorial_getter.get())

        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
