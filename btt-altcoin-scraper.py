#!/usr/bin/env python3
"""
btt-altcoin-scraper.py — BitcoinTalk 山寨币公告区抓取器
抓取 board=159 (Announcements - Altcoins) 最新发布的帖子（按创建时间排序）

用法:
  python3 btt-altcoin-scraper.py                  # 抓最新发布的 10 个帖子
  python3 btt-altcoin-scraper.py --count 20       # 抓 20 个
  python3 btt-altcoin-scraper.py --json            # 输出 JSON
  python3 btt-altcoin-scraper.py --output result.json  # 保存到文件
  python3 btt-altcoin-scraper.py --mining          # 只显示挖矿相关帖子

依赖: 仅 Python 3 标准库，无需安装任何第三方包

定时运行:
  crontab -e
  0 */6 * * * /usr/bin/python3 /path/to/btt-altcoin-scraper.py --json --output /path/to/btt_latest.json
"""
import argparse, json, logging, os, re, sys, time, urllib.request, uuid, zipfile
from datetime import datetime, timezone, timedelta
from io import BytesIO

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 按创建时间倒序排列（sort=first_post;desc）
BOARD_URL = "https://bitcointalk.org/index.php?board=159.0;sort=first_post;desc"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Discord Webhook（优先从环境变量读取，本地开发可硬编码）
DISCORD_WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1477185168698769430/0BtqMZWfdcSw8kUtZRfdIXI0Fz7rkYvku7c_nW5XlDUzYDY_K-fomaWYMMnY_-2eute2"
)

# 结果文件（用于去重）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_FILE = os.path.join(SCRIPT_DIR, "jieguo.json")

# 定时间隔（秒）
INTERVAL = 10 * 60

# 挖矿关键词
MINING_RE = re.compile(
    r"\bpow\b|\bPoW\b|proof.of.work|mining|miner|hashrate|hash.rate"
    r"|cpu.min|gpu.min|asic.resist|fair.launch|no.premine|block.reward"
    r"|mineable|mine?able"
    r"|RandomX|KawPow|ProgPoW|Equihash|Autolykos|kHeavyHash|CryptoNight"
    r"|MinotaurX|Verthash|FishHash|zkPoW|BeamHash|YesPoWer|SpectreX"
    r"|Ethash|\bScrypt\b|SHA.?256d?|Cuckoo|Blake3|Keccak.?256|Argon2"
    r"|stratum|solo.min|pool.min",
    re.IGNORECASE,
)
# 排除误判
MINING_EXCLUDE = re.compile(
    r"trading|bot|assistant|DeFi|swap|lending|staking|NFT|token sale"
    r"|presale|IDO|IEO|launchpad|airdrop|generosity|charity",
    re.IGNORECASE,
)


