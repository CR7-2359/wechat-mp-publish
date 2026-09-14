#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat_pub.py — Markdown 一键上传微信公众号（草稿 / 直接发布）

用法:
    python wechat_pub.py 文章.md                    # 上传到草稿箱（人工把关）
    python wechat_pub.py 文章.md --dry-run          # 只在本地生成 preview.html 预览排版
    python wechat_pub.py 文章.md --publish          # 上传草稿后立即发布（不再人工确认）
    python wechat_pub.py --publish-existing MEDIA_ID  # 发布一个已存在的草稿
    python wechat_pub.py 文章.md --author 某某       # 覆盖作者名

文章 .md 支持 frontmatter（可选）:
    ---
    title: 文章标题          # 缺省取正文第一个 # 标题
    author: 作者名
    digest: 摘要             # 缺省自动截取正文前 54 字
    cover: cover.jpg         # 封面图（本地路径，相对 md 文件），缺省取正文第一张图
    ---

凭据配置（.env，按以下顺序查找，找到第一个即用）:
    1) --env-file 指定的路径
    2) 环境变量 WECHAT_PUBLISHER_ENV 指定的路径
    3) 当前工作目录/.env
    4) 公众号工作区 wechat-publisher/.env
    5) 脚本同目录/.env
    内容:
        WECHAT_APPID=wx...
        WECHAT_APPSECRET=...
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import markdown
import requests
from dotenv import load_dotenv

BASE = "https://api.weixin.qq.com"
SCRIPT_DIR = Path(__file__).resolve().parent
# 兼容旧路径：真正的脚本在 <skill_dir>/scripts/wechat_pub.py
SKILL_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR


def find_env_file(cli_path=None):
    """按优先级查找 .env（找到第一个即用）"""
    cands = []
    if cli_path:
        cands.append(Path(cli_path).expanduser())
    if os.getenv("WECHAT_PUBLISHER_ENV"):
        cands.append(Path(os.getenv("WECHAT_PUBLISHER_ENV")).expanduser())
    cands.append(Path.cwd() / ".env")
    # 可用 WECHAT_ARTICLE_DIR 指定文章工作区（.env 放在那里）
    if os.getenv("WECHAT_ARTICLE_DIR"):
        cands.append(Path(os.getenv("WECHAT_ARTICLE_DIR")).expanduser() / ".env")
    cands.append(SKILL_DIR / ".env")
    for c in cands:
        if c.exists():
            return c
    return None


ENV_FILE = find_env_file()
if ENV_FILE:
    load_dotenv(ENV_FILE)
APPID = os.getenv("WECHAT_APPID", "").strip()
APPSECRET = os.getenv("WECHAT_APPSECRET", "").strip()

# 老版本遗留的 token 缓存文件
TOKEN_CACHE = SCRIPT_DIR / ".token_cache.json"

# ---------------------------------------------------------------- 排版样式
# 治愈系排版：暖棕灰文字、衬线感、大行距、克制留白
S_BODY = ("font-family:'Songti SC','STSong','SimSun',serif;"
          "font-size:15.5px;color:#4a4036;line-height:2.05;"
          "letter-spacing:0.6px;word-spacing:1px;")
S_P = "margin:1.6em 0;text-align:justify;"
S_H2 = ("margin:2.6em 0 1.4em;text-align:center;font-size:17px;"
        "font-weight:bold;color:#8a6d4f;letter-spacing:3px;")
S_H3 = ("margin:2.2em 0 1.2em;font-size:16px;font-weight:bold;"
        "color:#8a6d4f;letter-spacing:1.5px;")
S_QUOTE_WRAP = ("margin:1.8em 0;padding:0.2em 1.2em;"
                "border-left:3px solid #d8c3a5;background:#faf6ef;")
S_QUOTE_P = "margin:0.9em 0;color:#7a6a58;"
S_STRONG = "color:#a5714a;font-weight:bold;"
S_EM = "color:#7a6a58;font-style:italic;"
S_UL = "margin:1.6em 0;padding-left:1.4em;"
S_LI = "margin:0.5em 0;"
S_IMG_WRAP = "margin:1.8em 0;text-align:center;"
S_IMG = "max-width:100%;border-radius:8px;"
S_FIGCAPTION = ("margin-top:0.6em;font-size:12px;color:#a89880;"
                "letter-spacing:1px;")
