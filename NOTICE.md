# NOTICE

本文件说明许可范围与第三方内容归属，与 `LICENSE`（MIT）配合阅读。

## 许可范围

`LICENSE` 中的 MIT 许可覆盖本仓库的**代码与文档**，包括：

- `scripts/merge_sources.py`、`scripts/validate_feed.py`
- `tests/test_merge.py`
- `.github/workflows/sync-sources.yml`
- `config/sync.json`、`README.md`

## 不在 MIT 覆盖范围内的内容

`feed.json` 是对第三方 AltStore 源的**元数据聚合产物**，不属于本项目的原创作品：

- 其中收录的应用名称、简介、副标题、图标、截图、版本说明，著作权归各应用作者所有。
- 所有 `downloadURL` 都指向上游 GitHub Release 的原始地址。本仓库不托管、不镜像、不重新签名任何 `.ipa` 文件。
- 图标以 URL 形式引用上游仓库内的文件，未被复制进本仓库。
- 合并过程只做字段结构转换、排序与去重，不改写应用内容，也不改变下载资产本身。

## 上游来源与许可

| 上游仓库 | 许可 | 本项目使用方式 |
| --- | --- | --- |
| https://github.com/bebound/AltGallery | MIT | 读取 `all-apps.json`，合并其应用条目 |
| https://github.com/Kianuni/WQGuard | MIT | 经 GitHub API 读取 release 元数据，生成应用条目 |
| https://github.com/Sami-Wali/ryP0-repository | 未声明（保留所有权利） | 读取 `repo.json`，作为格式基准与主源 |
| https://github.com/Sami-Wali/ryP0 | 未声明（保留所有权利） | 仅参考其源格式与字段语义，未复制代码 |
| https://github.com/ios151/One-releases | 未声明（保留所有权利） | 读取 `altsource.json`，合并其应用条目 |
| https://github.com/ios151/Insav-releases | 未声明（保留所有权利） | 读取 `altsource.json`，合并其应用条目 |

许可证字段取自 GitHub API 的 `license` 元数据；「未声明」指仓库中无 LICENSE 文件且 GitHub 未识别出许可证。

## 异议处理

任一上游作者如不希望其条目出现在本聚合源中，删除 `config/sync.json` 里对应的 `sources` 条目即可，下一次工作流运行会把相关应用从 `feed.json` 中移除。也可用 `merge.excludeBundleIds` 单独排除指定应用。

## 商标与免责

各应用名称、图标与商标归其各自所有者。本项目与 Apple、AltStore、SideStore 及上述任何上游项目均无隶属关系。侧载未签名 IPA 需自行承担签名与合规责任，请遵守当地法律与 Apple 开发者协议。
