# Switch 卡带价格统计

本地使用的 Switch 卡带（NS / NS2）价格记录小工具：Flask + SQLite + 桌面窗口，
**内置 1.9 万余款 Switch 游戏目录**（官方英文介绍 + 盒装封面 + 港服繁体名称/介绍），
填表时**输入中文名或常用别名即可搜索关联**（如「塞尔达王国之泪」「喷射战士」「街霸6」）；
支持搜索、分类/来源筛选、排序、新增时自动联想已有卡带并提示价格涨跌、按来源统计；
**深色 / 浅色主题一键切换**（浅色为任天堂红点缀）。

## 快速开始（双击即用）

- **日常使用**：双击 **`启动.bat`**。首次运行会自动创建虚拟环境并安装依赖（需联网一次），
  之后每次双击即启动服务并自动打开浏览器；关闭黑色窗口即退出服务。
  如果程序已在运行，再次双击只会新开一个浏览器标签，不会重复启动。
  （bat 脚本内部的少量英文提示是刻意的：Windows cmd 解析非 ASCII 编码的 bat 容易出错，
  程序界面与日志均为中文。）
- **打包成桌面软件**：双击 **`打包.bat`**，完成后在 `release\SwitchPriceTracker\` 里双击
  `SwitchPriceTracker.exe` —— 弹出的是**独立软件窗口**（Edge WebView2 渲染），
  不打开浏览器、没有黑色控制台窗口，任务栏/窗口图标为应用图标。
  - **便携**：整个 `SwitchPriceTracker` 文件夹拷到任意位置（其他目录、其他电脑）双击即用，
    无需安装；系统需自带 WebView2 运行时（Win10/11 默认已有）；
  - 重复双击会提示「已在运行中」，不会开第二个窗口；
  - 数据保存在 exe 同目录的 `data` 文件夹下，随文件夹一起迁移；
  - 关闭窗口即退出服务。
  注意：**重新打包会清空 `release` 内的内容**，如数据已产生在 release 里，打包前请先备份
  （`打包.bat` 检测到时会提醒你）。
  打包完成后还会把整个文件夹压缩为 `release\SwitchPriceTracker-portable.zip`——
  发布到 GitHub Release 时，zip 即为可直接下载解压使用的单文件资产。

> 无需命令行；若想手动运行：`python run.py`（浏览器模式，便于开发调试）。

## 项目结构

```
switch-price-tracker/
├── 启动.bat                  # 双击启动（自动建 venv / 装依赖 / 开浏览器）
├── 打包.bat                  # 双击打包桌面 exe（dist\SwitchPriceTracker\）
├── run.py                    # 开发运行入口（浏览器模式）
├── launcher.py               # PyInstaller 打包入口（桌面窗口模式）
├── wsgi.py                   # WSGI 入口（供 waitress/gunicorn 使用）
├── requirements.txt          # 运行依赖
├── requirements-dev.txt      # 开发依赖（pytest、pyinstaller、pillow）
├── scripts/
│   ├── make_icon.py          # 生成应用图标
│   ├── icon.ico              # 应用图标（exe / 任务栏）
│   └── fetch_games.py        # 抓取/更新内置游戏库与封面
├── switch_price_tracker/     # 应用包
│   ├── __init__.py           # create_app 应用工厂 + 全局错误处理
│   ├── config.py             # 集中配置（路径/主机/端口，支持环境变量覆盖）
│   ├── routes.py             # 路由层（只做 HTTP：解析请求/构造响应）
│   ├── records.py            # 领域逻辑（字段校验 + CSV 导入/导出解析）
│   ├── database.py           # 数据访问层（全部 SQL 集中于此）
│   ├── games.py              # 内置游戏库（目录加载/搜索/封面解析）
│   ├── serve.py              # 浏览器模式启动逻辑（端口检测、自动开浏览器）
│   ├── window.py             # 桌面窗口模式（pywebview + 单实例锁 + 随机端口）
│   ├── templates/            # 前端页面
│   ├── static/               # 前端 JS / CSS + games.js
│   └── assets/               # 内置游戏库数据与封面缓存
├── android/                  # 安卓分支新增：APK 构建工程（见 android/README.md）
├── tests/                    # pytest 测试
└── data/                     # 本地数据
    ├── prices.db             # SQLite 数据库
    └── covers/               # 运行时下载的封面缓存
