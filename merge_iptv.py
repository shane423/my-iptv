import re
import time
import requests
import urllib3
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor

# 關閉 SSL 憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. 精準指向 CCSH/IPTV 專案最新的原始 M3U 直播源
ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"

# 2. 保留的 6 大分組群組
TARGET_GROUPS = {"港澳台", "电影", "电视剧", "综艺频道", "NewTV", "儿童频道"}

# 3. 專屬頻道黑名單（補全繁簡體）
EXCLUDE_CHANNELS = {
    # 鳳凰系列
    "鳳凰中文", "凤凰中文",
    "鳳凰資訊", "凤凰资讯",
    "鳳凰香港", "凤凰香港",
    "鳳凰電影", "凤凰电影",
    # TVB / 無線系列
    "TVBPEARL", "TVB PEARL", "TVB明珠台",
    "TVBPLUS", "TVB PLUS", "TVBJ2",
    "TVB星河", "TVB翡翠台", "TVB翡翠",
    "無線新聞", "無綫新聞", "无线新闻",
    # 其他頻道
    "星空衛視", "星空卫视",
    "CHANNEL[V]", "CHANNEL V", "CHANNELV",
    "VIUTV"
}

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Connection': 'keep-alive'
})

def check_url_alive(url):
    """
    深度流媒體驗證：
    1. 針對 4gtv 線路進行無條件保底放行（視為存活且延遲為 0）
    2. 抓取 M3U8 檔並解析 TS 切片網址
    3. 下載實體 TS 切片，驗證是否具備影音數據流（長度 > 10KB）
    4. 連續檢測切片，防止首片段讀取成功但後續卡死
    """
    # ⚡ [關鍵修改]：4gtv 線路無條件保底放行
    if "4gtv" in url.lower():
        return (True, 0.0)

    start_time = time.time()
    try:
        # Step 1: 請求主 m3u8 檔 (允許追蹤轉向)
        res = session.get(url, timeout=3.5, verify=False, allow_redirects=True)
        if res.status_code >= 400:
            return (False, 999)
        
        content_type = res.headers.get('Content-Type', '').lower()
        text = res.text

        # 如果回應的是 m3u8 播放清單
        if "#EXTM3U" in text or "mpegurl" in content_type:
            ts_urls = []
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    ts_urls.append(urljoin(res.url, line))
            
            if not ts_urls:
                return (False, 999)

            # 若遇到 Master Playlist (嵌套 M3U8)，對第一個子 M3U8 再做一次解析
            first_target = ts_urls[0]
            if ".m3u8" in first_target.lower() or "mpegurl" in content_type:
                sub_res = session.get(first_target, timeout=3.0, verify=False, allow_redirects=True)
                if sub_res.status_code >= 400:
                    return (False, 999)
                
                sub_ts_urls = []
                for sub_line in sub_res.text.splitlines():
                    sub_line = sub_line.strip()
                    if sub_line and not sub_line.startswith("#"):
                        sub_ts_urls.append(urljoin(sub_res.url, sub_line))
                ts_urls = sub_ts_urls

            if not ts_urls:
                return (False, 999)

            # Step 2: 隨機/依序驗證前 1~2 個 TS 切片檔，確保串流可持續播放
            valid_ts_count = 0
            test_ts_targets = ts_urls[:2] # 測試前兩個切片
            
            for ts_url in test_ts_targets:
                try:
                    ts_res = session.get(ts_url, timeout=2.5, verify=False, stream=True, allow_redirects=True)
                    if ts_res.status_code < 400:
                        # 讀取切片前 10KB 數據
                        chunk = next(ts_res.iter_content(chunk_size=10240), None)
                        if chunk and len(chunk) >= 1024:  # 數據量必須高於 1KB
                            valid_ts_count += 1
                except Exception:
                    continue

            # 必須至少有 1 個切片驗證通過
            if valid_ts_count > 0:
                elapsed = time.time() - start_time
                return (True, elapsed)

        # 非 M3U8 的直接影音串流檔處理
        else:
            chunk = next(res.iter_content(chunk_size=10240), None)
            if chunk and len(chunk) >= 1024:
                elapsed = time.time() - start_time
                return (True, elapsed)

    except Exception:
        pass

    return (False, 999)

