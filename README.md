# Switch 卡带价格统计

本地使用的 Switch 卡带（NS / NS2）价格记录小工具：Flask + SQLite + 桌面窗口，
支持搜索、分类/来源筛选、排序、新增时自动联想已有卡带并提示价格涨跌、按来源统计。

## 快速开始（双击即用）

- **日常使用**：双击 **`启动.bat`**。首次运行会自动创建虚拟环境并安装依赖（需联网一次），
  之后每次双击即启动服务并自动打开浏览器；关闭黑色窗口即退出服务。
  如果程序已在运行，再次双击只会新开一个浏览器标签，不会重复启动。
  （bat 脚本内部的少量英文提示是刻意的：Windows cmd 解析非 ASCII 编码的 bat 容易出错，
  程序界面与日志均为中文。）
- **打包成桌面软件**：双击 **`打包.bat`**，完成后在 `dist\SwitchPriceTracker\` 里双击
  `SwitchPriceTracker.exe` —— 弹出的是**独立软件窗口**（Edge WebView2 渲染），
  不打开浏览器、没有黑色控制台窗口，任务栏/窗口图标为应用图标。
  - 重复双击会提示「已在运行中」，不会开第二个窗口；
  - 数据保存在 exe 同目录的 `data` 文件夹下，整个文件夹可拷贝到其他 Windows 电脑
    （目标机器无需安装 Python；系统需自带 WebView2 运行时，Win10/11 默认已有）；
  - 关闭窗口即退出服务。
  注意：**重新打包会清空 `dist` 内的内容**，如数据已产生在 dist 里，打包前请先备份
  （`打包.bat` 检测到时会提醒你）。

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
│   └── icon.ico              # 应用图标（exe / 任务栏）
├── switch_price_tracker/     # 应用包
│   ├── __init__.py           # create_app 应用工厂 + 全局错误处理
│   ├── config.py             # 集中配置（路径/主机/端口，支持环境变量覆盖）
│   ├── routes.py             # 路由层（页面 + REST API，只做校验不碰 SQL）
│   ├── database.py           # 数据访问层（全部 SQL 集中于此）
│   ├── serve.py              # 浏览器模式启动逻辑（端口检测、自动开浏览器）
│   ├── window.py             # 桌面窗口模式（pywebview + 单实例锁 + 随机端口）
│   ├── templates/            # 前端页面
│   └── static/               # 前端 JS / CSS
├── tests/                    # pytest 测试
└── data/                     # 本地数据
    └── prices.db             # SQLite 数据库
```

## 功能与界面

- **统计卡片**：总记录 / NS / NS2 / 总花费一览，下方为来源分布；
- **来源追踪**：每条记录可标注来源（拼多多福袋 / 拼多多V3 / 支付宝刷券 / 其他可自由填写），
  支持按来源筛选，表格中彩色标签展示；
- **新增联想**：输入名称自动联想已有卡带并对比价格涨跌，可选择直接更新该条记录；
- **排序 / 搜索**：分类、名称、价格、来源、更新时间均可点击表头排序。

## 数据库说明

- 数据库文件：`data/prices.db`（打包版在 exe 同目录 `data/` 下），WAL 模式。
- 表结构由 `switch_price_tracker/database.py` 统一管理，采用 `PRAGMA user_version`
  轻量迁移：改表时把 `SCHEMA_VERSION` 加 1 并在 `MIGRATIONS` 追加步骤即可，
  首次运行会自动执行迁移，并把旧库备份为 `data/prices.backup-v<旧版本>.db`。
  （当前版本：v2 —— v2 新增 `source` 来源字段。）
- 备份数据：直接复制 `data/prices.db`（应用未运行时）即可。
- 测试使用临时数据库，不会触碰真实数据。

### 表结构（cartridges）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | INTEGER | 主键自增 |
| category | TEXT | 分类，仅允许 `NS` / `NS2` |
| name | TEXT | 卡带名称 |
| price | REAL | 价格（默认 0） |
| source | TEXT | 来源（预设值或自定义文本，最长 50 字符，默认空） |
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
| POST | `/api/cartridges` | 新增 |
| PUT | `/api/cartridges/<id>` | 更新（未提供的字段保留原值） |
| DELETE | `/api/cartridges/<id>` | 删除 |
| GET | `/api/cartridges/suggest?q=` | 名称联想（最多 5 条） |

响应统一为 `{"success": true|false, "data"?: ..., "message"?: ...}`。

## 测试

```
.venv\Scripts\python.exe -m pytest
```

## 从旧版本迁移

- v1（根目录单文件 `app.py` + `database.py`）→ 包结构重构，接口与页面行为不变，
  数据库自动建立索引并升级 schema；
- v1 → v2 自动新增 `source` 来源列，旧数据来源为空，不受影响。
