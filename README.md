# appsource-sync

多源 AltStore 源合并器，输出遵循 ryP0 字段规范，由 GitHub Actions 定时生成并提交。

## 订阅

| 项 | 地址 |
| --- | --- |
| 主 | `https://raw.githubusercontent.com/byteat/ryp0-altgallery-source/main/feed.json` |
| 镜像 | `https://cdn.jsdelivr.net/gh/byteat/ryp0-altgallery-source@main/feed.json` |

镜像走 jsDelivr 缓存，与主地址不同步。2026-11-14 实测：主地址 233 应用 / 3045 版本，镜像 258 应用 / 2651 版本（对应提交 `adb204b4`）。

## 数据快照

| 项 | 值 |
| --- | --- |
| 应用数 | 233 |
| 版本数 | 3045 |
| 主源应用 | 200 |
| 重复 bundleIdentifier | 6 组 / 13 条，全部来自主源 |
| 合并新引入的重复 bundleIdentifier | 0 组 |
| 空版本应用 | 13，全部来自主源 |
| 非 ISO 8601 日期 | 4，全部来自主源 |
| 应用内重复版本 | 397，按 `version` + `buildVersion` 计；主源自带 396 条（292 组），合并引入 1 条 |
| 按内容计的重复版本 | 13 组 / 13 条，按 `version` + `downloadURL` + `size` 计；上游自带 3 组，合并引入 10 组 |
| 重复版本构成 | 293 组中 292 组 `downloadURL` 不同，277 组 `size` 不同，`downloadURL` 与 `size` 全同的 0 组 |
| 缺 `sha256` 的版本 | 184，主源 129、导入 55 |
| 快照时间 | 2026-11-14 |

`version` + `buildVersion` 与 `version` + `downloadURL` + `size` 是两个口径：前者 397 条，后者 13 条。前者把同版本号下不同下载产物计为重复，其中 292 组 `downloadURL` 不同（Apollo 的 GLASS / GLASSICONS、Muffin-EMU 的 fakesigned 等并行产物）。后者只算 `version`、`downloadURL`、`size` 三项全同的记录。

按内容计的 13 组，合并引入的 10 组统一特征为「主源条目 `buildVersion` 有值、追加条目 `buildVersion` 缺失」：WQToolkit `1.0`、AniBaka `5.2.4`、Kazumi for iOS `3.0.5`、mangayomi `0.9.95`、RewindBox `0.0.11`、SideStore `0.7.0-20260911.328+6032424a`、TiebaPure-iOS `1.4.15`、AltStore `2.3.1`、DukeX `1.0.2`、DolphiniOS `5.0.0b6`。上游自带的 3 组：LiveContainer (Stable) `3.8.0`、EnsWilde `EnsWilde3.1.3`、PancakeStore `1.3.1`。

合并引入的重复最多的一组是 DolphiniOS `5.0.0b6`，主源该版本有两条记录，一条 `buildVersion` 缺失（`downloadURL` 指向 ryP0-repository），一条 `buildVersion` 为 `26`（`downloadURL` 指向 OatmealDome release）。AltGallery 同 ID 版本 `buildVersion` 缺失、`downloadURL` 与 `size` 与主源 `26` 那条一致；`append_secondary_versions` 按 `version` + `buildVersion` + `downloadURL` + `size` 四元组判重，因 `buildVersion` 一条缺失一条为 `26` 而不匹配，该版本被追加。

## 上游源

`sources` 为有序数组，首个元素为主源，决定输出格式与冲突优先级。

| 顺序 | `name` | 地址 | 快照 | 许可证 |
| --- | --- | --- | --- | --- |
| 1 | `ryp0` | `https://raw.githubusercontent.com/Sami-Wali/ryP0-repository/main/repo.json` | 200 应用 / 2955 版本 | 未声明 |
| 2 | `altgallery` | `https://raw.githubusercontent.com/bebound/AltGallery/refs/heads/master/all-apps.json` | 68 应用 / 69 版本 | MIT |
| 3 | `one` | `https://raw.githubusercontent.com/ios151/One-releases/main/altsource.json` | 1 应用 / 18 版本 | 未声明 |
| 4 | `insav` | `https://raw.githubusercontent.com/ios151/Insav-releases/main/altsource.json` | 1 应用 / 6 版本 | 未声明 |
| 5 | `wqguard` | `https://github.com/Kianuni/WQGuard` | 1 应用 / 1 版本（v1.2.1） | MIT |

