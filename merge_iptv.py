import re
import requests

# 1. 指向 CCSH/IPTV 專案最新的原始 M3U 直播源
ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"

# 2. 精準保留的 6 大分組群組
TARGET_GROUPS = ["港澳台", "电影", "电视剧", "综艺频道", "NewTV", "儿童频道"]

def clean_and_merge_pipe_format():
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
                
                # 【安全清洗邏輯】徹底抹除 -2、-3、(2)、副本、Copy、HD、藍光等字眼
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
                
                # 重新構造完全純淨無雜質的 `#EXTINF` 資訊行
                new_info = f'#EXTINF:-1 group-title="{g_name}",{clean_name}'
                
                # 【核心變更】：將同一個頻道的所有不同網址，通通收集到同一個陣列裡
                if unique_key not in channels:
                    channels[unique_key] = {"info": new_info, "urls": []}
                
                # 為了確保「第三個可以看」的順暢度，我們進行智慧排序：
                # 網址如果含有藍光、HD、或是原本排在後面的，我們用 insert(0) 讓它排在最前面優先加載
                if any(kw in raw_name for kw in ["藍光", "HD", "hd", "1080", "3", "-3"]):
                    channels[unique_key]["urls"].insert(0, line)
                else:
                    channels[unique_key]["urls"].append(line)
                
            current_info = None

    # 第三階段：重新格式化輸出為「多路徑備用管道格式」
    output = ["#EXTM3U"]
    for unique_key, ch_data in channels.items():
        info = ch_data["info"]
        
        # 去除重複的網址網頁
        unique_urls = list(dict.fromkeys(ch_data["urls"]))
        
        # 【終極多路徑融合】：利用管道符號 | 將多條線路黏成唯一一行！
        # 格式範例：http://線路1.m3u8|http://線路2.m3u8|http://線路3.m3u8
        # 這樣在 M3U 檔案裡，這個電視台就真的「只有一行」，Kodi 絕無可能再次展開它！
        merged_url = "|".join(unique_urls)
        
        output.append(info)
        output.append(merged_url)

    # 寫入最終成品檔案
    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    print(f"【管道多路徑備用優化完成】已成功將所有重複頻道精準黏合！共輸出 {len(channels)} 個唯一頻道。")

if __name__ == "__main__":
    clean_and_merge_pipe_format()
