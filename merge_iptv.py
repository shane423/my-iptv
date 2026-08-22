import re
import requests

# 1. 指向 CCSH/IPTV 專案最新的原始 M3U 直播源
ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"

# 2. 精準保留的 6 大分組群組
TARGET_GROUPS = ["港澳台", "电影", "电视剧", "综艺频道", "NewTV", "儿童频道"]

def clean_and_smart_select():
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

    # 用來暫存同一個頻道的所有線路
    channel_groups = {}
    current_info = None

    print("第一階段：收集並歸類指定群組的所有線路...")
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
                
                # 清洗名稱，回復成純淨主名稱
                clean_name = re.sub(r'[\-\s_#]*\d+', '', raw_name)
                clean_name = re.sub(r'[\s\(\（\.\[]*\d+[\s\)\）\]]*', '', clean_name)
                clean_name = re.sub(r'(副本|副本\d+|Copy|Copy\d+|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name)
                clean_name = clean_name.strip()
                
                if not clean_name:
                    clean_name = raw_name
                
                group_match_sub = re.search(r'group-title="([^"]+)"', current_info)
                g_name = group_match_sub.group(1).strip() if group_match_sub else "其他"
                unique_key = f"{g_name}___{clean_name}"
                
                # 重新修正不含數字的標準名稱資訊行
                new_info = re.sub(r',([^,]+)$', f',{clean_name}', current_info)
                
                if unique_key not in channel_groups:
                    channel_groups[unique_key] = []
                
                # 將每條線路存入陣列
                channel_groups[unique_key].append({
                    "info": new_info,
                    "url": line,
                    "raw_name": raw_name
                })
                
            current_info = None

    # 第二階段：強制定位篩選引擎
    output = ["#EXTM3U"]
    print("第二階段：強制鎖定高成功率線路...")
    
    for unique_key, streams in channel_groups.items():
        best_stream = None
        
        # 【深度優化防線】：將 key 轉為小寫，確保完全鎖定 TVBS 主頻道與 TVBS新聞台家族
        upper_key = unique_key.upper()
        if "TVBS" in upper_key:
            # 優先尋找名稱中包含 "3"、"-3" 的項目
            for stream in streams:
                if "3" in stream["raw_name"] or "-3" in stream["raw_name"]:
                    best_stream = stream
                    break
            
            # 如果名字被作者改掉或找不到帶 3 的，就直接強行抓取第 3 個元素（索引值 2）
            if not best_stream and len(streams) >= 3:
                best_stream = streams[2]
                
        # 如果不是 TVBS 家族，或者上述特殊規則沒抓到，則執行一般頻道的最佳化挑選
        if not best_stream:
            if len(streams) == 1:
                best_stream = streams[0]
            else:
                highest_score = -100
                for stream in streams:
                    score = 0
                    url = stream["url"]
                    r_name = stream["raw_name"]
                    
                    if "3" in r_name or "-3" in r_name:
                        score += 50
                    if " (2)" in r_name or "-2" in r_name or " (1)" in r_name:
                        score -= 20
                    if any(x in url for x in ["/163189/", "cdn", "live", "stream"]):
                        score += 40
                    if any(x in r_name for x in ["藍光", "1080", "4K", "HD"]):
                        score += 10
                        
                    if score > highest_score:
                        highest_score = score
                        best_stream = stream

        # 最終保底機制
        if not best_stream:
            best_stream = streams[0]
            
        output.append(best_stream["info"])
        output.append(best_stream["url"])

    # 第三階段：寫入最終成品檔案
    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    print(f"【TVBS全線鎖定完成】共有 {len(channel_groups)} 個精選頻道成功輸出。")

if __name__ == "__main__":
    clean_and_smart_select()