许可证取自 GitHub API `license` 字段。

## 源类型

| `type` | 数据来源 | 必填字段 |
| --- | --- | --- |
| 省略 / `altstore-json` | 含顶层 `apps` 数组的 AltStore 源 JSON | `url` |
| `github-releases` | GitHub API releases 接口 | `repo`（`owner/name`）、`bundleIdentifier`、`appName` |

`github-releases` 字段：

| 字段 | 作用 |
| --- | --- |
| `bundleIdentifier` | 写入应用的 bundleIdentifier，取自仓库 `project.pbxproj` 的 `PRODUCT_BUNDLE_IDENTIFIER`（WQGuard 为 `com.wqguard.app`） |
| `assetPattern` | 安装包资产正则，默认 `\.ipa$` |
| `excludePrerelease` | 排除 prerelease，默认 `true` |
| `maxVersions` | 版本数上限 |
| `minOSVersion` | 生成版本时写入；`strictRyP0Fields: true` 时从输出剔除 |
| `perPage` | releases 分页数，默认 30 |

版本号取 tag 去 `v` 前缀，`date` 取 `published_at`，`size` 取资产 `size`。

## 配置

### 新增源

```json
{ "name": "mySource", "url": "https://example.com/apps.json", "schema": "altstore", "required": false }
```

| 字段 | 说明 |
| --- | --- |
| `name` | 日志标识、错误来源标记、缓存文件名 |
| `required` | `true`：拉取失败即中止整次同步；默认 `false`：失败跳过并标记 `degraded` |

### `merge`

| 键 | 当前值 | 作用 |
| --- | --- | --- |
| `onBundleIdConflict` | `merge` | 同 ID 副源条目并入已有应用；`keep-all` 保留为独立应用 |
| `preservePrimaryVerbatim` | `true` | 主源条目逐字段原样输出 |
| `strictRyP0Fields` | `true` | 新增内容字段限定为主源实际出现过的字段 |
| `dropEmptyVersionApps` | `true` | 仅作用于导入应用 |
| `maxVersionsPerApp` | `0` | 仅作用于导入应用 |
| `carryNewsFrom` | `["ryp0"]` | 仅携带主源 news |
| `categoryAliases` | `entertainment` → `Movies` 等 | 上游分类归一 |
| `excludeBundleIds` | `[]` | 按 bundleIdentifier 排除 |

### `guards`

| 键 | 值 | 作用 |
| --- | --- | --- |
| `minAppsAbsolute` | 20 | 应用数下限 |
| `minPrimaryAppRatio` | 0.8 | 主源有效应用占比下限 |
| `minTotalAppRatio` | 0.9 | 合并后应用数相对主源的比例下限 |

## 合并规则

