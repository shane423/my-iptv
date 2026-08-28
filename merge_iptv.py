import os
import re
import time
import asyncio
import requests
import urllib3
import aiohttp
from urllib.parse import urljoin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SOURCE_TARGET_GROUPS = {
    "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u": {
        "港澳台", "电影", "儿童频道"
    },
    "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_platforms.m3u": {
        "zonghe", "一起看", "原创", "原创IP"
    },
    "https://live.zbds.top/tv/iptv4.m3u": {
        "儿童频道", "电影频道"
    }
}

GROUP_NAME_MAP = {
    "港澳台": "台灣",
    "电影": "電影",
    "电影频道": "電影",
    "儿童频道": "卡通",
    "zonghe": "其他",
    "一起看": "其他",
    "原创": "其他",
    "原创IP": "其他"
}

PLATFORM_GROUP_ORDER = {
    "zonghe": 1,
    "一起看": 2,
    "原创": 3,
    "原创IP": 4
}

ORDERED_GROUPS = ["台灣", "電影", "卡通", "其他"]

EXCLUDE_CHANNELS = {
    "凤凰中文", "凤凰资讯", "凤凰香港", "凤凰电影",
    "TVBPEARL", "TVB PEARL", "TVB明珠台", "TVBPLUS", "TVB PLUS", "TVBJ2",
    "TVB星河", "TVB翡翠台", "TVB翡翠", "无线新闻",
    "星空卫视", "CHANNEL[V]", "VIUTV"
}

# 模擬標準播放器/瀏覽器的 Header
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Connection': 'keep-alive'
}

async def check_single_url(session, url, sem):
    if any(k in url.lower() for k in ["4gtv", "zbds.top"]):
        return url, True, 0.0

    is_platform = "live_platforms" in url.lower()

    async with sem:
        start_time = time.time()
        try:
            timeout = aiohttp.ClientTimeout(total=3.0, connect=1.2)
            
            # 給予更全面的 Header 避免 403 誤判
            custom_headers = HEADERS.copy()
            if is_platform:
                custom_headers['Origin'] = 'https://raw.githubusercontent.com'
                custom_headers['Referer'] = 'https://raw.githubusercontent.com/'

            async with session.get(url, headers=custom_headers, ssl=False, timeout=timeout, allow_redirects=True) as res:
                if res.status >= 400:
                    return url, False, 999

                content_type = res.headers.get('Content-Type', '').lower()
                text = await res.text(errors='ignore')

                if "#EXTM3U" in text or "mpegurl" in content_type or ".m3u8" in url.lower():
                    # 抓取清單內的切片與子 M3U8
                    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
                    if not lines:
                        return url, False, 999

                    first_target = urljoin(str(res.url), lines[0])

                    # 若指向子 M3U8 清單
                    if ".m3u8" in first_target.lower():
                        sub_timeout = aiohttp.ClientTimeout(total=2.0)
                        async with session.get(first_target, headers=custom_headers, ssl=False, timeout=sub_timeout, allow_redirects=True) as sub_res:
                            if sub_res.status >= 400:
                                return url, False, 999
                            sub_text = await sub_res.text(errors='ignore')
                            lines = [urljoin(str(sub_res.url), line.strip()) for line in sub_text.splitlines() if line.strip() and not line.strip().startswith("#")]

                    if not lines:
                        return url, False, 999

                    # 針對 live_platforms 的檢測邏輯
                    if is_platform:
                        # 只要 HLS Playlist 正確解析出 2 個以上的 TS 切片，且回應碼正常，即認定存活
                        # (解決因防盜鏈或 Session 限制導致第二段 TS 請求失敗的誤判問題)
                        if len(lines) >= 2:
                            return url, True, time.time() - start_time
                        
                        # 備用點進度檢測
                        ts_url = lines[0]
                        ts_timeout = aiohttp.ClientTimeout(total=1.5)
                        async with session.get(ts_url, headers=custom_headers, ssl=False, timeout=ts_timeout, allow_redirects=True) as ts_res:
                            if ts_res.status < 400:
                                chunk = await ts_res.content.read(1024)
                                if chunk and len(chunk) > 0:
                                    return url, True, time.time() - start_time
                    else:
                        # 普通來源檢測
                        ts_url = lines[0]
                        ts_timeout = aiohttp.ClientTimeout(total=1.5)
                        async with session.get(ts_url, headers=custom_headers, ssl=False, timeout=ts_timeout, allow_redirects=True) as ts_res:
                            if ts_res.status < 400:
                                chunk = await ts_res.content.read(1024)
                                if chunk and len(chunk) >= 512:
                                    return url, True, time.time() - start_time
                else:
                    chunk = await res.content.read(1024)
                    if chunk and len(chunk) >= 512:
                        return url, True, time.time() - start_time

        except Exception:
            pass

        return url, False, 999

