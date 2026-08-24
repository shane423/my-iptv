import os
import re
import time
import asyncio
import requests
import urllib3
import aiohttp
from urllib.parse import urljoin
from yt_dlp import YoutubeDL

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 定義多個 M3U 來源網址
SOURCES = [
    "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u",
    "https://live.zbds.top/tv/iptv4.m3u"
]

# YouTube 頻道直播抓取配置
YOUTUBE_TARGETS = {
    "卡通": [
        "https://www.youtube.com/@Muse_Family/streams",
        "https://www.youtube.com/@MuseTW/streams",
        "https://www.youtube.com/@AniOneAnime/streams"
    ],
    "電視劇": [
        "https://www.youtube.com/@ELTAWORLD/streams",
        "https://www.youtube.com/@gtv-drama/streams",
        "https://www.youtube.com/@cts_drama/streams",
        "https://www.youtube.com/@SETdrama/streams"
    ]
}

# GitHub 等其他來源要抓取的簡體群組
TARGET_GROUPS = {"港澳台", "电影", "电视剧", "NewTV", "儿童频道", "电影频道"}

# zbds.top 來源指定抓取的群組（嚴格只抓這兩個）
ZBDS_TARGET_GROUPS = {"儿童频道", "电影频道"}

# 映射至 Kodi 顯示的繁體群組名稱
GROUP_NAME_MAP = {
    "港澳台": "台灣",
    "电影": "電影",
    "电影频道": "電影",
    "电视剧": "電視劇",
    "儿童频道": "卡通",
    "NewTV": "NewTV"
}

# 精選群組的指定輸出順序
ORDERED_GROUPS = ["台灣", "電影", "電視劇", "卡通", "NewTV"]

# 其他來源的頻道過濾黑名單
EXCLUDE_CHANNELS = {
    "凤凰中文", "凤凰资讯", "凤凰香港", "凤凰电影",
    "TVBPEARL", "TVB PEARL", "TVB明珠台", "TVBPLUS", "TVB PLUS", "TVBJ2",
    "TVB星河", "TVB翡翠台", "TVB翡翠", "无线新闻",
    "星空卫视", "CHANNEL[V]", "VIUTV"
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*'
}

def fetch_youtube_streams(target_group, urls):
    """
    使用 yt-dlp 解析 YouTube 頻道頁面中正在進行的直播，返回解析後的頻道字典
    """
    yt_channels = {}
    ydl_opts = {
        'extract_flat': 'in_playlist',
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
    }

    ydl_stream_opts = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
    }

    print(f"📡 開始解析 YouTube [{target_group}] 直播...", flush=True)

    with YoutubeDL(ydl_opts) as ydl, YoutubeDL(ydl_stream_opts) as ydl_stream:
        for channel_url in urls:
            try:
                # 抓取頻道頁面的影片清單
                info = ydl.extract_info(channel_url, download=False)
                entries = info.get('entries', [])
                
                for entry in entries:
                    live_status = entry.get('live_status')
                    # 篩選正在直播的項目
                    if live_status == 'is_live' or entry.get('is_live'):
                        video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                        title = entry.get('title', 'YouTube直播').strip()
                        thumbnail = entry.get('thumbnails', [{}])[-1].get('url', '')

                        # 解析真實 M3U8 播放網址
                        try:
                            stream_info = ydl_stream.extract_info(video_url, download=False)
                            m3u8_url = stream_info.get('url')
                            if m3u8_url:
                                key = f"{target_group}___{title}"
                                yt_channels[key] = {
                                    "group": target_group,
                                    "name": title,
                                    "logo_str": f' tvg-logo="{thumbnail}"' if thumbnail else "",
                                    "tvg_id_str": "",
                                    "is_zbds": False,
                                    "is_yt": True, # 標記為 YT 直播，便於後續置頂與豁免
                                    "urls": [m3u8_url]
                                }
                                print(f"  └─ [成功擷取] {title}", flush=True)
                        except Exception as e:
                            print(f"  └─ 擷取串流網址失敗 ({title}): {e}", flush=True)

            except Exception as e:
                print(f"解析 YouTube 頻道失敗 ({channel_url}): {e}", flush=True)

    return yt_channels

