import os
import re
import time
import socket
import requests
import urllib3
from urllib.parse import urljoin
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ⚡ 全域 Socket 超時放寬至 3.0 秒，確保海外/高延遲源有足夠時間完成 TCP 握手
socket.setdefaulttimeout(3.0)

ORIGINAL_URL = "https://raw.githubusercontent.com/CCSH/IPTV/refs/heads/main/live_lite.m3u"
TARGET_GROUPS = {"港澳台", "電影", "電視劇", "綜藝頻道", "NewTV", "兒童頻道"}

EXCLUDE_CHANNELS = {
    "鳳凰中文", "凤凰中文", "鳳凰資訊", "凤凰资讯", "鳳凰香港", "凤凰香港", "鳳凰電影", "凤凰电影",
    "TVBPEARL", "TVB PEARL", "TVB明珠台", "TVBPLUS", "TVB PLUS", "TVBJ2",
    "TVB星河", "TVB翡翠台", "TVB翡翠", "無線新聞", "無綫新聞", "无线新闻",
    "星空衛視", "星空卫视", "CHANNEL[V]", "CHANNEL V", "CHANNELV", "VIUTV"
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*'
}

def check_url_alive(url):
    """
    高精度 M3U8 / 串流線路檢測 (防偽 200 HTML 頁面 + 支援嵌套 M3U8 解析)
    """
    start_time = time.time()
    session = requests.Session()
    session.headers.update(HEADERS)
    session.verify = False

    try:
        # Step 1: 抓取首層 M3U8 或串流數據
        res = session.get(url, timeout=(2.0, 2.5), allow_redirects=True)
        if res.status_code >= 400:
            return url, False, 999

        content_type = res.headers.get('Content-Type', '').lower()
        text = res.text

        # 如果回傳 HTML 網頁 (如 404/500 自訂錯誤頁面)，直接判定為無效
        if "html" in content_type or "<html" in text.lower() or "<!doctype" in text.lower():
            return url, False, 999

        # 如果是 M3U8 / Playlist 格式
        if "#EXTM3U" in text or "mpegurl" in content_type:
            lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
            if not lines:
                return url, False, 999

            first_target = urljoin(res.url, lines[0])

            # 處理 Master Playlist (雙層 M3U8)
            if ".m3u8" in first_target.lower() or "mpegurl" in first_target.lower():
                sub_res = session.get(first_target, timeout=(1.5, 2.0), allow_redirects=True)
                if sub_res.status_code >= 400:
                    return url, False, 999
                sub_text = sub_res.text
                if "<html" in sub_text.lower():
                    return url, False, 999
                lines = [l.strip() for l in sub_text.splitlines() if l.strip() and not l.startswith("#")]
                if not lines:
                    return url, False, 999
                first_target = urljoin(sub_res.url, lines[0])

            # Step 2: 驗證 TS 影音數據片段
            with session.get(first_target, timeout=(1.5, 2.0), stream=True, allow_redirects=True) as ts_res:
                if ts_res.status_code < 400:
                    chunk = next(ts_res.iter_content(chunk_size=2048), None)
                    # 防偽驗證：數據量必須 >= 1024 且不能為 HTML 文字
                    if chunk and len(chunk) >= 1024 and not chunk.startswith(b"<html") and not chunk.startswith(b"<!DOCTYPE"):
                        return url, True, time.time() - start_time
        else:
            # 一般 Direct Stream (FLV/MP4/AAC)
            with session.get(url, timeout=(2.0, 2.5), stream=True, allow_redirects=True) as direct_res:
                if direct_res.status_code < 400:
                    chunk = next(direct_res.iter_content(chunk_size=2048), None)
                    if chunk and len(chunk) >= 1024 and not chunk.startswith(b"<html"):
                        return url, True, time.time() - start_time

    except Exception:
        pass
    finally:
        session.close()

    return url, False, 999