| 场景 | 处理 |
| --- | --- |
| 副源与已有应用同 ID | 不新增应用记录，版本并入该应用 |
| 主源条目 | 逐字段、逐键顺序输出；内部重复应用、重复版本、空版本应用、非 ISO 日期均不改写 |
| 副源版本并入 | 转换后追加至 `versions` 末尾；`version` / `buildVersion` / `downloadURL` / `size` 全同者跳过 |
| 同版本号、`downloadURL` 或 `size` 不同 | 两条均保留，记警告 |
| 主源与副源字段取值不同 | 主源不补全、不改写；差异记入 `logs/*.json` 的 `conflicts.metadata`，标记 `primary-immutable` |
| `strictRyP0Fields` 剔除 | `nsfw` / `screenshots` / `minOSVersion` 等主源未定义字段剔除并记录 |
| 后续源独有应用 | 转 ryP0 结构：生成 `catalogID`，`updatePolicy=static`，`appType=Static` |
| 分类取值 | `categoryOverrides` → `categoryAliases` → 关键词匹配 → `defaultCategory`（`Tools`） |
| 上游 `appPermissions` | 写入 `appPermissions.entitlements` 与 `appPermissions.privacy`，非扁平字段 |
| 应用内重复版本 | 主源应用保留，导入应用去重 |
| 版本数组为空 | 主源应用保留，导入应用移除 |
| `date` 非 ISO 8601 | 主源版本保留原值；导入版本归一为 `YYYY-MM-DDTHH:MM:SSZ`，无法归一则移除 |
| 后续源 `screenshots` | 默认丢弃；`keepScreenshots: true` 时保留后再由字段白名单剔除 |
| 后续源 `news` | 默认丢弃；`carryNewsFrom` 指定保留源 |
| `keep-all` | 同 ID 条目全部保留为独立应用（回退开关，未启用） |

## 字段差异

| 维度 | ryP0 | AltGallery | One / INSAV |
| --- | --- | --- | --- |
| 顶层字段 | `name` `identifier` `iconURL` `sourceURL` `categories` `apps` `news` | `name` `subtitle` `description` `iconURL` `website` `tintColor` `apps` `news` | 同 AltGallery，另有 `nsfw` `featuredApps` |
| 应用标识 | `bundleIdentifier` + `catalogID`（`project-` / `app-` / `source-` + 32 位十六进制，实测三种前缀并存） | `bundleIdentifier` | `bundleIdentifier` |
| 分类 | `category` + 顶层 `categories` 白名单 | 无 | `entertainment` |
| 版本字段 | `version` `date` `downloadURL` `size` `buildVersion` `localizedDescription` `releaseChannel` `sha256` `ipaBundleIdentifier` `upstreamAssetURL` `sourceAppName` `sourceAssetName` `sourceArchiveEntry` | `version` `date` `downloadURL` `size` `minOSVersion` `localizedDescription` `buildVersion` | `version` `buildVersion` `date` `localizedDescription` `downloadURL` `size` `minOSVersion` |
| 日期格式 | 主流 `2026-11-10T04:44:50Z`，另有 `2026-11-05` 与带时区偏移取值 | `2026-10-16` | `2026-11-04T16:15:28Z` |
| 截图 | 无 | `screenshots`（URL 数组） | 无 |
| 更新策略 | `updatePolicy`（`daily`/`static`）、`appType`（`Daily Update`/`Static`） | 无 | 无 |
| 健康检查 | `status`、`backup`、`automation`、`importSource` | 无 | 无 |
| 公告 | 空数组 | 69 条，带 `appID` | 空数组 |

ryP0 与 AltGallery 的 bundleIdentifier 重合数：34。

## 运行

| 方式 | 配置 |
| --- | --- |
| 定时 | `cron: "17 */6 * * *"`（UTC）→ 00:17 / 06:17 / 12:17 / 18:17；北京时间 08:17 / 14:17 / 20:17 / 次日 02:17 |
| 手动 | Actions → `Sync app sources` → `Run workflow` |

手动输入：

| 输入 | 作用 |
| --- | --- |
| `dry_run` | 只生成与校验，不提交 |
| `strict_validate` | 校验警告（含主源自带差异）判定失败 |
| `ryp0_url` | 覆盖 `ryp0` 地址 |
| `altgallery_url` | 覆盖 `altgallery` 地址 |
| `set_sources` | 通用覆盖，`name=url`，逗号分隔 |
| `skip_secondary` | 仅处理主源 |

并发组 `sync-app-sources`，`cancel-in-progress: false`。

### 退出码

| 码 | 触发条件 | 行为 |
| --- | --- | --- |
| 0 | 成功或非必要源降级 | 校验后提交 |
| 2 | 主源拉取失败且无缓存 | 不写 `feed.json`，任务失败 |
| 3 | 源格式不符，或 `required` 源不可用 | 不写文件，任务失败 |
| 4 | 触发安全阈值 | 不写文件，任务失败 |
| 5 | 写盘失败 | 任务失败 |

