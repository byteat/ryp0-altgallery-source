#!/usr/bin/env python3
"""把 ryP0 源与 AltGallery 源合并成一份符合 ryP0 字段规范的 AltStore 源。

用法:
    python3 scripts/merge_sources.py --config config/sync.json

退出码:
    0  成功（含"次要源降级"的成功）
    2  主源（ryP0）拉取失败
    3  源格式不符合预期 / 合并后为空
    4  安全阈值触发（合并结果异常缩水）
    5  写盘失败

设计约束:
    * 仅使用 Python 标准库，CI 无需 pip install。
    * 输出确定性（键顺序固定、稳定排序），便于 git diff 审计。
    * 任何"丢弃/改写/冲突"都会写入日志与报告，不做静默处理。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_PRIMARY_FETCH = 2
EXIT_SCHEMA = 3
EXIT_GUARD = 4
EXIT_WRITE = 5

# ryP0 观测到的字段顺序，用于稳定输出（未列出的字段追加在末尾）
APP_KEY_ORDER = [
    "name", "catalogID", "bundleIdentifier", "developerName",
    "localizedDescription", "subtitle", "category", "versions",
    "iconURL", "updatePolicy", "appType", "status", "githubURL",
    "bundleIdentifiers", "importSource", "automation", "backup",
    "githubProjectCard", "tintColor", "portDistribution", "appPermissions",
]
VERSION_KEY_ORDER = [
    "version", "date", "downloadURL", "size", "buildVersion",
    "releaseChannel", "minOSVersion", "localizedDescription", "sha256",
    "sourceAppName", "sourceAssetName", "ipaBundleIdentifier",
    "upstreamAssetURL", "sourceArchiveEntry",
]

# 用于从描述性文本猜测分类，仅在来源未提供 category 时兜底，且一定记日志
CATEGORY_HINTS = [
    ("EMU", r"emulat|\bemu\b|retroarch|dolphin|ppsspp|melocafe"),
    ("Games", r"\bgame\b|gameplay|gba|nintendo|minecraft|stardew"),
    ("Ports", r"\bport\b|porting|vitagl|wii ?u|bottled|translat"),
    ("Movies", r"\bmovie\b|video player|streaming|plex|jellyfin|infuse"),
    ("Social", r"social|mastodon|bluesky|discord|reddit|chat|messag"),
    ("Sideloading", r"sideload|signer|esign|altstore|sidestore|livecontainer|ipa install"),
]

DATE_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$"
)
BID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
GITHUB_RELEASE_RE = re.compile(
    r"^https://github\.com/([^/]+)/([^/]+)/releases/"
)


# --------------------------------------------------------------------------
# 日志
# --------------------------------------------------------------------------
class Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, level: str, msg: str, **fields: object) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        suffix = ""
        if fields:
            suffix = " " + json.dumps(fields, ensure_ascii=False, sort_keys=True)
        line = f"{ts} {level:<5} {msg}{suffix}"
        self.lines.append(line)
        print(line, file=sys.stdout if level != "ERROR" else sys.stderr, flush=True)

    def info(self, msg: str, **f: object) -> None:
        self("INFO", msg, **f)

    def warn(self, msg: str, **f: object) -> None:
        self("WARN", msg, **f)

    def error(self, msg: str, **f: object) -> None:
        self("ERROR", msg, **f)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_bid(value: object) -> str:
    return str(value).strip().lower() if isinstance(value, str) else ""


def natural_key(value: str) -> tuple:
    parts = re.split(r"(\d+)", str(value))
    out: list[object] = []
    for i, part in enumerate(parts):
        if i % 2:
            out.append((1, int(part)))
        else:
            out.append((0, part.lower()))
    return tuple(out)


def norm_date(value: object, log: Log, ctx: str) -> tuple[str, bool]:
    """统一成 ryP0 主流写法 YYYY-MM-DDTHH:MM:SSZ。

    返回 (规范化后的字符串, 是否发生了改写)。无法解析时原样返回并告警。
    """
    if not isinstance(value, str):
        log.warn("date 字段缺失或非字符串，已丢弃该值", ctx=ctx, value=repr(value)[:60])
        return "", False
    raw = value.strip()
    m = DATE_RE.match(raw)
    if not m:
        log.warn("date 无法解析为 ISO 8601，保留原值", ctx=ctx, value=raw)
        return raw, False
    y, mo, d, hh, mm, ss, tz = m.groups()
    if hh is None:
        dt = datetime(int(y), int(mo), int(d), tzinfo=timezone.utc)
    else:
        offset = timezone.utc
        if tz and tz != "Z":
            sign = 1 if tz[0] == "+" else -1
            body = tz[1:].replace(":", "")
            offset = timezone(
                sign * timedelta(hours=int(body[:2]), minutes=int(body[2:]))
            )
        dt = datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss or 0), tzinfo=offset)
    iso = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso, iso != raw


def ordered(d: dict, order: list[str]) -> dict:
    out = {k: d[k] for k in order if k in d}
    for k, v in d.items():
        if k not in out:
            out[k] = v
    return out


def stable_id(bid: str) -> str:
    return "project-" + hashlib.md5(bid.encode("utf-8")).hexdigest()


def clean_str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def is_http_url(value: object) -> bool:
    return isinstance(value, str) and (
        value.startswith("https://") or value.startswith("http://")
    )


# --------------------------------------------------------------------------
# 拉取
# --------------------------------------------------------------------------
def fetch_json(url: str, net: dict, log: Log, cache_dir: Path, label: str,
               expect: str = "object", extra_headers: dict | None = None):
    """带指数退避的 GET。失败时尝试读取本地缓存（cache_dir 由 CI 缓存持久化）。

    expect="object" 用于 AltStore 源，expect="array" 用于 GitHub releases 列表。
    """
    retries = int(net.get("retries", 4))
    backoff = float(net.get("backoffBase", 2.0))
    backoff_max = float(net.get("backoffMax", 30))
    timeout = float(net.get("timeout", 30))
    ua = str(net.get("userAgent", "appsource-sync/1.0"))
    headers = {"User-Agent": ua, "Accept": "application/vnd.github+json"
               if expect == "array" else "application/json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if extra_headers:
        headers.update(extra_headers)

    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            log.info("正在拉取源", source=label, attempt=attempt, url=url)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", None) or 200
                body = resp.read()
            if status != 200:
                raise urllib.error.HTTPError(url, status, "unexpected status", None, None)
            if not body.strip():
                raise ValueError("响应体为空")
            data = json.loads(body.decode("utf-8"))
            if expect == "object" and not isinstance(data, dict):
                raise ValueError(f"顶层应为对象，实际为 {type(data).__name__}")
            if expect == "array" and not isinstance(data, list):
                raise ValueError(f"顶层应为数组，实际为 {type(data).__name__}")
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / f"{label}.json").write_bytes(body)
            log.info("拉取成功", source=label, bytes=len(body))
            return data
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError, TimeoutError) as exc:
            code = getattr(exc, "code", None)
            last_err = f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}" + (
                f" (HTTP {code})" if code else ""
            )
            retryable = code is None or code in (408, 425, 429) or (isinstance(code, int) and code >= 500)
            log.warn("拉取失败", source=label, attempt=attempt, retryable=retryable, error=last_err)
            if not retryable or attempt == retries:
                break
            sleep = min(backoff * (2 ** (attempt - 1)), backoff_max)
            time.sleep(sleep)
        except Exception as exc:  # noqa: BLE001 - 兜底，避免 CI 静默失败
            last_err = f"{type(exc).__name__}: {exc}"
            log.error("拉取出现未预期异常", source=label, error=last_err)
            break

    cached = cache_dir / f"{label}.json"
    if cached.exists():
        try:
            data = json.loads(cached.read_text("utf-8"))
            log.warn("改用本地缓存的上一份源文件", source=label, path=str(cached))
            return data
        except (OSError, json.JSONDecodeError) as exc:
            log.error("本地缓存不可用", source=label, error=str(exc))
    log.error("拉取彻底失败且无可用缓存", source=label, error=last_err)
    return None


# --------------------------------------------------------------------------
# GitHub Releases → AltStore 源（用于只发 IPA、没有现成源文件的仓库）
# --------------------------------------------------------------------------
def releases_to_feed(src: dict, releases: list, log: Log) -> dict:
    """把仓库的 releases 列表转换成 AltStore 形状的源（只在内存里存在）。

    bundleIdentifier 必须由配置显式提供——它无法从 release 元数据可靠推断，
    猜错会让用户在设备上装出两个互不相认的同一个 App。
    """
    name = clean_str(src.get("name")) or clean_str(src.get("repo")) or "unknown"
    bid = clean_str(src.get("bundleIdentifier"))
    if not bid or not BID_RE.match(bid):
        raise SchemaError(f"github-releases 源 {name} 需要合法的 bundleIdentifier")

    pattern = re.compile(src.get("assetPattern") or r"\.ipa$", re.IGNORECASE)
    exclude_pre = bool(src.get("excludePrerelease", True))
    limit = int(src.get("maxVersions") or 0)

    versions: list[dict] = []
    for rel in releases if isinstance(releases, list) else []:
        if not isinstance(rel, dict) or rel.get("draft"):
            continue
        if exclude_pre and rel.get("prerelease"):
            continue
        tag = clean_str(rel.get("tag_name"))
        if not tag:
            continue
        asset = next(
            (a for a in (rel.get("assets") or [])
             if isinstance(a, dict) and pattern.search(str(a.get("name", "")))),
            None,
        )
        if not asset:
            log.info("该 release 没有匹配的安装包，跳过", source=name, tag=tag)
            continue
        version = re.sub(r"^[vV](?=\d)", "", tag)
        date, _ = norm_date(rel.get("published_at") or rel.get("created_at"), log, f"{name}@{tag}")
        if not date:
            log.warn("release 时间无法解析，跳过该版本", source=name, tag=tag)
            continue
        size = asset.get("size")
        versions.append({
            "version": version,
            "date": date,
            "downloadURL": clean_str(asset.get("browser_download_url")),
            "size": int(size) if isinstance(size, (int, float)) and size > 0 else 0,
            "releaseChannel": "prerelease" if rel.get("prerelease") else "release",
        })

    versions.sort(key=lambda v: (v["date"], natural_key(v["version"])), reverse=True)
    if limit > 0:
        versions = versions[:limit]
    if not versions:
        log.error("该仓库没有任何可用的 IPA release", source=name)
        return {"name": name, "apps": [], "news": []}

    app = {
        "name": clean_str(src.get("appName")) or name,
        "bundleIdentifier": bid,
        "developerName": clean_str(src.get("developerName")) or name,
        "subtitle": clean_str(src.get("subtitle")),
        "localizedDescription": clean_str(src.get("localizedDescription")),
        "category": clean_str(src.get("category")) or "Tools",
        "versions": versions,
        "iconURL": clean_str(src.get("iconURL")),
        "githubURL": f"https://github.com/{src.get('repo')}" if src.get("repo") else "",
    }
    if clean_str(src.get("minOSVersion")):
        for v in app["versions"]:
            v["minOSVersion"] = clean_str(src.get("minOSVersion"))
    log.info("从 releases 生成源条目", source=name, app=app["name"],
             bundleIdentifier=bid, versions=len(versions),
             latest=versions[0]["version"])
    return {"name": name, "apps": [app], "news": []}


def fetch_releases_source(src: dict, net: dict, log: Log, cache_dir: Path) -> dict | None:
    repo = clean_str(src.get("repo"))
    if not repo or "/" not in repo:
        raise SchemaError(f"源 {src.get('name')} 的 repo 字段应形如 owner/name")
    per_page = int(src.get("perPage") or 30)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if not token:
        log.warn("未提供 GITHUB_TOKEN，走未认证额度（每小时 60 次）", source=src.get("name"))
    url = f"https://api.github.com/repos/{repo}/releases?per_page={per_page}"
    releases = fetch_json(url, net, log, cache_dir, clean_str(src.get("name")) or repo,
                          expect="array", extra_headers=headers)
    if releases is None:
        return None
    return releases_to_feed(src, releases, log)


# --------------------------------------------------------------------------
# 规范化：把任意源的 app 转成 ryP0 app 结构
# --------------------------------------------------------------------------
def norm_version(
    raw: dict, app_bid: str, log: Log, app_name: str, defaults: dict, origin: str
) -> dict | None:
    if not isinstance(raw, dict):
        log.warn("版本条目不是对象，已跳过", app=app_name, origin=origin)
        return None
    version = clean_str(raw.get("version"))
    download = clean_str(raw.get("downloadURL"))
    if not version or not is_http_url(download):
        log.warn(
            "版本缺少 version 或合法 downloadURL，已跳过",
            app=app_name, origin=origin, version=version or None, downloadURL=download or None,
        )
        return None

    out: dict = {"version": version}

    date, changed = norm_date(raw.get("date"), log, f"{app_name}@{version}")
    if not date or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", date):
        log.warn("版本 date 无法归一为 ryP0 格式，已跳过该版本",
                 app=app_name, origin=origin, version=version, date=repr(raw.get("date"))[:40])
        return None
    out["date"] = date
    if changed:
        log.info("已规范化 date", app=app_name, version=version, to=date)

    out["downloadURL"] = download

    size = raw.get("size")
    if isinstance(size, bool) or not isinstance(size, (int, float)) or size <= 0:
        log.warn("版本 size 缺失或非法（保留字段以兼容客户端）", app=app_name, version=version, value=repr(size)[:40])
    else:
        out["size"] = int(size)

    build = clean_str(raw.get("buildVersion"))
    if build:
        out["buildVersion"] = build

    channel = clean_str(raw.get("releaseChannel")) or defaults.get("channel")
    if channel:
        out["releaseChannel"] = channel

    min_os = clean_str(raw.get("minOSVersion"))
    if min_os:
        out["minOSVersion"] = min_os

    desc = clean_str(raw.get("localizedDescription"))
    if desc:
        out["localizedDescription"] = desc

    for key in ("sha256", "sourceAppName", "sourceAssetName", "ipaBundleIdentifier",
                "upstreamAssetURL", "sourceArchiveEntry"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()

    # ryP0 的版本会带 ipaBundleIdentifier，缺失时用 app 的 bundleIdentifier 补齐
    out.setdefault("ipaBundleIdentifier", app_bid)
    return out


def version_identity(v: dict) -> tuple[str, str]:
    return (str(v.get("version", "")).strip(), str(v.get("buildVersion", "")).strip())


def convert_secondary_app(
    raw: dict, cfg: dict, log: Log, origin: str, source_nsfw: bool = False
) -> dict | None:
    """把 AltGallery 结构的 app 转成 ryP0 结构。"""
    bid = clean_str(raw.get("bundleIdentifier"))
    name = clean_str(raw.get("name"))
    if not bid or not BID_RE.match(bid):
        log.warn("app 缺少合法 bundleIdentifier，已丢弃", origin=origin, name=name or None)
        return None
    if not name:
        log.warn("app 缺少 name，已丢弃", origin=origin, bundleIdentifier=bid)
        return None

    versions_raw = raw.get("versions")
    if not isinstance(versions_raw, list) or not versions_raw:
        log.warn("app 没有任何可用版本，已丢弃", origin=origin, name=name)
        return None

    defaults = {"channel": cfg.get("importedReleaseChannel", "release")}
    versions: list[dict] = []
    for raw_v in versions_raw:
        nv = norm_version(raw_v, bid, log, name, defaults, origin)
        if nv:
            versions.append(nv)
    if not versions:
        log.warn("app 的所有版本都不合法，已丢弃", origin=origin, name=name)
        return None

    app: dict = {
        "name": name,
        "catalogID": stable_id(bid),
        "bundleIdentifier": bid,
        "developerName": clean_str(raw.get("developerName")) or "Unknown",
        "localizedDescription": clean_str(raw.get("localizedDescription")),
        "subtitle": clean_str(raw.get("subtitle")),
        "category": "",
        "versions": versions,
        "iconURL": clean_str(raw.get("iconURL")),
        "updatePolicy": cfg.get("importedUpdatePolicy", "static"),
        "appType": cfg.get("importedAppType", "Static"),
    }

    # 分类优先级：配置覆盖 > 源自带分类（经 categoryAliases 归一）> 关键词推断 > 默认值
    overrides = cfg.get("categoryOverrides") or {}
    aliases = {str(k).lower(): v for k, v in (cfg.get("categoryAliases") or {}).items()}
    cat = clean_str(overrides.get(bid)) or clean_str(overrides.get(bid.lower()))
    if cat:
        app["category"] = cat
    else:
        src_cat = clean_str(raw.get("category"))
        if src_cat:
            mapped = aliases.get(src_cat.lower())
            app["category"] = mapped or src_cat
            if mapped:
                log.info("按 categoryAliases 归一上游分类", app=name,
                         **{"from": src_cat, "to": mapped, "source": origin})
            else:
                log.info("沿用上游自带分类", app=name, category=src_cat, source=origin)
        else:
            haystack = " ".join(
                [name, app["subtitle"], app["localizedDescription"]]
            ).lower()
            for candidate, pattern in CATEGORY_HINTS:
                if re.search(pattern, haystack):
                    app["category"] = candidate
                    log.info("根据关键词推断分类，建议在 config 中用 categoryOverrides 固化",
                             app=name, category=candidate)
                    break
            else:
                app["category"] = cfg.get("defaultCategory", "Tools")
                log.info("未能推断分类，使用默认分类", app=name, category=app["category"])

    tint = clean_str(raw.get("tintColor"))
    if re.match(r"^#[0-9A-Fa-f]{6}$", tint):
        app["tintColor"] = tint

    # 从 GitHub Release 链接反推仓库地址，跑不通就不写，绝不猜测
    repo_url = None
    for v in versions:
        m = GITHUB_RELEASE_RE.match(str(v.get("downloadURL", "")))
        if m:
            repo_url = f"https://github.com/{m.group(1)}/{m.group(2)}"
            break
    if repo_url:
        app["githubURL"] = repo_url

    # 权限声明：上游给了就原样带上（ryP0 也用同一结构）
    perms = raw.get("appPermissions")
    if isinstance(perms, dict) and (perms.get("entitlements") or perms.get("privacy")):
        app["appPermissions"] = {
            "entitlements": [e for e in (perms.get("entitlements") or []) if isinstance(e, str)],
            "privacy": perms.get("privacy") or {},
        }

    # 内容分级：源级或应用级标了 nsfw 就透传给应用，避免把成人内容标成安全
    if raw.get("nsfw") is True or source_nsfw:
        app["nsfw"] = True
        log.info("应用标记为 nsfw", app=name, source=origin)

    # AltGallery 的 screenshots 是纯 URL 数组，与 AltStore 的 {imageURL,size} 结构不同，
    # 默认不合并进输出，避免客户端解析异常；需要时可在配置里打开。
    if cfg.get("keepScreenshots") and isinstance(raw.get("screenshots"), list):
        shots = [s for s in raw["screenshots"] if is_http_url(s)]
        if shots:
            app["screenshots"] = shots
            log.warn("已按配置保留 screenshots（该字段非 ryP0 规范字段，客户端兼容性未经验证）",
                     app=name, count=len(shots))

    return ordered(app, APP_KEY_ORDER)


# --------------------------------------------------------------------------
# 合并
# --------------------------------------------------------------------------
def merge_versions(
    primary_app: dict, secondary_app: dict, log: Log, app_name: str,
    primary_name: str = "ryp0", secondary_name: str = "altgallery",
) -> tuple[list[dict], list[dict], int, int]:
    """以主源版本为基准合并副源版本。

    返回 (合并后版本列表, 冲突列表, 新增版本数, 副源被丢弃的重复版本数)。
    """
    merged = list(primary_app.get("versions") or [])
    index: dict[tuple[str, str], dict] = {}
    for v in merged:
        index.setdefault(version_identity(v), v)

    conflicts: list[dict] = []
    added = 0
    duplicate = 0

    for v in secondary_app.get("versions") or []:
        ident = version_identity(v)
        if ident in index:
            existing = index[ident]
            same_url = existing.get("downloadURL") == v.get("downloadURL")
            same_size = existing.get("size") == v.get("size")
            if not (same_url and same_size):
                conflicts.append({
                    "app": app_name,
                    "bundleIdentifier": primary_app.get("bundleIdentifier"),
                    "version": ident[0],
                    "buildVersion": ident[1],
                    "field": "downloadURL/size",
                    "kept": {"source": primary_name, "downloadURL": existing.get("downloadURL"), "size": existing.get("size")},
                    "dropped": {"source": secondary_name, "downloadURL": v.get("downloadURL"), "size": v.get("size")},
                    "resolution": "primary-wins",
                })
                log.warn("版本冲突：保留主源记录", app=app_name, version=ident[0],
                         kept=existing.get("downloadURL"), dropped=v.get("downloadURL"),
                         secondary=secondary_name)
            else:
                duplicate += 1
                log.info("副源版本与主源一致，已去重", app=app_name, version=ident[0],
                         source=secondary_name)
            continue
        merged.append(v)
        index[ident] = v
        added += 1

    return merged, conflicts, added, duplicate


def merge_metadata(
    primary_app: dict, secondary_app: dict, log: Log,
    primary_name: str = "ryp0", secondary_name: str = "altgallery",
) -> list[dict]:
    """补全主源缺失的描述性字段；两边都有且不同则记录冲突、保留主源。"""
    conflicts: list[dict] = []
    fillable = ["developerName", "subtitle", "localizedDescription", "iconURL", "tintColor"]
    for field in fillable:
        p = clean_str(primary_app.get(field))
        s = clean_str(secondary_app.get(field))
        if not p and s:
            primary_app[field] = s
            log.info("用副源补全缺失字段", app=primary_app.get("name"), field=field,
                     source=secondary_name)
        elif p and s and p != s:
            conflicts.append({
                "app": primary_app.get("name"),
                "bundleIdentifier": primary_app.get("bundleIdentifier"),
                "field": field,
                "kept": {"source": primary_name, "value": p[:200]},
                "dropped": {"source": secondary_name, "value": s[:200]},
                "resolution": "primary-wins",
            })
    return conflicts


def build_feed(primary: dict, secondaries: list[tuple[str, dict]], cfg: dict,
               guards: dict, report: dict, log: Log,
               primary_name: str = "ryp0") -> dict:
    primary_apps = primary.get("apps")
    if not isinstance(primary_apps, list) or not primary_apps:
        raise SchemaError("主源 apps 字段缺失、非数组或为空")

    exclude = {norm_bid(x) for x in (cfg.get("excludeBundleIds") or []) if norm_bid(x)}
    # keep-all: 同 bundleIdentifier 的两条记录都保留（默认）；merge: 合并成一个应用的多个版本
    keep_all = str(cfg.get("onBundleIdConflict", "keep-all")) == "keep-all"
    if keep_all:
        log.info("冲突策略 keep-all：同 bundleIdentifier 的记录全部保留，不做合并")

    # 1) 主源逐条纳入（重复 bundleIdentifier 按策略处理）
    apps: list[dict] = []
    by_bid: dict[str, dict] = {}
    alias: dict[str, str] = {}
    for raw in primary_apps:
        if not isinstance(raw, dict):
            log.warn("主源存在非对象 app 条目，已跳过")
            continue
        bid = clean_str(raw.get("bundleIdentifier"))
        if not bid or not BID_RE.match(bid):
            log.warn("主源 app 缺少合法 bundleIdentifier，已跳过", name=clean_str(raw.get("name")))
            report["dropped"]["invalidPrimaryApps"] += 1
            continue
        key = norm_bid(bid)
        if key in exclude:
            log.info("按 excludeBundleIds 排除", bundleIdentifier=bid)
            report["dropped"]["excluded"] += 1
            continue
        if key in by_bid and keep_all:
            log.info("源内 bundleIdentifier 重复，按 keep-all 保留为独立条目",
                     bundleIdentifier=bid, name=clean_str(raw.get("name")))
            report["warnings"].append(f"重复 bundleIdentifier（保留两条）: {bid}")
            app = dict(raw)
            app["versions"] = [v for v in (app.get("versions") or []) if isinstance(v, dict)]
            app["_origin"] = primary_name
            apps.append(app)
            continue
        if key in by_bid:
            log.warn("主源内部 bundleIdentifier 重复，合并版本", bundleIdentifier=bid)
            report["warnings"].append(f"主源重复 bundleIdentifier: {bid}")
            existing = by_bid[key]
            seen = {version_identity(v) for v in existing.get("versions", [])}
            for v in raw.get("versions") or []:
                if isinstance(v, dict) and version_identity(v) not in seen:
                    existing.setdefault("versions", []).append(v)
            continue
        app = dict(raw)
        app["versions"] = [v for v in (app.get("versions") or []) if isinstance(v, dict)]
        app["_origin"] = primary_name
        apps.append(app)
        by_bid[key] = app
        for extra in app.get("bundleIdentifiers") or []:
            if isinstance(extra, str) and norm_bid(extra):
                alias.setdefault(norm_bid(extra), key)

    primary_count = len(apps)
    log.info("主源应用数", count=primary_count)

    conflicts_meta: list[dict] = []
    conflicts_ver: list[dict] = []
    imported = 0
    matched = 0
    added_versions = 0
    imported_keys: dict[str, str] = {}

    # 2) 按配置顺序依次合并其余源：先出现者优先，后来者只补空缺
    secondary_apps_total = 0
    for src_name, src_feed in secondaries:
        sec_apps = src_feed.get("apps")
        if not isinstance(sec_apps, list):
            log.error("源 apps 字段不是数组，跳过该源", source=src_name)
            report["sources"].setdefault(src_name, {})["status"] = "invalid-schema"
            continue
        secondary_apps_total += len(sec_apps)
        src_nsfw = src_feed.get("nsfw") is True
        src_stats = {"matched": 0, "imported": 0}

        for raw in sec_apps:
            if not isinstance(raw, dict):
                log.warn("源存在非对象 app 条目，已跳过", source=src_name)
                continue
            bid = clean_str(raw.get("bundleIdentifier"))
            key = norm_bid(bid)
            if not key:
                log.warn("app 缺少 bundleIdentifier，已跳过", source=src_name,
                         name=clean_str(raw.get("name")))
                report["dropped"]["invalidSecondaryApps"] += 1
                continue
            if key in exclude:
                report["dropped"]["excluded"] += 1
                continue

            target_key = None if keep_all else (key if key in by_bid else alias.get(key))
            if target_key:
                target = by_bid[target_key]
                matched += 1
                src_stats["matched"] += 1
                defaults = {"channel": cfg.get("importedReleaseChannel", "release")}
                sec_versions = [
                    nv for nv in (
                        norm_version(v, target.get("bundleIdentifier", bid), log,
                                     target.get("name", ""), defaults, src_name)
                        for v in (raw.get("versions") or [])
                    ) if nv
                ]
                merged_versions, vconf, added, _dup = merge_versions(
                    target, {"versions": sec_versions}, log, target.get("name", bid),
                    primary_name, src_name,
                )
                added_versions += added
                target["versions"] = merged_versions
                conflicts_meta.extend(
                    merge_metadata(target, raw, log, primary_name, src_name)
                )
                conflicts_ver.extend(vconf)
                if key != target_key:
                    log.info("通过 bundleIdentifiers 别名匹配到已有应用",
                             incoming=bid, matched_to=target.get("bundleIdentifier"),
                             source=src_name)
            else:
                app = convert_secondary_app(raw, cfg, log, src_name, src_nsfw)
                if app is None:
                    report["dropped"]["invalidSecondaryApps"] += 1
                    continue
                if key in by_bid:
                    src_stats["duplicates"] = src_stats.get("duplicates", 0) + 1
                    log.info("与已有条目 bundleIdentifier 相同，按 keep-all 另存一条",
                             app=app.get("name"), bundleIdentifier=bid, source=src_name)
                app["_origin"] = src_name
                apps.append(app)
                if key not in by_bid:
                    by_bid[key] = app
                imported += 1
                src_stats["imported"] += 1
                imported_keys[key] = src_name

        report["sources"].setdefault(src_name, {}).update(src_stats)
        log.info("源合并完成", source=src_name,
                 apps=len(sec_apps), matched=src_stats["matched"],
                 imported=src_stats["imported"])

    # 3) 逐应用规范化（含主源）、去重、排序、截断
    max_versions = int(cfg.get("maxVersionsPerApp") or 0)
    drop_empty = bool(cfg.get("dropEmptyVersionApps", True))
    final_apps: list[dict] = []
    dup_removed = 0
    for app in apps:
        bid = clean_str(app.get("bundleIdentifier"))
        name = clean_str(app.get("name"))
        origin = app.pop("_origin", primary_name)
        defaults = (
            {"channel": cfg.get("importedReleaseChannel", "release")}
            if origin != primary_name
            else {"channel": ""}
        )

        versions: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for raw_v in app.get("versions") or []:
            nv = norm_version(raw_v, bid, log, name, defaults, origin)
            if nv is None:
                report["dropped"]["invalidVersions"] += 1
                continue
            ident = version_identity(nv)
            if ident in seen:
                dup_removed += 1
                log.info("去除应用内重复版本（AltStore 会拒绝重复版本）",
                         app=name, version=ident[0], buildVersion=ident[1])
                continue
            seen.add(ident)
            versions.append(nv)

        versions.sort(key=lambda v: (str(v.get("date", "")), natural_key(v.get("version", ""))),
                      reverse=True)
        if max_versions > 0 and len(versions) > max_versions:
            log.info("按 maxVersionsPerApp 截断版本", app=name,
                     kept=max_versions, dropped=len(versions) - max_versions)
            versions = versions[:max_versions]
        app["versions"] = [ordered(v, VERSION_KEY_ORDER) for v in versions]

        if not versions:
            if drop_empty:
                report["dropped"]["emptyVersionApps"].append(name or bid)
                log.warn("应用没有任何合法版本，已从输出中移除", app=name, bundleIdentifier=bid)
                by_bid.pop(norm_bid(bid), None)
                continue
            log.warn("应用无可用版本，按配置仍在输出中保留（客户端可能忽略）", app=name)
        final_apps.append(ordered(app, APP_KEY_ORDER))
    apps = final_apps
    report["dropped"]["duplicateVersions"] = dup_removed
    log.info("应用内重复版本去重完成", removed=dup_removed)

    # 4) 排序：主源顺序优先，导入应用按名称追加
    if not cfg.get("preservePrimaryOrder", True):
        apps.sort(key=lambda a: natural_key(a.get("name", "")))

    # 5) 分类集合：先按大小写不敏感对齐上游分类，再补入新分类
    categories = [c for c in (primary.get("categories") or []) if isinstance(c, str) and c]
    canonical: dict[str, str] = {}
    for cat in categories:
        canonical.setdefault(cat.lower(), cat)
    for app in apps:
        cat = clean_str(app.get("category"))
        if not cat:
            continue
        low = cat.lower()
        if low in canonical:
            if canonical[low] != cat:
                log.info("统一分类大小写", app=app.get("name"), **{"from": cat, "to": canonical[low]})
                app["category"] = canonical[low]
        else:
            canonical[low] = cat
            categories.append(cat)
            log.info("新增分类到 categories 列表", category=cat)

    # 6) news：仅携带配置指定来源，默认只保留主源
    carry = cfg.get("carryNewsFrom") or [primary_name]
    news: list[dict] = []
    dropped_news = 0
    for src_name, src_data in [(primary_name, primary)] + list(secondaries):
        items = src_data.get("news")
        if not isinstance(items, list):
            continue
        if src_name not in carry:
            dropped_news += len(items)
            if items:
                log.info("按 carryNewsFrom 未携带该源 news", source=src_name, count=len(items))
            continue
        for item in items:
            if isinstance(item, dict):
                news.append(item)
    report["dropped"]["secondaryNews"] = dropped_news

    # 7) 阈值校验
    ratio_primary = primary_count / max(len(primary_apps), 1)
    if primary_count < int(guards.get("minAppsAbsolute", 1)):
        raise GuardError(f"主源合并后应用数 {primary_count} 低于 minAppsAbsolute")
    if ratio_primary < float(guards.get("minPrimaryAppRatio", 0)):
        raise GuardError(
            f"主源有效应用占比 {ratio_primary:.2%} 低于 minPrimaryAppRatio"
        )
    total_ratio = len(apps) / max(primary_count, 1)
    if total_ratio < float(guards.get("minTotalAppRatio", 0)):
        raise GuardError(
            f"合并后应用数 {len(apps)} 仅为 {primary_count} 的 {total_ratio:.2%}，疑似异常缩水"
        )

    merged_source_url = derive_source_url(cfg)
    if not merged_source_url:
        raise SchemaError(
            "无法确定 sourceURL：请设置 merge.sourceUrl、--source-url 或 GITHUB_REPOSITORY 环境变量"
        )
    feed = {
        "name": cfg.get("title", "ryP0 × AltGallery"),
        "subtitle": cfg.get("subtitle", ""),
        "description": cfg.get("description", ""),
        "iconURL": cfg.get("iconUrl", primary.get("iconURL", "")),
        "tintColor": cfg.get("tintColor", "#0A84FF"),
        "website": cfg.get("website", ""),
        "identifier": cfg.get("identifier", "com.ry0x.source.merged"),
        "sourceURL": merged_source_url,
        "categories": categories,
        "apps": apps,
        "news": news,
    }
    feed = {k: v for k, v in feed.items() if v not in ("", None) or k in ("subtitle", "description")}

    # 统计重复 bundleIdentifier（keep-all 下这是预期结果，但要如实报告）
    bid_counter: dict[str, int] = {}
    for a in apps:
        k = norm_bid(a.get("bundleIdentifier"))
        if k:
            bid_counter[k] = bid_counter.get(k, 0) + 1
    dup_groups = {k: v for k, v in bid_counter.items() if v > 1}
    if dup_groups:
        log.info("输出中存在重复 bundleIdentifier", groups=len(dup_groups),
                 entries=sum(dup_groups.values()))
        report["warnings"].append(
            f"输出含 {len(dup_groups)} 组重复 bundleIdentifier（共 {sum(dup_groups.values())} 条），"
            "部分客户端可能只显示其中一条"
        )

    report["counts"] = {
        "primaryApps": primary_count,
        "secondaryApps": secondary_apps_total,
        "matchedApps": matched,
        "importedApps": imported,
        "totalApps": len(apps),
        "addedVersions": added_versions,
        "totalVersions": sum(len(a.get("versions") or []) for a in apps),
        "conflicts": len(conflicts_meta) + len(conflicts_ver),
        "duplicateBidGroups": len(dup_groups),
        "duplicateBidEntries": sum(dup_groups.values()),
        "conflictPolicy": "keep-all" if keep_all else "merge",
    }
    report["conflicts"] = {
        "metadata": conflicts_meta,
        "versions": conflicts_ver,
    }
    return feed


class SchemaError(Exception):
    pass


class GuardError(Exception):
    pass


def derive_source_url(cfg: dict) -> str:
    raw = str(cfg.get("sourceUrl", "__auto__"))
    if raw and raw != "__auto__":
        return raw
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo:
        # 用实际分支名而非 HEAD，保证声明的地址与 README、订阅地址一致
        branch = os.environ.get("GITHUB_REF_NAME") or "main"
        return f"https://raw.githubusercontent.com/{repo}/{branch}/{cfg.get('output', 'feed.json')}"
    return ""


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="把多个 AltStore 源合并成一份 ryP0 结构源")
    parser.add_argument("--config", default="config/sync.json")
    parser.add_argument("--output", help="覆盖输出路径")
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--ryp0-url", default=None, help="等价于 --set ryp0=URL")
    parser.add_argument("--altgallery-url", default=None, help="等价于 --set altgallery=URL")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=URL",
                        help="覆盖指定名称源的 URL，可重复")
    parser.add_argument("--source-url", default=None, help="写进 sourceURL 的最终地址")
    parser.add_argument("--only-primary", "--skip-secondary", dest="only_primary",
                        action="store_true", help="只同步主源，忽略其余源")
    args = parser.parse_args(argv)

    root = Path(args.config).resolve().parent.parent
    cfg_all = json.loads(Path(args.config).read_text("utf-8"))
    output = Path(args.output) if args.output else root / cfg_all.get("output", "feed.json")
    log_dir = Path(args.log_dir) if args.log_dir else root / cfg_all.get("logDir", "logs")
    state_dir = root / cfg_all.get("stateDir", "state")
    cache_dir = state_dir / "cache"
    net = cfg_all.get("network", {})
    merge_cfg = dict(cfg_all.get("merge", {}))
    if args.source_url:
        merge_cfg["sourceUrl"] = args.source_url
    guards = cfg_all.get("guards", {})

    # 源列表：支持旧的字典写法与新的列表写法，列表顺序即优先级
    raw_sources = cfg_all.get("sources", {})
    if isinstance(raw_sources, dict):
        source_list = [{"name": k, **v} for k, v in raw_sources.items()]
    else:
        source_list = [dict(s) for s in raw_sources]
    if not source_list:
        raise SystemExit("配置里没有任何源")

    overrides: dict[str, str] = {}
    for pair in args.set:
        if "=" not in pair:
            raise SystemExit(f"--set 参数格式应为 NAME=URL，收到: {pair}")
        name, url = pair.split("=", 1)
        overrides[name.strip()] = url.strip()
    if args.ryp0_url:
        overrides["ryp0"] = args.ryp0_url
    if args.altgallery_url:
        overrides["altgallery"] = args.altgallery_url
    for src in source_list:
        if src.get("name") in overrides:
            src["url"] = overrides[src["name"]]

    primary_name = source_list[0].get("name", "primary")

    log = Log()
    started = utcnow()
    log.info("开始同步", version="1.1.0", startedAt=started, output=str(output),
             sources=[s.get("name") for s in source_list])

    report: dict = {
        "startedAt": started,
        "finishedAt": None,
        "status": "unknown",
        "sources": {},
        "counts": {},
        "conflicts": {"metadata": [], "versions": []},
        "dropped": {"invalidPrimaryApps": 0, "invalidSecondaryApps": 0,
                    "invalidVersions": 0, "duplicateVersions": 0,
                    "emptyVersionApps": [], "excluded": 0, "secondaryNews": 0},
        "warnings": [],
        "output": str(output),
    }

    def finish(code: int, status: str) -> int:
        report["status"] = status
        report["finishedAt"] = utcnow()
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (log_dir / f"sync-{stamp}.log").write_text(log.text(), "utf-8")
        (log_dir / f"sync-{stamp}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8"
        )
        (log_dir / "last_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8"
        )
        log.info("同步结束", status=status, code=code)
        return code

    # ---- 拉取：按优先级逐个拉；主源失败即中止，其余源失败则降级 ----
    primary: dict | None = None
    secondaries: list[tuple[str, dict]] = []
    any_secondary_failed = False

    for idx, src in enumerate(source_list):
        name = src.get("name") or f"source{idx}"
        src_type = src.get("type") or "altstore-json"
        url = src.get("url")
        required = bool(src.get("required")) or idx == 0

        if args.only_primary and idx > 0:
            log.info("已指定 --only-primary，跳过该源", source=name)
            continue
        if src_type != "github-releases" and not url:
            log.error("源缺少 url，已跳过", source=name)
            report["sources"][name] = {"url": None, "status": "no-url"}
            any_secondary_failed = any_secondary_failed or required
            continue

        if src_type == "github-releases":
            fetched = fetch_releases_source(src, net, log, cache_dir)
            shown_url = f"https://github.com/{src.get('repo')}"
        else:
            fetched = fetch_json(url, net, log, cache_dir, name)
            shown_url = url

        if fetched is None:
            report["sources"][name] = {"url": shown_url, "status": "failed"}
            if idx == 0 or required:
                log.error("必要源不可用，保留上一版 feed，不做任何写入", source=name)
                return finish(EXIT_PRIMARY_FETCH if idx == 0 else EXIT_SCHEMA,
                              "failed-primary" if idx == 0 else "failed-required-source")
            any_secondary_failed = True
            report["warnings"].append(f"源 {name} 拉取失败，本次跳过")
            if guards.get("failOnSecondaryFailure"):
                log.error("副源失败且 failOnSecondaryFailure=true，中止", source=name)
                return finish(EXIT_SCHEMA, "failed-secondary")
            log.warn("该源拉取失败，降级为其余源合并", source=name)
            continue

        entry = {"url": shown_url, "type": src_type, "status": "ok",
                 "apps": len(fetched.get("apps") or [])}
        report["sources"][name] = entry
        if idx == 0:
            primary = fetched
        else:
            secondaries.append((name, fetched))

    if primary is None:
        log.error("主源为空，无法合并")
        return finish(EXIT_PRIMARY_FETCH, "failed-primary")

    # ---- 合并 ----
    try:
        feed = build_feed(primary, secondaries, merge_cfg, guards, report, log, primary_name)
    except SchemaError as exc:
        log.error("源格式不符合预期", error=str(exc))
        return finish(EXIT_SCHEMA, "failed-schema")
    except GuardError as exc:
        log.error("安全阈值触发，拒绝写入", error=str(exc))
        return finish(EXIT_GUARD, "failed-guard")

    # ---- 原子写盘 ----
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix(output.suffix + ".tmp")
        payload = json.dumps(feed, ensure_ascii=False, indent=2) + "\n"
        tmp.write_text(payload, "utf-8")
        os.replace(tmp, output)
        log.info("已写入合并源", path=str(output), bytes=len(payload.encode("utf-8")),
                 apps=len(feed["apps"]))
    except OSError as exc:
        log.error("写入失败", error=str(exc))
        return finish(EXIT_WRITE, "failed-write")

    # ---- 状态与历史（供 commit 与排查使用）----
    status = "degraded" if any_secondary_failed else "ok"
    for src_name, info in report["sources"].items():
        if info.get("status") not in ("ok", None):
            status = "degraded"
    report["counts"]["sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    snapshot = {
        "startedAt": report["startedAt"],
        "finishedAt": report["finishedAt"],
        "status": status,
        "counts": report["counts"],
        "sources": report["sources"],
        "feedSha256": report["counts"]["sha256"],
    }
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "last_run.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", "utf-8"
        )
        history_path = state_dir / "history.jsonl"
        with history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n")
        lines = history_path.read_text("utf-8").splitlines()
        keep = int(guards.get("historyLines", 200))
        if len(lines) > keep:
            history_path.write_text("\n".join(lines[-keep:]) + "\n", "utf-8")
            log.info("history.jsonl 已裁剪", kept=keep, dropped=len(lines) - keep)
    except OSError as exc:
        log.warn("写入 state 失败（不影响 feed 发布）", error=str(exc))

    return finish(EXIT_OK, status)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
