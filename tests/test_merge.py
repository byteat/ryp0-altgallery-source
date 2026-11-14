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
# 与生产配置一致：主源原样保留 + 同 ID 副源只并入版本。
# 合成主源的字段不完整，字段白名单（strictRyP0Fields）在第 24 组用完整夹具单独验证。
MERGE_CFG["onBundleIdConflict"] = "merge"
MERGE_CFG["preservePrimaryVerbatim"] = True
MERGE_CFG["strictRyP0Fields"] = False
LEGACY_CFG = dict(MERGE_CFG)
LEGACY_CFG["preservePrimaryVerbatim"] = False
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
                    "emptyVersionApps": [], "excluded": 0, "secondaryNews": 0,
                    "nonRyP0Fields": []},
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


def run(prim: dict, sec: dict | None, log: ms.Log | None = None,
        extra: list[tuple[str, dict]] | None = None,
        cfg: dict | None = None) -> tuple[dict, dict, ms.Log]:
    log = log or ms.Log()
    report = new_report()
    secondaries: list[tuple[str, dict]] = []
    if sec is not None:
        secondaries.append(("altgallery", sec))
    if extra:
        secondaries.extend(extra)
    feed = ms.build_feed(prim, secondaries, cfg or MERGE_CFG, GUARDS, report, log)
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

print("2) 同 bundleIdentifier：主源字段不可变，差异只记录不改写")
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
check(a and a["developerName"] == "dev", "主源已有字段保持原值（developerName）")
check(a and a["subtitle"] == "", "主源空字段不被副源补全（subtitle）")
check(len(rep["conflicts"]["metadata"]) >= 1, "字段差异记入冲突报告")
check(any(c["field"] == "developerName" for c in rep["conflicts"]["metadata"]),
      "developerName 差异被单独记录")
check(all(c["resolution"] == "primary-immutable" for c in rep["conflicts"]["metadata"]),
      "冲突决议标记为 primary-immutable")

print("3) 同版本号但下载地址不同：主副源两条版本均保留")
feed, rep, _ = run(
    primary([app("com.p.one", versions=[ver("1.0", url="https://github.com/o/r/releases/download/1.0/a.ipa")])]),
    {"name": "AG", "apps": [{
        "name": "A", "bundleIdentifier": "com.p.one", "developerName": "d",
        "versions": [ver("1.0", url="https://github.com/o/r/releases/download/1.0/b.ipa")],
    }]},
)
a = by_bid(feed, "com.p.one")
check(a and len(a["versions"]) == 2, "同版本号不同地址，两条版本都保留")
check(a and a["versions"][0]["downloadURL"].endswith("a.ipa"), "主源已有版本顺序不变")
check(a and a["versions"][1]["downloadURL"].endswith("b.ipa"), "副源版本追加在末尾")
check(rep["counts"]["addedVersions"] == 1, "报告记录并入版本数")

print("4) 版本互补：副源独有版本追加，完全相同的版本跳过")
feed, rep, _ = run(
    primary([app("com.p.one", versions=[ver("1.0")])]),
    {"name": "AG", "apps": [{
        "name": "A", "bundleIdentifier": "com.p.one", "developerName": "d",
        "versions": [ver("2.0", "2026-03-03"), ver("1.0")],
    }]},
)
a = by_bid(feed, "com.p.one")
check(a and len(a["versions"]) == 2, "合并后共 2 个版本")
check(a and a["versions"][0]["version"] == "1.0", "主源版本顺序保持不变")
check(a and a["versions"][1]["version"] == "2.0", "副源新版本追加在末尾")
check(rep["counts"]["addedVersions"] == 1, "报告记录新增版本数")
check(rep["counts"]["skippedIdenticalVersions"] == 1, "完全相同的版本跳过并计数")

print("5) 主源内部重复版本原样保留")
dup_primary = lambda: primary([app("com.p.one", versions=[
    ver("1.0", "2026-01-02"), ver("1.0", "2026-01-01")])])
feed, rep, _ = run(dup_primary(), None)
a = by_bid(feed, "com.p.one")
check(a and len(a["versions"]) == 2, "主源重复版本不去重")
check(rep["dropped"]["duplicateVersions"] == 0, "报告不记录主源去重")
feed2, rep2, _ = run(dup_primary(), None, cfg=LEGACY_CFG)
check(len(by_bid(feed2, "com.p.one")["versions"]) == 1, "关闭保真后仍按旧规则去重")
check(rep2["dropped"]["duplicateVersions"] == 1, "旧规则去重数量写入报告")

