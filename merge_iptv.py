import os
import re
import time
import asyncio
import urllib3
import aiohttp
from urllib.parse import urljoin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 定義各 M3U 來源網址及其「指定抓取」的群組名稱（精確對應）
SOURCE_TARGET_GROUPS = {
    "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u": {
        "港澳台", "电影", "电视剧", "NewTV", "儿童频道", "电影频道"
    },
    "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_platforms.m3u": {
        "zonghe", "一起看", "原创", "原创IP"
    },
    "https://live.zbds.top/tv/iptv4.m3u": {
        "儿童频道", "电影频道"
    }
}

# 映射至 Kodi 顯示的繁體群組名稱
GROUP_NAME_MAP = {
    "港澳台": "台灣",
    "电影": "電影",
    "电影频道": "電影",
    "电视剧": "電視劇",
    "儿童频道": "卡通",
    "NewTV": "NewTV",
    "zonghe": "其他",
    "一起看": "其他",
    "原创": "其他",
    "原创IP": "其他"
}

# 定義 live_platforms.m3u 子群組的排序權重
PLATFORM_GROUP_ORDER = {
    "zonghe": 1,
    "一起看": 2,
    "原创": 3,
    "原创IP": 4
}

# 精選群組的指定輸出順序
ORDERED_GROUPS = ["台灣", "電影", "電視劇", "卡通", "NewTV", "其他"]

# 其他來源的頻道過濾黑名單
EXCLUDE_CHANNELS = {
    "凤凰中文", "凤凰资讯", "凤凰香港", "凤凰电影",
    "TVBPEARL", "TVB PEARL", "TVB明珠台", "TVBPLUS", "TVB PLUS", "TVBJ2",
    "TVB星河", "TVB翡翠台", "TVB翡翠", "无线新闻",
    "星空卫视", "CHANNEL[V]", "VIUTV"
}

# 通用 User-Agent 與 4gtv 防盜鏈防護參數
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': '*/*'
}

HEADERS_4GTV = {
    'User-Agent': USER_AGENT,
    'Referer': 'https://www.4gtv.tv/',
    'Origin': 'https://www.4gtv.tv',
    'Accept': '*/*'
}

KODI_4GTV_SUFFIX = f"|User-Agent={USER_AGENT}&Referer=https://www.4gtv.tv/&Origin=https://www.4gtv.tv"


async def fetch_m3u_text(session, url):
    """非同步下載 M3U 內容"""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with session.get(url, headers=HEADERS, ssl=False, timeout=timeout) as res:
            if res.status == 200:
                return await res.text(encoding='utf-8', errors='ignore')
    except Exception as e:
        print(f"下載失敗 ({url}): {e}", flush=True)
    return ""


async def check_single_url(session, url, sem):
    """
    非同步網路檢測
    為防範 4gtv 防盜鏈機制封鎖切片請求造成誤判，4gtv 回傳 HTTP 200 且包含 M3U 特徵即判定存活
    """
    is_4gtv = "4gtv" in url.lower()
    is_zbds = "zbds.top" in url.lower()
    
    req_headers = HEADERS_4GTV if is_4gtv else HEADERS

    async with sem:
        start_time = time.time()
        try:
            conn_timeout = 1.5 if (is_4gtv or is_zbds) else 1.0
            tot_timeout = 3.0 if (is_4gtv or is_zbds) else 2.0

            timeout = aiohttp.ClientTimeout(total=tot_timeout, connect=conn_timeout)
            async with session.get(url, headers=req_headers, ssl=False, timeout=timeout, allow_redirects=True) as res:
                if res.status >= 400:
                    return url, False, 999

                content_type = res.headers.get('Content-Type', '').lower()
                text = await res.text(errors='ignore')

                # 4gtv 專屬檢測邏輯
                if is_4gtv:
                    if "#EXTM3U" in text or "mpegurl" in content_type or res.status == 200:
                        return url, True, time.time() - start_time

                if "#EXTM3U" in text or "mpegurl" in content_type:
                    ts_urls = [urljoin(str(res.url), line.strip()) for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
                    if not ts_urls:
                        return url, False, 999

                    first_target = ts_urls[0]
                    if ".m3u8" in first_target.lower():
                        sub_timeout = aiohttp.ClientTimeout(total=1.5)
                        async with session.get(first_target, headers=req_headers, ssl=False, timeout=sub_timeout, allow_redirects=True) as sub_res:
                            if sub_res.status >= 400:
                                return url, False, 999
                            sub_text = await sub_res.text(errors='ignore')
                            ts_urls = [urljoin(str(sub_res.url), line.strip()) for line in sub_text.splitlines() if line.strip() and not line.strip().startswith("#")]

                    if not ts_urls:
                        return url, False, 999

                    ts_timeout = aiohttp.ClientTimeout(total=1.5)
                    async with session.get(ts_urls[0], headers=req_headers, ssl=False, timeout=ts_timeout, allow_redirects=True) as ts_res:
                        if ts_res.status < 400:
                            chunk = await ts_res.content.read(1024)
                            if chunk and len(chunk) >= 512:
                                delay = 0.0 if is_zbds else (time.time() - start_time)
                                return url, True, delay
                else:
                    chunk = await res.content.read(1024)
                    if chunk and len(chunk) >= 512:
                        delay = 0.0 if is_zbds else (time.time() - start_time)
                        return url, True, delay

        except Exception:
            pass

        return url, False, 999


async def scan_all_urls(scan_targets, session):
    sem = asyncio.Semaphore(40)
    alive_map = {}
    
    tasks = [check_single_url(session, url, sem) for url in scan_targets]
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=25.0)
        for res in results:
            if isinstance(res, tuple):
                u, is_alive, delay = res
                alive_map[u] = {"is_alive": is_alive, "delay": delay}
    except asyncio.TimeoutError:
        print("⚡ 已達非同步掃描上限時間，強制裁切剩餘請求！", flush=True)

    return alive_map


