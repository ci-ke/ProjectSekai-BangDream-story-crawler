import os, json, asyncio, traceback
from enum import Enum
from typing import Any
from asyncio import Semaphore

import aiohttp, aiofiles  # type: ignore


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


_net_semaphore = asyncio.Semaphore(20)
_file_semaphore = asyncio.Semaphore(20)


class Base_getter:
    network_semaphore: Semaphore
    file_semaphore: Semaphore

    def __init__(
        self,
        save_dir: str,
        assets_save_dir: str,
        online: bool,
        save_assets: bool,
        parse: bool,
        missing_download: bool,
    ):
        self.save_dir = save_dir
        self.assets_save_dir = assets_save_dir

        self.online = online
        self.save_assets = save_assets
        self.parse = parse
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
    url: str, content: Any, save_dir: str, file_semaphore: Semaphore
) -> None:
    path = url_to_path(url, save_dir)
    os.makedirs(os.path.split(path)[0], exist_ok=True)

    async with file_semaphore:
        async with aiofiles.open(path, 'w', encoding='utf8') as f:
            await f.write(json.dumps(content, ensure_ascii=False))


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
) -> Any:
    path = url_to_path(url, save_dir)
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
            )
        else:
            if missing_assets_file:
                await write_to_file(
                    missing_assets_file,
                    f"{extra_record_msg}{'：' if extra_record_msg else ''}{url}",
                    file_semaphore,
                )
            return '未能读取json文件'


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


async def fetch_url_json(
    url: str,
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
) -> Any:

    if network_semaphore is None:
        network_semaphore = _net_semaphore
    if file_semaphore is None:
        file_semaphore = _file_semaphore

    if online:
        assert session is not None

        async with network_semaphore:
            async with session.get(url) as res:
                res.raise_for_status()
                try:
                    json_content = await res.json(content_type=None)
                    if save:
                        await save_json_to_url(
                            url, json_content, save_dir, file_semaphore
                        )

                except Exception:
                    # if encounter "Can not decode content-encoding: br", pip install -U brotli
                    json_content = f'读取json出错：{traceback.format_exc()}'
                    print(json_content)
                    if error_assets_file:
                        await write_to_file(
                            error_assets_file,
                            f"{extra_record_msg}{'：' if extra_record_msg else ''}{url}",
                            file_semaphore,
                        )
    else:
        json_content = await read_json_from_url(
            url,
            missing_download,
            save_dir,
            extra_record_msg,
            error_assets_file,
            missing_assets_file,
            session,
            network_semaphore,
            file_semaphore,
        )

    if print_done:
        print('get ' + url + ' done.')

    return json_content


async def fetch_url_json_simple(
    url: str, self: Any, extra_record_msg: str = '', print_done: bool = False
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
    )
