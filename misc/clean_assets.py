#!/usr/bin/env python3
"""
clean_assets.py

扫描模式:
    python misc/clean_assets.py <src_base> <target_dir>
    1. 在 src_base 下查找所有 assets_*.log 文件
    2. 每行 split('||')[0] 提取路径，相对路径基于 src_base 解析
    3. 收集得到所有"合法路径"
    4. 遍历 target_dir 下的所有文件和文件夹
    5. 找出不在合法路径中的文件/文件夹，打印并保存到 unused_assets_list.txt

删除模式:
    python misc/clean_assets.py --act unused_assets_list.txt
    从文件逐行读取路径并执行删除（文件 unlink，空目录 rmdir，并向上清理变空的父目录）。
"""

import argparse
import glob
import sys
from pathlib import Path


def _remove_empty_ancestors(dir_path: Path) -> None:
    """从 dir_path 开始逐级向上检查，若目录已空则 rmdir，直到遇到非空目录为止。"""
    current = dir_path
    while True:
        try:
            if current.is_dir() and not any(current.iterdir()):
                current.rmdir()
                print(f"  [rmdir]  {current}")
                current = current.parent
            else:
                break
        except (OSError, PermissionError) as e:
            print(f"  [FAIL]   {current}  -> {e}", file=sys.stderr)
            break


def _delete_items(unused: list[Path]) -> None:
    """删除未引用的条目，按路径深度从深到浅排序。

    文件 → unlink，之后若父目录变空 → 逐级向上 rmdir。
    目录 → rmdir（此时应已为空，因上级循环先处理了子条目）。
    """
    sorted_items = sorted(unused, key=lambda p: len(p.parents), reverse=True)
    for p in sorted_items:
        try:
            if p.is_dir():
                p.rmdir()
                print(f"  [rmdir]  {p}")
            else:
                p.unlink()
                print(f"  [unlink] {p}")
                _remove_empty_ancestors(p.parent)
        except Exception as e:
            print(f"  [FAIL]   {p}  -> {e}", file=sys.stderr)


def collect_valid_paths(src_base: Path) -> set[Path]:
    """从 assets_*.log 中收集所有被引用的合法路径。"""
    valid: set[Path] = set()
    log_pattern = str(src_base / "assets_*.log")

    for log_file in sorted(glob.glob(log_pattern)):
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
                    if p.is_absolute():
                        resolved = p.resolve()
                    else:
                        resolved = (src_base / p).resolve()
                    valid.add(resolved)
        except Exception as e:
            print(f"[Warning] 读取 {log_file} 出错: {e}", file=sys.stderr)

    return valid


def collect_target_entries(target_dir: Path) -> list[Path]:
    """递归收集 target_dir 下所有文件和文件夹（相对于 target_dir）。"""
    entries: list[Path] = []
    for entry in target_dir.rglob("*"):
        entries.append(entry)
    return entries


def find_unused(
    target_dir: Path, entries: list[Path], valid_paths: set[Path]
) -> list[Path]:
    """找出所有不被合法路径引用的条目。

    对于目录：仅当它本身不在合法路径中，且其下没有任何被引用的文件时，才视为未引用。
    对于文件：只要不在合法路径中即视为未引用。
    """
    # 1) 标记哪些目录下含有合法文件
    dir_has_valid = set()
    for entry in entries:
        if not entry.is_file():
            continue
        resolved = entry.resolve()
        if resolved in valid_paths:
            # 向上标记所有祖先目录
            parent = entry.parent
            while parent != target_dir.parent:
                dir_has_valid.add(parent)
                parent = parent.parent
                if parent == target_dir.parent:
                    break

    # 2) 筛选未引用的条目
    unused: list[Path] = []
    for entry in entries:
        resolved = entry.resolve()
        if resolved in valid_paths:
            continue
        if entry.is_dir():
            if resolved in dir_has_valid:
                continue
        unused.append(resolved)

    return unused


UNUSED_LIST_FILE = "unused_assets_list.txt"


def _load_unused_file(file_path: str) -> list[Path]:
    """从文件加载要删除的条目列表（每行一个路径）。"""
    paths: list[Path] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            paths.append(Path(line))
    return paths


def main():
    parser = argparse.ArgumentParser(
        description="找出 target_dir 中未被任何 assets_*.log 引用的文件/文件夹。"
    )
    parser.add_argument("src_base", nargs="?", help="assets_*.log 所在的基础目录")
    parser.add_argument("target_dir", nargs="?", help="要扫描的目标目录")
    parser.add_argument(
        "--act",
        metavar="FILE",
        help="从指定文件读取条目并执行删除，此时无需 src_base 和 target_dir。"
        "该文件可由扫描模式自动生成（unused_assets_list.txt）。",
    )
    args = parser.parse_args()

    # ---- 删除模式 ----
    if args.act:
        unused = _load_unused_file(args.act)
        if not unused:
            print(f"{args.act} 中没有有效条目，无需操作。")
            return 0
        print(f"从 {args.act} 加载了 {len(unused)} 个条目，开始删除 ...\n" + "=" * 40)
        _delete_items(unused)
        print(f"\n删除完成。")
        return 0

    # ---- 扫描模式 ----
    if not args.src_base or not args.target_dir:
        parser.error("未使用 --act 时，必须提供 src_base 和 target_dir")

    src_base = Path(args.src_base).resolve()
    target_dir = Path(args.target_dir).resolve()

    if not src_base.is_dir():
        print(f"错误：src_base 不是有效目录: {src_base}", file=sys.stderr)
        sys.exit(1)
    if not target_dir.is_dir():
        print(f"错误：target_dir 不是有效目录: {target_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[1/3] 收集合法路径 from {src_base}/assets_*.log ...")
    valid_paths = collect_valid_paths(src_base)
    print(f"      -> 共收集到 {len(valid_paths)} 条合法路径")

    print(f"[2/3] 扫描目标目录 {target_dir} ...")
    all_entries = collect_target_entries(target_dir)
    print(f"      -> 共发现 {len(all_entries)} 个条目")

    print(f"[3/3] 比对并找出未引用条目 ...")
    unused = find_unused(target_dir, all_entries, valid_paths)

    if unused:
        # 排序：目录在前，文件在后，各自按路径名排序
        sorted_items = sorted(unused, key=lambda x: (not x.is_dir(), str(x)))
        print(f"\n未引用的条目 ({len(sorted_items)} 个):\n" + "=" * 40)
        for p in sorted_items:
            print(p)

        # 写入文件
        with open(UNUSED_LIST_FILE, "w", encoding="utf-8") as f:
            for p in sorted_items:
                f.write(str(p) + "\n")
        print(f"\n条目列表已保存到当前目录下的 {UNUSED_LIST_FILE}")
        print(f"审阅后执行: python misc/clean_assets.py --act {UNUSED_LIST_FILE}")
    else:
        print("\n所有条目均被引用，无需清理。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
