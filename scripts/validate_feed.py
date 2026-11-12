#!/usr/bin/env python3
"""校验合并后的 AltStore 源是否符合 ryP0 的字段与元数据规范。

用法:
    python3 scripts/validate_feed.py --feed feed.json

退出码:
    0  校验通过
    1  存在错误（未通过）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
BID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
TINT_RE = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


class Checker:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def require_str(self, obj: dict, key: str, where: str, allow_empty: bool = False) -> bool:
        val = obj.get(key)
        if not isinstance(val, str):
            self.err(f"{where}: 缺少字符串字段 {key}")
            return False
        if not allow_empty and not val.strip():
            self.err(f"{where}: 字段 {key} 为空")
            return False
        return True


def validate(feed: dict, min_apps: int = 1) -> Checker:
    c = Checker()

    # ---- 顶层 ----
    for key in ("name", "identifier", "sourceURL", "iconURL", "apps", "categories", "news"):
        if key not in feed:
            c.err(f"顶层缺少字段 {key}")

    if not isinstance(feed.get("apps"), list) or not feed["apps"]:
        c.err("顶层 apps 必须是非空数组")
        return c
    if not isinstance(feed.get("categories"), list):
        c.err("顶层 categories 必须是数组")
    if not isinstance(feed.get("news"), list):
        c.err("顶层 news 必须是数组")

    for key in ("name", "identifier", "sourceURL", "iconURL"):
        c.require_str(feed, key, "顶层")

    src = feed.get("sourceURL")
    if isinstance(src, str) and src and not src.startswith(("https://", "http://")):
        c.err(f"顶层 sourceURL 不是 http(s) 地址: {src}")

    cats = [x for x in (feed.get("categories") or []) if isinstance(x, str)]
    if len(cats) != len(set(cats)):
        dup = [k for k, v in Counter(cats).items() if v > 1]
        c.err(f"categories 存在重复项: {dup}")
    if not cats:
        c.warn("categories 为空数组，部分客户端不会显示分类")

    # ---- 应用 ----
    seen_bids: dict[str, str] = {}
    app_count = 0
    for idx, app in enumerate(feed["apps"]):
        where = f"apps[{idx}]"
        if not isinstance(app, dict):
            c.err(f"{where}: 不是对象")
            continue
        app_count += 1
        name = app.get("name") if isinstance(app.get("name"), str) else ""
        where = f"apps[{idx}]({name or '未命名'})"

        c.require_str(app, "name", where)
        c.require_str(app, "bundleIdentifier", where)
        c.require_str(app, "developerName", where)

        bid = app.get("bundleIdentifier")
        if isinstance(bid, str):
            if not BID_RE.match(bid):
                c.err(f"{where}: bundleIdentifier 含非法字符: {bid}")
            key = bid.lower()
            if key in seen_bids:
                c.err(f"{where}: bundleIdentifier 重复（另见 {seen_bids[key]}）")
            else:
                seen_bids[key] = where

        if "catalogID" in app and not isinstance(app["catalogID"], str):
            c.err(f"{where}: catalogID 必须是字符串")

        policy = app.get("updatePolicy")
        if policy is not None and policy not in ("daily", "static"):
            c.warn(f"{where}: updatePolicy 取值 '{policy}' 不在已知集合 daily/static 内")

        cat = app.get("category")
        if isinstance(cat, str) and cat:
            if cats and cat not in cats:
                c.err(f"{where}: category '{cat}' 未出现在顶层 categories 中")
        elif cat is None or cat == "":
            c.warn(f"{where}: 缺少 category（ryP0 上游也存在此情况，客户端可容忍）")

        tint = app.get("tintColor")
        if tint is not None and (not isinstance(tint, str) or not TINT_RE.match(tint)):
            c.err(f"{where}: tintColor 不是合法十六进制颜色: {tint!r}")

        for url_field in ("iconURL", "githubURL"):
            val = app.get(url_field)
            if val is not None and (not isinstance(val, str) or not val.startswith("https://")):
                c.warn(f"{where}: {url_field} 不是 https 地址")

        versions = app.get("versions")
        if not isinstance(versions, list) or not versions:
            c.err(f"{where}: versions 必须是非空数组")
            continue

        seen_versions: set[tuple[str, str]] = set()
        has_sha = 0
        for vidx, ver in enumerate(versions):
            vwhere = f"{where}.versions[{vidx}]"
            if not isinstance(ver, dict):
                c.err(f"{vwhere}: 不是对象")
                continue
            c.require_str(ver, "version", vwhere)
            c.require_str(ver, "downloadURL", vwhere)
            dl = ver.get("downloadURL")
            if isinstance(dl, str) and not dl.startswith("https://"):
                c.err(f"{vwhere}: downloadURL 必须是 https 地址")
            date = ver.get("date")
            if not isinstance(date, str) or not ISO_RE.match(date):
                c.err(f"{vwhere}: date 必须形如 2026-11-10T04:44:50Z，实际 {date!r}")
            else:
                try:
                    datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    c.err(f"{vwhere}: date 不是合法日期 {date!r}")
            size = ver.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                c.err(f"{vwhere}: size 必须是正整数，实际 {size!r}")
            if ver.get("sha256"):
                has_sha += 1
                if not re.match(r"^[0-9a-f]{64}$", str(ver.get("sha256"))):
                    c.err(f"{vwhere}: sha256 格式非法")
            ident = (str(ver.get("version")), str(ver.get("buildVersion", "")))
            if ident in seen_versions:
                c.err(f"{vwhere}: 同一应用内版本重复 version={ident[0]} buildVersion={ident[1]}")
            seen_versions.add(ident)
        if has_sha == 0 and len(versions) > 1:
            c.warn(f"{where}: 所有版本均无 sha256（ryP0 上游约 96% 版本带校验值）")

    if app_count < min_apps:
        c.err(f"应用总数 {app_count} 少于下限 {min_apps}")

    for idx, item in enumerate(feed.get("news") or []):
        if not isinstance(item, dict):
            c.err(f"news[{idx}]: 不是对象")
            continue
        if not isinstance(item.get("title"), str) or not item.get("title").strip():
            c.err(f"news[{idx}]: 缺少 title")

    return c


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default="feed.json")
    ap.add_argument("--min-apps", type=int, default=1)
    ap.add_argument("--strict", action="store_true", help="把 warning 也视为失败")
    args = ap.parse_args(argv)

    path = Path(args.feed)
    try:
        feed = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL 无法读取 {path}: {exc}", file=sys.stderr)
        return 1

    c = validate(feed, args.min_apps)
    for w in c.warnings:
        print(f"WARN {w}")
    for e in c.errors:
        print(f"FAIL {e}", file=sys.stderr)

    apps = len(feed.get("apps") or []) if isinstance(feed, dict) else 0
    versions = sum(len(a.get("versions") or []) for a in (feed.get("apps") or [])
                   if isinstance(a, dict))
    print(f"校验结果: 应用 {apps} 个 / 版本 {versions} 个 / 错误 {len(c.errors)} / 警告 {len(c.warnings)}")

    if c.errors or (args.strict and c.warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
