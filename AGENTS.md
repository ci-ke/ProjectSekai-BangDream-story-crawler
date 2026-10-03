# AGENTS.md

Project Sekai / BanG Dream! 剧本爬虫（story-crawler）。本文件供 AI 助手快速了解项目结构与约定，
所有路径默认相对本仓库根目录，改动涉及的结构若有变化应同步更新此文件。

## 仓库结构

本仓库是爬虫本体（GitHub 仓库 story-crawler）。上一级工作区目录（不是 git 仓库）里还有与本仓库配套的
6 个输出仓库和批量管理脚本，本仓库的运行产物最终输出到它们：

- `../repo_story_pjsk|bang|bdon/`：剧本文本输出仓库（story_cn/en/jp/tw 目录）
- `../repo_assets_pjsk|bang|bdon/`：assets 缓存输出仓库（assets/ 与 assets_decompress/。其中assets_decompress中存放的是用misc/decompress_assets.py解压的asset，会被git ignore）
- `../git_status.ps1`、`../pull_all.ps1`、`../sync_dev.ps1`：7 仓库批量管理脚本

本仓库结构：

```
├── src/        核心库：pjsk.py / bang.py / bdon.py / util.py / config.json / bypass.txt
├── action/     CI 入口脚本（9 个文件，GitHub Actions 调用）
├── test/       本地测试（被 gitignore 的 test* 规则忽略，不进仓库）
├── misc/       argparse 维护工具（check_bypass / clean_assets / decompress_assets）
└── .github/workflows/common-update.yml   可复用 CI 模板（workflow_call）
```

## 运行方式（一律走 uv，均在仓库根目录执行）

```bash
uv run -m src.pjsk                 # 本地抽样手测（三条线同理：src.bang / src.bdon）
uv run python -m action.all_pjsk   # CI 实际调用方式（action 是包，python -m action.xxx）
uv run python action/assets_pjsk.py full   # assets 入口，sys.argv[1] 取 full|incremental
uv run python -m test.smoke_bang_init      # 本地测试必须用 -m 方式运行
uv run mypy                                # 类型检查
```

## src 核心模块

三条产品线各一个模块，互不依赖，只依赖 util。每模块含：`Constant`（URL 与语言映射）、
`Story_reader`（统一持有 master 表）、若干 getter（抓剧本写 txt）、`Getters_type`（TypedDict）、
`Run`（getter 创建/初始化）、模块级 `main()`（本地抽样入口，硬编码参数，不用 argparse）。

**util.py**：`Base_fetcher`（assets 缓存与网络参数）、`Base_getter`（+ save_dir 与 parse）、
`fetch_url_json` / `read_json_from_url`（10 次重试、RateLimit QPS 控制、bypass.txt 名单、
失败记 assets_error.log、brotli `.br` 压缩缓存）、`Mark_multi_lang`（中/英标注符号表）、
`remove_olds_or_rename_old`（重抓时按 `(\d+) ` 数字前缀清理/改名旧文件）、`LATE_TIMESTAMP13`（+365 天）。
offline 模式（online=False）下缺文件且 missing_download=True 会自动联网补抓并写缓存。

## Run 类（getter 创建与初始化）

每个 src 模块有一个 `Run` 类，全部静态方法：

- `Run.create_getters(...)`：创建 reader + 全部 getter。
  pjsk 版签名 `create_getters(langs=(('cn', 'cn'),), save_dir='.', assets_save_dir='.', args=None)`，
  `langs` 是 (lang, mark_lang) 双语言元组列表，一次建多语言，返回 `dict[str, Getters_type]`（按 lang 为键）；
  bang/bdon 版无 langs，返回单套 `Getters_type`（其实例本身跨语言）。显式路径参数优先于 args 里的同名键；
  args 经 `**args` 展开进每个构造器（各构造器都有 `**args` 兜底，未声明的键静默吞掉）。
- `Run.init_getters(...)`：reader 最先 init（getter 的 init 依赖 reader 的 master 数据），其余并发 init；
  `init_names` 参数可只 init 子集（new_pjsk 用）。pjsk 版操作 `dict[str, Getters_type]`，
  bang/bdon 版操作单套。
