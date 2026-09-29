# 安卓版（GameLedger.apk）

本目录是 `android` 分支的安卓打包工程：把同一套前端（内置游戏库 + 原生存储桥）
打进一个无后端的 WebView 壳应用，产出可直接安装的 APK。

## 与桌面版的差异

| | 桌面版（main 分支） | 安卓版（android 分支） |
| --- | --- | --- |
| 后端 | Flask + SQLite（`data/prices.db`） | 无后端，`StorageBridge.java` 直连应用私有 SQLite |
| 数据层 | REST API over HTTP | 同一套 REST 语义，经 `GameLedgerBridge.request()` JS 桥同步调用 |
| 游戏库 | `/api/games/catalog`（服务端内存直出） | 构建期生成的 `www/games.js`（`window.__GAMES__`） |
| 封面 | 内置资源 → 本地缓存 → 在线下载 | 内置资产 + 缺失时在线回退（`app.js` 的 `coverImgError`） |
| 运行方式 | 桌面窗口（pywebview） | 安装 APK，全屏竖屏 WebView |
| 数据位置 | exe 同目录 `data/` | 应用私有目录 `prices.db`（随更新保留、卸载即清） |

前端在 `file://` 协议下自动进入 `NATIVE_MODE`（`game_ledger/static/app.js`），
全部 REST 调用改走存储桥；CSV 导出走 `StorageBridge.saveFile()`（写入系统下载目录），
CSV 导入走系统文件选择器（`onShowFileChooser`）。

## 构建一次（双击）

1. 确保已运行过桌面版 `start.bat`（存在 .venv，内含 jinja2/Pillow）；
2. 准备工具链（只需一次，约 250MB，见下）；
3. 首次构建先生成签名密钥（见仓库根 README「安卓签名密钥」小节）：
   `android\build_apk.bat --init-keystore`；
4. 双击 `build_apk.bat`；
5. 产物：`android\output\GameLedger.apk`，传到手机安装
   （需允许「安装未知应用」；签名证书固定，后续版本可直接覆盖安装）。

## 工具链准备（仅首次，两种方式任选）

**方式一（推荐）：系统级安装，全机项目共用**

1. 安装 JDK 17（如 Eclipse Temurin），设用户环境变量 `JAVA_HOME` 指向其根目录；
2. 准备 Android SDK：下载 [commandline-tools](https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip)
   解压到固定目录（如 `D:\Tools\android-sdk`，注意命令行工具需放入
   `cmdline-tools\latest\` 子目录），再安装两个组件：
   `sdkmanager "build-tools;34.0.0" "platforms;android-34"`；
3. 设用户环境变量 `ANDROID_HOME` 指向 SDK 根目录。完成——
   `build_apk.py` 优先从 `JAVA_HOME` / `ANDROID_HOME` 定位工具链，
   所有项目共享同一份，`sdkmanager` 统一升级。

（国内网络 `dl.google.com` 不可达时，组件 zip 可从腾讯云镜像
`https://mirrors.cloud.tencent.com/AndroidSDK/` 手动下载解压：
`build-tools_r34-windows.zip` → `build-tools\34.0.0`，
`platform-34-ext7_r03.zip` → `platforms\android-34`，
并在 `licenses\` 写入标准许可哈希后 `sdkmanager --list_installed` 应能识别。）

**方式二：项目内工具链（无环境变量时的回退）**

下载并解压到项目根目录 `.android-build\`（脚本自动识别目录名）：

| 组件 | 下载地址 | 解压后 |
| --- | --- | --- |
| JDK 17 | https://github.com/adoptium/temurin17-binaries/releases （选 `OpenJDK17U-jdk_x64_windows_hotspot_*_zip`） | `.android-build\jdk-17.0.x+x\` |
| Android Build-Tools 34 | https://dl.google.com/android/repository/build-tools_r34-windows.zip | `.android-build\android-14\` |
| Android Platform 34 | https://dl.google.com/android/repository/platform-34-ext7_r03.zip | `.android-build\android-34\` |

## 构建流程（build_apk.py 自动执行）

1. `android/prepare_assets.py`：Jinja2 预渲染前端页面（注入版本号/来源预设，
   `/static/` 改相对路径、注入 games.js），复制 `app.js / style.css / covers\`
   到 `app/src/main/assets/www/`（构建生成物，不入库）；
2. 从 `scripts/icon.ico` 生成全密度启动图标；
3. `javac --release 8` 编译 `MainActivity.java / StorageBridge.java` → `d8` 转 dex；
4. `aapt2 compile/link` 打包清单、资源与 www 资产（versionName 自动取
   `game_ledger.__version__`）→ `zipalign` → `apksigner` 用发布密钥签名。

## 存储桥语义

`StorageBridge.request(method, path, query, jsonBody)` 同步返回
`{"status": int, "body": <与桌面端 REST 响应一致的 JSON>}`，覆盖：
列表（搜索/分类/来源筛选）、CRUD、suggest（含历史最低价）、价格历史、
CSV 导出/导入（校验与去重规则移植自 `game_ledger/records.py`）。
表结构与迁移链（`PRAGMA user_version` v1→v5）与 `game_ledger/database.py`
一致，桌面端导出的 CSV 可直接导入。

## 注意

- SQLite 数据在应用私有目录，卸载即失；CSV 导出是唯一备份手段（README 已注明）；
- 新包名 `com.gameledger.app` + 新发布签名与旧侧载的 SwitchPriceTracker 不互通，
  需先卸载旧版再安装；
- 应用商店上架需要正式签名与合规审查，本 APK 为自签名旁加载包。
