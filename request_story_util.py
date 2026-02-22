import os, json, threading
from enum import Enum
from typing import Any

import requests  # type: ignore


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


def url_to_path(url: str, save_dir: str) -> str:
    url_path = url[url.index('//') + 2 :]
    return os.path.normpath(os.path.join(save_dir, url_path))


def save_json_to_url(url: str, content: Any, save_dir: str) -> None:
    path = url_to_path(url, save_dir)
    os.makedirs(os.path.split(path)[0], exist_ok=True)
    with open(path, 'w', encoding='utf8') as f:
        json.dump(content, f, ensure_ascii=False)


def read_json_from_url(
    url: str,
    missing_donwload: bool,
    save_dir: str,
    extra_record_msg: str,
    error_assets_file: str | None,
    missing_assets_file: str | None,
    proxies: dict[str, str] | None,
) -> Any:
    path = url_to_path(url, save_dir)
    if os.path.exists(path):
        with open(path, encoding='utf8') as f:
            return json.load(f)
    else:
        if missing_donwload:
            return get_url_json(
                url,
                True,
                True,
                save_dir,
                False,
                extra_record_msg,
                error_assets_file,
                None,
                proxies,
            )
        else:
            if missing_assets_file:
                if extra_record_msg:
                    write_to_file(missing_assets_file, f'{extra_record_msg}：{url}')
                else:
                    write_to_file(missing_assets_file, url)
            return '未能读取json文件'


file_lock = threading.Lock()


def write_to_file(file_path: str, content: str) -> None:
    with file_lock:
        with open(file_path, 'a', encoding='utf-8', newline='') as f:
            f.write(f"{content}\n")
            f.flush()


def get_url_json(
    url: str,
    online: bool,
    save: bool,
    save_dir: str,
    missing_download: bool,
    extra_record_msg: str = '',
    error_assets_file: str | None = 'assets_error.txt',
    missing_assets_file: str | None = 'assets_missing.txt',
    proxies: dict[str, str] | None = None,
) -> Any:
    '''
    proxies: example: {'http': 'http://127.0.0.1:10808', 'https': 'http://127.0.0.1:10808'}
    '''
    if online:
        res = requests.get(url, proxies=proxies)
        res.raise_for_status()
        try:
            json_content = res.json()
            if save:
                save_json_to_url(url, json_content, save_dir)
        except Exception as e:
            json_content = f'读取json出错：{e}'
            if error_assets_file:
                if extra_record_msg:
                    write_to_file(error_assets_file, f'{extra_record_msg}：{url}')
                else:
                    write_to_file(error_assets_file, url)
    else:
        json_content = read_json_from_url(
            url,
            missing_download,
            save_dir,
            extra_record_msg,
            error_assets_file,
            missing_assets_file,
            proxies,
        )

    return json_content
