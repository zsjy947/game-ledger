"""一键构建安卓 APK（无需 Android Studio）。

流程：准备资产 → 生成图标 → javac 编译 → d8 转 dex → aapt2 打包资源与资产
→ 合入 classes.dex → zipalign 对齐 → apksigner 签名。

工具链（JDK 17 / Android build-tools 34 / platform-34）默认从 .android-build/ 读取，
首次准备见 android/README.md。

签名：读取 keystore/keystore.properties（首次用 --init-keystore 生成，
见 README「安卓签名密钥」小节）。

用法：
    .venv\\Scripts\\python.exe android\\build_apk.py                # 构建
    .venv\\Scripts\\python.exe android\\build_apk.py --init-keystore # 首次：生成签名密钥
输出：
    android\\output\\GameLedger.apk
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANDROID_DIR = Path(__file__).resolve().parent
APP_DIR = ANDROID_DIR / "app" / "src" / "main"
BUILD_DIR = ANDROID_DIR / "output" / "build"
APK_OUT = ANDROID_DIR / "output" / "GameLedger.apk"

TOOLS_DIR = PROJECT_ROOT / ".android-build"
KEYSTORE_DIR = PROJECT_ROOT / "keystore"
KEYSTORE_FILE = KEYSTORE_DIR / "game-ledger-release.keystore"
KEYSTORE_PROPS = KEYSTORE_DIR / "keystore.properties"

MIN_SDK = 24
TARGET_SDK = 34


def find_toolchain():
    """定位 JDK、build-tools 与 platform android.jar。"""
    jdk = None
    for cand in sorted(TOOLS_DIR.glob("jdk-17*")) + sorted(TOOLS_DIR.glob("jdk-*")):
        if (cand / "bin" / "javac.exe").exists() or (cand / "bin" / "javac").exists():
            jdk = cand
            break
    if jdk is None:
        raise SystemExit("未找到 JDK：请按 android/README.md 先准备 .android-build/jdk-17*")

    bt = None
    for cand in sorted(TOOLS_DIR.glob("android-*")):
        if (cand / "aapt2.exe").exists() or (cand / "aapt2").exists():
            bt = cand
            break
    if bt is None:
        raise SystemExit("未找到 Android build-tools：请按 android/README.md 准备 .android-build/android-*")

    android_jar = None
    for cand in sorted(TOOLS_DIR.glob("android-*")):
        if (cand / "android.jar").exists():
            android_jar = cand / "android.jar"
            break
    if android_jar is None:
        raise SystemExit("未找到 platform android.jar：请按 android/README.md 准备")

    return jdk, bt, android_jar


def app_version() -> str:
    sys.path.insert(0, str(PROJECT_ROOT))
    from game_ledger import __version__

    return __version__


def init_keystore(jdk) -> None:
    """用工具链 keytool 生成发布签名密钥与 keystore.properties（随机强密码）。"""
    import secrets

    if KEYSTORE_PROPS.exists():
        raise SystemExit(f"已存在 {KEYSTORE_PROPS}，如需重新生成请先手动删除整个 keystore/ 目录")

    keytool = jdk / "bin" / "keytool.exe"
    if not keytool.exists():
        keytool = jdk / "bin" / "keytool"
    KEYSTORE_DIR.mkdir(parents=True, exist_ok=True)
    store_pass = secrets.token_urlsafe(24)
    print("==> 生成发布签名 keystore（RSA 2048，有效期 10000 天）")
    run(
        [
            keytool, "-genkeypair", "-keystore", KEYSTORE_FILE,
            "-alias", "gameledger", "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "10000",
            # keytool 用原始密码；「pass:」前缀是 apksigner 的参数约定，不能混用
            "-storepass", store_pass, "-keypass", store_pass,
            "-dname", "CN=GameLedger",
        ],
        desc="keytool 生成 keystore",
    )
    KEYSTORE_PROPS.write_text(
        "# GameLedger release signing credentials - NEVER commit or delete this folder\n"
        f"store.file={KEYSTORE_FILE.name}\n"
        f"store.password={store_pass}\n"
        "key.alias=gameledger\n"
        f"key.password={store_pass}\n",
        encoding="utf-8",
    )
    print(f"[OK] keystore 已生成：{KEYSTORE_FILE}")
    print("     该文件夹被 gitignore、绝不能删除——丢失后无法覆盖安装升级（详见 README）。")


def load_keystore_props() -> dict:
    if not KEYSTORE_PROPS.exists():
        raise SystemExit(
            f"未找到 {KEYSTORE_PROPS}。\n"
            "首次构建请先执行：.venv\\Scripts\\python.exe android\\build_apk.py --init-keystore\n"
            "详见 README「安卓签名密钥」小节。"
        )
    props = {}
    for line in KEYSTORE_PROPS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()
    missing = [k for k in ("store.file", "store.password", "key.alias", "key.password") if not props.get(k)]
    if missing:
        raise SystemExit(f"{KEYSTORE_PROPS} 缺少字段：{', '.join(missing)}")
    return props


def run(cmd, env=None, desc=""):
    print(f"==> {desc or ' '.join(str(c) for c in cmd[:4])}", flush=True)
    result = subprocess.run(
        [str(c) for c in cmd],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        raise SystemExit(f"步骤失败：{desc}")
    if result.stderr and result.stderr.strip():
        tail = result.stderr.strip().splitlines()[-2:]
        for line in tail:
            print("   ", line[:160])


def make_icons():
    """从 scripts/icon.ico 生成各密度启动图标。"""
    from PIL import Image

    src = Image.open(PROJECT_ROOT / "scripts" / "icon.ico")
    densities = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    for dpi, size in densities.items():
        dpi_dir = APP_DIR / "res" / f"mipmap-{dpi}"
        dpi_dir.mkdir(parents=True, exist_ok=True)
        img = src.resize((size, size), Image.LANCZOS)
        img.save(dpi_dir / "ic_launcher.png", "PNG")


def add_dex_to_apk(base_apk: Path, dex: Path, out_apk: Path) -> None:
    """把 classes.dex 合入 aapt2 产物（保留原压缩属性，resources.arsc 保持不压缩）。"""
    with zipfile.ZipFile(base_apk) as src, zipfile.ZipFile(
        out_apk, "w", zipfile.ZIP_DEFLATED
    ) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            info = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            info.compress_type = item.compress_type
            info.external_attr = item.external_attr
            dst.writestr(info, data)
        dst.write(dex, "classes.dex")


def main() -> None:
    import os

    jdk, bt, android_jar = find_toolchain()
    env = {**os.environ, "JAVA_HOME": str(jdk)}

    if "--init-keystore" in sys.argv:
        init_keystore(jdk)
        return

    props = load_keystore_props()
    keystore_path = KEYSTORE_DIR / props["store.file"]
    if not keystore_path.exists():
        raise SystemExit(f"keystore 文件不存在：{keystore_path}（检查 keystore.properties 的 store.file）")

    version_name = app_version()
    javac = jdk / "bin" / "javac.exe"
    java = jdk / "bin" / "java.exe"
    if not javac.exists():
        javac, java = jdk / "bin" / "javac", jdk / "bin" / "java"
    aapt2 = bt / "aapt2.exe" if (bt / "aapt2.exe").exists() else bt / "aapt2"
    zipalign = bt / "zipalign.exe" if (bt / "zipalign.exe").exists() else bt / "zipalign"
    d8_jar = bt / "lib" / "d8.jar"
    apksigner = bt / "apksigner.bat" if (bt / "apksigner.bat").exists() else bt / "apksigner"

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    # 1) 前端资产 + 图标
    run(
        [sys.executable, ANDROID_DIR / "prepare_assets.py"],
        desc="准备 WebView 资产 (www/)",
    )
    print("==> 生成启动图标")
    make_icons()

    # 2) javac
    classes = BUILD_DIR / "classes"
    java_files = list((APP_DIR / "java").rglob("*.java"))
    run(
        [
            javac, "-encoding", "UTF-8", "--release", "8",
            "-classpath", android_jar,
            "-d", classes,
            *java_files,
        ],
        env=env,
        desc="javac 编译",
    )

    # 3) d8 → classes.dex
    dex_dir = BUILD_DIR / "dex"
    dex_dir.mkdir()
    class_files = sorted(classes.rglob("*.class"))
    run(
        [
            java, "-cp", d8_jar, "com.android.tools.r8.D8",
            "--release", "--lib", android_jar, "--min-api", str(MIN_SDK),
            "--output", dex_dir,
            *class_files,
        ],
        env=env,
        desc="d8 转 dex",
    )

    # 4) aapt2 编译 + 链接（含资产目录；versionName 自动取 game_ledger.__version__）
    res_zip = BUILD_DIR / "res.zip"
    run(
        [aapt2, "compile", "--dir", APP_DIR / "res", "-o", res_zip],
        desc="aapt2 compile 资源",
    )
    base_apk = BUILD_DIR / "base.apk"
    run(
        [
            aapt2, "link",
            "-o", base_apk,
            "-I", android_jar,
            "--manifest", APP_DIR / "AndroidManifest.xml",
            "-A", APP_DIR / "assets",
            f"--min-sdk-version", str(MIN_SDK),
            f"--target-sdk-version", str(TARGET_SDK),
            "--version-code", "1",
            f"--version-name", version_name,
            "--auto-add-overlay",
            res_zip,
        ],
        desc="aapt2 link 打包",
    )

    # 5) 合入 classes.dex
    unsigned = BUILD_DIR / "unsigned.apk"
    add_dex_to_apk(base_apk, dex_dir / "classes.dex", unsigned)

    # 6) zipalign
    aligned = BUILD_DIR / "aligned.apk"
    run([zipalign, "-f", "4", unsigned, aligned], desc="zipalign 对齐")

    # 7) apksigner 签名（发布密钥）
    APK_OUT.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            apksigner, "sign",
            "--ks", keystore_path,
            "--ks-pass", f"pass:{props['store.password']}",
            "--ks-key-alias", props["key.alias"],
            "--key-pass", f"pass:{props['key.password']}",
            "--out", APK_OUT, aligned,
        ],
        desc="apksigner 签名（发布密钥）",
    )
    run([apksigner, "verify", APK_OUT], env=env, desc="apksigner 校验")

    size_mb = APK_OUT.stat().st_size / 1024 / 1024
    print(f"\n构建完成：{APK_OUT} ({size_mb:.1f} MB, versionName {version_name})")
    print("安装方式：把 APK 传到手机，点击安装（需允许“安装未知应用”）。")


if __name__ == "__main__":
    main()