### 机制

| 机制 | 取值 |
| --- | --- |
| 网络重试 | 4 次指数退避，起始 2s，上限 30s；触发条件为超时、429、5xx |
| 缓存 | `state/cache/<源名>.json`，经 Actions cache 持久化 |
| 写入方式 | 先写 `.tmp` 再 `os.replace` |
| 校验基准 | `--baseline state/cache/ryp0.json`，识别主源条目并容忍其自带格式差异 |
| 推送重试 | `git push` 失败后 `pull --rebase`，最多 3 次 |
| 提交条件 | `feed.json` 有变化 |

### 日志

| 位置 | 内容 | 保留期 |
| --- | --- | --- |
| Actions 运行摘要 | 应用/版本数、各源状态、并入版本数、重复 ID 组数、导入应用清理动作 | 随 run |
| `logs/sync-<时间戳>.log` | 逐行 UTC 日志 | artifact 30 天 |
| `logs/sync-<时间戳>.json` | 结构化报告：计数、冲突明细、丢弃清单 | artifact 30 天 |
| `state/last_run.json` | 最近一次运行快照，含 feed sha256 | 随仓库提交 |
| `state/history.jsonl` | 每次更新的追加记录，上限 200 行 | 随仓库提交 |
| git 提交信息 | 应用/版本数、主源保留数、导入数、并入版本数、新引入重复 ID 组数 | 永久 |

## 本地运行

```bash
python3 tests/test_merge.py                    # 26 组回归测试，无需网络

python3 scripts/merge_sources.py --config config/sync.json \
    --source-url https://raw.githubusercontent.com/OWNER/REPO/main/feed.json

python3 scripts/validate_feed.py --feed feed.json --config config/sync.json \
    --baseline state/cache/ryp0.json

python3 scripts/merge_sources.py --config config/sync.json \
    --set one=https://example.com/apps.json
```

依赖 Python 3.10+ 标准库（源码使用 `X | None` 注解，配 `from __future__ import annotations`；实测 3.9.6 下测试与校验均可运行）。`github-releases` 源读取 GitHub API：未认证 60 次/小时，认证后 5000 次/小时。

## 部署

| 步骤 | 操作 |
| --- | --- |
| 1 | 推送本目录内容至仓库根目录 |
| 2 | Settings → Actions → General → Workflow permissions 设为 **Read and write** |
| 3 | 手动运行工作流，`dry_run=true` |
| 4 | `dry_run=false`，`feed.json` 由工作流提交 |

GitHub Pages：Settings → Pages → Source 选 `Deploy from a branch`，分支 `main`，目录 `/ (root)`，订阅地址变为 `https://<owner>.github.io/<repo>/feed.json`，同步修改 `merge.sourceUrl`。

## 目录结构

```
appsource-sync/
├── .github/workflows/sync-sources.yml
├── config/sync.json
├── scripts/merge_sources.py
├── scripts/validate_feed.py
├── tests/test_merge.py
├── feed.json
├── LICENSE
├── NOTICE.md
├── logs/
└── state/
```

## 已知限制

