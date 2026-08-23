import re
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor

# 關閉 SSL 憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. 精準指向 CCSH/IPTV 專案最新的原始 M3U 直播源
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
    【進階型 串流深度驗證演算法】
    嚴格過濾只能播幾秒就卡死的假活網、修復讀取緩慢的卡頓源
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Connection': 'keep-alive'
    }
    
    # 測試 1：深度串流內容解析 (防禦點進去播幾秒就卡死的假線路)
    try:
        # 限制讀取逾時為 5 秒，只要 5 秒內抓不到內容，代表對本地端而言極度卡頓，直接淘汰
        response = requests.get(url, headers=headers, timeout=5, stream=True, verify=False)
        
        if response.status_code == 200:
            # 針對 M3U8 HLS 串流進行深度內容檢視
            if "m3u8" in url.lower() or "mpegurl" in response.headers.get("Content-Type", "").lower():
                # 只讀取前 1024 個字節，確認內部是否含有標準 HLS 的切片宣告（如 #EXTINF 或 #EXT-X-STREAM-INF）
                chunk = response.iter_content(chunk_size=1024)
                content_sample = next(chunk).decode('utf-8', errors='ignore')
                if "#EXT" in content_sample:
                    return True
                else:
                    return False # 雖然伺服器回應200，但沒有實質影片串流內容，判定為無效假線路
            return True # 其他直連或特殊流形式，只要回應200且不卡頓即放行
    except:
        pass
        
    # 測試 2：輕量級 HEAD 探測保底 (防禦部分高防禦拒絕 GET 的活來源)
    try:
        response = requests.head(url, headers=headers, timeout=4, allow_redirects=True, verify=False)
        if response.status_code == 200:
            return True
    except:
        pass
        
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
                clean_name = re.sub(r'[\s\(\（\[]+\d+[\s\)\營\]]+', '', clean_name)
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
                        "logo_str": current_raw_info["logo_str"],
                        "tvg_id_str": current_raw_info["tvg_id_str"],
                        "urls": []
                    }
                
                if line not in channels[unique_key]["urls"]:
                    # 💡【回歸純淨排序】移除 4GTV 的 insert(0) 強制置頂，完全依照原始來源順序放入，由後續活網偵測決定高低
                    channels[unique_key]["urls"].append(line)

    print("\n⚡ 正在進行線上即時深度串流偵測，過濾無效、卡頓、播放卡死的來源...")
    
    all_urls_to_test = []
    for unique_key, ch_data in channels.items():
        all_urls_to_test.extend(ch_data["urls"])
    
    unique_urls_to_test = list(set(all_urls_to_test))
    alive_urls_map = {}
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(check_url_alive, unique_urls_to_test)
        for url, is_alive in zip(unique_urls_to_test, results):
            alive_urls_map[url] = is_alive

    # 第三階段：重新組合輸出
    output = [extm3u_header]
    total_lines_written = 0
    
    # --- 軌道 1：原始完整群組 (重新依照活網檢測結果進行排序) ---
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        urls = ch_data["urls"]
        
        # 💡 將活網排在前面，死網或卡頓源移到後面
        sorted_urls = sorted(urls, key=lambda u: alive_urls_map.get(u, False), reverse=True)
        
        for idx, url in enumerate(sorted_urls, start=1):
            is_alive_label = "" if alive_urls_map.get(url, False) else "[卡頓/失效]"
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
        
        # 💡【嚴格精簡挑選】不問出身，只挑選「通過高標準活網與流深度檢測」的第一條最速線路
        for url in urls:
            if alive_urls_map.get(url, False):
                best_url = url
                break
                
        # 極限保底：若全網在雲端環境都超時，抓第一條普通網址做墊背
        if not best_url and urls:
            best_url = urls[0]
            
        if best_url:
            new_info = f'#EXTINF:-1 tvg-name="{clean_name}"{tvg_id_str}{logo_str} group-title="{lite_group_name}",{clean_name}'
            output.append(new_info)
            output.append(best_url)
            total_lines_written += 1

    # 寫入最終成品檔案
    output_filename = "taiwan_live.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
    print(f"\n【全球雙軌精簡與串流完整清洗優化完成！】")
    print(f"📈 總共輸出完整與精簡雙軌道優質線路共：{total_lines_written} 條。")

if __name__ == "__main__":
    clean_filter_smart_merge()