```

## 功能与界面

- **统计卡片**：总记录 / NS / NS2 / 总花费一览，下方为来源分布；
- **价格历史**：新增/改价自动记录（迁移时为存量记录播种当前价），
  详情弹窗显示价格走势图与最低/最高/记录次数；
  新增联想时提示「历史最低 ¥X」，输入价更低时提示「低于历史最低」；
- **CSV 导出 / 导入**：一键导出全部记录（UTF-8 带 BOM，Excel 直接打开），
  或从 CSV 批量导入——分类+名称重复的行自动跳过，坏行汇报不中断；

- **统计卡片**：总记录 / NS / NS2 / 总花费一览，下方为来源分布；
- **来源追踪**：每条记录可标注来源（拼多多福袋 / 拼多多V3 / 支付宝刷券 / 其他可自由填写），
  支持按来源筛选，表格中彩色标签展示；
- **内置游戏库**：19,500+ 款 Switch 游戏（名称、官方英文介绍、盒装封面、发行商、
  发售日期、分类、**港服繁体名称与繁体介绍**），数据来自 Nintendo eShop 欧洲区官方接口
  与港服目录镜像，随应用离线内置。桌面端从 `/api/games/catalog` 加载目录
  （唯一数据源 assets/games.json）；新增/编辑时输入名称即可联想游戏库——
  **中文名、简体化名、常用别名（喷射战士、街霸、怪物猎人……）均可命中**，
  点击「关联」自动把名称补全为规范全称、挂上高清封面与介绍；
  表格显示封面缩略图，点击名称弹出详情页（大图封面 + 介绍，繁体中文优先）；
  未内置的热门封面之外按需下载并缓存到 `data/covers/`，联网一次即离线可用；
- **自定义别名**：每条记录可填可选别名（如全称「塞尔达传说 旷野之息」加别名「野炊」），
  顶栏搜索与新增联想都会命中别名，多个别名用空格或逗号分隔；
- **深色 / 浅色主题**：右上角一键切换并记忆，首帧前应用主题、切换不闪烁；
  浅色主题以任天堂红（#E60012）为主色与描边；
- **新增联想**：输入名称自动联想已有卡带并对比价格涨跌，可选择直接更新该条记录；
- **排序 / 搜索**：分类、名称、价格、来源、更新时间均可点击表头排序。

### 游戏库数据更新（可选）

```bash
.venv\Scripts\python.exe scripts\fetch_games.py          # 全量目录 + 中文接入 + 前 400 个热门封面
.venv\Scripts\python.exe scripts\fetch_games.py --covers 800   # 自定义本地化封面数量
.venv\Scripts\python.exe scripts\fetch_games.py --skip-covers  # 只更新目录（含中文接入）
.venv\Scripts\python.exe scripts\fetch_games.py --skip-zh      # 跳过中文接入
```

脚本会从 Nintendo eShop（欧洲区）重新抓取并重建 `switch_price_tracker/assets/games.json`
（唯一数据源）与 `static/games.js`（仅供安卓分支打包 APK 使用，桌面端不用），
按发售日期倒序，封面本地化前 N 个热门游戏。

**中文数据接入**（默认开启，`--skip-zh` 跳过）：欧服目录的 Title ID（跨区通用）映射
[blawar/titledb](https://github.com/blawar/titledb) 的 `HK.zh.json`（港服目录镜像，MIT），
为每条记录补充繁体中文名 `zh` 与简体化名 `zhs`（OpenCC 转换 + 塞尔达/马力欧等译名修正）；
常用别名（喷射战士/街霸/怪物猎人等大陆叫法）人工维护在 `scripts/zh_aliases.py`。
首次运行会下载约 50 MB 镜像缓存到 `scripts/.cache/`；港服镜像通常滞后新发售游戏数天。

**存量记录反查**：为手输中文名的旧记录自动匹配游戏库（补封面与介绍），先备份再写库：

```bash
.venv\Scripts\python.exe scripts\link_existing.py          # 预览匹配结果
.venv\Scripts\python.exe scripts\link_existing.py --apply  # 确认无误后写库
```

## 数据库说明

- 数据库文件：`data/prices.db`（打包版在 exe 同目录 `data/` 下），WAL 模式。
- 表结构由 `switch_price_tracker/database.py` 统一管理，采用 `PRAGMA user_version`
  轻量迁移：改表时把 `SCHEMA_VERSION` 加 1 并在 `MIGRATIONS` 追加步骤即可，
  首次运行会自动执行迁移，并把旧库备份为 `data/prices.backup-v<旧版本>.db`。
  （当前版本：v5 —— v2 新增 `source` 来源字段，v3 新增 `cover`/`intro` 游戏库关联字段，
  v4 新增 `price_history` 价格历史表并为存量记录播种当前价，v5 新增 `alias` 自定义别名字段。）
- 备份数据：直接复制 `data/prices.db`（应用未运行时），或用界面上「导出 CSV」。
- 测试使用临时数据库，不会触碰真实数据。

### 表结构（cartridges）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | INTEGER | 主键自增 |
| category | TEXT | 分类，仅允许 `NS` / `NS2` |
| name | TEXT | 卡带名称 |
| alias | TEXT | 用户自定义别名（可选，如「野炊」，用于检索，最长 100 字符） |
| price | REAL | 价格（默认 0） |
| source | TEXT | 来源（预设值或自定义文本，最长 50 字符，默认空） |
| cover | TEXT | 关联的内置游戏 ID（NSUID，用于封面展示） |
| intro | TEXT | 游戏介绍（关联游戏库时自动填入，可编辑） |
| notes | TEXT | 备注 |
| created_at / updated_at | TIMESTAMP | 创建 / 更新时间（UTC） |

## 配置（环境变量，均可选）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SWPT_HOST` | `127.0.0.1` | 监听地址 |
| `SWPT_PORT` | `5000` | 监听端口（桌面窗口模式自动使用随机空闲端口） |
| `SWPT_DATA_DIR` | `<根目录>/data` | 数据目录位置 |
| `SWPT_NO_BROWSER` | 未设置 | 设为 `1` 时浏览器模式不自动打开浏览器 |

## REST API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 单页前端 |
| GET | `/api/cartridges?search=&category=&source=` | 列表（搜索 / 分类 / 来源过滤） |
| GET | `/api/cartridges/<id>` | 单条详情 |
| GET | `/api/cartridges/<id>/history` | 价格历史（时间正序） |
| POST | `/api/cartridges` | 新增 |
| PUT | `/api/cartridges/<id>` | 更新（未提供的字段保留原值；改价自动记历史） |
| DELETE | `/api/cartridges/<id>` | 删除 |
| GET | `/api/cartridges/suggest?q=` | 名称联想（最多 5 条，含历史最低价） |
| GET | `/api/export/csv` | 导出全部记录（UTF-8 带 BOM） |
| POST | `/api/import/csv` | 从 CSV 导入（multipart `file` 字段） |

响应统一为 `{"success": true|false, "data"?: ..., "message"?: ...}`。

## 测试

```
.venv\Scripts\python.exe -m pytest
```

## 从旧版本迁移

- v1（根目录单文件 `app.py` + `database.py`）→ 包结构重构，接口与页面行为不变，
  数据库自动建立索引并升级 schema；
- v1 → v2 自动新增 `source` 来源列，旧数据来源为空，不受影响。