async def scan_all_urls(scan_targets):
    sem = asyncio.Semaphore(30)
    alive_map = {}
    
    async with aiohttp.ClientSession() as session:
        tasks = [check_single_url(session, url, sem) for url in scan_targets]
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=30.0)
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

    for src_url, allowed_groups in SOURCE_TARGET_GROUPS.items():
        print(f"正在下載直播源: {src_url} ...", flush=True)
        is_zbds = "live.zbds.top" in src_url
        is_platform = "live_platforms" in src_url
        
        try:
            response = requests.get(src_url, headers=HEADERS, timeout=10)
            response.encoding = 'utf-8'
            lines = response.text.splitlines()
        except Exception as e:
            print(f"下載失敗 ({src_url}): {e}", flush=True)
            continue

        current_group = None
        current_raw_group = None
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
                
                if not is_4gtv and raw_g_name not in allowed_groups:
                    current_group = None
                    current_raw_group = None
                    continue

                g_name = "台灣" if is_4gtv else GROUP_NAME_MAP.get(raw_g_name, raw_g_name)

                name_match = re.search(r',([^,]+)$', line)
                if name_match:
                    raw_name = name_match.group(1).strip()

                    if is_zbds or is_platform:
                        clean_name = raw_name
                    else:
                        clean_name = re.sub(r'[\-\s_#]+\d+$', '', raw_name)
                        clean_name = re.sub(r'(副本\d*|Copy\d*|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name).strip() or raw_name

                        if any(b in clean_name.upper() or b in raw_name.upper() for b in EXCLUDE_CHANNELS):
                            current_group = None
                            current_raw_group = None
                            continue

                    logo_match = re.search(r'tvg-logo=["\']([^"\']+)["\']', line)
                    tvg_id_match = re.search(r'tvg-id=["\']([^"\']+)["\']', line)
                    logo_str = f' tvg-logo="{logo_match.group(1)}"' if logo_match else ""
                    tvg_id_str = f' tvg-id="{tvg_id_match.group(1)}"' if tvg_id_match else ""

                    current_group = g_name
                    current_raw_group = raw_g_name
                    current_name = clean_name
                    current_raw_info = {
                        "logo_str": logo_str,
                        "tvg_id_str": tvg_id_str,
                        "raw_group": raw_g_name,
                        "src_url": src_url
                    }
            elif line.startswith("http") and current_group and current_name:
                key = f"{current_group}___{current_name}"
                if key not in channels:
                    channels[key] = {
                        "group": current_group,
                        "raw_group": current_raw_group,
                        "name": current_name,
                        "logo_str": current_raw_info.get("logo_str", ""),
                        "tvg_id_str": current_raw_info.get("tvg_id_str", ""),
                        "src_url": current_raw_info.get("src_url", ""),
                        "urls": []
                    }
                if line not in channels[key]["urls"]:
                    channels[key]["urls"].append(line)

    all_urls = list(set([u for ch in channels.values() for u in ch["urls"]]))
    print(f"解析完成！共獲取 {len(channels)} 個頻道/電影項目，開始掃描 {len(all_urls)} 條線路...", flush=True)

    alive_urls_map = {}
    for u in all_urls:
        if any(k in u.lower() for k in ["4gtv", "zbds.top"]):
            alive_urls_map[u] = {"is_alive": True, "delay": 0.0}

    scan_targets = [u for u in all_urls if u not in alive_urls_map]
    start_time = time.time()

    scanned_results = asyncio.run(scan_all_urls(scan_targets))
    alive_urls_map.update(scanned_results)

    for u in all_urls:
        if u not in alive_urls_map:
            alive_urls_map[u] = {"is_alive": False, "delay": 999}

    output = [extm3u_header]
    
    def url_sort_key(u):
        info = alive_urls_map.get(u, {"is_alive": False, "delay": 999})
        is_exempt = any(k in u.lower() for k in ["4gtv", "zbds.top"])
        return (1 if info["is_alive"] else 0, 1 if is_exempt else 0, -info["delay"])

    def channel_group_sort_key(item):
        ch = item[1]
        group = ch["group"]
        group_idx = ORDERED_GROUPS.index(group) if group in ORDERED_GROUPS else 999
        sub_idx = PLATFORM_GROUP_ORDER.get(ch.get("raw_group", ""), 99)
        return (group_idx, sub_idx)

    sorted_channels = sorted(channels.items(), key=channel_group_sort_key)

    # 1. 輸出「精選」群組區塊
    for key, ch in sorted_channels:
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        src = ch.get("src_url", "")
        
        if "live.zbds.top" in src:
            best = sorted_urls[0] if sorted_urls else None
        else:
            best = next((u for u in sorted_urls if alive_urls_map.get(u, {}).get("is_alive", False)), None)
            
        if best:
            group_display = f"{ch['group']}_精選"
            output.append(f'#EXTINF:-1 tvg-name="{ch["name"]}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{group_display}",{ch["name"]}')
            # 針對平台類頻道增加播放器相容 Header 宣告，解決播幾秒退出的問題
            if "live_platforms" in src:
                output.append('#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36')
            output.append(best)

    # 2. 輸出「完整」群組區塊
    for key, ch in sorted_channels:
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        src = ch.get("src_url", "")
        for idx, url in enumerate(sorted_urls, 1):
            is_alive = alive_urls_map.get(url, {}).get("is_alive", False)
            label = "" if is_alive else "[卡頓/失效]"
            name = f"{ch['name']}{label} ({idx})"
            output.append(f'#EXTINF:-1 tvg-name="{name}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{ch["group"]}",{name}')
            if "live_platforms" in src:
                output.append('#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36')
            output.append(url)

    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"【成功完成！】總耗時：{round(time.time() - start_time, 1)} 秒。", flush=True)

if __name__ == "__main__":
    clean_filter_smart_merge()