- **任务编排留在 action**：`add_common_tasks` / `add_timestamp_tasks` / `add_all_tasks` 及常量
  `TIMESTAMP13`、`LANGS`、`NET_CONNECT_LIMIT` 是各 action 的差异所在，不放进 src。

## 路径与存储约定（重要）

- `save_dir` 参数语义是**根目录**（默认 `'.'`），固定子路径 `story_{lang}/<类型>` 写死在各 getter
  `__init__` 的 super 调用里（`os.path.join(save_dir, 'story_{lang}', 'event')`），不可自定义。
- `assets_save_dir` 同理：根目录默认 `'.'`，`Base_fetcher` 固定追加 `'assets'`。
- 取值约定：默认 `'.'` → 产物落在本仓库根目录（本地手测）；CI 传 `'..'` → 落在上级目录
  （输出仓库所在处）；test 传绝对路径 → 落在 ../repo_story_* / ../repo_assets_*。改输出位置只动这一处参数。
- getter 清单与固定子路径：

| 模块 | getter → story_{lang}/ 下的子路径 |
|---|---|
| pjsk（8 个） | event、main、card、area、self、special、mysekai、virtual_live |
| bang（6 个） | event、band、main、card、area、after_live |
| bdon（6 个） | band、special（仅 chapter.json 的 _isSpecialStory 章，目录/命名逻辑与 band 共用）、friendship、home、live_result、tutorial |

- assets 缓存与语言/站点分桶由 `append_save_path` 决定，与 save_dir 无关：pjsk 用 `pjsk-{lang}-master/`、
  `pjsk-{lang}-assets/`；bdon 用 config 的 `save_roots`（服务基址 → 存盘根）；bang 按 URL 路径落盘。

## 三条产品线的语言机制差异（重要）

- **pjsk**：`{lang}` 在 init 时 format，一个 getter 实例只服务一个语言；action 里按语言各建一套
  （`dict[str, Getters_type]`，键为 cn/tw/jp/en）。master/asset 的实际 URL 按 config.json 的
  `master_lang`/`asset_lang` 映射从各源站取。
- **bang**：`{lang}` 在每次 `get(id, lang, mark_lang)` 时 format，一个实例服务所有语言；
  文本取多语言数组的下标（`Constant.lang_index`）。`mark_lang`（'cn'/'en'）决定 `Mark_multi_lang` 标注风格。
- **bdon**：按**数据面**组织（`SIDES`/`SIDE_LANGS`）——国际服面 `en`（/master + en 段剧本表，
  全语言）与日服面 `jp`（/jp/master + ja 段剧本表，近乎纯日语）。两面各自一套 reader+getter
  （`Run.create_getters(side=..., lang_dir=...)`）与独立缓存桶（bdon-{en,jp}-master /
  bdon-{en,jp}-assets，基址映射在 config 的 `save_roots`）。CI 的 story_jp 由国际服面的
  合成语言 `en-jp`（国际服 dump 的日语列，`text_field`/`Fallback.chain` 已登记）产出，
  经 getter 的 `lang_dir={'en-jp': 'jp'}` 接管存储目录写 story_jp；日服面暂不参与 action，
  待其剧本表在发布服务稳定后用 `side='jp'` 启用（本地 main 同时产出两种日语来源供对比）。
  `get(master_id, langs=...)` 的 langs 缺省取所在面的 `SIDE_LANGS`；action 的 `CI_LANGS`
  不产出 kr。目标语言缺失时按回落链取值并标注实际语言，机制在独立类 `Fallback`
  （静态方法+类字段）。

## 时间戳抓取（pjsk/bang）

- `TIMESTAMP13` = UTC+36h（cn/tw 服务器先行），`TIMESTAMP13_EN` 再 +15h（定义在 action/all_pjsk.py）。
- `util.LATE_TIMESTAMP13` = +365 天 ≈ 全抓，是 timestamp13 的默认值。
- pjsk/bang 带时间戳字段的 getter 的 `get()` 都带 `timestamp13` 过滤（None 为不过滤）：
  pjsk 为 event/card/special/virtual/area，bang 为 event/card。