async def check_single_url(session, url, sem):
    # 【豁免機制】4gtv、live.zbds.top 與 YouTube/Google 直播源免受嚴格測速限制，直接判定為存活
    url_lower = url.lower()
    if "4gtv" in url_lower or "zbds.top" in url_lower or "googlevideo.com" in url_lower or "youtube.com" in url_lower:
        return url, True, 0.0

    async with sem:
        start_time = time.time()
        try:
            # 第一階段：主請求 (套用嚴格 1.5s/0.8s Timeout)
            timeout = aiohttp.ClientTimeout(total=1.5, connect=0.8)
            async with session.get(url, headers=HEADERS, ssl=False, timeout=timeout, allow_redirects=True) as res:
                if res.status >= 400:
                    return url, False, 999

                content_type = res.headers.get('Content-Type', '').lower()
                text = await res.text(errors='ignore')

                # 判斷是否為 M3U8 播放清單
                if "#EXTM3U" in text or "mpegurl" in content_type:
                    ts_urls = [urljoin(str(res.url), line.strip()) for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
                    if not ts_urls:
                        return url, False, 999

                    first_target = ts_urls[0]
                    # 第二階段：若內嵌二級 M3U8，進行下探解析
                    if ".m3u8" in first_target.lower():
                        sub_timeout = aiohttp.ClientTimeout(total=1.0)
                        async with session.get(first_target, headers=HEADERS, ssl=False, timeout=sub_timeout, allow_redirects=True) as sub_res:
                            if sub_res.status >= 400:
                                return url, False, 999
                            sub_text = await sub_res.text(errors='ignore')
                            ts_urls = [urljoin(str(sub_res.url), line.strip()) for line in sub_text.splitlines() if line.strip() and not line.strip().startswith("#")]

                    if not ts_urls:
                        return url, False, 999

                    # 第三階段：對最終 TS 切片進行數據流抓取測試
                    ts_timeout = aiohttp.ClientTimeout(total=1.0)
                    async with session.get(ts_urls[0], headers=HEADERS, ssl=False, timeout=ts_timeout, allow_redirects=True) as ts_res:
                        if ts_res.status < 400:
                            chunk = await ts_res.content.read(1024)
                            # 嚴格驗證：影音數據區塊必須 >= 512 bytes 才算真存活
                            if chunk and len(chunk) >= 512:
                                return url, True, time.time() - start_time
                else:
                    # 非 M3U8 的直接串流，同樣驗證是否有真實數據流
                    chunk = await res.content.read(1024)
                    if chunk and len(chunk) >= 512:
                        return url, True, time.time() - start_time

        except Exception:
            pass

        return url, False, 999

async def scan_all_urls(scan_targets):
    sem = asyncio.Semaphore(40)
    alive_map = {}
    
    async with aiohttp.ClientSession() as session:
        tasks = [check_single_url(session, url, sem) for url in scan_targets]
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=18.0)
            for res in results:
                if isinstance(res, tuple):
                    u, is_alive, delay = res
                    alive_map[u] = {"is_alive": is_alive, "delay": delay}
        except asyncio.TimeoutError:
            print("⚡ 已達非同步掃描上限時間，強制裁切剩餘請求！", flush=True)

    return alive_map

