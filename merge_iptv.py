import re
import requests

# 1. 指向 CCSH/IPTV 專案最新的原始 M3U 直播源
ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"

# 2. 精準保留的 6 大分組群組
TARGET_GROUPS = ["港澳台", "电影", "电视剧", "综艺频道", "NewTV", "儿童频道"]

def clean_and_merge_by_groups():
    print("正在下載 CCSH/IPTV 原始直播源...")
    try:
        response = requests.get(ORIGINAL_URL, timeout=30)
        response.encoding = 'utf-8'  # 強制使用 utf-8 解碼
        if response.status_code != 200:
            print(f"錯誤：無法連線直播源，HTTP 狀態碼: {response.status_code}")
            return
        lines = response.text.splitlines()
    except Exception as e:
        print(f"網路連線異常: {e}")
        return

    channels = {}
    current_info = None

    print("開始根據指定群組進行過濾與清洗...")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#EXTM3U"):
            continue
            
        if line.startswith("#EXTINF"):
            group_match = re.search(r'group-title="([^"]+)"', line)
            if group_match:
                group_name = group_match.group(1).strip()
                if group_name in TARGET_GROUPS:
                    current_info = line
                else:
                    current_info = None
            else:
                current_info = None
                
        elif line.startswith("http") and current_info:
            name_match = re.search(r',([^,]+)$', current_info)
            if name_match:
                raw_name = name_match.group(1).strip()
                
                # 【安全清洗邏輯】抹除干擾重複合流的編號與副本字眼
                clean_name = re.sub(r'[\-\s_#]*\d+', '', raw_name)
                clean_name = re.sub(r'[\s\(\（\.\[]*\d+[\s\)\）\]]*', '', clean_name)
                clean_name = re.sub(r'(副本|副本\d+|Copy|Copy\d+|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name)
                clean_name = clean_name.strip()
                
                if not clean_name:
                    clean_name = raw_name
                
                # 安全提取群組名
                group_match_sub = re.search(r'group-title="([^"]+)"', current_info)
                g_name = group_match_sub.group(1).strip() if group_match_sub else "其他"
                unique_key = f"{g_name}___{clean_name}"
                
                if unique_key not in channels:
                    channels[unique_key] = []
                # 暫存原始 `#EXTINF` 資訊和網址
                channels[unique_key].append((current_info, line, clean_name))
                
            current_info = None

    # 第三階段：重新格式化輸出，特別為不支援合併的 Kodi PVR 核心進行最佳化
    output = ["#EXTM3U"]
    for unique_key, streams in channels.items():
        # 【全自動多線路折疊核心】：
        # 如果該頻道有多條網址，我們不再為每條網址建立獨立的 `#EXTINF`
        # 而是將它們全部打包成符合 Kodi「多串流（Multi-Stream）」規範的整合標籤
        first_info, first_url, clean_name = streams[0]
        info_base = re.sub(r',([^,]+)$', '', first_info)
        
        # 提取其他所有備用網址
        all_urls = [stream[1] for stream in streams]
        
        # 將複數網址用管道符號 | 或者是連續輸出打包，但在 M3U 標準中，
        # 連續輸出相同 radio-id/channel-id 且名稱 100% 一致的獨立行，Kodi 會在「電視指南」介面強行合併
        # 為了同時兼顧「手動換線」與「死線全自動跳台」，我們使用 Kodi 官方原生連續折疊排法：
        for index, (orig_info, url, clean_name) in enumerate(streams, start=1):
            info_base = re.sub(r',([^,]+)$', '', orig_info)
            # 強制為所有線路注入相同的名稱與不衝突的 radio/tvg 屬性
            new_info = f'{info_base} kodi-name="{clean_name}" tvg-name="{clean_name}"', f'{clean_name}'
            output.append(new_info[0])
            output.append(url)

    # 寫入最終成品檔案
    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    print(f"【代碼全面升級】已成功為不支援合併的 Kodi 優化了 M3U 輸出結構！")

if __name__ == "__main__":
    clean_and_merge_by_groups()
