# appsource-sync

把多个 AltStore 源定期合并成一份统一源，输出严格遵循 ryP0 的字段结构与元数据规范，由 GitHub Actions 定时执行并自动提交。

## 上游源

按 `config/sync.json` 中 `sources` 数组的顺序合并，**数组第一个是主源（格式基准与冲突优先方）**，后面依次为补充源：

| 顺序 | 名称 | 地址 | 实测快照（2026-11-12） |
| --- | --- | --- | --- |
| 1（主源） | `ryp0` | `https://raw.githubusercontent.com/Sami-Wali/ryP0-repository/main/repo.json` | 182 个应用 / 2376 个版本 |
| 2 | `altgallery` | `https://raw.githubusercontent.com/bebound/AltGallery/refs/heads/master/all-apps.json` | 66 个应用 / 67 个版本 |
| 3 | `one` | `https://raw.githubusercontent.com/ios151/One-releases/main/altsource.json` | 1 个应用 / 18 个版本 |
| 4 | `insav` | `https://raw.githubusercontent.com/ios151/Insav-releases/main/altsource.json` | 1 个应用 / 5 个版本 |
| 5 | `wqguard` | `https://github.com/Kianuni/WQGuard`（无源文件，由 releases 生成） | 1 个应用 / 1 个版本（v1.2.1） |

### 怎么再加一个源

编辑 `config/sync.json` 的 `sources` 数组追加一项即可，不需要改代码：

```json
{ "name": "mySource", "url": "https://example.com/apps.json", "schema": "altstore", "required": false }
```

`name` 会用作日志标识、错误信息里的来源标记和缓存文件名，**不要重名**。`required: true` 表示该源拉取失败时整次同步中止；否则只降级跳过并标记 `degraded`。

两种源类型：

| `type` | 含义 | 必填字段 |
| --- | --- | --- |
| 省略或 `altstore-json` | 直接抓取一个 AltStore 源 JSON（顶层有 `apps`） | `url` |
| `github-releases` | 仓库只发 `.ipa`、没有源文件时，用 GitHub API 读 releases 现场生成条目 | `repo`（`owner/name`）、`bundleIdentifier`、`appName` |

`github-releases` 的注意事项：

- **`bundleIdentifier` 必须手填**，脚本无法从 release 元数据可靠推断。本项目里 `com.wqguard.app` 是从仓库 `project.pbxproj` 的 `PRODUCT_BUNDLE_IDENTIFIER` 读出来的，不是猜的。
- 只取非 draft、非 prerelease 的 release（`excludePrerelease` 可关），并在资产名里按 `assetPattern`（默认 `\.ipa$`）匹配安装包。
- 版本号取 tag 并去掉 `v` 前缀，日期取 `published_at`，大小取资产 `size`。
- 走 GitHub API，CI 里用 `GITHUB_TOKEN`（5000 次/小时）；本地无 token 时是 60 次/小时。

## 两个源的真实结构差异

这是脚本里每一处转换逻辑的依据，全部来自实测而非推测：

| 维度 | ryP0 | AltGallery |
| --- | --- | --- |
| 顶层字段 | `name` `identifier` `iconURL` `sourceURL` `categories` `apps` `news` | `name` `subtitle` `description` `iconURL` `website` `tintColor` `apps` `news` |
| 应用标识 | `bundleIdentifier` + `catalogID`（`project-` + 32 位十六进制） | 只有 `bundleIdentifier`，无 `catalogID` |
| 分类 | 有 `category` 字段 + 顶层 `categories` 白名单 | 完全没有分类信息 |
| 版本对象 | `version` `date` `downloadURL` `size` `buildVersion` `releaseChannel` `sha256` `ipaBundleIdentifier` `upstreamAssetURL` 等 | `version` `date` `downloadURL` `size` `minOSVersion` `localizedDescription` `buildVersion` |
| 日期格式 | 2370/2376 为 `2026-11-10T04:44:50Z`，另有 5 条 `2026-11-05`、1 条带时区偏移 | 67/67 全部是 `2026-10-16`（无时间） |
| 图标/截图 | 只有 `iconURL`，无截图字段 | `iconURL` + `screenshots`（纯 URL 字符串数组） |
| 更新策略 | `updatePolicy`（`daily`/`static`）、`appType`（`Daily Update`/`Static`） | 无 |
| 健康检查 | `status`（`state`/`checkedAt`/`message`）、`backup`、`automation`、`importSource` | 无 |
| 公告 | `news` 为空数组 | 67 条带 `appID` 的公告 |

实测重合度：两个源有 **32 个相同 bundleIdentifier**，合并时必然产生冲突，需要明确仲裁规则。

## 合并规则