def clean_filter_smart_merge():
    channels = {}
    extm3u_header = "#EXTM3U"

    # 1. 抓取 YouTube 直播頻道
    for group_name, yt_urls in YOUTUBE_TARGETS.items():
        yt_data = fetch_youtube_streams(group_name, yt_urls)
        channels.update(yt_data)

    # 2. 抓取一般 M3U 直播源
    for src_url in SOURCES:
        print(f"正在下載直播源: {src_url} ...", flush=True)
        is_zbds = "live.zbds.top" in src_url
        
        try:
            response = requests.get(src_url, headers=HEADERS, timeout=10)
            response.encoding = 'utf-8'
            lines = response.text.splitlines()
        except Exception as e:
            print(f"下載失敗 ({src_url}): {e}", flush=True)
            continue

        current_group = None
        current_name = None
        current_raw_info = {}

        for idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#EXTM3U"):
                if 'x-tvg-url=' in line and extm3u_header == "#EXTM3U":
                    extm3u_header = line
                continue
            if line.startswith("#EXTINF"):
                next_url = lines[idx+1].strip() if idx + 1 < len(lines) else ""
                is_4gtv = "4gtv" in next_url.lower()

                group_match = re.search(r'group-title=["\']?([^"\',]+)["\']?', line)
                raw_g_name = group_match.group(1).strip() if group_match else "其他"
                
                # 【準確過濾】：zbds 嚴格只留「儿童频道」與「电影频道」
                if is_zbds:
                    if raw_g_name not in ZBDS_TARGET_GROUPS:
                        current_group = None
                        continue
                else:
                    if not is_4gtv and raw_g_name not in TARGET_GROUPS:
                        current_group = None
                        continue

                g_name = "台灣" if is_4gtv else GROUP_NAME_MAP.get(raw_g_name, raw_g_name)

                name_match = re.search(r',([^,]+)$', line)
                if name_match:
                    raw_name = name_match.group(1).strip()

                    # zbds 來源保持完整片名不清理，防止電影同名被蓋掉
                    if is_zbds:
                        clean_name = raw_name
                    else:
                        clean_name = re.sub(r'[\-\s_#]+\d+$', '', raw_name)
                        clean_name = re.sub(r'(副本\d*|Copy\d*|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name).strip() or raw_name

                        if any(b in clean_name.upper() or b in raw_name.upper() for b in EXCLUDE_CHANNELS):
                            current_group = None
                            continue

                    logo_match = re.search(r'tvg-logo=["\']([^"\']+)["\']', line)
                    tvg_id_match = re.search(r'tvg-id=["\']([^"\']+)["\']', line)
                    logo_str = f' tvg-logo="{logo_match.group(1)}"' if logo_match else ""
                    tvg_id_str = f' tvg-id="{tvg_id_match.group(1)}"' if tvg_id_match else ""

                    current_group = g_name
                    current_name = clean_name
                    current_raw_info = {"logo_str": logo_str, "tvg_id_str": tvg_id_str, "is_zbds": is_zbds}
            elif line.startswith("http") and current_group and current_name:
                key = f"{current_group}___{current_name}"
                if key not in channels:
                    channels[key] = {
                        "group": current_group, "name": current_name,
                        "logo_str": current_raw_info.get("logo_str", ""),
                        "tvg_id_str": current_raw_info.get("tvg_id_str", ""),
                        "is_zbds": current_raw_info.get("is_zbds", False),
                        "is_yt": False,
                        "urls": []
                    }
                if line not in channels[key]["urls"]:
                    channels[key]["urls"].append(line)

    all_urls = list(set([u for ch in channels.values() for u in ch["urls"]]))
    print(f"解析完成！共獲取 {len(channels)} 個頻道/電影項目，開始掃描 {len(all_urls)} 條線路...", flush=True)

    alive_urls_map = {}
    # 預先處理豁免項目（4gtv、zbds.top 及 YouTube 直播來源直接判定存活）
    for u in all_urls:
        u_lower = u.lower()
        if "4gtv" in u_lower or "zbds.top" in u_lower or "googlevideo.com" in u_lower or "youtube.com" in u_lower:
            alive_urls_map[u] = {"is_alive": True, "delay": 0.0}

    scan_targets = [u for u in all_urls if u not in alive_urls_map]
    start_time = time.time()

    # 執行 AsyncIO 嚴格掃描（僅掃描一般來源）
    scanned_results = asyncio.run(scan_all_urls(scan_targets))
    alive_urls_map.update(scanned_results)

    # 備援與保底機制：若有未測到的剩餘網址（如整體 18s 超時），預設設為失效 (False, 999)
    for u in all_urls:
        if u not in alive_urls_map:
            alive_urls_map[u] = {"is_alive": False, "delay": 999}

    output = [extm3u_header]
    
    # URL 排序權重算法
    def url_sort_key(u):
        info = alive_urls_map.get(u, {"is_alive": False, "delay": 999})
        u_lower = u.lower()
        is_exempt = "4gtv" in u_lower or "zbds.top" in u_lower or "googlevideo.com" in u_lower or "youtube.com" in u_lower
        return (1 if info["is_alive"] else 0, 1 if is_exempt else 0, -info["delay"])

    # 頻道群組指定順序排序 + **YouTube 頻道強制頂置 (is_yt)**
    def channel_group_sort_key(item):
        ch = item[1]
        group = ch["group"]
        is_yt = 0 if ch.get("is_yt", False) else 1  # 0 排前面 (置頂)
        group_idx = ORDERED_GROUPS.index(group) if group in ORDERED_GROUPS else 999
        return (group_idx, is_yt)

    sorted_channels = sorted(channels.items(), key=channel_group_sort_key)

    # 1. 寫入「精選版」頻道（群組保留 _精選 後綴，頻道名稱乾淨無標籤）
    for key, ch in sorted_channels:
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        
        if ch.get("is_zbds", False) or ch.get("is_yt", False):
            best = sorted_urls[0] if sorted_urls else None
        else:
            best = next((u for u in sorted_urls if alive_urls_map.get(u, {}).get("is_alive", False)), None)
            
        if best:
            group_display = f"{ch['group']}_精選"
            output.append(f'#EXTINF:-1 tvg-name="{ch["name"]}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{group_display}",{ch["name"]}')
            output.append(best)

    # 2. 寫入「完整版」頻道（不論線路數量，統一加上 (1), (2), (3)... 序號）
    for key, ch in sorted_channels:
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        for idx, url in enumerate(sorted_urls, 1):
            is_alive = alive_urls_map.get(url, {}).get("is_alive", False)
            label = "" if is_alive else "[卡頓/失效]"
            name = f"{ch['name']}{label} ({idx})"
            output.append(f'#EXTINF:-1 tvg-name="{name}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{ch["group"]}",{name}')
            output.append(url)

    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"【成功完成！】總耗時：{round(time.time() - start_time, 1)} 秒。", flush=True)

if __name__ == "__main__":
    clean_filter_smart_merge()
