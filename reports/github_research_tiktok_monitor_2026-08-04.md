# GitHub 调研记录：TikTok 账号数据监控

- 调研日期：2026-08-04（Asia/Kuala_Lumpur）
- 目标：寻找可直接部署或可复用的开源项目，用于监控 TikTok 账号的视频播放量、点赞量、评论量、分享量及历史变化。
- 调研方式：GitHub/网页关键词检索、GitHub REST API 仓库元数据核对、候选仓库 TikTok provider 与 analytics 源码抽查、TikTok 官方开发者文档交叉验证。

## 检索关键词

1. `TikTok analytics dashboard open source account video views likes comments`
2. `TikTok API analytics dashboard OAuth video metrics`
3. `TikTok developer API Python SDK video list views likes comments`
4. `open source social media analytics TikTok dashboard`
5. `Postiz TikTok analytics insights`
6. `BrightBean Studio TikTok insights OAuth`
7. `TryPost TikTok analytics OAuth`
8. `TikTok view_count video.list dashboard`

## 候选项目

仓库数据为调研时通过 GitHub REST API 获取的快照。

| 项目 | Stars / Forks | 最近推送 | 技术栈 / 许可 | TikTok 指标能力 | 结论 |
|---|---:|---|---|---|---|
| [gitroomhq/postiz-app](https://github.com/gitroomhq/postiz-app) | 34,235 / 6,412 | 2026-08-04 | TypeScript；AGPL-3.0 | 官方 OAuth；账号粉丝/关注/获赞/视频数；最近 20 条视频的播放/点赞/评论/分享汇总；单视频指标 | 成熟度最高、可直接自托管，但它是完整社媒发布平台，依赖 PostgreSQL、Temporal 等，明显重于单一监控需求。现有 TikTok analytics 返回当天快照，provider 内的百分比变化固定为 0，不等于分钟级历史监控。适合作为产品与异常处理参考。 |
| [brightbeanxyz/brightbean-studio](https://github.com/brightbeanxyz/brightbean-studio) | 2,093 / 425 | 2026-07-12 | Python/Django；AGPL-3.0 | 官方 `video.list` / `video.query`；单视频播放/点赞/评论/分享；统一分析快照与趋势页面 | 与本地 Python 项目最接近，也可直接部署；但仍是完整社媒管理平台，生产部署包含 Web、worker、PostgreSQL、Caddy 等。TikTok 账号级 follower 指标在其 provider 中明确关闭。适合作为 Python 架构和指标快照设计参考，不建议整仓并入。 |
| [trypostit/trypost](https://github.com/trypostit/trypost) | 464 / 113 | 2026-08-04 | PHP/Laravel/Vue；AGPL-3.0 | 账号粉丝/关注/总获赞/视频数；最近 20 条视频播放/点赞/评论/分享汇总 | 可自托管，但与本地 Python 技术栈不匹配；生产环境指标缓存 1 小时，前端明确不支持日期范围，不符合“实时趋势”目标。 |
| [tiktok/tiktok-business-api-sdk](https://github.com/tiktok/tiktok-business-api-sdk) | 213 / 74 | 2026-03-09 | 官方 Python/Java/JS SDK；MIT | TikTok for Business 广告、报表、Campaign 等 | 官方且许可友好，但面向广告/营销 API，不是普通 TikTok 账号公开视频指标看板，不能直接满足目标。若后续需要广告投放数据可单独接入。 |
| [davidteather/TikTok-Api](https://github.com/davidteather/TikTok-Api) | 6,537 / 1,209 | 2026-07-03 | Python；MIT | 可抓公开视频、评论和统计字段 | 非官方抓取方案，不支持用户授权路由；README 明确提示 TikTok 经常改变结构、可能识别并封禁请求，常需浏览器 cookie、Playwright 或代理。不应用于卖家主账号的稳定生产监控。 |
| [tiktok/tiktok-research-api-wrapper](https://github.com/tiktok/tiktok-research-api-wrapper) | 32 / 9 | 2024-12-04 | 官方示例；MIT | Research API 的视频、用户、评论查询 | 仅适合获批研究者及研究用途，不是商家自有账号运营监控方案。 |

## 源码核对摘要

### Postiz

- 请求 scopes：`video.list`、`user.info.basic`、`user.info.profile`、`user.info.stats`，另含发布 scopes。
- `/v2/user/info/` 获取 `follower_count`、`following_count`、`likes_count`、`video_count`。
- `/v2/video/list/` 只取最近 20 条，再通过 `/v2/video/query/` 汇总 `view_count`、`like_count`、`comment_count`、`share_count`。
- 单视频 analytics 也能返回上述四项。
- 当前 provider 返回单日数据且 `percentageChange` 固定为 0；要做趋势仍需独立定时快照与历史库。

### BrightBean Studio

- TikTok analytics 使用 `video.list` scope。
- 单视频通过 `/v2/video/query/` 获取播放、点赞、评论、分享，并由统一 analytics 服务保存快照、计算趋势。
- 该仓库对 TikTok 账号级 metrics 明确返回空值，因为没有请求 `user.info.stats`。
- 架构上最值得参考的是：OAuth provider、周期任务、原始快照、派生指标和趋势展示的分层。

### TryPost

- `/v2/user/info/` 获取账号统计。
- `/v2/video/list/` 只取最近 20 条，再用 `/v2/video/query/` 汇总视频统计。
- 生产环境缓存 TTL 为 3600 秒，Vue 组件声明 `supportsDateRange: false`。

## 与 TikTok 官方接口的交叉验证

- 自有账号公开视频列表和指标应使用 Display API：`video.list` scope，可查询 `view_count`、`like_count`、`comment_count`、`share_count`。
- `/v2/video/query/` 每次最多查询 20 个视频 ID。
- `/v2/user/info/` 的粉丝、关注、账号总获赞和公开视频数需要 `user.info.stats` scope。
- 官方默认速率限制中，`/v2/user/info/`、`/v2/video/list/`、`/v2/video/query/` 均为每分钟滑动窗口 600 次请求。
- 官方接口提供当前累计值，不会替应用保存每分钟/每天的历史变化；“实时趋势”必须由本地轮询并保存快照实现。

## 决策

1. **不整仓引入 Postiz、BrightBean 或 TryPost。** 它们可以直接部署，但都是完整社媒发布/协作平台，运维范围远超当前需求；三者均为 AGPL-3.0，直接复制代码还会带来许可证义务。
2. **参考 Postiz 的 scope、token 刷新和错误分类，参考 BrightBean 的 Python provider、快照与派生指标分层。** 只参考设计，不复制 AGPL 源码。
3. **生产数据链路坚持使用 TikTok 官方 Login Kit + Display API。** 不使用 `TikTok-Api` 抓取卖家主账号，避免 cookie、验证码、封禁和接口漂移风险。
4. **在现有 Python/FastAPI/Streamlit/SQLite 项目内实现轻量监控最合适。** 轮询间隔可配置（例如 5 分钟），保存每次累计值快照，再计算增量、互动率、异常涨跌和日报。
5. 若用户希望直接部署一整套多平台社媒系统并接受较重运维，首选 Postiz；若更看重 Python 和内置趋势体系，首选 BrightBean Studio。

## 主要来源

- https://github.com/gitroomhq/postiz-app
- https://github.com/brightbeanxyz/brightbean-studio
- https://github.com/trypost-it/trypost
- https://github.com/tiktok/tiktok-business-api-sdk
- https://github.com/davidteather/TikTok-Api
- https://github.com/tiktok/tiktok-research-api-wrapper
- https://developers.tiktok.com/doc/tiktok-api-v2-video-query/
- https://developers.tiktok.com/doc/tiktok-api-v2-get-user-info/
- https://developers.tiktok.com/doc/tiktok-api-v2-rate-limit/
