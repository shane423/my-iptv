import os
import re
import time
import requests
import urllib3
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"
TARGET_GROUPS = {"港澳台", "电影", "电视剧", "综艺频道", "NewTV", "儿童频道"}

EXCLUDE_CHANNELS = {
    "鳳凰中文", "凤凰中文", "鳳凰資訊", "凤凰资讯", "鳳凰香港", "凤凰香港", "鳳凰電影", "凤凰电影",
    "TVBPEARL", "TVB PEARL", "TVB明珠台", "TVBPLUS", "TVB PLUS", "TVBJ2",
    "TVB星河", "TVB翡翠台", "TVB翡翠", "無線新聞", "無綫新聞", "无线新闻",
    "星空衛視", "星空卫视", "CHANNEL[V]", "CHANNEL V", "CHANNELV", "VIUTV"
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*'
}

def check_url_alive(url):
    # 4gtv 一律直接判定成功
    if "4gtv" in url.lower():
        return url, True, 0.0

    start_time = time.time()
    try:
        res = requests.get(url, headers=HEADERS, timeout=1.5, verify=False, allow_redirects=True)
        if res.status_code >= 400:
            return url, False, 999

        content_type = res.headers.get('Content-Type', '').lower()
        text = res.text

        if "#EXTM3U" in text or "mpegurl" in content_type:
            ts_urls = [urljoin(res.url, line.strip()) for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
            if not ts_urls:
                return url, False, 999

            first_target = ts_urls[0]
            if ".m3u8" in first_target.lower():
                sub_res = requests.get(first_target, headers=HEADERS, timeout=1.0, verify=False, allow_redirects=True)
                if sub_res.status_code >= 400:
                    return url, False, 999
                ts_urls = [urljoin(sub_res.url, line.strip()) for line in sub_res.text.splitlines() if line.strip() and not line.strip().startswith("#")]

            if not ts_urls:
                return url, False, 999

            ts_res = requests.get(ts_urls[0], headers=HEADERS, timeout=1.0, verify=False, stream=True, allow_redirects=True)
            if ts_res.status_code < 400:
                chunk = next(ts_res.iter_content(chunk_size=1024), None)
                if chunk and len(chunk) >= 512:
                    return url, True, time.time() - start_time
        else:
            chunk = next(res.iter_content(chunk_size=1024), None)
            if chunk and len(chunk) >= 512:
                return url, True, time.time() - start_time

    except Exception:
        pass

    return url, False, 999

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

            if g_name == "港澳台" or is_4gtv:
                g_name = "台灣"

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

    # ⚡ 關鍵修復：預先將所有 4gtv 填寫為通過（is_alive: True），避免超時 break 導致未測到的 4gtv 被預設為 False！
    alive_urls_map = {}
    for u in all_urls:
        if "4gtv" in u.lower():
            alive_urls_map[u] = {"is_alive": True, "delay": 0.0}

    start_time = time.time()

    executor = ThreadPoolExecutor(max_workers=15)
    futures = [executor.submit(check_url_alive, url) for url in all_urls if "4gtv" not in url.lower()]
    
    for future in as_completed(futures):
        if time.time() - start_time > 30:
            print("⚡ 已達 30 秒上限，強制收尾並寫入檔案！", flush=True)
            break
        try:
            u, is_alive, delay = future.result()
            alive_urls_map[u] = {"is_alive": is_alive, "delay": delay}
        except Exception:
            pass

    output = [extm3u_header]
    def url_sort_key(u):
        info = alive_urls_map.get(u, {"is_alive": False, "delay": 999})
        return (1 if info["is_alive"] else 0, 1 if "4gtv" in u.lower() else 0, -info["delay"])

    # 輸出完整版
    for key, ch in channels.items():
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        for idx, url in enumerate(sorted_urls, 1):
            is_alive = alive_urls_map.get(url, {}).get("is_alive", False)
            label = "" if is_alive else "[卡頓/失效]"
            name = f"{ch['name']}{label} ({idx})"
            output.append(f'#EXTINF:-1 tvg-name="{name}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{ch["group"]}",{name}')
            output.append(url)

    # 輸出精選版
    for key, ch in channels.items():
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        best = next((u for u in sorted_urls if alive_urls_map.get(u, {}).get("is_alive", False)), None)
        if best:
            output.append(f'#EXTINF:-1 tvg-name="{ch["name"]}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{ch["group"]}_精選",{ch["name"]}')
            output.append(best)

    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"【成功完成！】總耗時：{round(time.time() - start_time, 1)} 秒，直接退出進程。", flush=True)
    os._exit(0)

if __name__ == "__main__":
    clean_filter_smart_merge()
