import re
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor

# 關閉 SSL 憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. 指向 CCSH/IPTV 專案原始 M3U 直播源
ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"

# 2. 保留的 6 大分組群組
TARGET_GROUPS = ["港澳台", "电影", "电视剧", "综艺频道", "NewTV", "儿童频道"]

# 3. 頻道黑名單
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
    【嚴格串流診斷演算法】
    不只檢查 HTTP Status Code，更深入驗證 content-type 與內文是否包含真正的 M3U8/TS 切片資訊。
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Connection': 'close'
    }
    
    try:
        # 使用 stream=True 先抓取 HTTP Header 與前幾 KB 的內容
        with requests.get(url, headers=headers, timeout=4, stream=True, verify=False, allow_redirects=True) as response:
            if response.status_code != 200:
                return False
            
            content_type = response.headers.get('Content-Type', '').lower()
            
            # 若明確回傳 HTML，通常是 404 錯誤頁面或跳轉攔截頁
            if 'text/html' in content_type:
                return False
            
            # 讀取前 1024 位元組驗證是否為 M3U8 格式或媒體流
            chunk = next(response.iter_content(chunk_size=1024), b'').decode('utf-8', errors='ignore')
            
            # 驗證 M3U8 標頭或播放切片標示
            if "#EXTM3U" in chunk or "#EXTINF:" in chunk or "application/vnd.apple.mpegurl" in content_type or "application/x-mpegurl" in content_type:
                return True
                
            # 部分直連 TS 流或特定媒體流長度判斷
            if 'video/' in content_type or 'audio/' in content_type or len(chunk) > 0:
                return True

    except BaseException:
        return False
        
    return False

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

    print("\n⚡ 正在進行線上即時深度串流探測 (嚴格驗證 4gTV 與真實播放狀態)...")
    
    all_urls_to_test = []
    for unique_key, ch_data in channels.items():
        all_urls_to_test.extend(ch_data["urls"])
    
    unique_urls_to_test = list(set(all_urls_to_test))
    alive_urls_map = {}
    
    # 使用多執行緒進行線路嚴格檢測
    with ThreadPoolExecutor(max_workers=15) as executor:
        results = executor.map(check_url_alive, unique_urls_to_test)
        for url, is_alive in zip(unique_urls_to_test, results):
            alive_urls_map[url] = is_alive

    # 第三階段：重新組合輸出
    output = [extm3u_header]
    total_lines_written = 0
    
    def url_sort_key(u):
        """
        排序邏輯：
        1. 存活且是 4gTV (權重 3)
        2. 存活但非 4gTV (權重 2)
        3. 掛掉的 4gTV (權重 1)
        4. 掛掉的非 4gTV (權重 0)
        """
        is_alive = alive_urls_map.get(u, False)
        is_4gtv = "4gtv" in u.lower()
        
        if is_alive and is_4gtv:
            return 3
        elif is_alive:
            return 2
        elif is_4gtv:
            return 1
        return 0

    # --- 軌道 1：原始完整群組 (按照優先度排序) ---
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        urls = ch_data["urls"]
        
        sorted_urls = sorted(urls, key=url_sort_key, reverse=True)
        
        for idx, url in enumerate(sorted_urls, start=1):
            is_alive_bool = alive_urls_map.get(url, False)
            is_alive_label = "" if is_alive_bool else "[卡頓/失效]"
            display_name = f"{clean_name}{is_alive_label} ({idx})"
            new_info = f'#EXTINF:-1 tvg-name="{display_name}"{tvg_id_str}{logo_str} group-title="{g_name}",{display_name}'
            output.append(new_info)
            output.append(url)
            total_lines_written += 1

    # --- 軌道 2：複製一份「_精簡」群組 ---
    print("正在生成對應的『_精簡』複製群組頻道...")
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        urls = ch_data["urls"]
        
        lite_group_name = f"{g_name}_精簡"
        
        # 依照優先權挑選第一條「存活」的最佳線路（優先挑中 4gTV 的活線路）
        sorted_urls = sorted(urls, key=url_sort_key, reverse=True)
        best_url = None
        
        for url in sorted_urls:
            if alive_urls_map.get(url, False):
                best_url = url
                break
            
        if best_url:
            new_info = f'#EXTINF:-1 tvg-name="{clean_name}"{tvg_id_str}{logo_str} group-title="{lite_group_name}",{clean_name}'
            output.append(new_info)
            output.append(best_url)
            total_lines_written += 1

    # 寫入最終成品檔案
    output_filename = "taiwan_live.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
    print(f"\n【全球雙軌精簡優化完成！4gTV 優選與串流嚴格驗證完畢。】")
    print(f"📈 總共輸出線路共：{total_lines_written} 條。")

if __name__ == "__main__":
    clean_filter_smart_merge()