- pjsk/bang 的 event、card 另保留 `get_newest`（按 quantity 取最新若干条，quantity=0 为全抓）；
  其内部调 `get(..., timestamp13=None)`（id 层已按 timestamp13 筛过，避免 get 层二次过滤）。
- 其余 getter 由 action 遍历 `tell_ids()` / `tell_categories()` 并把 timestamp13 传入 get
  （见 all_pjsk 的 `add_timestamp_tasks`）。

## action/（CI 入口）

9 个脚本分三组：`all_*`（全量）、`new_*`（增量）、`assets_*`（仅 assets，`sys.argv[1]` = full|incremental，
full 在线抓、incremental 只读缓存）。对应输出仓库：

| action | 输出仓库 |
|---|---|
| all_pjsk / new_pjsk | ProjectSekai-story |
| all_bang / new_bang | BangDream-story |
| all_bdon / assets_bdon | BanG Dream! Our Notes stories |
| assets_pjsk / assets_bang | Story-assets (pjsk-bang-story-assets) |

CI 链路：各输出仓库的 workflow 通过 `.github/workflows/common-update.yml` 模板（workflow_call）→
clone 本仓库 →（assets 任务先 clone assets 仓库并把 `assets/` 移入本仓库根目录）→
在仓库根目录下执行 `python -m action.xxx` → commit & push 输出仓库。

## test/（本地测试，gitignore）

- `all_*.py`：与对应 action/all_* 的唯一差异是输出位置——任务编排函数与常量直接从 `action.*` 导入，
  只自定义顶部 `STORY_ROOT` / `ASSETS_ROOT` 两个常量（`ASSETS_ROOT` 是父目录，不带 `\assets` 后缀）。
- `assets_*.py`：assets 版本地测试，与 test/all_* 同模式——任务编排从 `action.*` 导入，
  `ASSETS_ROOT` 常量指定缓存仓库（父目录，不带 `\assets` 后缀）；
  用法同 action 版（`uv run python -m test.assets_pjsk full`）。
- `smoke_*_init.py`：只 create+init 不抓剧本，打印数据量。
- 运行必须 `uv run python -m test.xxx` 且在仓库根目录下（普通路径方式 import 不到 src/action）。

## 验证清单（改完代码后）

1. `uv run mypy`（mypy.ini 覆盖 src/、action/ 与 misc/，本地文件未入 git，项目 venv 未装
   mypy，实际走全局 uv tool 的 mypy；TypedDict 用变量做下标需 `# type: ignore[literal-required]`）。
2. import 冒烟：`uv run python -c "import action.all_pjsk, action.all_bang, action.all_bdon, ..."`。
3. smoke：`uv run python -m test.smoke_bang_init` / `test.smoke_bdon_init`（online=False + 本地缓存，
   缺文件会联网补抓，属正常行为）。
4. 涉及路径改动：临时脚本构造 getter 打印 save_dir 验证拼接，无需网络。

## 环境注意事项

- Windows + Git Bash；Python 全部由 uv 管理，一律 `uv run ...`，禁止 --break-system-packages。
- 网络需走系统代理：aiohttp 会话要 `trust_env=True`（所有正式入口都已带）。不带时访问
  sekai-world.github.io（pjsk master 源）会失败并记入 assets_error.log；bestdori.com / bdon.moe 可直连。
- 本地 assets/ 缓存（仓库根目录下）长期只有 bang/bdon 数据；pjsk 首次跑会大量在线补抓。
- 临时调试脚本不要留在 test/ 里（该目录虽被 gitignore，但会干扰下次阅读）。

## 代码风格

- 注释用中文；无 linter/formatter 配置。
- action/src 的 main 不用 argparse（只有 misc/ 用）；assets_* action 用 sys.argv[1] 断言取 full|incremental。
- 基类构造参数：online / save_assets / parse（getter 才有）/ missing_download / compress_assets /
  force_master_online。
- `_path` 类私有常量、`Xxx_type` 类型别名、`Getters_type` TypedDict 是既有命名惯例。
