#!/usr/bin/env python3
"""merge_sources 的离线回归测试（不依赖网络）。

运行:
    python3 tests/test_merge.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import merge_sources as ms  # noqa: E402
import validate_feed as vf  # noqa: E402

CFG = json.loads((ROOT / "config" / "sync.json").read_text("utf-8"))
MERGE_CFG = dict(CFG["merge"])
MERGE_CFG["sourceUrl"] = "https://example.test/feed.json"
GUARDS = {"minAppsAbsolute": 1, "minPrimaryAppRatio": 0, "minTotalAppRatio": 0}

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        failures.append(msg)


def new_report() -> dict:
    return {
        "startedAt": "test", "finishedAt": None, "status": "unknown",
        "sources": {}, "counts": {},
        "conflicts": {"metadata": [], "versions": []},
        "dropped": {"invalidPrimaryApps": 0, "invalidSecondaryApps": 0,
                    "invalidVersions": 0, "duplicateVersions": 0,
                    "emptyVersionApps": [], "excluded": 0, "secondaryNews": 0},
        "warnings": [], "output": "feed.json",
    }


def primary(apps: list[dict], categories: list[str] | None = None) -> dict:
    return {
        "name": "ryP0", "identifier": "com.ry0x.source",
        "iconURL": "https://e/i.png", "sourceURL": "https://e/r.json",
        "categories": categories or ["Tools", "Games"], "news": [], "apps": apps,
    }


def app(bid: str, name: str = "A", versions: list[dict] | None = None, **extra) -> dict:
    base = {
        "name": name, "bundleIdentifier": bid, "developerName": "dev",
        "category": "Tools", "iconURL": "https://e/i.png", "updatePolicy": "daily",
        "versions": versions if versions is not None else [ver()],
    }
    base.update(extra)
    return base


def ver(v: str = "1.0", date: str = "2026-01-01T00:00:00Z", url: str | None = None,
        size: int = 100, **extra) -> dict:
    base = {"version": v, "date": date,
            "downloadURL": url or f"https://github.com/o/r/releases/download/{v}/a.ipa",
            "size": size}
    base.update(extra)
    return base


def run(prim: dict, sec: dict | None, log: ms.Log | None = None) -> tuple[dict, dict, ms.Log]:
    log = log or ms.Log()
    report = new_report()
    feed = ms.build_feed(prim, sec, MERGE_CFG, GUARDS, report, log)
    return feed, report, log


def by_bid(feed: dict, bid: str) -> dict | None:
    for a in feed["apps"]:
        if a["bundleIdentifier"].lower() == bid.lower():
            return a
    return None


print("1) 基本合并：副源独有应用应被转换为 ryP0 结构")
feed, rep, _ = run(
    primary([app("com.p.one", "Primary One")]),
    {"name": "AltGallery", "apps": [{
        "name": "Second App", "bundleIdentifier": "com.s.two", "developerName": "sdev",
        "subtitle": "sub", "localizedDescription": "desc", "iconURL": "https://e/i2.png",
        "tintColor": "#112233", "versions": [ver("2.0", "2026-02-02")],
        "screenshots": ["https://e/s.png"],
    }]},
)
check(len(feed["apps"]) == 2, "应用数 = 2")
second = by_bid(feed, "com.s.two")
check(second is not None, "副源应用进入输出")
check(second and second["catalogID"].startswith("project-"), "catalogID 按 ryP0 规则生成")
check(second and second["updatePolicy"] == "static", "导入应用 updatePolicy=static")
check(second and second["appType"] == "Static", "导入应用 appType=Static")
check(second and second["category"] in feed["categories"], "分类存在于 categories")
check(second and second["versions"][0]["date"] == "2026-02-02T00:00:00Z", "date 规范化为 ISO 8601 Z")
check(second and "screenshots" not in second, "非 ryP0 字段 screenshots 默认剔除")
check(second and second["githubURL"] == "https://github.com/o/r", "从 Release 链接反推 githubURL")
check(rep["counts"]["importedApps"] == 1, "报告记录导入数")

print("2) 同 bundleIdentifier：主源字段保留，缺失字段由副源补全")
feed, rep, _ = run(
    primary([app("com.p.one", "Primary One", subtitle="")]),
    {"name": "AG", "apps": [{
        "name": "Primary One", "bundleIdentifier": "com.P.ONE", "developerName": "altdev",
        "subtitle": "副源副标题", "localizedDescription": "d", "iconURL": "https://e/i2.png",
        "versions": [],
    }]},
)
a = by_bid(feed, "com.p.one")
check(len(feed["apps"]) == 1, "bundleIdentifier 大小写不同仍视为同一应用")
check(a and a["developerName"] == "dev", "已有字段保留主源值（developerName）")
check(a and a["subtitle"] == "副源副标题", "空字段由副源补全（subtitle）")
check(len(rep["conflicts"]["metadata"]) >= 1, "字段差异记入冲突报告")
check(any(c["field"] == "developerName" for c in rep["conflicts"]["metadata"]),
      "developerName 差异被单独记录")

print("3) 版本冲突：同版本不同下载地址，保留主源并记录")
feed, rep, _ = run(
    primary([app("com.p.one", versions=[ver("1.0", url="https://github.com/o/r/releases/download/1.0/a.ipa")])]),
    {"name": "AG", "apps": [{
        "name": "A", "bundleIdentifier": "com.p.one", "developerName": "d",
        "versions": [ver("1.0", url="https://github.com/o/r/releases/download/1.0/b.ipa")],
    }]},
)
a = by_bid(feed, "com.p.one")
check(a and a["versions"][0]["downloadURL"].endswith("a.ipa"), "冲突时保留主源 downloadURL")
check(len(rep["conflicts"]["versions"]) == 1, "版本冲突写入报告")

print("4) 版本互补：副源独有版本合并进主源应用")
feed, rep, _ = run(
    primary([app("com.p.one", versions=[ver("1.0")])]),
    {"name": "AG", "apps": [{
        "name": "A", "bundleIdentifier": "com.p.one", "developerName": "d",
        "versions": [ver("2.0", "2026-03-03"), ver("1.0")],
    }]},
)
a = by_bid(feed, "com.p.one")
check(a and len(a["versions"]) == 2, "合并后共 2 个版本")
check(a and a["versions"][0]["version"] == "2.0", "版本按日期倒序，最新在前")
check(rep["counts"]["addedVersions"] == 1, "报告记录新增版本数")

print("5) 应用内重复版本（ryP0 上游真实存在）应被去重")
feed, rep, _ = run(
    primary([app("com.p.one", versions=[ver("1.0", "2026-01-02"), ver("1.0", "2026-01-01")])]),
    None,
)
a = by_bid(feed, "com.p.one")
check(a and len(a["versions"]) == 1, "重复版本被去掉")
check(rep["dropped"]["duplicateVersions"] == 1, "去重数量写入报告")

print("6) 空版本应用（上游真实存在 13 个）默认被移除")
feed, rep, _ = run(primary([app("com.p.one"), app("com.p.empty", "Empty", versions=[])]), None)
check(len(feed["apps"]) == 1, "空版本应用被移除")
check(rep["dropped"]["emptyVersionApps"] == ["Empty"], "移除名单写入报告")

print("7) 主源格式错误 → SchemaError")
for bad in ({"apps": "nope"}, {"apps": []}, {}):
    try:
        run(bad, None)
        check(False, f"未对畸形主源抛错: {bad}")
    except ms.SchemaError:
        check(True, f"畸形主源抛出 SchemaError: {list(bad.keys()) or '空对象'}")

print("8) 阈值守卫：应用数骤降 → GuardError")
try:
    ms.build_feed(primary([app("com.p.one")]), None,
                  MERGE_CFG, {"minTotalAppRatio": 5}, new_report(), ms.Log())
    check(False, "未触发 GuardError")
except ms.GuardError:
    check(True, "命中 minTotalAppRatio 触发 GuardError")

print("9) bundleIdentifiers 别名匹配")
feed, rep, _ = run(
    primary([app("com.p.main", bundleIdentifiers=["com.p.alias"])]),
    {"name": "AG", "apps": [{
        "name": "Alias App", "bundleIdentifier": "com.p.alias", "developerName": "d",
        "versions": [ver("3.0")],
    }]},
)
check(len(feed["apps"]) == 1, "别名应用不重复输出")
check(rep["counts"]["matchedApps"] == 1, "别名匹配计入 matchedApps")
a = by_bid(feed, "com.p.main")
check(a and any(v["version"] == "3.0" for v in a["versions"]), "副源版本挂到主源应用上")

print("10) 非法条目被跳过而非崩溃")
feed, rep, _ = run(
    primary([app("com.p.one"), {"name": "no-bid"}, {"bundleIdentifier": "bad id!", "name": "x"}]),
    {"name": "AG", "apps": ["junk", {"bundleIdentifier": "com.s.ok", "name": "OK",
                                     "versions": [{"version": "1", "downloadURL": "ftp://x"}]}]},
)
check(len(feed["apps"]) == 1, "非法主源/副源条目被跳过")
check(rep["dropped"]["invalidPrimaryApps"] == 2, "记录被丢弃的主源条目数")

print("11) news 默认不携带副源公告")
feed, rep, _ = run(
    primary([app("com.p.one")]),
    {"name": "AG", "apps": [], "news": [{"title": "a", "identifier": "x"}, {"title": "b", "identifier": "y"}]},
)
check(feed["news"] == [], "news 为空")
check(rep["dropped"]["secondaryNews"] == 2, "丢弃数量写入报告")

print("12) 日期多格式归一")
cases = [("2026-01-01", "2026-01-01T00:00:00Z"),
         ("2026-01-01T12:30:00Z", "2026-01-01T12:30:00Z"),
         ("2026-01-01T12:30:00+08:00", "2026-01-01T04:30:00Z"),
         ("2026-01-01 12:30:00", "2026-01-01T12:30:00Z")]
for raw, expect in cases:
    got, _ = ms.norm_date(raw, ms.Log(), "t")
    check(got == expect, f"{raw} -> {got}")

print("13) 校验器能拒绝不规范输出")
bad_feed = {
    "name": "x", "identifier": "y", "sourceURL": "https://e/f.json", "iconURL": "https://e/i.png",
    "categories": ["Tools"], "news": [],
    "apps": [{"name": "A", "bundleIdentifier": "com.a.b", "developerName": "d", "category": "Nope",
              "versions": [{"version": "1", "date": "2026-01-01", "downloadURL": "http://e/a.ipa",
                            "size": 0}]}],
}
c = vf.validate(bad_feed, 1)
check(len(c.errors) >= 4, f"校验器报出 {len(c.errors)} 处错误")
ok_feed, _, _ = run(primary([app("com.p.one")]), None)
check(len(vf.validate(ok_feed, 1).errors) == 0, "合法输出零错误")

print()
if failures:
    print(f"失败 {len(failures)} 项：")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("全部用例通过")
