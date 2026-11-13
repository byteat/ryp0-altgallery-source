# appsource-sync

将多个 AltStore 源合并为一份符合 ryP0 字段规范的源文件，由 GitHub Actions 按计划运行并提交。

## 产物

| 项 | 值 |
| --- | --- |
| 应用数 | 251 |
| 版本数 | 2597 |
| 重复 bundleIdentifier | 35 组，涉及 74 条记录 |
| 数据时点 | 2026-11-13 |
| 订阅地址 | `https://raw.githubusercontent.com/byteat/ryp0-altgallery-source/main/feed.json` |
| 镜像地址 | `https://cdn.jsdelivr.net/gh/byteat/ryp0-altgallery-source@main/feed.json` |

## 上游源

`config/sync.json` 的 `sources` 为有序数组，第一个元素是主源（格式基准与冲突优先方）。

| 顺序 | 名称 | 地址 | 快照 | 许可证 |
| --- | --- | --- | --- | --- |
| 1 | `ryp0` | `https://raw.githubusercontent.com/Sami-Wali/ryP0-repository/main/repo.json` | 195 个应用 | 未声明 |
| 2 | `altgallery` | `https://raw.githubusercontent.com/bebound/AltGallery/refs/heads/master/all-apps.json` | 66 个应用 / 67 个版本 | MIT |
| 3 | `one` | `https://raw.githubusercontent.com/ios151/One-releases/main/altsource.json` | 1 个应用 / 18 个版本 | 未声明 |
| 4 | `insav` | `https://raw.githubusercontent.com/ios151/Insav-releases/main/altsource.json` | 1 个应用 / 5 个版本 | 未声明 |
| 5 | `wqguard` | `https://github.com/Kianuni/WQGuard` | 1 个应用 / 1 个版本（v1.2.1） | MIT |

许可证数据取自 GitHub API 的 `license` 字段。

## 源类型

| `type` | 数据来源 | 必填字段 |
| --- | --- | --- |
| 省略或 `altstore-json` | 顶层含 `apps` 数组的 AltStore 源 JSON | `url` |
| `github-releases` | GitHub API 的 releases 接口 | `repo`（`owner/name`）、`bundleIdentifier`、`appName` |

`github-releases` 的字段：

| 字段 | 作用 |
| --- | --- |
| `bundleIdentifier` | 写入应用的 bundleIdentifier，取值为仓库 `project.pbxproj` 中的 `PRODUCT_BUNDLE_IDENTIFIER`（WQGuard 为 `com.wqguard.app`） |
| `assetPattern` | 安装包资产匹配正则，默认 `\.ipa$` |
| `excludePrerelease` | 是否排除 prerelease，默认 `true` |
| `maxVersions` | 保留的版本数上限 |
| `minOSVersion` | 写入每个版本的 `minOSVersion` |
| `perPage` | releases 接口分页数，默认 30 |

版本号取自 tag 并去掉 `v` 前缀，`date` 取自 `published_at`，`size` 取自资产 `size`。

## 新增源

在 `config/sync.json` 的 `sources` 数组追加对象：

```json
{ "name": "mySource", "url": "https://example.com/apps.json", "schema": "altstore", "required": false }
```

| 字段 | 说明 |
| --- | --- |
| `name` | 日志标识、错误信息中的来源标记、缓存文件名 |
| `required` | `true` 时该源拉取失败则整次同步中止；默认 `false`，失败时跳过并标记 `degraded` |

## 字段差异

| 维度 | ryP0 | AltGallery | One / INSAV |
| --- | --- | --- | --- |
| 顶层字段 | `name` `identifier` `iconURL` `sourceURL` `categories` `apps` `news` | `name` `subtitle` `description` `iconURL` `website` `tintColor` `apps` `news` | 同 AltGallery，另有 `nsfw` `featuredApps` |
| 应用标识 | `bundleIdentifier` + `catalogID`（`project-` + 32 位十六进制） | `bundleIdentifier` | `bundleIdentifier` |
| 分类 | `category` + 顶层 `categories` 白名单 | 无 | `entertainment` |
| 版本字段 | `version` `date` `downloadURL` `size` `buildVersion` `releaseChannel` `sha256` `ipaBundleIdentifier` `upstreamAssetURL` | `version` `date` `downloadURL` `size` `minOSVersion` `localizedDescription` `buildVersion` | `version` `buildVersion` `date` `localizedDescription` `downloadURL` `size` `minOSVersion` |
| 日期格式 | 主流 `2026-11-10T04:44:50Z`，另有 `2026-11-05` 与带时区偏移的取值 | `2026-10-16` | `2026-11-04T16:15:28Z` |
| 截图 | 无 | `screenshots`（URL 字符串数组） | 无 |
| 更新策略 | `updatePolicy`（`daily`/`static`）、`appType`（`Daily Update`/`Static`） | 无 | 无 |
| 健康检查 | `status`、`backup`、`automation`、`importSource` | 无 | 无 |
| 公告 | 空数组 | 67 条带 `appID` 的公告 | 空数组 |