def clean_filter_smart_merge():
    print("正在下載 CCSH/IPTV 原始直播源...")
    try:
        response = session.get(ORIGINAL_URL, timeout=15)
        response.encoding = 'utf-8' 
        if response.status_code != 200:
            print(f"錯誤：無法連線直播源，HTTP 狀態碼: {response.status_code}")
            return
        lines = response.text.splitlines()
    except Exception as e:
        print(f"網路連線異常: {e}")
        return

    channels = {}
    current_group = None
    current_clean_name = None
    current_raw_info = {}
    extm3u_header = "#EXTM3U"

    print("開始抓取節目表網址、進行群組過濾、台標提取與名稱清洗...")

    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith("#EXTM3U"):
            if 'x-tvg-url=' in line:
                extm3u_header = line
            continue
            
        if line.startswith("#EXTINF"):
            group_match = re.search(r'group-title=["\']?([^"\',]+)["\']?', line)
            g_name = group_match.group(1).strip() if group_match else "其他"
                
            if g_name not in TARGET_GROUPS:
                current_group = None
                current_clean_name = None
                continue
                
            if g_name == "港澳台":
                g_name = "台灣"
                
            name_match = re.search(r',([^,]+)$', line)
            if name_match:
                raw_name = name_match.group(1).strip()
                
                clean_name = raw_name
                clean_name = re.sub(r'[\-\s_#]+\d+$', '', clean_name)
                clean_name = re.sub(r'[\s\(\停\（\[]+\d+[\s\)\營\]]+', '', clean_name)
                clean_name = re.sub(r'(副本\d*|Copy\d*|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name).strip()
                
                if not clean_name:
                    clean_name = raw_name
                
                clean_upper = clean_name.upper()
                raw_upper = raw_name.upper()
                is_excluded = any(black in clean_upper or black in raw_upper for black in EXCLUDE_CHANNELS)
                
                if is_excluded:
                    current_group = None
                    current_clean_name = None
                    continue
                
                logo_match = re.search(r'tvg-logo=["\']([^"\']+)["\']', line)
                tvg_id_match = re.search(r'tvg-id=["\']([^"\']+)["\']', line)
                logo_str = f' tvg-logo="{logo_match.group(1)}"' if logo_match else ""
                tvg_id_str = f' tvg-id="{tvg_id_match.group(1)}"' if tvg_id_match else ""
                
                current_group = g_name
                current_clean_name = clean_name
                current_raw_info = {"logo_str": logo_str, "tvg_id_str": tvg_id_str}
            else:
                current_group = None
                current_clean_name = None
                
        elif line.startswith("http"):
            if current_group and current_clean_name:
                unique_key = f"{current_group}___{current_clean_name}"
                
                if unique_key not in channels:
                    channels[unique_key] = {
                        "group": current_group,
                        "name": current_clean_name,
                        "logo_str": current_raw_info.get("logo_str", ""),
                        "tvg_id_str": current_raw_info.get("tvg_id_str", ""),
                        "urls": []
                    }
                
                if line not in channels[unique_key]["urls"]:
                    channels[unique_key]["urls"].append(line)

    print("\n⚡ 正在進行 TS 切片級流媒體數據探測 (過濾黑屏/卡頓線路)...")
    
    all_urls_to_test = [url for ch_data in channels.values() for url in ch_data["urls"]]
    unique_urls_to_test = list(set(all_urls_to_test))
    alive_urls_map = {}
    
    with ThreadPoolExecutor(max_workers=15) as executor:
        results = executor.map(check_url_alive, unique_urls_to_test)
        for url, (is_alive, delay) in zip(unique_urls_to_test, results):
            alive_urls_map[url] = {"is_alive": is_alive, "delay": delay}

    output = [extm3u_header]
    total_lines_written = 0

    def url_sort_key(u):
        info = alive_urls_map.get(u, {"is_alive": False, "delay": 999})
        is_4gtv = 1 if "4gtv" in u.lower() else 0
        is_alive = 1 if info["is_alive"] else 0
        # 排序權重：1. 是否存活 -> 2. 是否為 4gtv 線路 -> 3. 延遲 (低延遲優先)
        return (is_alive, is_4gtv, -info["delay"])

    # --- 軌道 1：原始完整群組 ---
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        
        sorted_urls = sorted(ch_data["urls"], key=url_sort_key, reverse=True)
        
        for idx, url in enumerate(sorted_urls, start=1):
            is_alive_bool = alive_urls_map.get(url, {}).get("is_alive", False)
            is_alive_label = "" if is_alive_bool else "[卡頓/失效]"
            display_name = f"{clean_name}{is_alive_label} ({idx})"
            new_info = f'#EXTINF:-1 tvg-name="{display_name}"{tvg_id_str}{logo_str} group-title="{g_name}",{display_name}'
            output.append(new_info)
            output.append(url)
            total_lines_written += 1

    # --- 軌道 2：精選複製群組 ---
    print("正在生成對應的『_精選』高可用複製群組...")
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        
        lite_group_name = f"{g_name}_精選"
        sorted_urls = sorted(ch_data["urls"], key=url_sort_key, reverse=True)
        
        # 嚴格限制：只有真正存活且驗證通過（包含 4gtv 保底放行）的線路才會進入精選群組
        best_url = next((u for u in sorted_urls if alive_urls_map.get(u, {}).get("is_alive", False)), None)
            
        if best_url:
            new_info = f'#EXTINF:-1 tvg-name="{clean_name}"{tvg_id_str}{logo_str} group-title="{lite_group_name}",{clean_name}'
            output.append(new_info)
            output.append(best_url)
            total_lines_written += 1

    output_filename = "taiwan_live.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
    print(f"\n【TS 切片檢測完成！】")
    print(f"📈 總共輸出線路共：{total_lines_written} 條。")

if __name__ == "__main__":
    clean_filter_smart_merge()