def fetch_page(url: str) -> str:
    """抓取页面 HTML"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("iso-8859-1", errors="replace")


def parse_posts(html: str) -> list[dict]:
    """用正则解析帖子列表（比 HTMLParser 更可靠）"""
    posts = []

    # 提取所有帖子行：msg_ID 开头的 span 包含标题和链接
    # 格式: <span id="msg_XXXXX"><a href="...topic=NNNNN.0">标题</a></span>
    pattern = re.compile(
        r'<span\s+id="msg_(\d+)">'
        r'\s*<a\s+href="(https://bitcointalk\.org/index\.php\?topic=(\d+)\.\d+)">'
        r'(.+?)</a>\s*</span>',
        re.DOTALL,
    )

    matches = list(pattern.finditer(html))

    # 提取置顶帖的 topic ID（通过 stickyicon 图片识别）
    sticky_pattern = re.compile(r'id="stickyicon_(\d+)"')
    sticky_topics = set()
    for m in sticky_pattern.finditer(html):
        sticky_topics.add(m.group(1))

    # 提取每个帖子的作者、回复数、浏览数
    # 帖子行结构：在 msg_XXX 之后，同一个 tr 里有作者、回复、浏览
    # 用 topic ID 关联

    # 提取作者：紧跟在帖子标题后面的 profile 链接
    author_pattern = re.compile(
        r'topic=(\d+)\.\d+">.*?</a>.*?'
        r'action=profile[^"]*">([^<]+)</a>',
        re.DOTALL,
    )
    authors = {}
    for m in author_pattern.finditer(html):
        authors[m.group(1)] = m.group(2).strip()

    # 提取回复数和浏览数：在 td class="stickybg2" 或 "windowbg2" 中
    # 简化方案：用 topic 顺序对应
    stats_pattern = re.compile(
        r'<td\s+class="(?:stickybg2|windowbg2|stickybg|windowbg)"\s+'
        r'(?:style="[^"]*"\s+)?'
        r'(?:width="[^"]*"\s+)?'
        r'[^>]*>\s*(\d+)\s*</td>',
    )

    for m in matches:
        msg_id = m.group(1)
        url = m.group(2)
        topic_id = m.group(3)
        title = m.group(4).strip()

        # 清理 HTML 实体
        title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        title = title.replace("&#039;", "'").replace("&quot;", '"')
        # 解码数字 HTML 实体（如 &#128293; -> 🔥）
        title = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), title)
        title = re.sub(r'<[^>]+>', '', title)  # 去掉残留 HTML 标签

        # 跳过置顶帖
        if topic_id in sticky_topics:
            continue

        # 跳过版规帖（msg_id 很小的通常是版规）
        if int(msg_id) < 20000000:
            continue

        # 跳过非常旧的帖子（topic_id 很小说明创建时间很早）
        if int(topic_id) < 5500000:
            continue

        post = {
            "topic_id": int(topic_id),
            "msg_id": int(msg_id),
            "title": title,
            "url": url,
            "author": authors.get(topic_id, ""),
        }
        posts.append(post)

    # 按 topic_id 倒序（最新创建的在前）
    posts.sort(key=lambda x: x["topic_id"], reverse=True)

    return posts


def is_mining_related(post: dict) -> bool:
    """判断帖子是否与挖矿相关"""
    title = post.get("title", "")
    if MINING_EXCLUDE.search(title):
        return False
    return bool(MINING_RE.search(title))


def load_seen_topics() -> dict:
    """从 jieguo.json 加载已记录的帖子，返回 {topic_id: record}"""
    if os.path.exists(RESULT_FILE):
        try:
            with open(RESULT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return {item['topic_id']: item for item in data}
        except (json.JSONDecodeError, KeyError):
            logger.warning(f"jieguo.json 格式异常，将重新创建")
    return {}


def save_seen_topics(seen: dict):
    """将已记录帖子写回 jieguo.json"""
    data = sorted(seen.values(), key=lambda x: x['topic_id'], reverse=True)
    with open(RESULT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_topic_html(url: str) -> bytes | None:
    """抓取帖子详情页 HTML（返回原始字节，用于保存/上传）"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as e:
        logger.error(f"抓取帖子页面失败: {e}")
        return None


def compress_html_to_zip(html_bytes: bytes, html_filename: str) -> bytes:
    """将 HTML 压缩为 ZIP"""
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(html_filename, html_bytes)
    return zip_buffer.getvalue()


def send_discord_file(file_bytes: bytes, filename: str, message_text: str, content_type: str = "application/zip"):
    """通过 multipart/form-data 向 Discord Webhook 发送文件附件"""
    boundary = uuid.uuid4().hex
    body = b''

    # payload_json part（消息文本）
    body += f'--{boundary}\r\n'.encode()
    body += b'Content-Disposition: form-data; name="payload_json"\r\n'
    body += b'Content-Type: application/json\r\n\r\n'
    body += json.dumps({"content": message_text}).encode('utf-8')
    body += b'\r\n'

    # file part
    body += f'--{boundary}\r\n'.encode()
    body += f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'.encode()
    body += f'Content-Type: {content_type}\r\n\r\n'.encode()
    body += file_bytes
    body += b'\r\n'

    body += f'--{boundary}--\r\n'.encode()

    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status in (200, 204):
                logger.info(f"✅ Discord 文件已发送: {filename}")
            else:
                logger.warning(f"⚠️ Discord 文件上传返回 HTTP {resp.status}")
    except Exception as e:
        logger.error(f"❌ Discord 文件上传失败: {e}")


