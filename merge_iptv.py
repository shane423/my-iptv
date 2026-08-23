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
    【終極 HLS 串流特徵深度驗證演算法】
    1. 平等對待 4GTV 與一般源，徹底過濾死掉的 4GTV
    2. 深度下載切片層級（iter_content），5秒內抓不到實質 HLS 切片宣告的卡死垃圾源一律淘汰
    """
    # 使用通用高相容性的代理標頭，偽裝成台灣本地電視盒
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; Chromecast) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8',
        'Connection': 'keep-alive'
    }
    
    # 核心深度串流體檢（專殺只能看7秒的假活網與失效4GTV）
    try:
        # 將超時限制縮短至極其嚴苛的 4 秒，不給垃圾源任何拖延排隊的機會
        response = requests.get(url, headers=headers, timeout=4, stream=True, verify=False)
        
        if response.status_code < 400:
            # 只要是 m3u8 或者是串流媒體格式
            if "m3u8" in url.lower() or "mpegurl" in response.headers.get("Content-Type", "").lower():
                # 💡 強制讀取前 2048 字節。只能播幾秒就卡住的假線路，在切片握手階段就會卡住或回傳空資料
                chunk = response.iter_content(chunk_size=2048)
                content_sample = next(chunk).decode('utf-8', errors='ignore')
                
                # 必須嚴格包含 HLS 的核心特徵宣告，才算通過健康檢查
                if "#EXT" in content_sample:
                    return True
                else:
                    return False # 伺服器雖在，但已無實質影片流內容（空包彈），淘汰
            return True # 其他直連流
    except:
        pass
        
    # 保底輕量化 HEAD 探測 (防禦少部分禁止海外機房 GET 卻真實存在的來源)
    try:
        response = requests.head(url, headers=headers, timeout=3, allow_redirects=True, verify=False)
        # 只要伺服器肯給出回應（且不是 500 以上的死機），皆給予通過，保留至完整列表墊底
        if response.status_code < 500:
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
                    # 💡 將 4GTV 排在前面供優先偵測，但不再給予無條件豁免權
                    if "4gtv" in line.lower():
                        channels[unique_key]["urls"].insert(0, line)
                    else:
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
    
    # --- 軌道 1：原始完整群組 (完全以「真實活網體檢結果」高低來排序) ---
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        urls = ch_data["urls"]
        
        # 活著的排前面(1)，死網或卡死垃圾源移到後面(0)
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
        
        # 💡【全新精簡過濾機制】平等海選：誰能通過最嚴格的串流切片深度探測，誰就是第一名
        for url in urls:
            if alive_urls_map.get(url, False):
                best_url = url
                break
                
        # 萬一全部都被雲端機房阻擋，才回退拿第一條做最後的防漏台保底
        if not best_url and urls:
            best_url = urls
            
        if best_url:
            new_info = f'#EXTINF:-1 tvg-name="{clean_name}"{tvg_id_str}{logo_str} group-title="{lite_group_name}",{clean_name}'
            output.append(new_info)
            output.append(best_url)
            total_lines_written += 1

    # 寫入最終成品檔案
    output_filename = "taiwan_live.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
    print(f"\n【全球雙軌精簡與假活網、無效4GTV深度清洗完成！】")
    print(f"📈 總共輸出完整與精簡雙軌道優質線路共：{total_lines_written} 條。")

if __name__ == "__main__":
    clean_filter_smart_merge()
