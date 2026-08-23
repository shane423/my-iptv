import re
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor

# 關閉 SSL 憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. 精準指向 CCSH/IPTV 專案最新的原始 M3U 直播源
ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u" # 請填入完整正確的 GitHub Raw 網址

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
    【深度串流流暢度驗證】
    1. 不只檢查 200 OK，還會解析 .m3u8 內容取得真實 .ts 檔案
    2. 下載實體數據切片，驗證是否真有數據流（防卡死/假活網）
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Connection': 'keep-alive'
    }
    
    try:
        # 第一階段：請求 m3u8 檔案
        resp = requests.get(url, headers=headers, timeout=4, verify=False, stream=True)
        if resp.status_code != 200:
            return False
        
        content_type = resp.headers.get('Content-Type', '').lower()
        content_text = resp.text
        
        # 判斷是否為合法的 M3U/HLS 檔案格式
        if "#EXTM3U" not in content_text and "mpegurl" not in content_type:
            # 若為直連 TS 檔則嘗試讀取封包
            if "video" in content_type or url.endswith(".ts"):
                return len(resp.raw.read(1024 * 64)) > 0
            return False

        # 第二階段：提取內部 TS 數據切片連結
        ts_urls = []
        for line in content_text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                if line.startswith("http"):
                    ts_urls.append(line)
                else:
                    # 處理相對路徑
                    base_url = url.rsplit('/', 1)[0]
                    ts_urls.append(f"{base_url}/{line}")
        
        if not ts_urls:
            return False

        # 第三階段：對前 2 個 TS 數據切片進行數據下載實測（驗證流暢度）
        verified_ts = 0
        for ts_url in ts_urls[:2]:
            try:
                with requests.get(ts_url, headers=headers, timeout=3, stream=True, verify=False) as ts_resp:
                    if ts_resp.status_code == 200:
                        # 試讀取 64KB 數據，確保沒有中途斷流
                        chunk = ts_resp.raw.read(1024 * 64)
                        if len(chunk) > 0:
                            verified_ts += 1
            except Exception:
                continue

        # 至少要有 1 個 TS 切片順利下載才認定為真正可播頻道
        return verified_ts > 0

    except Exception:
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
                        "logo_str": current_raw_info["logo_str"],
                        "tvg_id_str": current_raw_info["tvg_id_str"],
                        "urls": []
                    }
                
                if line not in channels[unique_key]["urls"]:
                    channels[unique_key]["urls"].append(line)

    # 對每個頻道的網址進行權重排序（優先將 4gtv 置頂）
    for unique_key in channels:
        channels[unique_key]["urls"].sort(key=lambda u: 0 if "4gtv" in u.lower() else 1)

    print("\n⚡ 正在進行線上即時深度 TS 切片流偵測（預計需時較長，確保撥放品質）...")
    
    all_urls_to_test = []
    for unique_key, ch_data in channels.items():
        all_urls_to_test.extend(ch_data["urls"])
    
    unique_urls_to_test = list(set(all_urls_to_test))
    alive_urls_map = {}
    
    # 降低併發數以提升 TS 數據串流測試穩定度
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(check_url_alive, unique_urls_to_test)
        for url, is_alive in zip(unique_urls_to_test, results):
            alive_urls_map[url] = is_alive

    output = [extm3u_header]
    total_lines_written = 0
    
    # --- 軌道 1：完整群組（排在前面且可用的線路優先，標註失效線路） ---
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        urls = ch_data["urls"]
        
        # 排序：活網優先，且活網中 4gtv 排最前面
        sorted_urls = sorted(urls, key=lambda u: (0 if alive_urls_map.get(u, False) else 1, 0 if "4gtv" in u.lower() else 1))
        
        for idx, url in enumerate(sorted_urls, start=1):
            is_alive_bool = alive_urls_map.get(url, False)
            is_alive_label = "" if is_alive_bool else "[卡頓/失效]"
            display_name = f"{clean_name}{is_alive_label} ({idx})"
            new_info = f'#EXTINF:-1 tvg-name="{display_name}"{tvg_id_str}{logo_str} group-title="{g_name}",{display_name}'
            output.append(new_info)
            output.append(url)
            total_lines_written += 1

    # --- 軌道 2：精簡群組（僅保留通過 TS 測試的最佳線路，優先挑選 4gtv） ---
    print("正在生成對應的『_精簡』複製群組頻道...")
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        logo_str = ch_data["logo_str"]
        tvg_id_str = ch_data["tvg_id_str"]
        urls = ch_data["urls"]
        
        lite_group_name = f"{g_name}_精簡"
        best_url = None
        
        # 優先選擇「有效」且「為 4gtv 來源」的網址
        for url in urls:
            if alive_urls_map.get(url, False):
                best_url = url
                break  # 因為之前已經將 4gtv 排在最前面，第一個找到的就是最佳解
            
        if best_url:
            new_info = f'#EXTINF:-1 tvg-name="{clean_name}"{tvg_id_str}{logo_str} group-title="{lite_group_name}",{clean_name}'
            output.append(new_info)
            output.append(best_url)
            total_lines_written += 1

    # 寫入最終檔
    output_filename = "taiwan_live.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
    print(f"\n【全球雙軌精簡優化完成！】")
    print(f"📈 總共輸出線路共：{total_lines_written} 條。")

if __name__ == "__main__":
    clean_filter_smart_merge()
