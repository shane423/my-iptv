import re
import requests

# 1. 已更新：指向 CCSH/IPTV 專案最新的原始 M3U 直播源
ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"

# 2. 精準保留的 6 大分組群組
TARGET_GROUPS = ["港澳台", "电影", "电视剧", "综艺频道", "NewTV", "儿童频道"]

def clean_and_merge_kodi_format():
    print("正在下載 CCSH/IPTV 原始直播源...")
    try:
        # 加上 User-Agent 避免部分 GitHub 請求被拒絕
        headers = {'User-Agent': 'Mozilla/5.0'}
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
    current_info = None
    print("開始根據指定群組進行過濾與清洗...")

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#EXTM3U"):
            continue
            
        if line.startswith("#EXTINF"):
            group_match = re.search(r'group-title="([^"]+)"', line)
            if not group_match:
                # 兼容沒有雙引號的 group-title=群組名 格式
                group_match = re.search(r'group-title=([^ ,]+)', line)
                
            if group_match:
                group_name = group_match.group(1).strip()
                if group_name in TARGET_GROUPS:
                    current_info = line
                    continue
            current_info = None
            
        elif line.startswith("http") and current_info:
            # 提取逗號後面的原始頻道名稱
            name_match = re.search(r',([^,]+)$', current_info)
            if name_match:
                raw_name = name_match.group(1).strip()
                
                # 【強力安全清洗邏輯】確保名字完全一致，Kodi 才能順利合併
                clean_name = raw_name
                # 移除末尾的 -1, -2, -3, #1, #2 等數字
                clean_name = re.sub(r'[\-\s_#]+\d+$', '', clean_name)
                # 移除 (1), (2), （2）等括號數字
                clean_name = re.sub(r'[\s\(\（\[]+\d+[\s\)\營\]]+', '', clean_name)
                # 移除常見的雜質關鍵字
                clean_name = re.sub(r'(副本\d*|Copy\d*|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name)
                clean_name = clean_name.strip()
                
                if not clean_name:
                    clean_name = raw_name

                # 提取群組名
                group_match_sub = re.search(r'group-title="([^"]+)"', current_info)
                if not group_match_sub:
                    group_match_sub = re.search(r'group-title=([^ ,]+)', current_info)
                g_name = group_match_sub.group(1).strip() if group_match_sub else "其他"
                
                # 以 群組+清洗後的頻道名 作為唯一 Key
                unique_key = f"{g_name}___{clean_name}"
                
                if unique_key not in channels:
                    channels[unique_key] = {
                        "group": g_name,
                        "name": clean_name,
                        "urls": []
                    }
                
                # 智慧排序：高品質線路插到最前面 (線路1)
                if line not in channels[unique_key]["urls"]:
                    if any(kw in raw_name.upper() for kw in ["藍光", "HD", "1080", "4K"]):
                        channels[unique_key]["urls"].insert(0, line)
                    else:
                        channels[unique_key]["urls"].append(line)
                        
            current_info = None

    # 第三階段：重新格式化輸出為 Kodi 標準的多線路同名格式
    output = ["#EXTM3U"]
    unique_channel_count = 0
    
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        urls = ch_data["urls"]
        
        if not urls:
            continue
            
        unique_channel_count += 1
        
        # 遍歷該頻道的所有線路，每一條網址都要配上「完全相同」的 #EXTINF 標頭
        for url in urls:
            # 使用標準的雙引號格式，利於 Kodi 識別
            new_info = f'#EXTINF:-1 group-title="{g_name}" tvg-name="{clean_name}",{clean_name}'
            output.append(new_info)
            output.append(url)

    # 寫入最終成品檔案
    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
    print(f"【Kodi 多線路優化完成】已成功抓取並精準分類！共輸出 {unique_channel_count} 個唯一頻道。")

if __name__ == "__main__":
    clean_and_merge_kodi_format()