DIVIDER = ('<section style="margin:2.2em 0;text-align:center;'
           'color:#c9b393;letter-spacing:8px;font-size:14px;">'
           '·&nbsp;·&nbsp;·</section>')


# ---------------------------------------------------------------- 微信 API
class WxError(RuntimeError):
    pass


def _check(resp: dict, what: str) -> dict:
    if "errcode" in resp and resp["errcode"] != 0:
        errcode = resp.get("errcode")
        errmsg = str(resp.get("errmsg", ""))
        msg = f"{what} 失败: errcode={errcode} errmsg={errmsg}"
        if errcode == 40164:
            m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", errmsg)
            ip = m.group(1) if m else "（见上方 errmsg）"
            msg += (f"\n\n👉 当前公网 IP [{ip}] 不在 IP 白名单里。\n"
                    "   解决: 登录 mp.weixin.qq.com → 设置与开发 → 基本配置 → "
                    "IP白名单 → 把上面这个 IP 加进去，保存后立刻生效。\n"
                    "   提示: 家庭宽带/手机的 IP 会变，换网络后可能需要在白名单里更新。")
        elif errcode in (40013, 40125):
            msg += "\n\n👉 AppID 或 AppSecret 不正确，请检查 .env 文件。"
        elif errcode == 48001:
            msg += "\n\n👉 该账号没有调用此接口的权限（个人未认证订阅号不支持）。"
        elif errcode == 45009:
            msg += "\n\n👉 接口调用次数已达上限（发布接口有配额），次日重置。"
        raise WxError(msg)
    return resp


def get_access_token(force: bool = False) -> str:
    if not APPID or not APPSECRET:
        sys.exit("错误: 请先在 .env 中配置 WECHAT_APPID 和 WECHAT_APPSECRET\n"
                 + ("      已找到的 .env: " + str(ENV_FILE) if ENV_FILE else
                    "      已查找的位置: --env-file / $WECHAT_PUBLISHER_ENV / "
                    f"{Path.cwd() / '.env'} / $WECHAT_ARTICLE_DIR/.env / "
                    f"{SKILL_DIR / '.env'}"))
    if not force and TOKEN_CACHE.exists():
        try:
            cache = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            if cache.get("expires_at", 0) - time.time() > 300:
                return cache["access_token"]
        except (json.JSONDecodeError, KeyError):
            pass
    resp = requests.get(f"{BASE}/cgi-bin/token", params={
        "grant_type": "client_credential",
        "appid": APPID,
        "secret": APPSECRET,
    }, timeout=15).json()
    _check(resp, "获取 access_token")
    TOKEN_CACHE.write_text(json.dumps({
        "access_token": resp["access_token"],
        "expires_at": time.time() + resp.get("expires_in", 7200),
    }), encoding="utf-8")
    return resp["access_token"]


def api(method: str, path: str, *, retry: bool = True, **kwargs) -> dict:
    """统一调用；token 过期自动刷新重试一次"""
    token = get_access_token()
    params = kwargs.pop("params", {})
    params["access_token"] = token
    resp = requests.request(method, f"{BASE}{path}",
                            params=params, timeout=30, **kwargs)
    data = resp.json()
    if retry and data.get("errcode") in (40001, 40014, 42001):
        get_access_token(force=True)
        return api(method, path, retry=False, **kwargs)
    return data


def upload_content_image(img_path: Path) -> str:
    """上传正文图片 → 返回可在 content 中使用的 https URL（不占素材库额度）"""
    with open(img_path, "rb") as f:
        data = api("POST", "/cgi-bin/media/uploadimg",
                   files={"media": (img_path.name, f)})
    _check(data, f"上传正文图片 {img_path.name}")
    return data["url"]


def upload_thumb(img_path: Path) -> str:
    """上传封面图 → 返回永久素材 media_id"""
    with open(img_path, "rb") as f:
        data = api("POST", "/cgi-bin/material/add_material",
                   params={"type": "thumb"},
                   files={"media": (img_path.name, f)})
    _check(data, f"上传封面 {img_path.name}")
    return data["media_id"]