def send_discord_notification(post: dict, topic_html: bytes | None = None):
    """发送 Discord Webhook 通知（文本 + HTML 文件附件）"""
    mining_tag = " ⛏️" if post.get("is_mining") else ""
    text = (
        f"\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆕 **New Post / 新帖发布**{mining_tag}\n\n"
        f"> 📌 **{post['title']}**\n"
        f"> \n"
        f"> 👤 Author / 作者: **{post.get('author', 'N/A')}**\n"
        f"> 🕐 Time / 时间: {post.get('found_at', 'N/A')}\n"
        f"> 🔗 <{post['url']}>\n"
        f"\n"
    )

    if topic_html:
        # 有页面内容：压缩为 zip 后发送（避免 Discord 预览）
        html_filename = f"topic_{post['topic_id']}.html"
        zip_bytes = compress_html_to_zip(topic_html, html_filename)
        zip_filename = f"topic_{post['topic_id']}.zip"
        send_discord_file(zip_bytes, zip_filename, text, "application/zip")
    else:
        # 抓取失败：仅发文本
        message = {"content": text}
        data = json.dumps(message).encode('utf-8')
        req = urllib.request.Request(
            DISCORD_WEBHOOK_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 204:
                    logger.info(f"✅ Discord 通知已发送: {post['title']}")
                else:
                    logger.warning(f"⚠️ Discord 返回 HTTP {resp.status}")
        except Exception as e:
            logger.error(f"❌ Discord 通知失败: {e}")


def run_once() -> int:
    """执行一次抓取，返回新发现的帖子数量"""
    logger.info("开始抓取...")
    try:
        html = fetch_page(BOARD_URL)
    except Exception as e:
        logger.error(f"抓取页面失败: {e}")
        return 0

    posts = parse_posts(html)
    logger.info(f"解析到 {len(posts)} 个帖子（已排除置顶/版规）")

    seen = load_seen_topics()
    new_count = 0

    for post in posts:
        topic_id = post['topic_id']
        if topic_id in seen:
            continue

        # 新帖子
        post['is_mining'] = is_mining_related(post)
        post['found_at'] = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        seen[topic_id] = post
        new_count += 1

        logger.info(f"🆕 新帖: {post['title']} (topic={topic_id})")

        # 抓取帖子详情页 HTML（用于备份）
        topic_html = fetch_topic_html(post['url'])
        send_discord_notification(post, topic_html)
        # 避免触发 Discord rate limit
        time.sleep(2)

    save_seen_topics(seen)
    logger.info(f"本轮完成: {new_count} 条新帖, 总记录 {len(seen)} 条")
    return new_count


def run_loop():
    """定时循环运行，每 10 分钟一次"""
    logger.info(f"启动定时模式，每 {INTERVAL // 60} 分钟运行一次 (Ctrl+C 停止)")
    while True:
        try:
            run_once()
        except Exception as e:
            logger.error(f"运行异常: {e}")
        logger.info(f"等待 {INTERVAL // 60} 分钟后再次运行...")
        time.sleep(INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="BitcoinTalk Altcoin ANN Scraper")
    parser.add_argument("--loop", action="store_true", help="定时循环模式（每10分钟一次）")
    parser.add_argument("--once", action="store_true", help="运行一次（抓取+去重+通知）")
    parser.add_argument("--count", type=int, default=10, help="抓取数量 (默认 10)")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--output", type=str, help="保存到文件")
    parser.add_argument("--mining", action="store_true", help="只显示挖矿相关帖子")
    args = parser.parse_args()

    # 定时循环模式
    if args.loop:
        run_loop()
        return

    # 单次运行模式（抓取 + 去重 + Discord 通知）
    if args.once:
        run_once()
        return

    # 以下为原始查看模式（不保存、不通知）
    html = fetch_page(BOARD_URL)
    posts = parse_posts(html)

    if args.mining:
        posts = [p for p in posts if is_mining_related(p)]

    posts = posts[:args.count]

    for p in posts:
        p["is_mining"] = is_mining_related(p)

    if args.json or args.output:
        result = {
            "scraped_at": datetime.now(tz=timezone.utc).isoformat(),
            "board": "Announcements (Altcoins)",
            "board_url": BOARD_URL,
            "sort": "newest_first",
            "count": len(posts),
            "mining_only": args.mining,
            "posts": posts,
        }
        json_str = json.dumps(result, indent=2, ensure_ascii=False)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(json_str)
            print(f"✅ 已保存到 {args.output} ({len(posts)} 条)")
        else:
            print(json_str)
    else:
        print(f"\n📋 BitcoinTalk 山寨币公告区 — 最新发布 {len(posts)} 条")
        print(f"   排序: 按创建时间（最新在前）")
        if args.mining:
            print(f"   过滤: 仅挖矿相关")
        print("=" * 70)
        for i, p in enumerate(posts, 1):
            mining_tag = " ⛏️" if p["is_mining"] else ""
            print(f"\n[{i:2d}] {p['title']}{mining_tag}")
            print(f"     作者: {p['author']}  |  Topic ID: {p['topic_id']}")
            print(f"     {p['url']}")
        print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
