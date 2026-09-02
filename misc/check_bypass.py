#!/usr/bin/env python3
"""
check_bypass.py — 测试 bypass 名单中的 URL 是否仍然是错误

逐个对名单中的 URL 发起真实请求（复用 util.fetch_url_json）：
    - 仍返回 'ERROR: ...'（JSONDecodeError / 404 等）-> 仍是错误
    - 能正常解析出内容                                -> 不再是错误，打印到标准输出

用法:
    python -m misc.check_bypass [bypass_file] [--max-retries N] [--concurrency N]

bypass_file 默认 'bypass.txt'（相对 src 目录，支持 # 注释行）。
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import aiohttp

# 允许以 python -m misc.check_bypass 或 python misc/check_bypass.py 两种方式运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import util  # noqa: E402


async def check_one(
    url: str,
    session: aiohttp.ClientSession,
    max_retries: int,
    semaphore: asyncio.Semaphore,
) -> tuple[str, bool]:
    """请求单个 URL，返回 (url, 是否不再是错误)。"""
    async with semaphore:
        result = await util.fetch_url_json(
            url,
            online=True,
            save=False,
            save_dir='.',
            missing_download=False,
            session=session,
            success_assets_file=None,
            error_assets_file=None,
            max_retries=max_retries,
            bypass_urls=frozenset(),  # 本次需要真实请求，绕过 bypass 名单拦截
        )
    return url, not (isinstance(result, str) and result.startswith('ERROR:'))


async def main() -> int:
    parser = argparse.ArgumentParser(
        description='测试 bypass 名单中的 URL 是否仍然是错误'
    )
    parser.add_argument(
        'bypass_file',
        nargs='?',
        default='bypass.txt',
        help="名单文件（默认 'bypass.txt'，相对 src 目录）",
    )
    parser.add_argument('--max-retries', type=int, default=2)
    parser.add_argument('--concurrency', type=int, default=20)
    args = parser.parse_args()

    urls = sorted(util.load_bypass_urls(args.bypass_file))
    if not urls:
        print(f'bypass 名单为空或文件未找到: {args.bypass_file}', file=sys.stderr)
        return 1

    # fetch_url_json 内部对失败会打 WARNING 日志，直接展示到标准输出（简洁格式）
    logging.basicConfig(level=logging.WARNING, format='%(message)s', stream=sys.stdout)

    print(
        f'checking {len(urls)} urls '
        f'(concurrency={args.concurrency}, max_retries={args.max_retries}) ...'
    )

    semaphore = asyncio.Semaphore(args.concurrency)
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            *(check_one(u, session, args.max_retries, semaphore) for u in urls)
        )

    fixed = [u for u, ok in results if ok]
    still_error = len(results) - len(fixed)

    print(
        f'summary: total={len(results)}  '
        f'still_error={still_error}  no_longer_error={len(fixed)}'
    )
    print('--- no longer error urls ---')
    for u in fixed:
        print(u)
    if not fixed:
        print('(none)')
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))