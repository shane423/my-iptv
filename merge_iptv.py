import re
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 嘗試載入 OpenCC 進行簡繁轉換
try:
    from opencc import OpenCC
    cc = OpenCC('s2twp')
except ImportError:
    cc = None
    print("提示：未檢測到 opencc-python-reimplemented 庫，將不會進行簡繁轉換。")

# 定義各 M3U 來源網址及其「指定抓取」的群組名稱（精確對應）
SOURCE_TARGET_GROUPS = {
    "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u": {
        "港澳台", "电影", "儿童频道"
    },
    "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_platforms.m3u": {
        "zonghe", "一起看", "原创", "原创IP"
    },
    "https://live.zbds.top/tv/iptv4.m3u": {
        "儿童频道", "电影频道"
    }
}

# 映射至 Kodi 顯示的繁體群組名稱
GROUP_NAME_MAP = {
    "港澳台": "台灣",
    "电影": "電影",
    "电影频道": "電影",
    "儿童频道": "卡通",
    "zonghe": "其他",
    "一起看": "其他",
    "原创": "其他",
    "原创IP": "其他"
}

# 定義群組的指定輸出順序
ORDERED_GROUPS = ["台灣", "電影", "卡通", "其他"]

# 定義 live_platforms.m3u 子群組的排序權重
PLATFORM_GROUP_ORDER = {
    "zonghe": 1,
    "一起看": 2,
    "原创": 3,
    "原创IP": 4
}

# 其他來源的頻道過濾黑名單（保留簡體或繁體皆可，因比對原始名稱）
EXCLUDE_CHANNELS = {
    "凤凰中文", "凤凰资讯", "凤凰香港", "凤凰电影",
    "TVBPEARL", "TVB PEARL", "TVB明珠台", "TVBPLUS", "TVB PLUS", "TVBJ2",
    "TVB星河", "TVB翡翠台", "TVB翡翠", "无线新闻",
    "星空卫视", "CHANNEL[V]", "VIUTV",
    "鳳凰中文", "鳳凰資訊", "鳳凰香港", "鳳凰電影", "無線新聞", "星空衛視"
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*'
}

def fetch_and_categorize():
    channels = {}
    extm3u_header = "#EXTM3U"

    for src_url, allowed_groups in SOURCE_TARGET_GROUPS.items():
        print(f"正在下載直播源: {src_url} ...", flush=True)
        is_zbds = "live.zbds.top" in src_url
        is_platform = "live_platforms" in src_url
        
        try:
            response = requests.get(src_url, headers=HEADERS, timeout=10)
            response.encoding = 'utf-8'
            lines = response.text.splitlines()
        except Exception as e:
            print(f"下載失敗 ({src_url}): {e}", flush=True)
            continue

        current_group = None
        current_raw_group = None
        current_display_name = None
        current_raw_info = {}

        for idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#EXTM3U"):
                if 'x-tvg-url=' in line and extm3u_header == "#EXTM3U":
                    extm3u_header = line
                continue
            if line.startswith("#EXTINF"):
                group_match = re.search(r'group-title=["\']?([^"\',]+)["\']?', line)
                raw_g_name = group_match.group(1).strip() if group_match else "其他"
                
                if raw_g_name not in allowed_groups:
                    current_group = None
                    current_raw_group = None
                    continue

                g_name = GROUP_NAME_MAP.get(raw_g_name, raw_g_name)

                name_match = re.search(r',([^,]+)$', line)
                if name_match:
                    raw_name = name_match.group(1).strip()

                    # 檢查黑名單（比對原始名稱）
                    if not (is_zbds or is_platform):
                        if any(b in raw_name for b in EXCLUDE_CHANNELS):
                            current_group = None
                            current_raw_group = None
                            continue

                    # 擷取原始的 tvg-name（若有），保留給 EPG 匹配用
                    tvg_name_match = re.search(r'tvg-name=["\']([^"\']+)["\']', line)
                    if tvg_name_match:
                        raw_tvg_name = tvg_name_match.group(1)
                    else:
                        raw_tvg_name = raw_name # 如果原本沒有，用原始名稱填補

                    # 顯示名稱轉為繁體中文（給介面看）
                    display_name = cc.convert(raw_name) if cc else raw_name

                    logo_match = re.search(r'tvg-logo=["\']([^"\']+)["\']', line)
                    tvg_id_match = re.search(r'tvg-id=["\']([^"\']+)["\']', line)
                    
                    logo_str = f' tvg-logo="{logo_match.group(1)}"' if logo_match else ""
                    tvg_id_str = f' tvg-id="{tvg_id_match.group(1)}"' if tvg_id_match else ""
                    
                    # 關鍵：保留原始簡體 tvg-name 確保 EPG 不失效
                    tvg_name_str = f' tvg-name="{raw_tvg_name}"'

                    current_group = g_name
                    current_raw_group = raw_g_name
                    current_display_name = display_name
                    current_raw_info = {
                        "logo_str": logo_str,
                        "tvg_id_str": tvg_id_str,
                        "tvg_name_str": tvg_name_str,
                        "raw_group": raw_g_name
                    }
            elif line.startswith("http") and current_group and current_display_name:
                key = f"{current_group}___{current_display_name}"
                if key not in channels:
                    channels[key] = {
                        "group": current_group,
                        "raw_group": current_raw_group,
                        "display_name": current_display_name,
                        "logo_str": current_raw_info.get("logo_str", ""),
                        "tvg_id_str": current_raw_info.get("tvg_id_str", ""),
                        "tvg_name_str": current_raw_info.get("tvg_name_str", ""),
                        "urls": []
                    }
                if line not in channels[key]["urls"]:
                    channels[key]["urls"].append(line)

    print(f"解析完成！共獲取 {len(channels)} 個頻道/電影項目，開始寫入檔案...", flush=True)

    output = [extm3u_header]

    def channel_group_sort_key(item):
        ch = item[1]
        group = ch["group"]
        group_idx = ORDERED_GROUPS.index(group) if group in ORDERED_GROUPS else 999
        sub_idx = PLATFORM_GROUP_ORDER.get(ch.get("raw_group", ""), 99)
        return (group_idx, sub_idx)

    sorted_channels = sorted(channels.items(), key=channel_group_sort_key)

    # 輸出：tvg-name 維持原樣（救回節目表），逗號後顯示名稱改為繁體
    for key, ch in sorted_channels:
        d_name = ch['display_name']
        for url in ch["urls"]:
            extinf_line = f'#EXTINF:-1{ch["tvg_name_str"]}{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{ch["group"]}",{d_name}'
            output.append(extinf_line)
            output.append(url)

    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print("【成功完成！】雙軌 M3U 檔案已儲存為 taiwan_live.m3u。", flush=True)

if __name__ == "__main__":
    fetch_and_categorize()