| 场景 | 处理方式 |
| --- | --- |
| 应用 ID 相同（`onBundleIdConflict: "keep-all"`，当前默认） | **全部保留为独立条目**，不合并、不丢弃；日志会逐条记录，报告里统计重复组数 |
| 应用 ID 相同（`onBundleIdConflict: "merge"`） | 以**配置顺序最靠前**的源为骨架；后续源只补全已有应用的**空字段**（`developerName`/`subtitle`/`localizedDescription`/`iconURL`/`tintColor`） |
| 同字段两边都有值且不同 | **保留排在前面的源的值**，差异写入 `logs/*.json` 的 `conflicts.metadata` |
| 同版本号但 `downloadURL`/`size` 不同 | **保留排在前面的源**，写入 `conflicts.versions`，附双方地址与来源名 |
| 版本互补（后续源有前面没有的版本） | 合并进同一应用，按 `date` 倒序排列 |
| 后续源独有应用 | 转成 ryP0 结构：生成 `catalogID`、`updatePolicy=static`、`appType=Static` |
| 分类判定（导入应用） | 顺序为：`categoryOverrides`（按 bundleId 精确指定）→ 上游自带 `category` 经 `categoryAliases` 归一（如 `entertainment` → `Movies`）→ 关键词推断 → 默认 `Tools`。每一步都写日志 |
| 上游 `nsfw: true` | 透传到应用级 `nsfw` 字段，避免把成人内容标成安全（实测 `insav` 源为 true） |
| 上游 `appPermissions` | 原样透传 `entitlements` / `privacy` |
| 应用内重复版本 | 去重（AltStore 会拒绝重复版本；ryP0 上游实测有 136 条重复） |
| 版本数组为空 | 移除该应用（ryP0 上游实测有 13 个，AltStore 无法安装无版本应用） |
| `date` 非 ISO 8601 | 归一为 `YYYY-MM-DDTHH:MM:SSZ`；无法归一则该版本不进入输出 |
| 副源 `screenshots` | 默认丢弃（纯 URL 数组与 AltStore 的 `{imageURL,size}` 结构不同，兼容性未经验证），可用 `keepScreenshots` 打开 |
| 后续源 `news` | 默认不带入（AltGallery 有 67 条逐应用公告会挤满客户端首页），可用 `carryNewsFrom` 指定要携带的源 |
| 主源内部 ID 重复 | 合并版本并告警（实测 5 个 ID，如 `com.kdt.livecontainer`） |

## 目录结构

```
appsource-sync/
├── .github/workflows/sync-sources.yml   # 定时 + 手动工作流
├── config/sync.json                     # 上游地址、合并开关、阈值
├── scripts/merge_sources.py             # 拉取 + 规范化 + 合并 + 落盘
├── scripts/validate_feed.py             # 独立的输出校验器
├── tests/test_merge.py                  # 21 组离线回归测试
├── feed.json                            # 产物（提交进仓库）
├── logs/                                # 每次运行的 .log 与 .json（artifact）
└── state/                               # last_run.json / history.jsonl / cache/
```

## 触发方式

| 方式 | 说明 |
| --- | --- |
| 定时 | `cron: "17 */6 * * *"`，**UTC**，每 6 小时一次：UTC 00:17 / 06:17 / 12:17 / 18:17，即北京时间 08:17 / 14:17 / 20:17 / 次日 02:17 |
| 手动 | Actions 页面 → `Sync app sources` → `Run workflow`，可覆盖：`dry_run`（只跑不提交）、`strict_validate`（警告也失败）、`ryp0_url`、`altgallery_url`、`set_sources`（通用覆盖，格式 `name=url`，多个逗号分隔）、`skip_secondary`（只用主源） |

工作流带 `concurrency: sync-app-sources`，同一时刻只跑一个实例，避免两次提交互相覆盖。

## 异常处置

脚本用退出码区分故障类型，工作流据此决定"是否更新 feed"：

| 退出码 | 含义 | 行为 |
| --- | --- | --- |
| 0 | 成功（含副源降级） | 校验 → 提交 |
| 2 | 主源拉取失败且无缓存 | 不写 `feed.json`，保留上一版，任务标记失败 |
| 3 | 源格式不符合预期 | 不写文件，任务失败 |
| 4 | 合并结果触发安全阈值 | 不写文件，任务失败（防上游异常导致源被清空） |
| 5 | 写盘失败 | 任务失败 |

其他保护措施：

- **网络重试**：默认 4 次、指数退避（2s 起，上限 30s），仅对超时/429/5xx 重试，404 立即放弃。
- **缓存兜底**：`state/cache/` 由 Actions cache 持久化，主源彻底不可达时可沿用上一份，避免源中断。
- **安全阈值**：`minAppsAbsolute`、`minPrimaryAppRatio`（主源有效率 ≥80%）、`minTotalAppRatio`（合并后不少于主源的 90%）任一不满足即拒绝发布。
- **发布前校验**：`validate_feed.py` 独立检查必填字段、ID 唯一性、日期格式、`size` 正整数、版本内重复、分类白名单；校验不过不提交。
- **原子写入**：先写 `.tmp` 再 `os.replace`，避免半截文件被提交。
- **推送冲突**：`git push` 失败时自动 `pull --rebase` 重试，最多 3 次。

