---
name: wechat-mp-publish
description: 把 Markdown 文章一键上传为微信公众号草稿或直接发布（官方接口）。当用户要发布公众号文章、把 md 转成公众号排版、上传草稿、发布已存草稿时使用。触发词：发布公众号、上传草稿、md 转公众号、公众号排版、发布文章。
agent_created: true
---

# 微信公众号 Markdown → 草稿 / 发布

配套脚本：本 skill 目录下的 `scripts/wechat_pub.py`（详细文档见仓库 README）。

## 适用条件
- 公众号**已认证**，有 AppID/AppSecret（mp.weixin.qq.com → 设置与开发 → 基本配置）
- 个人未认证订阅号没有接口权限（会报 48001），此流程不可用，需改用浏览器自动化

## 凭据配置
复制 `.env.example` 为 `.env`，填 `WECHAT_APPID` / `WECHAT_APPSECRET`。
查找顺序：`--env-file` → `$WECHAT_PUBLISHER_ENV` → `./.env` → `$WECHAT_ARTICLE_DIR/.env` → skill 目录 `.env`。

## 核心命令
```bash
PY=<python>   # 需装好 requests / markdown / python-dotenv
SK=<skill_dir>/scripts/wechat_pub.py

"$PY" "$SK" 文章.md --dry-run                 # 1) 本地预览排版 → preview.html
"$PY" "$SK" 文章.md                           # 2) 上传草稿（人工把关，推荐默认）
"$PY" "$SK" 文章.md --publish                 # 3) 上传草稿并立即发布
"$PY" "$SK" --publish-existing <media_id>     # 4) 发布已有草稿
"$PY" "$SK" --show-ip                         # 5) 查当前出口 IP（填白名单用）
```
可选覆盖参数：`--title / --author / --digest / --cover`

## 标准作业流程
1. **排版预览**：先跑 `--dry-run`，把 `preview.html` 用 present_files 打开给用户看。
2. **封面**：必须有封面，否则脚本直接退出。流程：
   - 优先沿用**该账号历史封面**做风格参考（img2img）以保持视觉统一；
     **生成前先告知用户会消耗额度**
   - AI 生图常带角标水印，用 Pillow 中心裁切到 **2.35:1（推荐 1080×460）** 去掉
   - 存成文章同目录的 `cover.jpg`，frontmatter 写 `cover: cover.jpg`
   - 用户已有实拍/设计图时直接用，不要画蛇添足
3. **上传**：默认只建草稿，让用户到后台预览后手动点发布；用户明确要求全自动时才加 `--publish`。
4. **记录**：建草稿后会写 `<文章名>.draft.json`（media_id/title/时间），便于后续发布或追溯。

## 文章 .md 规范
```markdown
---
title: 标题              # 缺省取正文第一个 # 标题，再缺省用文件名
author: 署名             # 可留空
digest: 摘要             # 缺省自动截正文前 54 字
cover: cover.jpg        # 缺省取正文第一张本地图
---

正文……
```
- 本地配图 `![图注](图片.png)` 自动上传微信素材库并换成 https URL，图注渲染为小字说明
- 单独一行的 `---` 渲染成居中的「· · ·」分隔符，用于给长文分块、制造呼吸感
- 正文中的一级标题会被移除（公众号标题栏已有标题）

## 排版风格（脚本内 S_* 常量，改这里即可调）
默认治愈系：暖棕灰 #4a4036 衬线正文 15.5px / line-height 2.05 / 字距 0.6px；
居中 h2（#8a6d4f，字距 3px）；米金 blockquote（#faf6ef 底 + #d8c3a5 左边框）；
加粗 #a5714a；图片圆角 8px；段落 `margin:1.6em 0` 保持一两句一段的轻盈感。

## 发布接口说明
- 草稿：`POST /cgi-bin/draft/add`
- 发布：`POST /cgi-bin/freepublish/submit` → 轮询 `/cgi-bin/freepublish/get`
  （publish_status: 0 成功 / 1 发布中 / 2 原创校验 / 3 待审核 / 4 审核失败 / 5 已删除 / 6 已发布）
- **发布接口有每日配额**，超限报 45009，次日重置
- `freepublish` 是「发布到主页」不推送粉丝；要推送需走群发接口（本 skill 未含）

## 常见问题
| 报错 | 原因 / 处理 |
|---|---|
| 40164 invalid ip | 公网 IP 不在白名单。脚本会自动提取 IP 并提示；填 设置与开发→基本配置→IP白名单 |
| 40013 / 40125 | AppID 或 AppSecret 错，检查 .env |
| 48001 | 账号无接口权限（未认证订阅号） |
| 45009 | 发布次数配额用尽 |
| 40007 | media_id 无效/已被删除 |

### 动态 IP 环境
若用户网络出口是运营商动态 IP（手机热点、部分宽带），IP 会漂移、白名单需反复维护。
排查时 **以微信报错里的 IP 为准**（第三方查询服务可能因多出口/代理得到不同结果）；
`--show-ip` 会同时打印国内/境外两个出口以便判断是否受代理影响。
建议把 `api.weixin.qq.com`、`mp.weixin.qq.com` 在代理规则里设为直连。
长期方案：换到家庭宽带运行，或部署到有固定公网 IP 的服务器，白名单只需加一次。

## 排版注意事项（写稿时）
- 「让读者看起来不疲惫」是硬要求：短文尤其保持一两句一段，避免大段密排
- 标题要正扣文章核心主题，别拿次要细节当标题
- 结尾落点可加粗一句（该账号验证过的高转化写法），但不要通篇加粗
