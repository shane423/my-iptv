import os
import re
import time
import asyncio
import requests
import urllib3
import aiohttp
from urllib.parse import urljoin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"

# 原始 M3U 中要抓取的簡體群組
TARGET_GROUPS = {"港澳台", "电影", "电视剧", "NewTV", "儿童频道"}

# 映射至 Kodi 顯示的繁體群組名稱
GROUP_NAME_MAP = {
    "港澳台": "台灣",
    "电影": "電影",
    "电视剧": "電視劇",
    "儿童频道": "卡通",
    "NewTV": "NewTV"
}

# Kodi 選單指定排序邏輯（精選排最前，再依指定類別排列）
ORDER_PRIORITY = [
    "台灣_精選", "電影_精選", "電視劇_精選", "卡通_精選", "NewTV_精選",
    "台灣", "電影", "電視劇", "卡通", "NewTV"
]

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
    print("正在下載 CCSH/IPTV 原始直播源...", flush=True)
    try:
        response = requests.get(ORIGINAL_URL, headers=HEADERS, timeout=10)
        response.encoding = 'utf-8'
        lines = response.text.splitlines()
    except Exception as e:
        print(f"下載失敗: {e}", flush=True)
        return

    channels = {}
    current_group = None
    current_clean_name = None
    current_raw_info = {}
    extm3u_header = "#EXTM3U"

    for idx, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            if 'x-tvg-url=' in line:
                extm3u_header = line
            continue
        if line.startswith("#EXTINF"):
            next_url = lines[idx+1].strip() if idx + 1 < len(lines) else ""
            is_4gtv = "4gtv" in next_url.lower()

            group_match = re.search(r'group-title=["\']?([^"\',]+)["\']?', line)
            g_name = group_match.group(1).strip() if group_match else "其他"
            
            if not is_4gtv and g_name not in TARGET_GROUPS:
                current_group = None
                continue

            g_name = "台灣" if is_4gtv else GROUP_NAME_MAP.get(g_name, g_name)

            name_match = re.search(r',([^,]+)$', line)
            if name_match:
                raw_name = name_match.group(1).strip()
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

    scanned_results = asyncio.run(scan_all_urls(scan_targets))
    alive_urls_map.update(scanned_results)

    for u in all_urls:
        if u not in alive_urls_map:
            alive_urls_map[u] = {"is_alive": True, "delay": 5.0}

    def url_sort_key(u):
        info = alive_urls_map.get(u, {"is_alive": False, "delay": 999})
        return (1 if info["is_alive"] else 0, 1 if "4gtv" in u.lower() else 0, -info["delay"])

    # 1. 產生所有頻道的 M3U 紀錄
    entries_by_group = {}

    # 精選版條目
    for key, ch in channels.items():
        group_name = f"{ch['group']}_精選"
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        best = next((u for u in sorted_urls if alive_urls_map.get(u, {}).get("is_alive", False)), None)
        if best:
            item = (f'#EXTINF:-1 tvg-name="{ch["name"]}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{group_name}",{ch["name"]}\n{best}')
            entries_by_group.setdefault(group_name, []).append(item)

    # 完整版條目
    for key, ch in channels.items():
        group_name = ch["group"]
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        for idx, url in enumerate(sorted_urls, 1):
            is_alive = alive_urls_map.get(url, {}).get("is_alive", False)
            label = "" if is_alive else "[卡頓/失效]"
            name = f"{ch['name']}{label} ({idx})"
            item = (f'#EXTINF:-1 tvg-name="{name}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{group_name}",{name}\n{url}')
            entries_by_group.setdefault(group_name, []).append(item)

    # 2. 依照指定優先順序寫入檔頭與內容
    output = [extm3u_header]
    for g in ORDER_PRIORITY:
        if g in entries_by_group:
            output.extend(entries_by_group[g])

    # 寫入剩餘未定義在 ORDER_PRIORITY 中的群組（如有）
    for g, items in entries_by_group.items():
        if g not in ORDER_PRIORITY:
            output.extend(items)

    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"【成功完成！】總耗時：{round(time.time() - start_time, 1)} 秒。", flush=True)

if __name__ == "__main__":
    clean_filter_smart_merge()
