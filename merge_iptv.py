import re
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor

# 關閉 SSL 憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. 指向 CCSH/IPTV 專案最新的原始 M3U 直播源
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
    【專業級串流狀態深度快篩機制】
    1. 針對 4gtv 注入合法 Referer 與 Origin，防止被 4gtv 伺服器拒接誤判。
    2. 攔截 HTTP 非 200/206 狀態碼（過濾 403, 404, 500 等死網）。
    3. 讀取前 512 位元組，判斷是否為無效 HTML 網頁，並確保包含 #EXTM3U 等 HLS 切片標籤。
    """
    is_4gtv = "4gtv" in url.lower()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'close'
    }
    
    # 為 4gtv 串流補上防盜鏈驗證標頭
    if is_4gtv:
        headers['Referer'] = 'https://www.4gtv.tv/'
        headers['Origin'] = 'https://www.4gtv.tv'

    try:
        with requests.get(url, headers=headers, timeout=3, stream=True, verify=False, allow_redirects=True) as response:
            # 狀態碼必須為 200 OK 或 206 Partial Content
            if response.status_code in (200, 206):
                sample = response.raw.read(512).decode('utf-8', errors='ignore')
                
                # 攔截假活網（部分伺服器或 4gtv 過期會回傳 200 + HTML 錯誤頁面）
                if "<html" in sample.lower() or "<body" in sample.lower() or "<xml" in sample.lower():
                    return False
                
                # m3u8 標準切片標籤驗證
                hls_tags = ["#EXTM3U", "#EXTINF", "#EXT-X-STREAM-INF", "#EXT-X-TARGETDURATION", "#EXT-X-MEDIA-SEQUENCE"]
                if any(tag in sample for tag in hls_tags):
                    return True
                elif "m3u8" not in url.lower():
                    return True
                    
            return False
    except BaseException:
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
                    # 4gtv 線路優先放置於最前面
                    if "4gtv" in line.lower():
                        channels[unique_key]["urls"].insert(0, line)
                    else:
                        channels[unique_key]["urls"].append(line)

    print("\n⚡ 正在進行線上即時深度串流偵測...")
    
    all_urls_to_test = []
    for unique_key, ch_data in channels.items():
        all_urls_to_test.extend(ch_data["urls"])
    
    unique_urls_to_test = list(set(all_urls_to_test))
    alive_urls_map = {}
    
    # 使用 15 個線程進行併發探測
    with ThreadPoolExecutor(max_workers=15) as executor:
        results = executor.map(check_url_alive, unique_urls_to_test)
        for url, is_alive in zip(unique_urls_to_test, results):
            alive_urls_map[url] = is_alive

    # 第三階段：重新組合輸出
    output = [extm3u_header]
    total_lines_written = 0
    
    # --- 軌道 1：原始完整群組 ---
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        urls = ch_data["urls"]
        
        # 將驗證為 True 的活網排在前，False 排在後
        sorted_urls = sorted(urls, key=lambda u: 1 if alive_urls_map.get(u, False) else 0, reverse=True)
        
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
        best_url = None
        
        # 尋找第一條通過驗證的真實活網
        for url in urls:
            if alive_urls_map.get(url, False):
                best_url = url
                break
                
        # 僅當找到有效線路時才寫入，確保死網完全剔除
        if best_url:
            new_info = f'#EXTINF:-1 tvg-name="{clean_name}"{tvg_id_str}{logo_str} group-title="{lite_group_name}",{clean_name}'
            output.append(new_info)
            output.append(best_url)
            total_lines_written += 1

    # 寫入檔案
    output_filename = "taiwan_live.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
    print(f"\n【全球雙軌精簡優化完成！已剔除全軍覆沒頻道。】")
    print(f"📈 總共輸出優質線路共：{total_lines_written} 條。")

if __name__ == "__main__":
    clean_filter_smart_merge()