ryP0 与 AltGallery 的 bundleIdentifier 重合数为 32。

## 合并规则

| 场景 | 处理 |
| --- | --- |
| `onBundleIdConflict: "keep-all"`（默认） | 同 bundleIdentifier 的条目全部保留，不合并不丢弃；日志逐条记录 |
| `onBundleIdConflict: "merge"` | 以顺序最靠前的源为骨架，后续源补全空字段 `developerName` / `subtitle` / `localizedDescription` / `iconURL` / `tintColor` |
| 同字段取值不同 | 采用顺序靠前的源，差异写入 `logs/*.json` 的 `conflicts.metadata` |
| 同版本号但 `downloadURL` 或 `size` 不同 | 采用顺序靠前的源，写入 `conflicts.versions` |
| 后续源存在新版本 | 仅 `merge` 模式下并入同一应用，按 `date` 倒序 |
| 后续源独有应用 | 转为 ryP0 结构：生成 `catalogID`，`updatePolicy=static`，`appType=Static` |
| 分类取值 | `categoryOverrides`（按 bundleId）→ 上游 `category` 经 `categoryAliases` 映射（`entertainment` → `Movies`）→ 关键词匹配 → `defaultCategory`（`Tools`） |
| 上游 `nsfw: true` | 写入应用级 `nsfw` |
| 上游 `appPermissions` | 写入 `entitlements` 与 `privacy` |
| 应用内重复版本 | 去重，保留日期较新者 |
| 版本数组为空 | 移除该应用 |
| `date` 非 ISO 8601 | 归一为 `YYYY-MM-DDTHH:MM:SSZ`；无法归一时移除该版本 |
| 后续源 `screenshots` | 默认丢弃，`keepScreenshots: true` 时保留 |
| 后续源 `news` | 默认丢弃，`carryNewsFrom` 指定保留的源 |

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

## 触发方式

| 方式 | 配置 |
| --- | --- |
| 定时 | `cron: "17 */6 * * *"`（UTC）：00:17 / 06:17 / 12:17 / 18:17，对应北京时间 08:17 / 14:17 / 20:17 / 次日 02:17 |
| 手动 | Actions → `Sync app sources` → `Run workflow` |

手动触发的输入项：

| 输入 | 作用 |
| --- | --- |
| `dry_run` | 只生成与校验，不提交 |
| `strict_validate` | 校验警告也判定失败 |
| `ryp0_url` | 覆盖 `ryp0` 源地址 |
| `altgallery_url` | 覆盖 `altgallery` 源地址 |
| `set_sources` | 通用覆盖，`name=url`，多个以逗号分隔 |
| `skip_secondary` | 只处理主源 |

并发组为 `sync-app-sources`，`cancel-in-progress: false`。

## 退出码

| 码 | 触发条件 | 行为 |
| --- | --- | --- |
| 0 | 成功，或非必要源降级 | 校验后提交 |
| 2 | 主源拉取失败且无缓存 | 不写 `feed.json`，任务失败 |
| 3 | 源格式不符，或 `required` 源不可用 | 不写文件，任务失败 |
| 4 | 触发安全阈值 | 不写文件，任务失败 |
| 5 | 写盘失败 | 任务失败 |

安全阈值：`minAppsAbsolute`、`minPrimaryAppRatio`（主源有效应用占比）、`minTotalAppRatio`（合并后应用数相对主源的比例）。

## 其他机制

| 机制 | 取值 |
| --- | --- |
| 网络重试 | 4 次指数退避，起始 2s，上限 30s；重试条件为超时、429、5xx |
| 缓存 | `state/cache/<源名>.json`，经 Actions cache 持久化 |
| 写入方式 | 先写 `.tmp` 再 `os.replace` |
| 推送重试 | `git push` 失败后 `pull --rebase`，最多 3 次 |
| 提交条件 | `feed.json` 有变化 |

## 日志