def format_url_for_kodi(url):
    """為 4gtv 網址自動附加 Kodi 標頭參數，防範播放時崩潰"""
    if "4gtv" in url.lower() and "|User-Agent=" not in url:
        return f"{url}{KODI_4GTV_SUFFIX}"
    return url


async def clean_filter_smart_merge_async():
    channels = {}
    extm3u_header = "#EXTM3U"

    async with aiohttp.ClientSession() as session:
        for src_url, allowed_groups in SOURCE_TARGET_GROUPS.items():
            print(f"正在下載直播源: {src_url} ...", flush=True)
            is_zbds = "live.zbds.top" in src_url
            is_platform = "live_platforms" in src_url
            
            m3u_text = await fetch_m3u_text(session, src_url)
            if not m3u_text:
                continue

            lines = m3u_text.splitlines()

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
                            "is_zbds": is_zbds,
                            "raw_group": raw_g_name
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
                            "is_zbds": current_raw_info.get("is_zbds", False),
                            "urls": []
                        }
                    if line not in channels[key]["urls"]:
                        channels[key]["urls"].append(line)

        all_urls = list(set([u for ch in channels.values() for u in ch["urls"]]))
        print(f"解析完成！共獲取 {len(channels)} 個頻道/電影項目，開始掃描驗證 {len(all_urls)} 條線路...", flush=True)

        start_time = time.time()
        alive_urls_map = await scan_all_urls(all_urls, session)

        for u in all_urls:
            if u not in alive_urls_map:
                alive_urls_map[u] = {"is_alive": False, "delay": 999}

        output = [extm3u_header]
        
        def url_sort_key(u):
            info = alive_urls_map.get(u, {"is_alive": False, "delay": 999})
            is_special = ("4gtv" in u.lower() or "zbds.top" in u.lower())
            return (1 if info["is_alive"] else 0, 1 if is_special else 0, -info["delay"])

        def channel_group_sort_key(item):
            ch = item[1]
            group = ch["group"]
            group_idx = ORDERED_GROUPS.index(group) if group in ORDERED_GROUPS else 999
            sub_idx = PLATFORM_GROUP_ORDER.get(ch.get("raw_group", ""), 99)
            return (group_idx, sub_idx)

        sorted_channels = sorted(channels.items(), key=channel_group_sort_key)

        # 生成第一階段：精選頻道列表 (只嚴格寫入測速存活的線路，無存活則跳過)
        for key, ch in sorted_channels:
            sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
            
            # 嚴格選取測速存活的最佳線路
            best = next((u for u in sorted_urls if alive_urls_map.get(u, {}).get("is_alive", False)), None)
            
            # 僅在有存活線路時才寫入精選區
            if best:
                formatted_best = format_url_for_kodi(best)
                group_display = f"{ch['group']}_精選"
                output.append(f'#EXTINF:-1 tvg-name="{ch["name"]}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{group_display}",{ch["name"]}')
                output.append(formatted_best)

        # 生成第二階段：完整頻道與備用線路列表 (包含所有測試成功與失敗的備用線路)
        for key, ch in sorted_channels:
            sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
            for idx, url in enumerate(sorted_urls, 1):
                is_alive = alive_urls_map.get(url, {}).get("is_alive", False)
                label = "" if is_alive else "[卡頓/失效]"
                name = f"{ch['name']}{label} ({idx})"
                formatted_url = format_url_for_kodi(url)
                output.append(f'#EXTINF:-1 tvg-name="{name}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{ch["group"]}",{name}')
                output.append(formatted_url)

        with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
            f.write("\n".join(output))

        print(f"【成功完成！】總耗時：{round(time.time() - start_time, 1)} 秒。", flush=True)


def clean_filter_smart_merge():
    asyncio.run(clean_filter_smart_merge_async())


if __name__ == "__main__":
    clean_filter_smart_merge()