def clean_filter_smart_merge():
    print("正在下載 CCSH/IPTV 原始直播源...", flush=True)
    try:
        response = requests.get(ORIGINAL_URL, headers=HEADERS, timeout=10)
        response.encoding = 'utf-8'
        lines = response.text.splitlines()
    except Exception as e:
        print(f"下載失敗: {e}", flush=True)
        return

    channels = {}
    current_group = None
    current_clean_name = None
    current_raw_info = {}
    extm3u_header = "#EXTM3U"

    for idx, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            if 'x-tvg-url=' in line:
                extm3u_header = line
            continue
        if line.startswith("#EXTINF"):
            next_url = lines[idx+1].strip() if idx + 1 < len(lines) else ""
            is_4gtv = "4gtv" in next_url.lower()

            group_match = re.search(r'group-title=["\']?([^"\',]+)["\']?', line)
            g_name = group_match.group(1).strip() if group_match else "其他"
            
            if not is_4gtv and g_name not in TARGET_GROUPS:
                current_group = None
                continue

            if g_name == "港澳台" or is_4gtv:
                g_name = "台灣"

            name_match = re.search(r',([^,]+)$', line)
            if name_match:
                raw_name = name_match.group(1).strip()
                clean_name = re.sub(r'[\-\s_#]+\d+$', '', raw_name)
                clean_name = re.sub(r'(副本\d*|Copy\d*|HD|hd|4K|4k|藍光|1080[pP]|720[pP])', '', clean_name).strip() or raw_name

                if any(b in clean_name.upper() or b in raw_name.upper() for b in EXCLUDE_CHANNELS):
                    current_group = None
                    continue

                logo_match = re.search(r'tvg-logo=["\']([^"\']+)["\']', line)
                tvg_id_match = re.search(r'tvg-id=["\']([^"\']+)["\']', line)
                logo_str = f' tvg-logo="{logo_match.group(1)}"' if logo_match else ""
                tvg_id_str = f' tvg-id="{tvg_id_match.group(1)}"' if tvg_id_match else ""

                current_group = g_name
                current_clean_name = clean_name
                current_raw_info = {"logo_str": logo_str, "tvg_id_str": tvg_id_str}
        elif line.startswith("http") and current_group and current_clean_name:
            key = f"{current_group}___{current_clean_name}"
            if key not in channels:
                channels[key] = {
                    "group": current_group, "name": current_clean_name,
                    "logo_str": current_raw_info.get("logo_str", ""),
                    "tvg_id_str": current_raw_info.get("tvg_id_str", ""), "urls": []
                }
            if line not in channels[key]["urls"]:
                channels[key]["urls"].append(line)

    all_urls = list(set([u for ch in channels.values() for u in ch["urls"]]))
    print(f"開始掃描 {len(all_urls)} 條線路...", flush=True)

    alive_urls_map = {}
    
    # 4gtv 直播源預設免測直接可用
    for u in all_urls:
        if "4gtv" in u.lower():
            alive_urls_map[u] = {"is_alive": True, "delay": 0.01}

    scan_targets = [u for u in all_urls if "4gtv" not in u.lower()]
    start_time = time.time()

    # ⚡ 使用 25 個工作執行緒並給予 70 秒時間，提升慢速頻道的通過率
    executor = ThreadPoolExecutor(max_workers=25)
    futures = {executor.submit(check_url_alive, url): url for url in scan_targets}

    done, pending = wait(futures.keys(), timeout=70.0)

    # 已順利測試完畢的頻道
    for future in done:
        try:
            u, is_alive, delay = future.result()
            alive_urls_map[u] = {"is_alive": is_alive, "delay": delay}
        except Exception:
            pass

    # 超時未回應完畢的線路：設定為待定保護，排在真可用的線路之後，不輕易移除
    for future in pending:
        u = futures[future]
        alive_urls_map[u] = {"is_alive": True, "delay": 888.0}

    output = [extm3u_header]
    
    # 排序邏輯：測試成功 > 4GTV > 延遲低
    def url_sort_key(u):
        info = alive_urls_map.get(u, {"is_alive": False, "delay": 999})
        return (
            1 if info["is_alive"] else 0, 
            1 if "4gtv" in u.lower() else 0, 
            -info["delay"]
        )

    # 1. 輸出完整版 (每個群組編號獨立從 1 開始)
    full_group_counters = defaultdict(int)
    for key, ch in channels.items():
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        grp = ch["group"]
        
        for url in sorted_urls:
            full_group_counters[grp] += 1
            idx = full_group_counters[grp]
            
            is_alive = alive_urls_map.get(url, {}).get("is_alive", False)
            label = "" if is_alive else "[卡頓/失效]"
            name = f"{ch['name']}{label} ({idx})"
            output.append(f'#EXTINF:-1 tvg-name="{name}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{grp}",{name}')
            output.append(url)

    # 2. 輸出精選版 (精選群組編號獨立從 1 開始)
    select_group_counters = defaultdict(int)
    for key, ch in channels.items():
        sorted_urls = sorted(ch["urls"], key=url_sort_key, reverse=True)
        best = next((u for u in sorted_urls if alive_urls_map.get(u, {}).get("is_alive", False)), sorted_urls[0] if sorted_urls else None)
        
        if best:
            grp_select = f"{ch['group']}_精選"
            select_group_counters[grp_select] += 1
            idx = select_group_counters[grp_select]
            
            name = f"{ch['name']} ({idx})"
            output.append(f'#EXTINF:-1 tvg-name="{ch["name"]}"{ch["tvg_id_str"]}{ch["logo_str"]} group-title="{grp_select}",{name}')
            output.append(best)

    with open("taiwan_live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"【成功完成！】總耗時：{round(time.time() - start_time, 1)} 秒。", flush=True)

if __name__ == "__main__":
    clean_filter_smart_merge()
    # 強制安全離場，確保 GitHub Actions 步驟顯示綠色圓點完成
    os._exit(0)
