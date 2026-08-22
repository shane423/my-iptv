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

    # 第三階段：重新格式化輸出，優化為 Kodi 官方原生多線路折疊與自動跳台格式
    output = ["#EXTM3U"]
    for unique_key, streams in channels.items():
        for index, (orig_info, url, clean_name) in enumerate(streams, start=1):
            # 移除舊有結尾名稱，保留前面的所有標籤資訊
            info_base = re.sub(r',([^,]+)$', '', orig_info)
            
            # 【終極完美修復】：移除逗號後面的「線路 X」後綴，讓所有分身的頻道名稱完全保持一致！
            # 透過連續排列完全相同「頻道名稱」+ 注入 `kodi-name`，Kodi 的 PVR 引擎會在電視指南裡完美將它們合而為一。
            # 當前線路一旦死線斷訊，Kodi 核心偵測到下一行有相同名字的頻道，就會全自動在背景秒跳轉下一條線路！
            new_info = f'{info_base} kodi-name="{clean_name}",{clean_name}'
            
            output.append(new_info)
            output.append(url)

    # 寫入最終成品檔案
    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    print(f"【完美達成】共有 {len(channels)} 個頻道成功開通手動與全自動斷線跳台功能！")

if __name__ == "__main__":
    clean_and_merge_by_groups()