## 日志与追踪

| 位置 | 内容 | 保留 |
| --- | --- | --- |
| Actions 运行摘要 | 应用/版本数、上游状态、清理动作、版本冲突表 | 永久（随 run） |
| `logs/sync-<时间戳>.log` | 逐行 UTC 日志，含每次冲突与改写 | artifact 30 天 |
| `logs/sync-<时间戳>.json` | 结构化报告（计数、冲突明细、丢弃清单） | artifact 30 天 |
| `state/last_run.json` | 最近一次运行快照（含 feed 的 sha256） | 随仓库提交 |
| `state/history.jsonl` | 每次运行的追加历史（最多 200 行） | 随仓库提交 |
| git 提交信息 | 本次变更的应用/版本/冲突数量 | 永久 |

## 本地运行

```bash
python3 tests/test_merge.py                                  # 13 组回归测试，无需网络
python3 scripts/merge_sources.py --config config/sync.json \
    --source-url https://raw.githubusercontent.com/OWNER/REPO/main/feed.json
# 临时替换某个源（不改进 config）：
python3 scripts/merge_sources.py --config config/sync.json --set one=https://example.com/apps.json
python3 scripts/validate_feed.py --feed feed.json
```

只依赖 Python 3.10+ 标准库，CI 不需要 `pip install`。

## 接入自己的仓库

1. 把本目录内容推到仓库根目录（`feed.json` 可先不提交）。
2. Settings → Actions → General → Workflow permissions 选 **Read and write**。
3. 手动跑一次 `Sync app sources`，勾选 `dry_run` 先看产物与摘要。
4. 确认无误后取消 `dry_run`，`feed.json` 会被自动提交，订阅地址为：
   `https://raw.githubusercontent.com/<owner>/<repo>/main/feed.json`

想用 GitHub Pages 发布：Settings → Pages → Source 选 `Deploy from a branch`、分支 `main`、目录 `/ (root)`，之后订阅 `https://<owner>.github.io/<repo>/feed.json`（这个地址还需要同步改 `config/sync.json` 的 `merge.sourceUrl`，否则 feed 里声明的 `sourceURL` 与真实地址不一致）。

## 已知限制

- **GitHub 定时任务不精确**：`schedule` 按 UTC 计算，高负载时可能延迟数十分钟甚至跳过某次。另外公开仓库连续 60 天无提交活动会被自动停用定时任务；由于本项目只在 `feed.json` 变化时才提交，若上游恰好长期无更新，也可能触发这条限制，届时在 Actions 页面手动 Run 一次即可恢复。
- **定时任务只在默认分支上生效**：`main` 上的工作流文件才会被调度，其他分支的改动不影响触发。
- **`screenshots` 兼容性未验证**：默认丢弃是为了避免结构不一致导致客户端解析失败，本项目没有在真机 AltStore/SideStore 上验证过保留后的表现。
- **导入应用的分类是推断值**：关键词命中不了就落到 `Tools`，建议在 `config/sync.json` 的 `categoryOverrides` 里固化。
- **导入应用不带 `status`/`backup`/`automation`**：这些字段依赖 ryP0 自己的自动化流水线，本仓库无法诚实生成，故留空而非伪造。
- **`keep-all` 会产生重复 bundleIdentifier**：实测当前五个源合并后有 35 组、共 39 条重复。AltStore / SideStore 以 bundleIdentifier 作为应用身份，同一 ID 出现多次时客户端可能只显示其中一条，或让"更新"指向错误的下载地址。本项目未在真机验证过这种源的订阅与更新行为；若出现异常，把 `merge.onBundleIdConflict` 改成 `"merge"` 即回到「合并版本」的旧行为。
- **部分源没有 `sha256`**：One 与 INSAV 的源不提供校验值，合并后这两个应用的所有版本都缺 `sha256`，校验器会给出警告但不阻断发布。
- **未对 IPA 下载地址做存活性探测**：每次 HEAD 数百个链接会显著拖慢任务，目前依赖上游 `status` 字段。

## 参考

"bebound/AltGallery: Curated AltStore Sources for IPA Projects on GitHub." *GitHub*, https://github.com/bebound/AltGallery. Accessed 12 Nov. 2026.

"Sami-Wali/ryP0: ryP0 Is a Modern iOS App Library for Discovering, Downloading, and Managing IPA Files." *GitHub*, https://github.com/Sami-Wali/ryP0. Accessed 12 Nov. 2026.

*AltGallery all-apps.json*, https://raw.githubusercontent.com/bebound/AltGallery/refs/heads/master/all-apps.json. Accessed 12 Nov. 2026.

*ryP0 repo.json*, https://raw.githubusercontent.com/Sami-Wali/ryP0-repository/main/repo.json. Accessed 12 Nov. 2026.