| 位置 | 内容 | 保留期 |
| --- | --- | --- |
| Actions 运行摘要 | 应用/版本数、各源状态、清理动作、版本冲突表 | 随 run |
| `logs/sync-<时间戳>.log` | 逐行 UTC 日志 | artifact 30 天 |
| `logs/sync-<时间戳>.json` | 结构化报告：计数、冲突明细、丢弃清单 | artifact 30 天 |
| `state/last_run.json` | 最近一次运行快照，含 feed 的 sha256 | 随仓库提交 |
| `state/history.jsonl` | 每次更新的追加记录，上限 200 行 | 随仓库提交 |
| git 提交信息 | 应用/版本/冲突数量 | 永久 |

## 本地运行

```bash
python3 tests/test_merge.py                    # 21 组回归测试，不需要网络

python3 scripts/merge_sources.py --config config/sync.json \
    --source-url https://raw.githubusercontent.com/OWNER/REPO/main/feed.json

python3 scripts/validate_feed.py --feed feed.json --config config/sync.json

python3 scripts/merge_sources.py --config config/sync.json \
    --set one=https://example.com/apps.json
```

依赖 Python 3.10+ 标准库。`github-releases` 类型的源读取 GitHub API，未认证时额度为 60 次/小时，认证后为 5000 次/小时。

## 部署

1. 将本目录内容推送至仓库根目录。
2. Settings → Actions → General → Workflow permissions 设为 **Read and write**。
3. 手动运行一次工作流，`dry_run` 设为 `true`。
4. `dry_run` 设为 `false` 后，`feed.json` 由工作流提交。

订阅地址：`https://raw.githubusercontent.com/<owner>/<repo>/main/feed.json`。

GitHub Pages：Settings → Pages → Source 选择 `Deploy from a branch`、分支 `main`、目录 `/ (root)`，订阅地址变为 `https://<owner>.github.io/<repo>/feed.json`；同时需修改 `config/sync.json` 的 `merge.sourceUrl`。

## 已知限制

| 项 | 事实 |
| --- | --- |
| 定时精度 | `schedule` 按 UTC 计算；实测延迟 26 分钟与数小时两种 |
| 定时停用 | 公开仓库连续 60 天无提交活动时，`schedule` 自动停用 |
| 分支范围 | `schedule` 仅对默认分支生效 |
| 重复 ID | `keep-all` 下输出 35 组重复 bundleIdentifier；AltStore / SideStore 以 bundleIdentifier 作为应用身份，同一 ID 多次出现时的客户端行为未验证 |
| `screenshots` | 保留该字段时的客户端兼容性未验证，默认关闭 |
| 分类 | 关键词未匹配时取 `defaultCategory`（`Tools`） |
| `status` / `backup` / `automation` | 导入应用不含这三个字段 |
| `sha256` | One、INSAV、WQGuard 不提供校验值，对应版本缺该字段 |
| 下载地址 | 未做存活性探测，取上游 `status` 字段 |

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

`feed.json` 的内容构成：

| 项 | 状态 |
| --- | --- |
| `.ipa` 文件 | 不托管、不镜像、不重新签名；`downloadURL` 指向上游 GitHub Release |
| 图标 | 以 URL 引用上游仓库文件 |
| 应用名称、简介、截图 | 著作权归各应用作者 |
| 合并操作 | 字段结构转换、排序、去重 |

移除上游条目的方式：删除 `config/sync.json` 中对应 `sources` 元素，或将该应用的 bundleIdentifier 加入 `merge.excludeBundleIds`，下一次运行生效。

## 参考

"bebound/AltGallery: Curated AltStore Sources for IPA Projects on GitHub." *GitHub*, https://github.com/bebound/AltGallery. Accessed 13 Nov. 2026.

"Kianuni/WQGuard." *GitHub*, https://github.com/Kianuni/WQGuard. Accessed 13 Nov. 2026.

"Sami-Wali/ryP0: ryP0 Is a Modern iOS App Library for Discovering, Downloading, and Managing IPA Files." *GitHub*, https://github.com/Sami-Wali/ryP0. Accessed 13 Nov. 2026.

*AltGallery all-apps.json*, https://raw.githubusercontent.com/bebound/AltGallery/refs/heads/master/all-apps.json. Accessed 13 Nov. 2026.

*Insav-releases altsource.json*, https://raw.githubusercontent.com/ios151/Insav-releases/main/altsource.json. Accessed 13 Nov. 2026.

*One-releases altsource.json*, https://raw.githubusercontent.com/ios151/One-releases/main/altsource.json. Accessed 13 Nov. 2026.

*ryP0 repo.json*, https://raw.githubusercontent.com/Sami-Wali/ryP0-repository/main/repo.json. Accessed 13 Nov. 2026.
