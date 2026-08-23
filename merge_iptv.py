import os
import re
import time
import asyncio
import requests
import urllib3
import aiohttp
from urllib.parse import urljoin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 定義多個 M3U 來源網址
SOURCES = [
    "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u",
    "https://live.zbds.top/tv/iptv4.m3u"
]

# 原始 M3U 中要抓取的簡體群組
TARGET_GROUPS = {"港澳台", "电影", "电视剧", "NewTV", "儿童频道", "电影频道"}

# 映射至 Kodi 顯示的繁體群組名稱
GROUP_NAME_MAP = {
    "港澳台": "台灣",
    "电影": "電影",
    "电影频道": "電影",
    "电视剧": "電視劇",
    "儿童频道": "卡通",
    "NewTV": "NewTV"
}

# 精選群組的頂部排序前綴（確保 Kodi 排序時排在最前面）
SELECT_GROUP_SORT = {
    "台灣": "01.台灣_精選",
    "電影": "02.電影_精選",
    "電視劇": "03.電視劇_精選",
    "卡通": "04.卡通_精選",
    "NewTV": "05.NewTV_精選"
}

# 一般頻道過濾黑名單
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

async def check_single_url(session, url, sem):
    if "4gtv" in url.lower():
        return url, True, 0.0

    async with sem:
        start_time = time.time()
        try:
            # 限制每個請求最多 1.5 秒
            timeout = aiohttp.ClientTimeout(total=1.5, connect=0.8)
            async with session.get(url, headers=HEADERS, ssl=False, timeout=timeout, allow_redirects=True) as res:
                if res.status >= 400:
                    return url, False, 999

                content_type = res.headers.get('Content-Type', '').lower()
                text = await res.text(errors='ignore')

                if "#EXTM3U" in text or "mpegurl" in content_type:
                    ts_urls = [urljoin(str(res.url), line.strip()) for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
                    if not ts_urls:
                        return url, False, 999

                    first_target = ts_urls[0]
                    if ".m3u8" in first_target.lower():
                        sub_timeout = aiohttp.ClientTimeout(total=1.0)
                        async with session.get(first_target, headers=HEADERS, ssl=False, timeout=sub_timeout, allow_redirects=True) as sub_res:
                            if sub_res.status >= 400:
                                return url, False, 999
                            sub_text = await sub_res.text(errors='ignore')
                            ts_urls = [urljoin(str(sub_res.url), line.strip()) for line in sub_text.splitlines() if line.strip() and not line.strip().startswith("#")]

                    if not ts_urls:
                        return url, False, 999

                    ts_timeout = aiohttp.ClientTimeout(total=1.0)
                    async with session.get(ts_urls[0], headers=HEADERS, ssl=False, timeout=ts_timeout, allow_redirects=True) as ts_res:
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
    # 限制最大同時發送 40 個請求，既快又不會被對手伺服器擋
    sem = asyncio.Semaphore(40)
    alive_map = {}
    
    async with aiohttp.ClientSession() as session:
        tasks = [check_single_url(session, url, sem) for url in scan_targets]
        # 設定整體任務的硬性絕殺時間（例如 18 秒）
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

    # 依次下載並解析所有來源網址
    for src_url in SOURCES:
        print(f"正在下載直播源: {src_url} ...", flush=True)
        try:
            response = requests.get(src_url, headers=HEADERS, timeout=10)
            response.encoding = 'utf-8'
            lines = response.text.splitlines()
        except Exception as e:
            print(f"下載失敗 ({src_url}): {e}", flush=True)
            continue

        current_group = None
        raw_g_name = None
        current_clean_name = None
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
                
                # 判斷是否在要擷取的群組目標內（4gtv 線路直接放行）
                if not is_4gtv and raw_g_name not in TARGET_GROUPS:
                    current_group = None
                    continue

                # 將群組轉為 Kodi 顯示的繁體名稱（4gtv 強制歸類為「台灣」）
                g_name = "台灣" if is_4gtv else GROUP_NAME_MAP.get(raw_g_name, raw_g_name)

                name_match = re.search(r',([^,]+)$', line)
                if name_match:
                    raw_name = name_match.group(1).strip()
                    clean_name = re.sub(r'[\-\s_#]+\d+$', '', raw_name)
                    clean_name = re.sub(r'(副本\d*|Copy\d*|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name).strip() or raw_name

                    # 只有來源為 zbds.top 且屬特定群組時不進行過濾，其餘來源一律執行過濾
                    is_zbds = "live.zbds.top" in src_url
                    skip_filter = is_zbds and (raw_g_name in {"电影频道", "儿童频道"})

                    if not skip_filter:
                        if any(b in clean_name.upper() or b in raw_name.upper() for b in EXCLUDE_CHANNELS):
                            current_group = None
                            continue

                    logo_match = re.search(r'tvg-logo=["\']([^"\']+)["\']', line)
                    tvg_id_match = re.search(r'tvg-id=["\']([^"\']+)["\']', line)
                    logo_str = f' tvg-logo="{logo_match.group(1)}"' if logo_match else ""
                    tvg_id_str = f' tvg-id="{tvg_id_match.group(1)}"' if tvg_id_match else ""

                    current_group = g_name
                    current_clean_name = clean_name
                    current_raw_info = {"logo_str": logo_str, "tvg_id_str": tvg_id_str}
            elif line.startswith("http") and current_group and current_clean_name:
                key = f"{current_group}___{current_clean_name}"
                if key not in channels:
                    channels[key] = {
                        "group": current_group, "name": current_clean_name,
                        "logo_str": current_raw_info.get("logo_str", ""),
                        "tvg_id_str": current_raw_info.get("tvg_id_str", ""), "urls": []
                    }
                if line not in channels[key]["urls"]:
                    channels[key]["urls"].append(line)

    all_urls = list(set([u for ch in channels.values() for u in ch["urls"]]))
    print(f"開始掃描 {len(all_urls)} 條線路...", flush=True)

    alive_urls_map = {}
    for u in all_urls:
        if "4gtv" in u.lower():
            alive_urls_map[u] = {"is_alive": True, "delay": 0.0}

    scan_targets = [u for u in all_urls if "4gtv" not in u.lower()]
    start_time = time.time()

    # 執行 AsyncIO 掃描
    scanned_results = asyncio.run(scan_all_urls(scan_targets))
    alive_urls_map.update(scanned_results)

    # 保障機制：超時未測完的非 4gtv URL 預設保留為有效 (True)，防止頻道被誤刪
    for u in all_urls:
        if u not in alive_urls_map:
            alive_urls_map[u] = {"is_alive": True, "delay": 5.0}

    output = [extm3u_header]
    def url_sort_key(u):
        info = alive_urls_map.get(u, {"is_alive": False, "delay": 999})
        return (1 if info["is_alive"] else 0, 1 if "4gtv" in u.lower() else 0, -info["delay"])

    # 優先輸出「精選版」群組，並加上前綴數字，保證排在 Kodi 最頂端
    for key, ch in channels.items():
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        best = next((u for u in sorted_urls if alive_urls_map.get(u, {}).get("is_alive", False)), None)
        if best:
            group_display = SELECT_GROUP_SORT.get(ch["group"], f"00.{ch['group']}_精選")
            output.append(f'#EXTINF:-1 tvg-name="{ch["name"]}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{group_display}",{ch["name"]}')
            output.append(best)

    # 輸出完整版群組
    for key, ch in channels.items():
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
