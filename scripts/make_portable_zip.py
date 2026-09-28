"""把 release\\GameLedger 文件夹打包为便携 zip（GitHub Release 资产）。

排除 data 用户数据子文件夹：发布包绝不能带上个人记录与封面缓存。
由 build.bat 在 PyInstaller 构建完成后调用。
"""

import sys
import zipfile
from pathlib import Path


def main() -> int:
    project = Path(__file__).resolve().parent.parent
    src = project / "release" / "GameLedger"
    dst = project / "release" / "GameLedger-portable.zip"
    if not src.is_dir():
        print(f"[ERROR] {src} not found - run build.bat first.")
        return 1

    count = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(src)
            if rel.parts and rel.parts[0] == "data":
                continue
            zf.write(path, f"GameLedger/{rel.as_posix()}")
            count += 1

    size_mb = dst.stat().st_size / 1024 / 1024
    print(f"[OK] {dst} ({count} files, {size_mb:.1f} MB, data/ excluded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
