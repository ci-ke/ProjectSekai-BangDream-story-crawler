import bisect
import os, json, asyncio, traceback
from enum import Enum
from typing import Any
from asyncio import Semaphore

import aiohttp, aiofiles


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


# https://github.com/moe-sekai/Moesekai/blob/main/web/src/types/story.ts
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
    MemoryIn = 27
    MemoryOut = 28
    BlackWipeInLeft = 29
    BlackWipeOutLeft = 30
    BlackWipeInRight = 31
    BlackWipeOutRight = 32
    BlackWipeInTop = 33
    BlackWipeOutTop = 34
    BlackWipeInBottom = 35
    BlackWipeOutBottom = 36
    PlayMV = 37  # special, only in pjsk unit main story
    FullScreenTextShow = 38
    FullScreenTextHide = 39
    SekaiInCenter = 40
    SekaiOutCenter = 41
    ChangeCameraPosition = 42
    ChangeCameraZoomLevel = 43
    Blur = 44


Mark_multi_lang = {
    ':': {'cn': '：', 'en': ': '},
    '(': {'cn': '（', 'en': ' ('},
    ')': {'cn': '）', 'en': ')'},
    ',': {'cn': '、', 'en': ', '},
    '[': {'cn': '【', 'en': '['},
    ']': {'cn': '】', 'en': ']'},
    '<': {'cn': '《', 'en': '<'},
    '>': {'cn': '》', 'en': '>'},
    'characters': {'cn': '（登场角色：', 'en': '(Character: '},
    'place': {'cn': '（地点：', 'en': '(Place: '},
    'fullscreen text': {'cn': '（全屏幕文字）：', 'en': '(Fullscreen text): '},
    'selection': {'cn': '（选项：', 'en': '(Selection: '},
    'video': {'cn': '（播放视频：', 'en': '(Video: '},
    'mv': {'cn': '（播放MV：', 'en': '(Music video: '},
    'cg': {'cn': '（插入CG：', 'en': '(CG insert: '},
    'background': {'cn': '（背景切换）', 'en': '(Background change)'},
    'memory in': {'cn': '（回忆切入）', 'en': '(Memory cut-in)'},
    'memory out': {'cn': '（回忆切出）', 'en': '(Memory cut-out)'},
    'black out': {'cn': '（黑屏转场）', 'en': '(Black cut)'},
    'white out': {'cn': '（白屏转场）', 'en': '(White cut)'},
    'gacha phrase': {'cn': '抽卡台词：', 'en': 'Gacha phrase: '},
    'self intro': {'cn': '自我介绍：', 'en': 'Self introduction: '},
    'anime story': {'cn': '动画故事', 'en': 'Anime story'},
    'see main story': {'cn': '见主线故事', 'en': 'See in main story'},
    'see band story': {'cn': '见乐队故事', 'en': 'See in band story'},
}


_net_semaphore = asyncio.Semaphore(20)
_file_semaphore = asyncio.Semaphore(20)
_MISSING = object()  # 哨兵，用于区分"文件不存在"与"文件内容为 null"


class Base_fetcher:
    def __init__(
        self,
        assets_save_dir: str,
        online: bool,
        save_assets: bool,
        missing_download: bool,
    ):
        self.assets_save_dir = assets_save_dir
        self.online = online
        self.save_assets = save_assets
        self.missing_download = missing_download

    async def init(
        self,
        session: aiohttp.ClientSession | None = None,
        network_semaphore: Semaphore | None = None,
        file_semaphore: Semaphore | None = None,
    ) -> None:
        self.session = session

        if network_semaphore is None:
            self.network_semaphore = _net_semaphore
        else:
            self.network_semaphore = network_semaphore

        if file_semaphore is None:
            self.file_semaphore = _file_semaphore
        else:
            self.file_semaphore = file_semaphore


class Base_getter(Base_fetcher):
    def __init__(
        self,
        save_dir: str,
        assets_save_dir: str,
        online: bool,
        save_assets: bool,
        parse: bool,
        missing_download: bool,
    ):
        super().__init__(assets_save_dir, online, save_assets, missing_download)

        self.save_dir = save_dir
        self.parse = parse


class DictLookup:
    def __init__(self, data: list[dict[str, Any]], attr_name: str):
        self.data = data
        self.ids = [int(d[attr_name]) for d in data]

    def find_index(self, target_id: int) -> int:
        left_index = bisect.bisect_left(self.ids, target_id)
        if left_index < len(self.ids) and self.ids[left_index] == target_id:
            return left_index
        return -1


def valid_filename(filename: str) -> str:
    return (
        filename.strip()
        .replace('*', '＊')
        .replace(':', '：')
        .replace('/', '／')
        .replace('\\', '＼')
        .replace('?', '？')
        .replace('"', "''")
        .replace('\n', ' ')
    )


def url_to_path(url: str, save_dir: str) -> str:
    url_path = url[url.index('//') + 2 :]
    return os.path.normpath(os.path.join(save_dir, url_path))