print("6) 主源空版本应用原样保留")
empty_primary = lambda: primary([app("com.p.one"), app("com.p.empty", "Empty", versions=[])])
feed, rep, _ = run(empty_primary(), None)
check(len(feed["apps"]) == 2, "空版本应用保留")
check(rep["dropped"]["emptyVersionApps"] == [], "报告不记录移除")
feed2, rep2, _ = run(empty_primary(), None, cfg=LEGACY_CFG)
check(len(feed2["apps"]) == 1, "关闭保真后按旧规则移除")
check(rep2["dropped"]["emptyVersionApps"] == ["Empty"], "旧规则移除名单写入报告")

print("7) 主源格式错误 → SchemaError")
for bad in ({"apps": "nope"}, {"apps": []}, {}):
    try:
        run(bad, None)
        check(False, f"未对畸形主源抛错: {bad}")
    except ms.SchemaError:
        check(True, f"畸形主源抛出 SchemaError: {list(bad.keys()) or '空对象'}")

print("8) 阈值守卫：应用数骤降 → GuardError")
try:
    ms.build_feed(primary([app("com.p.one")]), [],
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

print("14) 多源合并：第三个源的应用独立导入，分类经 aliases 归一")
feed, rep, _ = run(
    primary([app("com.p.one", "Primary One")]),
    {"name": "AG", "apps": [{
        "name": "Alt App", "bundleIdentifier": "com.s.two", "developerName": "d",
        "category": "utility", "versions": [ver("2.0")],
    }]},
    extra=[("one", {"name": "One", "apps": [{
        "name": "One", "bundleIdentifier": "com.ios151.one", "developerName": "ios151",
        "category": "entertainment", "nsfw": False,
        "appPermissions": {"entitlements": ["get-task-allow"]},
        "versions": [ver("1.7.1", "2026-11-04T16:15:28Z")],
    }]})],
)
check(len(feed["apps"]) == 3, "三个源共 3 个应用")
one = by_bid(feed, "com.ios151.one")
check(one is not None, "第三个源的应用被导入")
check(one and one["category"] == "Movies", "entertainment 经 categoryAliases 归一为 Movies")
check(one and one["appPermissions"]["entitlements"] == ["get-task-allow"], "appPermissions 透传")
check(rep["counts"]["importedApps"] == 2, "两个副源各导入 1 个应用")
check(rep["sources"].get("one", {}).get("imported") == 1, "报告记录每个源的导入数")

print("15) 源级 nsfw 透传到应用")
feed, rep, _ = run(
    primary([app("com.p.one")]),
    None,
    extra=[("insav", {"name": "INSAV", "nsfw": True, "apps": [{
        "name": "INSAV", "bundleIdentifier": "com.ios151.insav", "developerName": "ios151",
        "versions": [ver("1.3.0")],
    }]})],
)
insav = by_bid(feed, "com.ios151.insav")
check(insav is not None and insav.get("nsfw") is True, "源级 nsfw=true 标记到应用")

print("16) 多源冲突：同 ID 全部并入主源应用")
feed, rep, _ = run(
    primary([app("com.p.one", versions=[ver("1.0")])]),
    {"name": "AG", "apps": [{"name": "A", "bundleIdentifier": "com.p.one",
                             "developerName": "d", "versions": [ver("2.0")]}]},
    extra=[("one", {"name": "One", "apps": [{"name": "A2", "bundleIdentifier": "com.p.one",
                                             "developerName": "d2", "versions": [ver("3.0")]}]})],
)
a = by_bid(feed, "com.p.one")
check(len(feed["apps"]) == 1, "同 ID 应用只出现一次")
check(a and len(a["versions"]) == 3, "三个源的版本合并到同一个应用")
check(rep["counts"]["matchedApps"] == 2, "两个副源各匹配 1 次")

print("17) keep-all：同 bundleIdentifier 的两条记录都保留（回退开关）")
cfg_keep = dict(MERGE_CFG); cfg_keep["onBundleIdConflict"] = "keep-all"
rep = new_report()
feed = ms.build_feed(
    primary([app("com.p.one", "主源条目", versions=[ver("1.0")])]),
    [("altgallery", {"name": "AG", "apps": [{
        "name": "副源条目", "bundleIdentifier": "com.P.ONE", "developerName": "d",
        "versions": [ver("2.0")],
    }]})],
    cfg_keep, GUARDS, rep, ms.Log(),
)
check(len(feed["apps"]) == 2, "两条同 ID 记录都保留")
names = {a["name"] for a in feed["apps"]}
check(names == {"主源条目", "副源条目"}, f"保留的是两条独立记录: {names}")
check(rep["counts"]["duplicateBidGroups"] == 1, "报告统计出 1 组重复 ID")
check(rep["counts"]["conflictPolicy"] == "keep-all", "报告记录了策略")

print("18) merge 策略：同 ID 只保留一条应用，版本并入")
cfg_merge = dict(MERGE_CFG); cfg_merge["onBundleIdConflict"] = "merge"
rep = new_report()
feed = ms.build_feed(
    primary([app("com.p.one", versions=[ver("1.0")])]),
    [("altgallery", {"name": "AG", "apps": [{
        "name": "A", "bundleIdentifier": "com.p.one", "developerName": "d",
        "versions": [ver("2.0")],
    }]})],
    cfg_merge, GUARDS, rep, ms.Log(),
)
check(len(feed["apps"]) == 1, "merge 策略下仍合并为一条")
check(len(feed["apps"][0]["versions"]) == 2, "两个版本合并到同一应用")
check(rep["counts"]["newDuplicateBidGroups"] == 0, "未引入新的重复 ID 组")

print("19) keep-all：源内重复 ID 也保留")
rep = new_report()
feed = ms.build_feed(
    primary([app("com.p.dup", "A"), app("com.p.dup", "B")]),
    [], cfg_keep, GUARDS, rep, ms.Log(),
)
check(len(feed["apps"]) == 2, "源内重复 ID 保留两条")

print("20) github-releases 适配器")
src = {
    "name": "wqguard", "type": "github-releases", "repo": "Kianuni/WQGuard",
    "bundleIdentifier": "com.wqguard.app", "appName": "WQGuard",
    "developerName": "Kianuni", "category": "Tools", "minOSVersion": "16.0",
    "assetPattern": r"\.ipa$", "excludePrerelease": True, "maxVersions": 10,
}
releases = [
    {"tag_name": "v1.2.1", "draft": False, "prerelease": False,
     "published_at": "2026-11-12T16:49:46Z",
     "assets": [{"name": "WQGuard_v1.2.1.ipa", "size": 2007635,
                 "browser_download_url": "https://github.com/Kianuni/WQGuard/releases/download/v1.2.1/WQGuard_v1.2.1.ipa"},
                {"name": "WQGuard-Brotli-Shield.conf", "size": 1338,
                 "browser_download_url": "https://x/conf"}]},
    {"tag_name": "v1.3.0-beta", "draft": False, "prerelease": True,
     "published_at": "2026-11-20T00:00:00Z",
     "assets": [{"name": "WQGuard_v1.3.0.ipa", "size": 1, "browser_download_url": "https://x/beta.ipa"}]},
    {"tag_name": "v1.0.0", "draft": False, "prerelease": False,
     "published_at": "2026-10-01T00:00:00Z",
     "assets": [{"name": "notes.txt", "size": 10, "browser_download_url": "https://x/notes"}]},
]
gen = ms.releases_to_feed(src, releases, ms.Log())
gen_app = gen["apps"][0]
check(gen_app["bundleIdentifier"] == "com.wqguard.app", "bundleIdentifier 来自配置")
check(len(gen_app["versions"]) == 1, "只取 .ipa 资产与非预发布版本")
check(gen_app["versions"][0]["version"] == "1.2.1", "去掉 tag 的 v 前缀")
check(gen_app["versions"][0]["size"] == 2007635, "size 取自资产大小")
check(gen_app["versions"][0]["minOSVersion"] == "16.0", "minOSVersion 来自配置")
check(gen_app["versions"][0]["date"] == "2026-11-12T16:49:46Z", "date 规范化")

print("21) github-releases 缺 bundleIdentifier 应报错")
try:
    ms.releases_to_feed({"name": "x", "repo": "a/b"}, releases, ms.Log())
    check(False, "未抛错")
except ms.SchemaError:
    check(True, "缺少 bundleIdentifier 抛 SchemaError")

print("22) 主源条目逐字段、逐键顺序保持一致")
raw_app = app("com.p.one", "Primary One", versions=[ver("1.0")])
raw_app["status"] = "ok"
raw_app["githubProjectCard"] = "https://e/card"
feed, rep, _ = run(primary([raw_app]), None)
out = feed["apps"][0]
check(list(out.keys()) == list(raw_app.keys()), "字段集合与键顺序一致")
check(out == raw_app, "主源应用逐字段原样保留")
check("_origin" not in out, "内部来源标记不进入输出")
check(rep["counts"]["preservePrimaryVerbatim"] is True, "报告记录主源保真开关")

print("23) 生产配置的合并策略取值")
check(CFG["merge"]["onBundleIdConflict"] == "merge", "配置为 merge")
check(CFG["merge"]["preservePrimaryVerbatim"] is True, "配置为 preservePrimaryVerbatim")
check(CFG["merge"]["strictRyP0Fields"] is True, "配置为 strictRyP0Fields")

print("24) 严格字段：新增内容不含主源未定义的字段")
full_primary_app = {
    "name": "P", "catalogID": "project-x", "bundleIdentifier": "com.p.one",
    "developerName": "dev", "localizedDescription": "", "subtitle": "",
    "category": "Tools", "iconURL": "https://e/i.png", "updatePolicy": "daily",
    "appType": "Daily Update", "status": "ok", "githubURL": "https://github.com/o/r",
    "bundleIdentifiers": [], "importSource": "", "automation": {}, "backup": {},
    "githubProjectCard": "", "tintColor": "#112233", "portDistribution": {},
    "appPermissions": {},
    "versions": [ver("1.0", buildVersion="1", releaseChannel="release",
                     sha256="a" * 64, ipaBundleIdentifier="com.p.one",
                     localizedDescription="d", sourceAppName="x",
                     sourceAssetName="y", upstreamAssetURL="https://e/z",
                     sourceArchiveEntry="e")],
}
cfg_strict = dict(MERGE_CFG)
cfg_strict["strictRyP0Fields"] = True
cfg_strict["keepScreenshots"] = True
feed, rep, _ = run(
    primary([full_primary_app]),
    {"name": "AG", "nsfw": True, "apps": [{
        "name": "Imported", "bundleIdentifier": "com.s.two", "developerName": "d",
        "appPermissions": {"entitlements": ["get-task-allow"], "privacy": {}},
        "screenshots": ["https://e/s.png"],
        "versions": [ver("2.0", minOSVersion="16.0")],
    }]},
    cfg=cfg_strict,
)
imported = by_bid(feed, "com.s.two")
check(imported is not None, "副源应用被导入")
check(imported and "nsfw" not in imported, "主源未定义的 nsfw 被剔除")
check(imported and "screenshots" not in imported, "主源未定义的 screenshots 被剔除")
check(imported and "catalogID" in imported and "appPermissions" in imported,
      "主源已定义字段保留")
check(imported and "minOSVersion" not in imported["versions"][0],
      "主源版本未定义的 minOSVersion 被剔除")
check(imported and "releaseChannel" in imported["versions"][0],
      "主源版本已定义字段保留")
dropped_fields = {x["field"] for x in rep["dropped"]["nonRyP0Fields"]}
check({"nsfw", "screenshots", "minOSVersion"} <= dropped_fields,
      "被剔除字段写入报告")
check(feed["apps"][0] == full_primary_app, "字段白名单不影响主源条目")

print("25) 同 ID 副源不新增应用条目，主源自带重复组不变")
feed, rep, _ = run(
    primary([app("com.p.one", "P", versions=[ver("1.0")]),
             app("com.p.one", "P2", versions=[ver("1.1")])]),
    {"name": "AG", "apps": [{
        "name": "Alt", "bundleIdentifier": "COM.P.ONE", "developerName": "d",
        "versions": [ver("2.0")],
    }]},
)
check(len(feed["apps"]) == 2, "仍为主源两条，副源不新增条目")
check(rep["counts"]["newDuplicateBidGroups"] == 0, "未引入新的重复 ID 组")
check(rep["counts"]["primaryDuplicateBidGroups"] == 1, "主源自带 1 组重复 ID")
check(any(v["version"] == "2.0" for v in feed["apps"][0]["versions"]),
      "副源版本并入首条主源应用")
check(feed["apps"][1]["versions"][0]["version"] == "1.1",
      "第二条主源应用保持原样")

print("26) 校验器：主源自带差异降为警告，副源新增问题仍为错误")
prim_apps = [
    app("com.p.one", "P", versions=[ver("1.0", date="2026-01-01"),
                                    ver("1.0", date="2026-01-01")]),
    app("com.p.empty", "Empty", versions=[]),
]
feed, _, _ = run(primary(prim_apps), None)
baseline_keys = {(a["bundleIdentifier"].lower(), a["name"]) for a in prim_apps}
c = vf.validate(feed, 1, False, baseline_keys, True)
check(len(c.errors) == 0, "主源自带差异不判错")
check(len(c.warnings) >= 2, "主源差异记为警告")
feed["apps"].append({
    "name": "Imported Bad", "bundleIdentifier": "com.s.bad", "developerName": "d",
    "category": "Tools",
    "versions": [{"version": "1", "date": "2026-01-01",
                  "downloadURL": "https://e/a.ipa", "size": 1}],
})
c2 = vf.validate(feed, 1, False, baseline_keys, True)
check(any("date 必须形如" in e for e in c2.errors), "副源新增内容的非法 date 仍判错")

print()
if failures:
    print(f"失败 {len(failures)} 项：")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("全部用例通过")
