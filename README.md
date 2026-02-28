# 🔍 BitcoinTalk Altcoin Monitor / 比特论坛山寨币监控

Auto-monitor [BitcoinTalk Announcements (Altcoins)](https://bitcointalk.org/index.php?board=159.0) for newly created posts, with Discord notifications.

自动监控 [BitcoinTalk 山寨币公告区](https://bitcointalk.org/index.php?board=159.0) 新发布的帖子，发现新帖自动推送 Discord 通知。

## Features / 功能

- **New post detection / 新帖检测** — Sorted by creation time, skips sticky & old posts / 按创建时间排序，跳过置顶帖和旧帖
- **Deduplication / 去重** — Tracks seen posts in `jieguo.json`, only notifies once / 记录已发送帖子，不重复通知
- **Discord notifications / Discord 通知** — Sends new post alerts to Discord webhook / 新帖自动推送到 Discord
- **Mining detection / 挖矿识别** — Tags mining-related posts with ⛏️ / 自动标记挖矿相关帖子
- **Zero dependencies / 零依赖** — Uses only Python 3 standard library / 仅使用 Python 标准库

## Usage / 用法

```bash
# View latest posts (no save, no notify) / 查看最新帖子（不保存、不通知）
python3 btt-altcoin-scraper.py

# Run once: scrape + dedup + Discord notify / 运行一次：抓取 + 去重 + 通知
python3 btt-altcoin-scraper.py --once

# Scheduled loop, every 10 min / 定时循环，每10分钟一次
python3 btt-altcoin-scraper.py --loop

# Mining-related posts only / 仅显示挖矿相关
python3 btt-altcoin-scraper.py --mining

# Custom count / 自定义数量
python3 btt-altcoin-scraper.py --count 20

# JSON output / JSON 输出
python3 btt-altcoin-scraper.py --json

# Save to file / 保存到文件
python3 btt-altcoin-scraper.py --output result.json
```

## CI / 自动化

项目配置了 CI 流水线（`.github/workflows/scrape.yml`），每 **10 分钟** 自动运行一次。

### Setup / 配置步骤

1. Fork or push this repo to GitHub/Gitee
2. Add repository secret: **`DISCORD_WEBHOOK_URL`** — your Discord webhook URL
3. The workflow will auto-run every 10 min, commit `jieguo.json` back to repo for persistence

### Environment Variables / 环境变量

| Variable / 变量 | Description / 说明 |
|---|---|
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL (required for notifications / 通知必需) |

## File Structure / 文件结构

```
├── btt-altcoin-scraper.py   # Main script / 主脚本
├── jieguo.json              # Seen posts record (auto-generated) / 已记录帖子（自动生成）
├── requirements.txt         # No runtime deps needed / 无运行时依赖
├── .github/workflows/
│   └── scrape.yml           # CI workflow / CI 流水线
└── README.md
```

## Requirements / 环境要求

- Python >= 3.10
- No third-party packages required / 无需第三方包
