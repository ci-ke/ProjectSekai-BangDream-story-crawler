#!/usr/bin/env python3
"""
clean_assets.py — 子命令工具

子命令:

    unused --src path [path ...] --dst path [path ...]
        从所有 --src 目录的 assets_*.log 收集合法路径，
        在所有 --dst 目录中找出未被引用的文件，输出到 unused_file.txt。

    empty <dst>
        在 dst 中递归找出所有空文件夹（只含空子文件夹也算空），
        子条目在前、父条目在后排序，输出到 empty_folder.txt。

    act <file>
        从 <file> 逐行读取路径并删除（文件 unlink，目录 rmdir）。
        如需清理删除后产生的空文件夹，可配合 empty 子命令使用。
"""

import argparse
import glob
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 共用工具
# ---------------------------------------------------------------------------


def _delete_items(items: list[Path]) -> None:
    """按深度降序删除条目（文件 unlink，目录 rmdir）。"""
    sorted_items = sorted(items, key=lambda p: len(p.parents), reverse=True)
    for p in sorted_items:
        try:
            if p.is_dir():
                p.rmdir()
                print(f"  [rmdir]  {p}")
            else:
                p.unlink()
                print(f"  [unlink] {p}")
        except Exception as e:
            print(f"  [FAIL]   {p}  -> {e}", file=sys.stderr)


def _load_list_file(file_path: str) -> list[Path]:
    """从文本文件加载路径列表（每行一个）。"""
    paths: list[Path] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                paths.append(Path(line))
    return paths


# ---------------------------------------------------------------------------
# unused 子命令
# ---------------------------------------------------------------------------


def _collect_valid_paths(src_base: Path) -> set[Path]:
    """从 src_base/assets_*.log 收集所有合法路径。"""
    valid: set[Path] = set()
    for log_file in sorted(glob.glob(str(src_base / "assets_*.log"))):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    path_str = line.split("||")[0].strip()
                    if not path_str:
                        continue
                    p = Path(path_str)
                    resolved = (
                        p.resolve() if p.is_absolute() else (src_base / p).resolve()
                    )
                    valid.add(resolved)
        except Exception as e:
            print(f"[Warning] 读取 {log_file} 出错: {e}", file=sys.stderr)
    return valid


def _collect_all_files(target_dir: Path) -> list[Path]:
    """递归收集所有文件（不含目录）。"""
    files: list[Path] = []
    for entry in target_dir.rglob("*"):
        if entry.is_file():
            files.append(entry)
    return files


def cmd_unused(src_list: list[str], dst_list: list[str]) -> int:
    # 校验所有 src / dst 目录
    src_bases = [Path(p).resolve() for p in src_list]
    dst_dirs = [Path(p).resolve() for p in dst_list]

    for s in src_bases:
        if not s.is_dir():
            print(f"错误：src 不是有效目录: {s}", file=sys.stderr)
            return 1
    for d in dst_dirs:
        if not d.is_dir():
            print(f"错误：dst 不是有效目录: {d}", file=sys.stderr)
            return 1

    # 收集所有合法路径
    valid: set[Path] = set()
    for s in src_bases:
        print(f"收集合法路径 from {s / 'assets_*.log'} ...")
        v = _collect_valid_paths(s)
        print(f"  -> {len(v)} 条")
        valid |= v
    print(f"  -> 合计 {len(valid)} 条合法路径")

    # 收集所有目标文件
    all_files: list[Path] = []
    for d in dst_dirs:
        print(f"扫描目标目录 {d} ...")
        files = _collect_all_files(d)
        print(f"  -> {len(files)} 个文件")
        all_files.extend(files)

    print("比对中 ...")
    unused: list[Path] = []
    for f in all_files:
        if f.resolve() not in valid:
            unused.append(f.resolve())

    out_file = "unused_file.txt"
    if unused:
        print(f"\n未引用的文件 ({len(unused)} 个):")
        for p in sorted(unused, key=str):
            print(f"  {p}")
        with open(out_file, "w", encoding="utf-8") as f:
            for p in sorted(unused, key=str):
                f.write(str(p) + "\n")
        print(f"\n列表已保存到 {out_file}")
    else:
        print("\n所有文件均被引用，无需清理。")

    return 0