# ------------------------------------------------------- 草稿 & 发布
def create_draft(article: dict) -> str:
    data = api("POST", "/cgi-bin/draft/add",
               data=json.dumps({"articles": [article]},
                               ensure_ascii=False).encode("utf-8"),
               headers={"Content-Type": "application/json"})
    _check(data, "创建草稿")
    return data["media_id"]


def publish(media_id: str, timeout_s: int = 60) -> dict:
    """发布草稿 → 轮询发布状态，返回发布结果"""
    data = api("POST", "/cgi-bin/freepublish/submit",
               data=json.dumps({"media_id": media_id}).encode("utf-8"),
               headers={"Content-Type": "application/json"})
    _check(data, "提交发布")
    publish_id = data.get("publish_id")
    if not publish_id:
        return data

    print(f"  已提交发布 (publish_id={publish_id})，等待微信处理...")
    deadline = time.time() + timeout_s
    STATUS = {0: "发布成功", 1: "正在发布", 2: "原创校验中",
              3: "等待审核", 4: "审核失败", 5: "已删除", 6: "已发布"}
    while time.time() < deadline:
        time.sleep(3)
        r = api("POST", "/cgi-bin/freepublish/get",
                data=json.dumps({"publish_id": publish_id}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
        if r.get("errcode") not in (None, 0):
            _check(r, "查询发布状态")
        status = r.get("publish_status")
        print(f"  状态: {STATUS.get(status, status)}")
        if status in (0, 6):
            return r
        if status in (4, 5):
            raise WxError(f"发布未成功: {STATUS.get(status, status)} "
                          f"(fail_idx={r.get('fail_idx')})")
    print("  ⚠️ 等待超时，微信可能仍在处理中，请到后台「发表记录」确认。")
    return {"publish_id": publish_id}


def draft_sidecar(md_file: Path) -> Path:
    return md_file.with_suffix(".draft.json")


def _ip_from(url: str) -> str:
    try:
        text = requests.get(url, timeout=10).text.strip()
    except requests.RequestException:
        return ""
    m = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", text)
    return m.group(1) if m else ""


def wechat_seen_ip(tries: int = 3) -> tuple[str, str]:
    """向微信 token 接口探明「微信实际看到的出口 IP」。

    返回 (ip, note)。token 已可取到时返回 ("", "已可用")。
    要点：ip-echo 站点与 api.weixin.qq.com 可能走不同的运营商出口，
    站点查到的 IP 不能用来填白名单 —— 只有这里拿到的才准。
    """
    seen = []
    for i in range(tries):
        try:
            r = requests.get(f"{BASE}/cgi-bin/token",
                             params={"grant_type": "client_credential",
                                     "appid": APPID, "secret": APPSECRET},
                             timeout=10)
            j = r.json()
        except requests.RequestException as e:
            return "", f"请求失败 {type(e).__name__}"
        if "access_token" in j:
            return "", "已可用"
        m = re.search(r"invalid ip ([0-9a-fA-F:.]+)", j.get("errmsg", ""))
        if not m:
            return "", f"errcode={j.get('errcode')} {j.get('errmsg', '')}"
        seen.append(m.group(1))
        if i + 1 < tries:
            time.sleep(0.5)
    uniq = sorted(set(seen))
    return (uniq[0] if len(uniq) == 1 else " / ".join(uniq)), ""


def _cidr_for(ip: str) -> list[str]:
    """给出建议填写的白名单条目。

    实测该网络（移动 CGNAT）的微信侧出口会跨 /24 漂移
    （223.104.72.x → 223.104.88.x → 223.104.80.x），
    所以 /24 往往不够，需要连同 /16 一起填。
    """
    out = [ip]
    parts = ip.split(".")
    if len(parts) == 4:
        out.append(".".join(parts[:3]) + ".0/24")
        out.append(".".join(parts[:2]) + ".0.0/16")
    return out


def wait_until_allowed(timeout: int, interval: int = 25) -> bool:
    """轮询 token 接口，直到当前出口 IP 进入白名单（或超时）。

    用途：用户在后台加完白名单后不必再手跑一次 —— 网段生效有几分钟延迟，
    这里自动等到生效就继续。探测用只读的 token 接口，不会产生任何草稿。
    """
    deadline = time.time() + timeout
    n = 0
    while True:
        n += 1
        try:
            j = requests.get(f"{BASE}/cgi-bin/token",
                             params={"grant_type": "client_credential",
                                     "appid": APPID, "secret": APPSECRET},
                             timeout=10).json()
        except requests.RequestException as e:
            j = {"errmsg": f"请求失败 {type(e).__name__}"}
        if "access_token" in j:
            print(f"  ✅ 第 {n} 次探测通过 —— 出口 IP 已在白名单内")
            return True
        m = re.search(r"invalid ip ([0-9a-fA-F:.]+)", j.get("errmsg", ""))
        cur = m.group(1) if m else j.get("errmsg", "未知错误")
        if time.time() >= deadline:
            print(f"  ⏱ 等待超时，最后看到的 IP 仍是 {cur}")
            return False
        print(f"  第 {n} 次：{cur} 未在白名单，{interval}s 后重试…", flush=True)
        time.sleep(min(interval, max(1, deadline - time.time())))


def show_current_ip():
    """打印出口 IP 与代理分流情况，并给出可直接填的白名单条目"""
    print("正在查询出口 IP...")
    domestic = ""
    for url in ("https://4.ipw.cn", "https://ip.3322.net",
                "https://myip.ipip.net"):
        domestic = _ip_from(url)
        if domestic:
            break
    overseas = _ip_from("https://api.ipify.org")

    print(f"\n  国内出口（探测站点看到的）: {domestic or '查询失败'}")
    print(f"  境外出口（走代理时是这个）: {overseas or '查询失败'}")

    if domestic and overseas and domestic != overseas:
        print("\n  ⚠️ 代理是「分流/规则模式」：国内直连、境外走 VPN。"
              "微信接口走国内出口。")
    elif domestic and domestic == overseas:
        print("\n  ℹ️ 两个出口相同 → 没开代理，或开了「全局模式」。"
              "全局模式下微信看到的是境外 IP，有风控风险，建议关掉。")

    # --- 关键：只认微信自己报出来的 IP
    print("\n正在向微信确认它实际看到的出口 IP ...")
    wx_ip, note = wechat_seen_ip()

    if note == "已可用":
        print("\n  ✅ 当前出口已在白名单内，可以直接上传。")
        return

    if not wx_ip:
        print(f"\n  ⚠️ 无法确认微信看到的 IP（{note}）")
        print("     请检查 .env 里的 WECHAT_APPID / WECHAT_APPSECRET。")
        return

    print(f"\n  ▶ 微信实际看到: {wx_ip}")
    if domestic and wx_ip != domestic and " / " not in wx_ip:
        print(f"  ⚠️ 与探测站点的 {domestic} 不一样 —— 以微信这个为准！"
              "（不同目标走不同运营商出口，填站点查到的那个是没用的）")

    print("\n请登录 mp.weixin.qq.com → 设置与开发 → 基本配置 → IP白名单，"
          "加入（每行一个，也可用网段）:")
    for item in _cidr_for(wx_ip.split(" / ")[0]):
        print(f"      {item}")
    print("\n提示: 网段写法受支持（如 223.104.88.0/24）；"
          "不支持 223.104.88.* 这种星号写法。")
    print("      ⚠️ /24 可能不够：实测该网络会跨 /24 漂移"
          "（223.104.72.x → 223.104.88.x → 223.104.80.x），"
          "建议一并加 /16，一劳永逸。")
    print("      同段地址反复漂移 = 运营商动态 IP（移动/宽带 CGNAT）；"
          "彻底解决请换家庭宽带或固定公网 IP 的服务器。")


# ---------------------------------------------------------------- Markdown 处理
def parse_frontmatter(text: str) -> tuple[dict, str]:
    meta = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip("\"'")
        text = text[m.end():]
    return meta, text


def plain_text(md_text: str) -> str:
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md_text)   # 图片
    t = re.sub(r"[#>*`\-\[\]()]", "", t)               # 标记符号
    return re.sub(r"\s+", "", t)


def style_html(html: str) -> str:
    """给 markdown 输出的 HTML 逐标签加内联样式"""
    # 图片：包一层居中容器，alt 作为图注
    def img_repl(m):
        alt, src = m.group(1), m.group(2)
        cap = (f'<section style="{S_FIGCAPTION}">{alt}</section>'
               if alt else "")
        return (f'<section style="{S_IMG_WRAP}">'
                f'<img src="{src}" style="{S_IMG}"/>{cap}</section>')

    html = re.sub(r'<img alt="([^"]*)" src="([^"]*)"[^/]*/?>', img_repl, html)
    html = re.sub(r"<hr\s*/?>", DIVIDER, html)
    html = re.sub(r"<blockquote>\s*<p>(.*?)</p>\s*</blockquote>",
                  rf'<blockquote style="{S_QUOTE_WRAP}">'
                  rf'<p style="{S_QUOTE_P}">\1</p></blockquote>',
                  html, flags=re.S)
    html = re.sub(r"<h2>(.*?)</h2>", rf'<h2 style="{S_H2}">\1</h2>', html)
    html = re.sub(r"<h3>(.*?)</h3>", rf'<h3 style="{S_H3}">\1</h3>', html)
    html = re.sub(r"<strong>(.*?)</strong>",
                  rf'<strong style="{S_STRONG}">\1</strong>', html)
    html = re.sub(r"<em>(.*?)</em>", rf'<em style="{S_EM}">\1</em>', html)
    html = re.sub(r"<ul>", f'<ul style="{S_UL}">', html)
    html = re.sub(r"<li>", f'<li style="{S_LI}">', html)
    html = re.sub(r"<p>", f'<p style="{S_P}">', html)
    return f'<section style="{S_BODY}">{html}</section>'


def build_article(md_file: Path, args, dry_run: bool) -> dict:
    text = md_file.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)

    # 标题：frontmatter > 第一个一级标题 > 文件名
    h1 = re.search(r"^#\s+(.+)$", body, re.M)
    title = args.title or meta.get("title") or (h1.group(1).strip() if h1 else md_file.stem)
    if h1:  # 正文里去掉一级标题（公众号标题栏已有）
        body = body.replace(h1.group(0), "", 1)

    author = args.author or meta.get("author", "")
    digest = args.digest or meta.get("digest") or plain_text(body)[:54]

    # 正文图片：本地路径 → 微信 URL
    def img_upload_repl(m):
        alt, src = m.group(1), m.group(2).strip()
        if src.startswith(("http://", "https://")):
            return m.group(0)
        p = (md_file.parent / src).resolve()
        if not p.exists():
            print(f"  ⚠️ 图片不存在，跳过上传: {src}")
            return m.group(0)
        if dry_run:
            print(f"  [dry-run] 将上传正文图片: {p.name}")
            return m.group(0)
        url = upload_content_image(p)
        print(f"  ✓ 正文图片已上传: {p.name}")
        return f"![{alt}]({url})"

    body = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", img_upload_repl, body)

    html = markdown.markdown(body, extensions=["extra", "nl2br"])
    html = style_html(html)

    # 封面：frontmatter cover > 正文第一张本地图
    cover = args.cover or meta.get("cover")
    if not cover:
        first_img = re.search(r"!\[[^\]]*\]\((?!https?://)([^)]+)\)", body)
        cover = first_img.group(1) if first_img else None

    thumb_media_id = None
    if cover:
        cover_path = (md_file.parent / cover).resolve()
        if cover_path.exists():
            if dry_run:
                print(f"  [dry-run] 将上传封面: {cover_path.name}")
            else:
                thumb_media_id = upload_thumb(cover_path)
                print(f"  ✓ 封面已上传: {cover_path.name}")
        else:
            print(f"  ⚠️ 封面不存在: {cover}")
    if not thumb_media_id and not dry_run:
        sys.exit("错误: 没有可用封面。请用 frontmatter cover: 或 --cover 指定封面图"
                 "（公众号草稿必须有封面）")

    return {
        "title": title,
        "author": author,
        "digest": digest,
        "content": html,
        "thumb_media_id": thumb_media_id or "DRY_RUN",
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="Markdown → 公众号草稿 / 发布")
    ap.add_argument("md_file", type=Path, nargs="?", help="文章 markdown 文件")
    ap.add_argument("--title", help="覆盖标题")
    ap.add_argument("--author", help="覆盖作者")
    ap.add_argument("--digest", help="覆盖摘要")
    ap.add_argument("--cover", help="覆盖封面图路径")
    ap.add_argument("--dry-run", action="store_true",
                    help="不调用微信接口，只生成 preview.html 预览排版")
    ap.add_argument("--publish", action="store_true",
                    help="创建草稿后立即发布（跳过人工确认）")
    ap.add_argument("--publish-existing", metavar="MEDIA_ID",
                    help="发布一个已存在的草稿（填草稿 media_id）")
    ap.add_argument("--show-ip", action="store_true",
                    help="查询【微信实际看到的】出口 IP（用于填公众号 IP 白名单）")
    ap.add_argument("--wait-ip", type=int, metavar="SECONDS", default=0,
                    help="先等出口 IP 进入白名单（最多 SECONDS 秒）再上传；"
                         "加完白名单不必手跑第二次，如 --wait-ip 600")
    ap.add_argument("--env-file", help="指定 .env 文件路径")
    args = ap.parse_args()

    if args.show_ip:
        show_current_ip()
        return

    global ENV_FILE, APPID, APPSECRET
    if args.env_file:
        p = Path(args.env_file).expanduser()
        if not p.exists():
            sys.exit(f".env 文件不存在: {p}")
        load_dotenv(p, override=True)
        ENV_FILE = p
        APPID = os.getenv("WECHAT_APPID", "").strip()
        APPSECRET = os.getenv("WECHAT_APPSECRET", "").strip()

    # --- 只发布已有草稿
    if args.publish_existing:
        print(f"发布已有草稿: {args.publish_existing}")
        result = publish(args.publish_existing)
        print("\n✅ 已提交发布，请到公众号后台「发表记录」查看。")
        detail = (result.get("article_detail") or {}).get("item") or []
        for it in detail:
            if it.get("article_url"):
                print(f"   文章链接: {it['article_url']}")
        return

    if not args.md_file:
        ap.error("请指定文章 markdown 文件（或用 --publish-existing MEDIA_ID）")

    md_file = args.md_file.resolve()
    if not md_file.exists():
        sys.exit(f"文件不存在: {md_file}")

    # --- 先等白名单生效（只读探测，不会产生草稿）
    if args.wait_ip and not args.dry_run:
        print(f"等待出口 IP 进入白名单（最多 {args.wait_ip} 秒）…")
        if not wait_until_allowed(args.wait_ip):
            print("\n仍被拦截。用 --show-ip 取微信实际看到的 IP 加入白名单，"
                  "建议一并加同段 /24 网段。")
            return

    print(f"处理文章: {md_file.name}")
    article = build_article(md_file, args, args.dry_run)

    if args.dry_run:
        preview = md_file.parent / "preview.html"
        preview.write_text(
            f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{article['title']}</title></head>"
            f"<body style='max-width:420px;margin:2em auto;padding:0 16px;'>"
            f"{article['content']}</body></html>",
            encoding="utf-8")
        print(f"\n[dry-run] 预览已生成: {preview}")
        print(f"标题: {article['title']}  作者: {article['author']}")
        print(f"摘要: {article['digest']}")
        return

    print("正在创建草稿...")
    media_id = create_draft(article)
    draft_sidecar(md_file).write_text(json.dumps({
        "media_id": media_id,
        "title": article["title"],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 草稿创建成功! media_id: {media_id}")
    print(f"   （已记录到 {draft_sidecar(md_file).name}，之后可用 "
          f"--publish-existing {media_id} 发布）")

    if not args.publish:
        print("请到公众号后台「草稿箱」预览确认后发布。")
        return

    print("\n开始发布...")
    result = publish(media_id)
    print("\n🎉 发布流程完成，请到公众号后台「发表记录」确认。")
    detail = (result.get("article_detail") or {}).get("item") or []
    for it in detail:
        if it.get("article_url"):
            print(f"   文章链接: {it['article_url']}")


if __name__ == "__main__":
    main()