async def save_json_to_url(
    url: str,
    content: Any,
    save_dir: str,
    file_semaphore: Semaphore,
    append_save_path: str | None,
) -> None:
    if append_save_path is None:
        path = url_to_path(url, save_dir)
    else:
        path = os.path.normpath(os.path.join(save_dir, append_save_path))
    os.makedirs(os.path.split(path)[0], exist_ok=True)

    async with file_semaphore:
        async with aiofiles.open(path, 'w', encoding='utf8') as f:
            await f.write(json.dumps(content, ensure_ascii=False))


_file_locks = {}


def _get_lock(file_path: str) -> asyncio.Lock:
    if file_path not in _file_locks:
        _file_locks[file_path] = asyncio.Lock()
    return _file_locks[file_path]


async def write_to_file(
    file_path: str, content: str, file_semaphore: Semaphore
) -> None:
    async with file_semaphore:
        lock = _get_lock(file_path)
        async with lock:
            async with aiofiles.open(file_path, 'a', encoding='utf-8') as f:
                await f.write(f"{content}\n")


async def read_json_from_url(
    url: str,
    missing_download: bool,
    save_dir: str,
    extra_record_msg: str,
    error_assets_file: str | None,
    missing_assets_file: str | None,
    session: aiohttp.ClientSession | None,
    network_semaphore: Semaphore,
    file_semaphore: Semaphore,
    append_save_path: str | None,
) -> Any:
    if append_save_path is None:
        path = url_to_path(url, save_dir)
    else:
        path = os.path.normpath(os.path.join(save_dir, append_save_path))
    if os.path.exists(path):
        async with file_semaphore:
            async with aiofiles.open(path, encoding='utf8') as f:
                content = await f.read()
                return json.loads(content)
    else:
        if missing_download:
            return await fetch_url_json(
                url,
                True,
                True,
                save_dir,
                False,
                extra_record_msg,
                error_assets_file,
                None,
                session,
                network_semaphore,
                file_semaphore,
                append_save_path=append_save_path,
            )
        else:
            if missing_assets_file:
                await write_to_file(
                    missing_assets_file,
                    f"{extra_record_msg}{': ' if extra_record_msg else ''}{url}",
                    file_semaphore,
                )
            return _MISSING


async def fetch_url_json(
    url: str | list[str],
    online: bool,
    save: bool,
    save_dir: str,
    missing_download: bool,
    extra_record_msg: str = '',
    error_assets_file: str | None = 'assets_error.log',
    missing_assets_file: str | None = 'assets_missing.log',
    session: aiohttp.ClientSession | None = None,
    network_semaphore: Semaphore | None = None,
    file_semaphore: Semaphore | None = None,
    print_done: bool = False,
    append_save_path: str | None = None,
    max_retries: int = 5,
) -> Any:

    if network_semaphore is None:
        network_semaphore = _net_semaphore
    if file_semaphore is None:
        file_semaphore = _file_semaphore

    # 统一转为列表
    urls = [url] if isinstance(url, str) else url

    if online:
        assert session is not None

        json_content = None
        last_error = None

        for current_url in urls:
            for attempt in range(max_retries):
                async with network_semaphore:
                    async with session.get(current_url) as res:
                        try:
                            res.raise_for_status()
                            json_content = await res.json(content_type=None)
                            if save:
                                await save_json_to_url(
                                    current_url,
                                    json_content,
                                    save_dir,
                                    file_semaphore,
                                    append_save_path,
                                )
                            # 成功，直接跳出所有循环
                            last_error = None
                            break

                        except Exception:
                            # if encounter "Can not decode content-encoding: br", pip install -U brotli
                            last_error = f'Fetch json error (attempt {attempt + 1}/{max_retries}, url: {current_url}):\n{traceback.format_exc()}'
                            if attempt + 1 == max_retries:
                                print(last_error)

            # 内层 for 循环正常结束（所有尝试均失败）则更换url，若被 break 则 last_error 为 None
            if last_error is None:
                break

        # 全部url尝试后仍失败
        if last_error is not None:
            json_content = last_error
            if error_assets_file:
                failed_urls = ', '.join(urls)
                await write_to_file(
                    error_assets_file,
                    f"{extra_record_msg}{': ' if extra_record_msg else ''}{failed_urls}",
                    file_semaphore,
                )

    else:
        # offline 模式：按顺序尝试所有 url，返回第一个成功的
        json_content = _MISSING
        for current_url in urls:
            result = await read_json_from_url(
                current_url,
                missing_download,
                save_dir,
                extra_record_msg,
                error_assets_file,
                missing_assets_file,
                session,
                network_semaphore,
                file_semaphore,
                append_save_path,
            )
            if result is not _MISSING:
                json_content = result
                break

        # 全部 url 均失败
        if json_content is _MISSING:
            json_content = 'Unable to read json file'

    if print_done:
        print('fetch ' + (urls[0] if len(urls) == 1 else str(urls)) + ' done.')

    return json_content


async def fetch_url_json_simple(
    url: str | list[str],
    self: Base_fetcher,
    extra_record_msg: str = '',
    print_done: bool = False,
    append_save_path: str | None = None,
) -> Any:
    return await fetch_url_json(
        url,
        self.online,
        self.save_assets,
        self.assets_save_dir,
        self.missing_download,
        extra_record_msg=extra_record_msg,
        session=self.session,
        network_semaphore=self.network_semaphore,
        file_semaphore=self.file_semaphore,
        print_done=print_done,
        append_save_path=append_save_path,
    )
