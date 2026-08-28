import os
import re
import time
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 指定來源與欲抓取的群組
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

# 映射至繁體群組名稱
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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*'
}

def test_url_alive(url):
    """通用的網址檢測（含 ottiptv.cc / 虎牙 / 平台轉碼流處理）"""
    # 4gtv 與 zbds.top 豁免測速，直接判定成功
    if any(k in url.lower() for k in ["4gtv", "zbds.top"]):
        return url, True, 0.0

    start_time = time.time()
    try:
        req_headers = HEADERS.copy()
        if "huya" in url.lower():
            req_headers['Referer'] = 'https://www.huya.com/'
        elif "douyu" in url.lower():
            req_headers['Referer'] = 'https://www.douyu.com/'

        # stream=True 只抓前小段數據，不下載全片
        res = requests.get(url, headers=req_headers, timeout=3.5, verify=False, stream=True, allow_redirects=True)
        if res.status_code < 400:
            for chunk in res.iter_content(chunk_size=512):
                if chunk and len(chunk) > 0:
                    return url, True, round(time.time() - start_time, 2)
                break
    except Exception:
        pass
    return url, False, 999.0

def main():
    channels = {}
    extm3u_header = "#EXTM3U"

    for src_url, allowed_groups in SOURCE_TARGET_GROUPS.items():
        print(f"📡 下載直播源: {src_url} ...", flush=True)
        is_zbds = "live.zbds.top" in src_url
        is_platform = "live_platforms" in src_url
        
        try:
            res = requests.get(src_url, headers=HEADERS, timeout=15)
            res.encoding = 'utf-8'
            lines = res.text.splitlines()
        except Exception as e:
            print(f"❌ 下載失敗 ({src_url}): {e}", flush=True)
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

                # 解析 group-title
                group_match = re.search(r'group-title=["\']?([^"\',]+)["\']?', line)
                raw_g_name = group_match.group(1).strip() if group_match else "其他"

                # 平台源或一般源的群組篩選
                if not is_4gtv and raw_g_name not in allowed_groups:
                    current_group = None
                    current_raw_group = None
                    continue

                g_name = "台灣" if is_4gtv else GROUP_NAME_MAP.get(raw_g_name, raw_g_name)

                # 解析頻道名稱
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
    print(f"🔍 成功解析 {len(channels)} 個頻道，開始使用多執行緒測試 {len(all_urls)} 條線路...", flush=True)

    alive_urls_map = {}
    
    # 使用 25 個安全執行緒進行快速連線測試
    with ThreadPoolExecutor(max_workers=25) as executor:
        results = list(executor.map(test_url_alive, all_urls))
        for u, is_alive, delay in results:
            alive_urls_map[u] = {"is_alive": is_alive, "delay": delay}

    alive_count = sum(1 for v in alive_urls_map.values() if v["is_alive"])
    print(f"✅ 線路檢測完成！存活線路：{alive_count} / {len(all_urls)}", flush=True)

    output = [extm3u_header]

    def url_sort_key(u):
        info = alive_urls_map.get(u, {"is_alive": False, "delay": 999.0})
        is_exempt = any(k in u.lower() for k in ["4gtv", "zbds.top"])
        return (1 if info["is_alive"] else 0, 1 if is_exempt else 0, -info["delay"])

    def channel_group_sort_key(item):
        ch = item[1]
        group = ch["group"]
        group_idx = ORDERED_GROUPS.index(group) if group in ORDERED_GROUPS else 999
        sub_idx = PLATFORM_GROUP_ORDER.get(ch.get("raw_group", ""), 99)
        return (group_idx, sub_idx)

    sorted_channels = sorted(channels.items(), key=channel_group_sort_key)

    # 1. 輸出「精選」區塊
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
            output.append(best)

    # 2. 輸出「完整」區塊
    for key, ch in sorted_channels:
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        for idx, url in enumerate(sorted_urls, 1):
            is_alive = alive_urls_map.get(url, {}).get("is_alive", False)
            label = "" if is_alive else "[卡頓/失效]"
            name = f"{ch['name']}{label} ({idx})"
            output.append(f'#EXTINF:-1 tvg-name="{name}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{ch["group"]}",{name}')
            output.append(url)

    # 寫入檔案
    output_filename = "taiwan_live.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    file_size = os.path.getsize(output_filename) if os.path.exists(output_filename) else 0
    print(f"🎉【處理完成】已成功生成檔案：{output_filename}（大小：{round(file_size/1024, 2)} KB）", flush=True)

if __name__ == "__main__":
    main()
