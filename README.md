# wechat-mp-publish

把 Markdown 文章一键上传到微信公众号**草稿箱**或**直接发布**——走微信官方接口，不模拟点击，稳定合规。

同时它也是一个 [WorkBuddy](https://www.workbuddy.cn/docs/workbuddy/Overview) / Claude Code 风格的 **Skill**：安装后直接对 AI 说「把这篇文章发到公众号」，它会自动完成排版、封面上传、创建草稿的全流程。

```
文章.md ──► 解析 frontmatter ──► 上传正文图片到素材库
                                      │
                                      ▼
                          Markdown → 内联样式 HTML
                                      │
                                      ▼
              ┌───────────── 上传封面（永久素材）─────────────┐
              ▼                                              ▼
        draft/add 建草稿  ──► 你到后台预览后手动发布
              │
              └─► --publish 直接调用 freepublish/submit 发布
```

## 特性

- **Markdown → 公众号排版**：逐标签写入内联样式，微信编辑器不会丢样式
- **图片全自动**：正文里的本地图片自动上传到微信素材库并替换为 https URL；封面自动上传为永久素材
- **草稿 / 发布两档**：默认只建草稿（保留人工把关），加 `--publish` 才真正发出去
- **本地预览**：`--dry-run` 生成一个 HTML 预览，排版满意了再上传
- **诊断友好**：常见报错（IP 白名单、凭据错误、权限不足、配额用尽）都翻译成中文并给出解决步骤
- **零多余依赖**：requests + markdown + python-dotenv

## 环境要求

- 微信公众号**已认证**，并在 [设置与开发 → 基本配置](https://mp.weixin.qq.com) 拿到 **AppID / AppSecret**
- Python 3.9+

> 个人未认证订阅号**没有**调用这些接口的权限（会报 `48001`），本工具无法使用。

## 安装

```bash
git clone git@github.com:<你的用户名>/wechat-mp-publish.git
cd wechat-mp-publish
pip install -r requirements.txt
```

作为 WorkBuddy / Claude Skill 使用时，把本仓库放进技能目录即可：

```bash
git clone git@github.com:<你的用户名>/wechat-mp-publish.git \
  ~/.workbuddy/skills/wechat-mp-publish
```

## 配置

复制并填入凭据：

```bash
cp .env.example .env
```

```ini
WECHAT_APPID=wx0123456789abcdef
WECHAT_APPSECRET=0123456789abcdef0123456789abcdef
```

`.env` 的查找顺序（找到第一个即用）：

1. `--env-file` 指定的路径
2. 环境变量 `WECHAT_PUBLISHER_ENV` 指向的文件
3. 当前工作目录 `./.env`
4. 环境变量 `WECHAT_ARTICLE_DIR` 指向目录下的 `.env`
5. 脚本所在目录 `.env`

## 使用

```bash
# 1) 本地预览排版（不调用任何接口）
python scripts/wechat_pub.py 文章.md --dry-run

# 2) 上传到草稿箱（推荐，去后台预览后手动发布）
python scripts/wechat_pub.py 文章.md

# 3) 上传并立即发布
python scripts/wechat_pub.py 文章.md --publish

# 4) 发布一个已存在的草稿
python scripts/wechat_pub.py --publish-existing <media_id>

# 5) 查当前公网 IP（填白名单用）
python scripts/wechat_pub.py --show-ip
```

可用参数：`--title / --author / --digest / --cover` 分别覆盖标题、署名、摘要、封面。

## 文章格式

```markdown
---
title: 标题            # 缺省取正文第一个 # 标题，再缺省用文件名
author: 署名           # 可留空
digest: 摘要           # 缺省自动截取正文前 54 字
cover: cover.jpg      # 封面图，缺省取正文第一张本地图
---

正文段落……

![图注](images/photo.jpg)

---

## 小标题

> 引用
```

- 本地图片会自动上传并替换链接，图注渲染成小字说明
- 单独一行的 `---` 会渲染成居中分隔符 `· · ·`，适合给长文分块
- 正文中的一级标题会被移除（公众号标题栏已有标题）

## 排版风格

内置一套偏「治愈系」的排版：暖棕灰宋体正文、大行距、居中标题、米金色引用块。样式集中在脚本顶部的 `S_*` 常量里，改几行就能换成你自己的风格：

| 常量 | 作用 |
|---|---|
| `S_BODY` | 正文字体 / 字号 / 颜色 / 行距 |
| `S_H2` `S_H3` | 小标题 |
| `S_QUOTE_WRAP` `S_QUOTE_P` | 引用块 |
| `S_STRONG` `S_EM` | 加粗 / 斜体 |
| `S_IMG` `S_FIGCAPTION` | 图片与图注 |
| `DIVIDER` | `---` 对应的分隔符 |

## 常见问题

| 报错 | 原因与解决 |
|---|---|
| `40164 invalid ip` | 调用方公网 IP 不在白名单。到 设置与开发 → 基本配置 → IP白名单 添加报错里出现的 IP（脚本会直接提示是哪个） |
| `40013` / `40125` | AppID 或 AppSecret 不正确 |
| `48001` | 账号无接口权限（个人未认证订阅号） |
| `45009` | 接口调用次数达到上限，次日重置 |
| `40007` | media_id 无效或素材已删除 |

**关于 IP 白名单**：如果所在网络是动态 IP（手机热点、部分宽带），IP 会漂移，需要反复更新白名单。
需要长期稳定的话，把脚本部署到有固定公网 IP 的服务器上运行。

## 说明

- 发布接口 `freepublish` 是「发布到公众号主页」，**不会推送消息给粉丝**；要推送需走群发接口，本工具未实现。
- 默认只创建草稿，避免误发。请自行确认内容后再决定是否使用 `--publish`。

## License

[MIT](LICENSE)