# ---------------------------------------------------------------------------
# empty 子命令
# ---------------------------------------------------------------------------


def cmd_empty(dst_list: list[str]) -> int:
    dst_dirs = [Path(p).resolve() for p in dst_list]
    for d in dst_dirs:
        if not d.is_dir():
            print(f"错误：dst 不是有效目录: {d}", file=sys.stderr)
            return 1

    empty_dirs: set[Path] = set()
    for dst_dir in dst_dirs:
        print(f"扫描空文件夹 from {dst_dir} ...")
        for root, dirs, files in os.walk(dst_dir, topdown=False):
            root_path = Path(root)
            if not files and all((root_path / d) in empty_dirs for d in dirs):
                empty_dirs.add(root_path)

    if not empty_dirs:
        print("没有找到空文件夹。")
        return 0

    sorted_dirs = sorted(empty_dirs, key=lambda p: len(p.parents), reverse=True)

    print(f"\n空文件夹 ({len(sorted_dirs)} 个):")
    for p in sorted_dirs:
        print(f"  {p}")

    out_file = "empty_folder.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        for p in sorted_dirs:
            f.write(str(p) + "\n")
    print(f"\n列表已保存到 {out_file}")
    return 0


# ---------------------------------------------------------------------------
# act 子命令
# ---------------------------------------------------------------------------


def cmd_act(file_list: list[str]) -> int:
    all_items: list[Path] = []
    for f in file_list:
        if not os.path.isfile(f):
            print(f"错误：文件不存在: {f}", file=sys.stderr)
            return 1
        items = _load_list_file(f)
        print(f"  {f}: {len(items)} 个条目")
        all_items.extend(items)

    if not all_items:
        print("所有文件均为空，无需操作。")
        return 0

    print(f"\n合计 {len(all_items)} 个条目，开始删除 ...\n" + "=" * 40)
    _delete_items(all_items)
    print("\n删除完成。")
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="资源清理工具 — unused / empty / act 三个子命令",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # unused
    p_unused = sub.add_parser(
        "unused",
        help="找出 dst 中未被 src log 引用的文件",
        description="从 src/assets_*.log 收集合法路径，找出 dst 中未被引用的文件。"
        "简单用法: unused src dst；多目录用法: unused --src x y --dst z u",
    )
    p_unused.add_argument(
        "positional",
        nargs="*",
        help="src 和 dst（两个位置参数时为简单模式，否则须用 --src/--dst）",
    )
    p_unused.add_argument("--src", nargs="+", help="assets_*.log 所在目录（可多个）")
    p_unused.add_argument("--dst", nargs="+", help="要扫描的目标目录（可多个）")

    # empty
    p_empty = sub.add_parser(
        "empty",
        help="找出 dst 下所有空文件夹（递归）",
        description="递归找出所有空文件夹（只含空子文件夹也算空）。",
    )
    p_empty.add_argument("dst", nargs="+", help="要扫描的目标目录（可多个）")

    # act
    p_act = sub.add_parser("act", help="按列表文件执行删除")
    p_act.add_argument("file", nargs="+", help="路径列表文件（可多个）")

    args = parser.parse_args()

    if args.command == "unused":
        if args.src or args.dst:
            if not args.src or not args.dst:
                parser.error("--src 和 --dst 必须同时使用")
            return cmd_unused(args.src, args.dst)
        elif len(args.positional) == 2:
            return cmd_unused([args.positional[0]], [args.positional[1]])
        else:
            parser.error(
                "unused 需要两个位置参数（src dst），"
                "或多个目录时使用 --src x y --dst z u"
            )
    elif args.command == "empty":
        return cmd_empty(args.dst)
    elif args.command == "act":
        return cmd_act(args.file)
    return 1


if __name__ == "__main__":
    sys.exit(main())
