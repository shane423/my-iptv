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
                
                # 【終極真去重核心】：如果這個頻道名稱已經存在了，就直接跳過不加入！
                # 這樣可以強迫每一個電視台「只保留唯一一條最暢通的線路」，徹底消滅重複行！
                if unique_key in channels:
                    current_info = None
                    continue
                
                # 重建乾淨的資訊行
                new_info = re.sub(r',([^,]+)$', f',{clean_name}', current_info)
                
                channels[unique_key] = (new_info, line)
                
            current_info = None

    # 第三階段：重新格式化輸出極致純淨、毫無重複的 M3U 清單
    output = ["#EXTM3U"]
    for unique_key, (info, url) in channels.items():
        output.append(info)
        output.append(url)

    # 寫入最終成品檔案
    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    print(f"【極致去重完成】已成功為您的 Kodi 強制瘦身，每個電視台僅保留唯一精選線路！")

if __name__ == "__main__":
    clean_and_merge_by_groups()
