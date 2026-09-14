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
PY=<python>   # 需装好 requests / markdown / python-dotenv；封面修补另需 Pillow + numpy
SK=<skill_dir>/scripts/wechat_pub.py

"$PY" "$SK" 文章.md --dry-run                 # 1) 本地预览排版 → preview.html
"$PY" "$SK" 文章.md                           # 2) 上传草稿（人工把关，推荐默认）
"$PY" "$SK" 文章.md --publish                 # 3) 上传草稿并立即发布
"$PY" "$SK" --publish-existing <media_id>     # 4) 发布已有草稿
"$PY" "$SK" --show-ip                         # 5) 查【微信实际看到的】出口 IP（填白名单用）
```
可选覆盖参数：`--title / --author / --digest / --cover`

## 标准作业流程
1. **排版预览**：先跑 `--dry-run`，把 `preview.html` 用 present_files 打开给用户看。
2. **封面**：必须有封面，否则脚本直接退出。流程：
   - 优先沿用**该账号历史封面**做风格参考（img2img）以保持视觉统一；
     **生成前先告知用户会消耗额度**
   - img2img 的 `input_fidelity` 用 **`low`**。用 `medium`/`high` 会把参考图里的
     沙发、电视等场景元素原样搬过来，封面和上一期撞脸；新场景要写足，并显式写反向约束
     （`no sofa, no television, no text`）
   - **生成后先肉眼确认构图贴题，再裁切**——不要跳过这一步，否则白裁一版
   - AI 生图常带角标水印，用 Pillow 中心裁切到 **2.35:1（推荐 1080×460）** 去掉。
     ⚠️ 水印若在画面纵向 60% 左右，中心裁切**裁不掉**，需要修补（见下方「水印修补」）
   - 存成文章同目录的 `cover.jpg`，frontmatter 写 `cover: cover.jpg`
   - 用户已有实拍/设计图时直接用，不要画蛇添足

### 水印修补（裁切后仍残留时）
拿**垂直方向**（同宽、紧邻上方区域垂直翻转）覆盖，**不要用水平镜像取样**——
背景墙/桌面通常有水平光渐变，水平取样会留下一块肉眼可见的偏亮矩形。
覆盖后必须对补丁的**上、下、左三边做 alpha 羽化**（约 12px），否则接缝仍在。

```python
import numpy as np                      # venv 里需 pip install numpy
from PIL import Image
im = Image.open(src).convert("RGB")
a = np.asarray(im).astype(np.float32)
x0, y0, x1, y1 = 956, 292, 1080, 368    # 水印框，四周各留几像素余量
ph, pw = y1 - y0, x1 - x0
patch = a[y0 - ph:y0, x0:x1][::-1]      # 上方同尺寸区域，垂直翻转
alpha = np.ones((ph, pw), np.float32); f = 12
alpha[:f, :] *= np.linspace(0, 1, f)[:, None]
alpha[-f:, :] *= np.linspace(1, 0, f)[:, None]
alpha[:, :f] *= np.linspace(1, 0, f)[None, :]
t = a[y0:y1, x0:x1]
a[y0:y1, x0:x1] = t * (1 - alpha[..., None]) + patch * alpha[..., None]
Image.fromarray(a.round().clip(0, 255).astype(np.uint8)).save("cover.jpg", quality=93)
```
修完把局部放大 2 倍另存一张 `.png` 自检，边界看不见了再上传。
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
| 40164 invalid ip | 公网 IP 不在白名单。**用 `--show-ip` 拿微信实际看到的 IP**（别用第三方站点查的），填 设置与开发→基本配置→IP白名单；建议填 `/24` 网段，见下节 |
| 40013 / 40125 | AppID 或 AppSecret 错，检查 .env |
| 48001 | 账号无接口权限（未认证订阅号） |
| 45009 | 发布次数配额用尽 |
| 40007 | media_id 无效/已被删除 |

### 动态 IP 环境（踩过的坑，2026-09-14 补齐）

现象：`40164 invalid ip`，报错里的 IP 每次都不一样。

**第一条铁律：只有微信自己报出来的 IP 才是要填的那个。**
第三方 ip-echo 站点（4.ipw.cn / ip.3322.net / myip.ipip.net）走的是**另一条运营商出口**，
实测同一时刻站点报 `223.104.72.153`、微信却看到 `223.104.88.149`。
拿站点查到的 IP 去填白名单，永远对不上 —— 这是之前反复失败的真正原因。

所以 `--show-ip` 已改为**先向 token 接口探明微信实际看到的 IP**，并直接给出可填条目：

```
"$PY" "$SK" --show-ip
  ▶ 微信实际看到: 223.104.88.149
  请加入：223.104.88.149  /  223.104.88.0/24
```

**第二条：填网段，别填单 IP。**
公众号 API IP 白名单**支持 CIDR**（官方文档示例 `172.0.0.1/24`；
不支持 `172.0.0.*` 星号写法）。移动/宽带 CGNAT 会在同段内漂移，
填 `/24` 一次覆盖；仍漂移就用 `/16`。

其他要点：
- 白名单**修改后需数分钟生效**，改完立刻报错不一定是没填对
- 建议把 `api.weixin.qq.com`、`mp.weixin.qq.com` 在代理规则里设为**直连**
  （分流模式下境外出口是 VPN IP，有风控风险）
- 长期方案：换家庭宽带运行，或部署到有固定公网 IP 的服务器，白名单只需加一次
- 想快速对号时，直接解析 token 报错里的 `invalid ip` 字段即可：
  `curl "https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid=X&secret=Y"`

## 排版注意事项（写稿时）
- 「让读者看起来不疲惫」是硬要求：短文尤其保持一两句一段，避免大段密排
- 标题要正扣文章核心主题，别拿次要细节当标题
- 结尾落点可加粗一句（该账号验证过的高转化写法），但不要通篇加粗
