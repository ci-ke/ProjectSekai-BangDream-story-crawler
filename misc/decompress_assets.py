import argparse
import json
import logging
import os
import shutil
import asyncio
import brotli
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(message)s", datefmt="%H:%M:%S"
)

_decompress_executor = ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 4)))

DST_NAME = "assets_decompress"


async def process_file(src_path: str, dst_path: str, incremental: bool) -> None:
    target_path = dst_path[:-3] if src_path.endswith('.br') else dst_path
    if incremental and os.path.exists(target_path):
        logging.info(f"Skipped: {target_path}")
        return
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    if src_path.endswith('.br'):
        with open(src_path, 'rb') as f:
            compressed_bytes = f.read()
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            _decompress_executor, brotli.decompress, compressed_bytes
        )
        try:
            data = json.loads(raw)
            with open(dst_path[:-3], 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except json.decoder.JSONDecodeError:
            with open(dst_path[:-3], 'w', encoding='utf-8') as f:
                f.write(raw.decode('utf-8'))
        logging.info(f"Decompressed: {src_path} -> {dst_path[:-3]}")
    else:
        shutil.copy2(src_path, dst_path)
        logging.info(f"Copied: {src_path} -> {dst_path}")


async def traverse(
    start_path: str, src_root: str, dst_root: str, incremental: bool
) -> None:
    tasks = []
    if os.path.isfile(start_path):
        rel = os.path.relpath(start_path, src_root)
        tasks.append(process_file(start_path, os.path.join(dst_root, rel), incremental))
    else:
        for root, _, files in os.walk(start_path):
            for file in files:
                sf = os.path.join(root, file)
                rel = os.path.relpath(sf, src_root)
                df = os.path.join(dst_root, rel)
                tasks.append(process_file(sf, df, incremental))

    await asyncio.gather(*tasks)


def find_assets_root(path_abs: str) -> str | None:
    """向上查找路径所在（或自身就是）的最外层 assets 文件夹，找不到返回 None。

    取最外层而非最近一层：源目录里可能存在嵌套的同名 assets 文件夹
    （如 bestdori.com/assets/...），无论传入哪个子路径，输出都应落在
    顶层 assets 旁的同一个 assets_decompress 里。
    """
    current = path_abs if os.path.isdir(path_abs) else os.path.dirname(path_abs)
    root = None
    while True:
        if os.path.basename(current) == 'assets':
            root = current
        parent = os.path.dirname(current)
        if parent == current:
            return root
        current = parent


async def main_async(args: argparse.Namespace) -> None:
    mode = "Incremental" if args.incremental else "Full"

    for p in args.paths:
        input_abs: str = os.path.abspath(p)
        if not os.path.exists(input_abs):
            logging.warning(f"Path does not exist: {input_abs}")
            continue

        src_root = find_assets_root(input_abs)
        if src_root is None:
            logging.error(f"Invalid path (not under an assets folder): {p}")
            continue
        dst_root = os.path.join(os.path.dirname(src_root), DST_NAME)

        logging.info(f"Source: {src_root} | Target: {dst_root} | Mode: {mode}")
        await traverse(input_abs, src_root, dst_root, args.incremental)

    logging.info("Processing completed")


def main() -> None:
    parser = argparse.ArgumentParser(description='Assets decompression tool')
    parser.add_argument(
        '--incremental',
        '-i',
        action='store_true',
        help='Incremental mode (skip existing files)',
    )
    parser.add_argument(
        'paths',
        nargs='+',
        help='assets 文件夹路径（或其下的子目录/文件），输出到 assets 旁的 assets_decompress',
    )
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == '__main__':
    main()
