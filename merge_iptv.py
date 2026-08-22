import re
import requests

# 1. 精準指向 CCSH/IPTV 專案最新的原始 M3U 直播源
ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"

# 2. 精準保留的 6 大分組群組
TARGET_GROUPS = ["港澳台", "电影", "电视剧", "综艺频道", "NewTV", "儿童频道"]

def clean_and_merge_kodi_stream_switch():
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
    current_raw_name = None

    print("開始針對原始 M3U 進行超精準名稱清洗...")

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#EXTM3U"):
            continue
            
        if line.startswith("#EXTINF"):
            group_match = re.search(r'group-title=["\']?([^"\',]+)["\']?', line)
            g_name = group_match.group(1).strip() if group_match else "其他"
                
            if g_name not in TARGET_GROUPS:
                current_group = None
                current_clean_name = None
                continue
                
            name_match = re.search(r',([^,]+)$', line)
            if name_match:
                raw_name = name_match.group(1).strip()
                
                # 強力清洗名稱雜質
                clean_name = raw_name
                clean_name = re.sub(r'[\-\s_#]+\d+$', '', clean_name)
                clean_name = re.sub(r'[\s\(\（\[]+\d+[\s\)\營\]]+', '', clean_name)
                clean_name = re.sub(r'(副本\d*|Copy\d*|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name)
                clean_name = clean_name.strip()
                
                if not clean_name:
                    clean_name = raw_name
                    
                current_group = g_name
                current_clean_name = clean_name
                current_raw_name = raw_name
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
                        "urls": []
                    }
                
                if line not in channels[unique_key]["urls"]:
                    if any(kw in current_raw_name.upper() for kw in ["藍光", "HD", "1080", "4K"]):
                        channels[unique_key]["urls"].insert(0, line)
                    else:
                        channels[unique_key]["urls"].append(line)

    # 第三階段：輸出為 Kodi 影像串流多音軌/多線路切換格式
    output = ["#EXTM3U"]
    unique_channel_count = 0
    
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        urls = ch_data["urls"]
        
        if not urls:
            continue
            
        unique_channel_count += 1
        
        # 1. 寫入唯一的電視台名稱（保證主畫面列表不重複）
        output.append(f'#EXTINF:-1 group-title="{g_name}" tvg-name="{clean_name}" tvg-id="{clean_name}",{clean_name}')
        
        # 2. 如果有備用線路，利用 KODIPROP 將線路 2、線路 3 綁定在背景 (從 1 開始編號)
        if len(urls) > 1:
            for idx, alt_url in enumerate(urls[1:], start=1):
                output.append(f'#KODIPROP:inputstream.adaptive.stream_url_{idx}={alt_url}')
        
        # 3. 【已修正漏洞】：這裡必須寫入第一條主線路的「網址字串」，而不是整個 urls 陣列
        output.append(urls[0])

    # 寫入最終成品檔案
    output_filename = "taiwan_live.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
    print(f"\n【Kodi 影像串流切換優化完成！】")
    print(f"成功將多條線路合併至背景，主列表只會顯示 {unique_channel_count} 個獨立頻道。")

if __name__ == "__main__":
    clean_and_merge_kodi_stream_switch()