| 项 | 事实 |
| --- | --- |
| 定时精度 | `schedule` 按 UTC 计算，实测延迟 21 分钟至 339 分钟（近 4 次定时运行：21 / 43 / 101 / 339 分钟） |
| 定时停用 | 公开仓库连续 60 天无提交活动时 `schedule` 自动停用 |
| 分支范围 | `schedule` 仅对默认分支生效 |
| 重复 ID | 输出含 6 组重复 bundleIdentifier（13 条），全部来自主源；`merge` 策略不引入新组；客户端行为未验证 |
| 主源自带异常 | 13 个空版本应用、396 条应用内重复版本、4 条非 ISO 日期原样保留；`--baseline` 下记为警告 |
| 重复版本性质 | 292 组主源重复中 291 组 `downloadURL` 不同、0 组 `downloadURL` 与 `size` 全同；按四元组去重对主源影响 0 条 |
| 合并引入重复版本 | 1 条，DolphiniOS `5.0.0b6`，`buildVersion` 缺失与 `26` 判为两个身份 |
| 空版本应用 | 13 个，均为 `category=Ports`、`portDistribution=source-code`、bid 形如 `source-port-*`，无任何 IPA |
| `buildVersion` 缺失 | feed 内 145 条版本无该字段；`version_identity` 用 `str(v.get('buildVersion',''))`，显式 `null` 会被当作字符串 `'None'`（当前数据未触发） |
| `strict_validate` | 开启时主源自带警告亦判定失败 |
| `minOSVersion` / `nsfw` | 主源字段集合未定义，导入内容不含该两字段 |
| `screenshots` | 字段白名单开启时剔除；实测主源与导入应用均无该字段，`keepScreenshots: false` |
| 分类 | 优先级为 `categoryOverrides` → `categoryAliases` → 关键词推断 → `defaultCategory`（`Tools`） |
| `status` / `backup` / `automation` | 导入应用不含该三字段（实测 33 个导入应用均为 0 条） |
| `appPermissions` | 实测位于 `appPermissions.entitlements` 与 `appPermissions.privacy`，非扁平字段。feed 内 8 个应用有该字段：主源 7 个（原样保留，仅 `entitlements`）、导入 1 个（One，含 `privacy`） |
| `sha256` | 184 条版本缺该字段（主源 129、导入 55）。上游不提供该值时字段缺失，非空字符串 |
| 下载地址 | 不做存活性探测；主源取上游自带 `status.checkedDownloadURL`，副源无此步骤 |

## 许可

| 对象 | 许可 |
| --- | --- |
| 本仓库代码与文档 | MIT，版权 2026 byteat，见 `LICENSE` |
| 覆盖范围与第三方内容归属 | 见 `NOTICE.md` |
| `bebound/AltGallery` | MIT |
| `Kianuni/WQGuard` | MIT |
| `Sami-Wali/ryP0-repository` | 未声明 |
| `Sami-Wali/ryP0` | 未声明 |
| `ios151/One-releases` | 未声明 |
| `ios151/Insav-releases` | 未声明 |

`feed.json` 内容构成：

| 项 | 状态 |
| --- | --- |
| `.ipa` 文件 | 不托管、不镜像、不重签名；`downloadURL` 指向上游 GitHub Release |
| 图标 | URL 引用上游仓库文件 |
| 应用名称、简介、截图 | 著作权归各应用作者 |
| 合并操作 | 主源条目原样保留；副源字段转换、同 ID 版本并入、导入应用去重 |

移除上游条目：删除 `sources` 中对应元素，或将 bundleIdentifier 加入 `merge.excludeBundleIds`，下次运行生效。

## 参考

"bebound/AltGallery: Curated AltStore Sources for IPA Projects on GitHub." *GitHub*, https://github.com/bebound/AltGallery. Accessed 13 Nov. 2026.

"Kianuni/WQGuard." *GitHub*, https://github.com/Kianuni/WQGuard. Accessed 13 Nov. 2026.

"Sami-Wali/ryP0: ryP0 Is a Modern iOS App Library for Discovering, Downloading, and Managing IPA Files." *GitHub*, https://github.com/Sami-Wali/ryP0. Accessed 13 Nov. 2026.

*AltGallery all-apps.json*, https://raw.githubusercontent.com/bebound/AltGallery/refs/heads/master/all-apps.json. Accessed 13 Nov. 2026.

*Insav-releases altsource.json*, https://raw.githubusercontent.com/ios151/Insav-releases/main/altsource.json. Accessed 13 Nov. 2026.

*One-releases altsource.json*, https://raw.githubusercontent.com/ios151/One-releases/main/altsource.json. Accessed 13 Nov. 2026.

*ryP0 repo.json*, https://raw.githubusercontent.com/Sami-Wali/ryP0-repository/main/repo.json. Accessed 13 Nov. 2026.
