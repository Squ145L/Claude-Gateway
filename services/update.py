"""
Auto-update service — check GitHub Releases for new versions,
download zip, extract and overwrite files (preserving user config).

Called by:
  - api/update.py    (HTTP routes)
  - update.bat       (manual emergency hatch via __main__)
"""
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_PATH = BASE_DIR / "version.json"
REPO = "Squ145L/Claude-Gateway"
GITHUB_API = f"https://api.github.com/repos/{REPO}"

# Files/dirs to skip when overwriting (preserve user data)
SKIP_PATHS = {
    ".env", ".env.example",
    "data/", "data",  # SQLite DB
    "logs/", "logs",
    ".venv/", ".venv",
    "__pycache__/", "__pycache__",
    "version.json",   # don't overwrite version during apply — we write it separately
}

# ── Helpers ──────────────────────────────────────────────

def _read_version() -> dict:
    """Read local version.json. Returns {"version": "0.0.0"} if missing."""
    if VERSION_PATH.exists():
        try:
            return json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": "0.0.0", "released": ""}


def _newer(latest: str, current: str) -> bool:
    """True if latest > current. Strips leading 'v' from latest."""
    try:
        l = tuple(map(int, latest.lstrip("v").split(".")))
        c = tuple(map(int, current.split(".")))
        return l > c
    except (ValueError, AttributeError):
        return False


def _strip_top_dir(member_name: str) -> str:
    """Zip members have a top-level dir (Claude-Gateway-v1.0.0/).
    Return the path relative to that dir, or empty string if it IS that dir."""
    parts = member_name.replace("\\", "/").split("/")
    if len(parts) <= 1:
        return ""  # top-level dir entry itself
    return "/".join(parts[1:])


def _should_skip(rel_path: str) -> bool:
    """True if this file path should be preserved (not overwritten)."""
    p = rel_path.replace("\\", "/").strip("/")
    if not p:
        return True  # skip empty/dir entries
    for skip in SKIP_PATHS:
        s = skip.replace("\\", "/").rstrip("/")
        if p == s or p.startswith(s + "/"):
            return True
    return False


# ── Public API ───────────────────────────────────────────

def check():
    """Compare local version.json with latest GitHub Release.

    Returns:
        {"current": "1.0.0", "latest": "1.3.0", "has_update": True,
         "body": "release notes...", "url": "https://..."}
        OR
        {"error": "network", "current": "1.0.0"}
        OR
        {"has_update": False}  (no releases yet)
    """
    local = _read_version()
    current = local.get("version", "0.0.0")

    try:
        # Use /releases?per_page=1 instead of /releases/latest —
        # /latest excludes prereleases, /releases returns all.
        req = Request(f"{GITHUB_API}/releases?per_page=1")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "ClaudeGateway")
        with urlopen(req, timeout=15) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
            if not releases:
                return {"has_update": False, "current": current}
            release = releases[0]
    except HTTPError as e:
        if e.code == 404:
            return {"has_update": False, "current": current}
        return {"error": "network", "current": current}
    except (URLError, OSError):
        return {"error": "network", "current": current}

    tag = release.get("tag_name", "")
    body = release.get("body", "")
    url = release.get("html_url", f"https://github.com/{REPO}/releases")
    has_update = _newer(tag, current)

    return {
        "current": current,
        "latest": tag.lstrip("v"),
        "has_update": has_update,
        "body": body,
        "url": url,
    }


def apply():
    """Download latest release zip and overwrite all files (preserving SKIP_PATHS).

    Returns:
        {"status": "ok", "version": "1.3.0"}
    Raises:
        RuntimeError on failure.
    """
    info = check()
    if info.get("error"):
        raise RuntimeError("无法连接到 GitHub，请检查网络后重试")
    if not info.get("has_update"):
        raise RuntimeError("当前已是最新版本")

    latest_tag = info.get("latest", "")
    zip_url = f"https://github.com/{REPO}/archive/refs/tags/v{latest_tag}.zip"

    # Download
    try:
        req = Request(zip_url)
        req.add_header("User-Agent", "ClaudeGateway")
        with urlopen(req, timeout=60) as resp:
            zip_data = resp.read()
    except (URLError, OSError) as e:
        raise RuntimeError(f"下载失败: {e}")

    # Write zip bytes to temp file (zipfile needs seekable file)
    tmp_dir = tempfile.mkdtemp(prefix="cgw-update-")
    zip_path = os.path.join(tmp_dir, "update.zip")
    with open(zip_path, "wb") as f:
        f.write(zip_data)

    overwritten = 0
    skipped = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                rel = _strip_top_dir(member.filename)
                if _should_skip(rel):
                    skipped += 1
                    continue

                dest = BASE_DIR / rel
                if member.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue

                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(dest, "wb") as dst:
                    dst.write(src.read())
                overwritten += 1

        # Write back updated version.json
        VERSION_PATH.write_text(json.dumps({
            "version": latest_tag,
            "released": "",
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    finally:
        # Cleanup temp files
        try:
            os.remove(zip_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass

    return {
        "status": "ok",
        "version": latest_tag,
        "overwritten": overwritten,
        "skipped": skipped,
    }


# ── CLI entry (update.bat) ───────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  Claude Gateway — 检查更新")
    print("=" * 50)
    print()

    print("正在检查...")
    info = check()

    if info.get("error"):
        print(f"⚠️  网络不通，无法检查更新")
        sys.exit(1)

    if not info.get("has_update"):
        print(f"✅ 当前已是最新版本 ({info['current']})")
        print()
        input("按任意键退出...")
        sys.exit(0)

    print(f"发现新版本 v{info['latest']} (当前 v{info['current']})")
    print()
    if info.get("body"):
        print(info["body"])
        print()

    answer = input("是否立即更新？更新将覆盖代码文件并重启服务 [y/N]: ")
    if answer.lower() not in ("y", "yes"):
        print("已取消")
        sys.exit(0)

    print()
    print("正在下载更新...")
    try:
        result = apply()
        print(f"✅ 更新完成 — 版本 v{result['version']}")
        print(f"   覆盖 {result['overwritten']} 个文件，跳过 {result['skipped']} 个")
        print()
        print("请手动重启 Gateway (关闭 run.bat 窗口 → 重新双击 run.bat)")
    except RuntimeError as e:
        print(f"❌ 更新失败: {e}")
        sys.exit(1)

    input("按任意键退出...")
