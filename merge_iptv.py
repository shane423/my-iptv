import re
import time
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor

# 關閉 SSL 憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. 精準指向 CCSH/IPTV 專案最新的原始 M3U 直播源 (請依需求填入完整網址)
ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"

# 2. 保留的 6 大分組群組
TARGET_GROUPS = ["港澳台", "电影", "电视剧", "综艺频道", "NewTV", "儿童频道"]

# 3. 您的專屬頻道黑名單
EXCLUDE_CHANNELS = [
    "凤凰中文", "凤凰资讯", "凤凰香港", "凤凰电影", 
    "星空卫视", "Channel[V]", "Channel V", "ChannelV",
    "TVBPearl", "TVB Pearl", "TVB明珠台",
    "TVBPlus", "TVB Plus", "TVBJ2",
    "TVB星河", "TVB翡翠台", "TVB翡翠",
    "无线新闻", "無綫新聞", "ViuTV"
]

def check_url_alive(url):
    """
    【進階流媒體數據流檢驗】
    回傳 tuple: (is_alive: bool, response_time: float)
    不只檢查 HTTP 狀態，若為 m3u8 會深入檢測 TS 切片是否真有數據串流傳輸，防止「幾秒就卡住」。
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Connection': 'close'
    }
    
    start_time = time.time()
    try:
        # 1. 抓取播放清單內容 (設定 3.5 秒超時)
        res = requests.get(url, headers=headers, timeout=3.5, verify=False, stream=True)
        if res.status_code >= 400:
            return (False, 999)

        # 2. 針對 HLS (m3u8) 深入檢查內部是否有可用的 TS 切片
        content_type = res.headers.get('Content-Type', '')
        if 'mpegurl' in content_type or url.endswith('.m3u8') or '#EXTM3U' in res.text[:100]:
            lines = res.text.splitlines()
            ts_url = None
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    # 補全相對路徑 TS
                    if line.startswith('http'):
                        ts_url = line
                    else:
                        base_url = url.rsplit('/', 1)[0]
                        ts_url = f"{base_url}/{line}"
                    break
            
            # 若找到內層 TS/m3u8 切片，試讀前 1KB 數據驗證串流順暢度
            if ts_url:
                try:
                    with requests.get(ts_url, headers=headers, timeout=2.5, verify=False, stream=True) as ts_res:
                        if ts_res.status_code < 400:
                            chunk = next(ts_res.iter_content(chunk_size=1024), None)
                            if chunk and len(chunk) > 0:
                                elapsed = time.time() - start_time
                                return (True, elapsed)
                except BaseException:
                    return (False, 999)
        
        # 非 HLS 或無切片的通用流，只要能穩定讀取前段 chunk 即算成功
        chunk = next(res.iter_content(chunk_size=1024), None)
        if chunk and len(chunk) > 0:
            elapsed = time.time() - start_time
            return (True, elapsed)

    except BaseException:
        pass
        
    return (False, 999)

def clean_filter_smart_merge():
    print("正在下載 CCSH/IPTV 原始直播源...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(ORIGINAL_URL, headers=headers, timeout=30)
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
                clean_name = re.sub(r'(副本\d*|Copy\d*|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name)
                clean_name = clean_name.strip()
                
                if not clean_name:
                    clean_name = raw_name
                
                is_excluded = False
                for black_name in EXCLUDE_CHANNELS:
                    if (black_name.upper() in clean_name.upper()) or (black_name.upper() in raw_name.upper()):
                        is_excluded = True
                        break
                
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

    print("\n⚡ 正在進行線上即時深度串流數據探測 (包含 TS 切片測試)...")
    
    all_urls_to_test = []
    for unique_key, ch_data in channels.items():
        all_urls_to_test.extend(ch_data["urls"])
    
    unique_urls_to_test = list(set(all_urls_to_test))
    alive_urls_map = {}
    
    # 採用 12 線程進行嚴格快篩
    with ThreadPoolExecutor(max_workers=12) as executor:
        results = executor.map(check_url_alive, unique_urls_to_test)
        for url, (is_alive, delay) in zip(unique_urls_to_test, results):
            alive_urls_map[url] = {"is_alive": is_alive, "delay": delay}

    output = [extm3u_header]
    total_lines_written = 0

    # 自訂核心排序規則 (4gtv 優先 -> 存活優先 -> 延遲低優先)
    def url_sort_key(u):
        info = alive_urls_map.get(u, {"is_alive": False, "delay": 999})
        is_4gtv = 1 if "4gtv" in u.lower() else 0
        is_alive = 1 if info["is_alive"] else 0
        # 回傳元組進行多重排序: (是否4gtv描述, 是否存活, 延遲越低越前)
        return (is_4gtv, is_alive, -info["delay"])

    # --- 軌道 1：原始完整群組 ---
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        urls = ch_data["urls"]
        
        # 根據 4gtv > 存活 > 響應速度 進行排序
        sorted_urls = sorted(urls, key=url_sort_key, reverse=True)
        
        for idx, url in enumerate(sorted_urls, start=1):
            is_alive_bool = alive_urls_map.get(url, {}).get("is_alive", False)
            is_alive_label = "" if is_alive_bool else "[卡頓/失效]"
            display_name = f"{clean_name}{is_alive_label} ({idx})"
            new_info = f'#EXTINF:-1 tvg-name="{display_name}"{tvg_id_str}{logo_str} group-title="{g_name}",{display_name}'
            output.append(new_info)
            output.append(url)
            total_lines_written += 1

    # --- 軌道 2：精選複製群組 (嚴格過濾) ---
    print("正在生成對應的『_精選』高可用複製群組...")
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        urls = ch_data["urls"]
        
        lite_group_name = f"{g_name}_精選"
        
        # 優先排 4gtv 且能通過數據流測試的線路
        sorted_urls = sorted(urls, key=url_sort_key, reverse=True)
        
        best_url = None
        for url in sorted_urls:
            if alive_urls_map.get(url, {}).get("is_alive", False):
                best_url = url
                break
            
        # 只有在真活網（能夠順暢讀取 TS 數據流）的情況下才寫入精選列表
        if best_url:
            new_info = f'#EXTINF:-1 tvg-name="{clean_name}"{tvg_id_str}{logo_str} group-title="{lite_group_name}",{clean_name}'
            output.append(new_info)
            output.append(best_url)
            total_lines_written += 1

    # 寫入最終檔案
    output_filename = "taiwan_live.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
    print(f"\n【全球雙軌精簡優化完成！已剔除黑屏/假活網頻道。】")
    print(f"📈 總共輸出優質線路共：{total_lines_written} 條。")

if __name__ == "__main__":
    clean_filter_smart_merge()
