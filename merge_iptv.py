import re
import requests

# 1. 精準指向 CCSH/IPTV 專案最新的原始 M3U 直播源
ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"

# 2. 您指定要精準保留的 6 大分組群組
TARGET_GROUPS = ["港澳台", "电影", "电视剧", "综艺频道", "NewTV", "儿童频道"]

def clean_and_merge_kodi_format():
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
            
        # 第一階段：精準拆解 #EXTINF 行
        if line.startswith("#EXTINF"):
            # 1. 精準提取 group-title 的內容（不論有沒有雙引號，都洗掉引號）
            group_match = re.search(r'group-title=["\']?([^"\',]+)["\']?', line)
            if group_match:
                g_name = group_match.group(1).strip()
            else:
                g_name = "其他"
                
            # 檢查這個群組是不是你要保留的
            if g_name not in TARGET_GROUPS:
                current_group = None
                current_clean_name = None
                continue
                
            # 2. 精準提取最末尾逗號後面的「真正電視台名稱」
            name_match = re.search(r',([^,]+)$', line)
            if name_match:
                raw_name = name_match.group(1).strip()
                
                # 強力清洗名稱雜質
                clean_name = raw_name
                clean_name = re.sub(r'[\-\s_#]+\d+$', '', clean_name)  # 移除末尾 -1, -2, #1
                clean_name = re.sub(r'[\s\(\（\[]+\d+[\s\)\）\]]+', '', clean_name)  # 移除 (1), （2）
                clean_name = re.sub(r'(副本\d*|Copy\d*|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name)
                clean_name = clean_name.strip()
                
                if not clean_name:
                    clean_name = raw_name
                    
                # 暫存當前合格的頻道資訊，等待下一行的網址
                current_group = g_name
                current_clean_name = clean_name
                current_raw_name = raw_name
            else:
                current_group = None
                current_clean_name = None
                
        # 第二階段：配對網址（跳過中途可能的空行）
        elif line.startswith("http"):
            if current_group and current_clean_name:
                unique_key = f"{current_group}___{current_clean_name}"
                
                if unique_key not in channels:
                    channels[unique_key] = {
                        "group": current_group,
                        "name": current_clean_name,
                        "urls": []
                    }
                
                # 防止完全相同的網址重複塞入
                if line not in channels[unique_key]["urls"]:
                    # 智慧高畫質排序
                    if any(kw in current_raw_name.upper() for kw in ["藍光", "HD", "1080", "4K"]):
                        channels[unique_key]["urls"].insert(0, line)
                    else:
                        channels[unique_key]["urls"].append(line)
            
            # 網址配對完後，重設狀態，尋找下一個 #EXTINF
            # 註：不清除 current_group 避免部分 M3U 網址連續出現的特殊狀況

    # 第三階段：重新輸出為 Kodi 專用同名多行格式
    output = ["#EXTM3U"]
    unique_channel_count = 0
    
    for unique_key, ch_data in channels.items():
        g_name = ch_data["group"]
        clean_name = ch_data["name"]
        urls = ch_data["urls"]
        
        if not urls:
            continue
            
        unique_channel_count += 1
        
        # 把所有合併的線路依序吐出來，配上完全一樣的標頭
        for url in urls:
            new_info = f'#EXTINF:-1 group-title="{g_name}" tvg-name="{clean_name}",{clean_name}'
            output.append(new_info)
            output.append(url)

    # 寫入最終成品檔案
    output_filename = "taiwan_live.m3u"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
    print(f"\n【Kodi 專用格式 - 精準對齊優化完成！】")
    print(f"成功篩選指定群組，並將重複線路合併！")
    print(f"目前共輸出 {unique_channel_count} 個獨立電視台頻道。")
    print(f"請使用產出的 「{output_filename}」 檔案匯入 Kodi IPTV Simple Client。")

if __name__ == "__main__":
    clean_and_merge_kodi_format()
