#!/usr/bin/env python3
"""FOD conference demonstration: one command for supported on-demand streams.

Usage:
    python fod_demo.py --cookie cookies.txt --wvd device.wvd --url EPISODE_URL
    python fod_demo.py --cookie cookies.txt --wvd device.wvd --url EPISODE_URL --seconds 15
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import shutil
import re
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from playwright.sync_api import sync_playwright
from subtitle_utils import hls_tracks, hls_inband_captions, dash_tracks, materialize
from pywidevine.cdm import Cdm
from pywidevine.device import Device
from pywidevine.pssh import PSSH

LICENSE_SERVER = "https://cenc.webstream.ne.jp/drmapi/wv/fujitv"
WIDEVINE_SCHEME = "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"


def launch_browser(pw):
    """Use Playwright-managed Chromium, then an installed system browser."""
    selected=os.getenv("CHROME_PATH")
    if selected:
        if not Path(selected).is_file():
            raise RuntimeError(f"CHROME_PATH path not found: {selected}")
        return pw.chromium.launch(headless=True,executable_path=selected)
    failures=[]
    try:
        return pw.chromium.launch(headless=True)
    except Exception as exc:
        failures.append(type(exc).__name__)
    candidates=[]
    if sys.platform=="darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            str(Path.home()/"Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"])
    elif sys.platform.startswith("linux"):
        candidates.extend(["/usr/bin/chromium","/usr/bin/chromium-browser",
                           "/usr/bin/google-chrome"])
    for executable in ("chromium","chromium-browser","google-chrome","chrome"):
        resolved=shutil.which(executable)
        if resolved:
            candidates.append(resolved)
    for executable in dict.fromkeys(candidates):
        if not Path(executable).is_file():
            continue
        try:
            options={"headless":True,"executable_path":executable}
            if sys.platform.startswith("linux"):
                options["args"]=["--no-sandbox"]
            return pw.chromium.launch(**options)
        except Exception as exc:
            failures.append(f"{Path(executable).name}:{type(exc).__name__}")
    raise RuntimeError(
        "Chromiumを起動できません。python -m playwright install chromium "
        "を実行するか、CHROME_PATHでブラウザの実行ファイルを指定してください。"
        " 詳細: " + ", ".join(failures[-4:]))


def media_executable(name):
    """Find ffmpeg/ffprobe on macOS Homebrew, Linux and custom installs."""
    key="FOD_FFMPEG_BIN" if name=="ffmpeg" else "FOD_FFPROBE_BIN"
    override=os.getenv(key)
    if override:
        resolved=override if Path(override).is_file() else shutil.which(override)
        if not resolved:
            raise RuntimeError(f"{key} executable not found: {override}")
        return str(resolved)
    candidates=[]
    if sys.platform.startswith("linux"):
        candidates.append(f"/usr/bin/{name}")
    candidates.append(shutil.which(name))
    if sys.platform=="darwin":
        candidates.extend([f"/opt/homebrew/bin/{name}",f"/usr/local/bin/{name}"])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError(
        f"{name} が見つかりません。macOS: brew install ffmpeg、"
        "Debian/Ubuntu: sudo apt-get install ffmpeg")

def arguments():
    parser = argparse.ArgumentParser(description="FOD発表用：配信方式を自動判別して動画を保存")
    parser.add_argument("--cookie", type=Path, required=True, help="Netscape形式のCookieファイル")
    parser.add_argument("--wvd", type=Path, required=True, help="Widevineデバイスファイル")
    parser.add_argument("--url", required=True, help="FODのシリーズまたはエピソードページURL")
    parser.add_argument("--seconds", type=float, help="指定秒数だけ保存。省略すると全編")
    parser.add_argument("--output", type=Path, default=Path("Shows"), help="Jellyfinテレビ番組ライブラリのルートフォルダ（既定: ./Shows）")
    parser.add_argument("--list-only", action="store_true", help="シリーズ内のエピソードを一覧表示して終了")
    parser.add_argument("--episodes", help="シリーズで指定した話数のみ（例: 1,3-5）")
    parser.add_argument("--overwrite", action="store_true", help="既存の正常な動画も再取得する")
    parser.add_argument("--no-subtitles", action="store_true", help="字幕の自動取得・埋め込みを無効にする")
    parser.add_argument("--season", type=int, default=1, help="Jellyfinシーズン番号（既定: 1、特別編は0）")
    parser.add_argument("--year", type=int, help="作品フォルダの制作・公開年（自動検出できない場合に指定）")
    args = parser.parse_args()
    for name in ("cookie", "wvd"):
        value=getattr(args,name)
        if not value.is_file():parser.error(f"{name}ファイルが見つかりません: {value}")
    address=urlsplit(args.url)
    series_match = re.fullmatch(r"/title/([0-9a-zA-Z]+)/?",address.path)
    episode_match = re.fullmatch(r"/title/([0-9a-zA-Z]+)/([0-9a-zA-Z]+)/?",address.path)
    if address.scheme!="https" or address.hostname!="fod.fujitv.co.jp" or not (series_match or episode_match):
        parser.error("--url にはFODのシリーズまたはエピソードページURLを指定してください")
    if args.seconds is not None and not 1 <= args.seconds <= 3600:
        parser.error("--seconds は1〜3600の範囲で指定してください")
    args.is_series=bool(series_match)
    args.series_id=(series_match or episode_match).group(1)
    if args.season<0 or args.season>999:
        parser.error("--season は0〜999で指定してください")
    if args.year is not None and not 1900<=args.year<=2100:
        parser.error("--year は1900〜2100で指定してください")
    if (args.list_only or args.episodes) and not args.is_series:
        parser.error("--list-only、--episodes はシリーズURLで使用してください")
    return args

def cookie_list(filepath):
    jar=http.cookiejar.MozillaCookieJar()
    jar.load(str(filepath),ignore_discard=True,ignore_expires=False)
    current=int(time.time())
    data=[]
    for c in jar:
        if c.is_expired(current):continue
        obj={"name":c.name,"value":c.value,"domain":c.domain,"path":c.path or "/",
             "secure":c.secure,"httpOnly":bool(c._rest.get("HttpOnly") is not None)}
        if c.expires:obj["expires"]=int(c.expires)
        data.append(obj)
    if not data:raise RuntimeError("有効なCookieがありません")
    return jar,data

def authorized_manifest(page_url, cookies):
    # Register the listener BEFORE navigation, then wait for a valid response
    # rather than relying on a fixed 6.5-second delay.
    responses = []
    manifests = []
    errors = []
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        try:
            context = browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo")
            context.add_cookies(cookies)
            page = context.new_page()
            def got_response(response):
                try:
                    path = urlsplit(response.url).path
                    if path == "/apps/api/1/auth/contents/web":
                        if response.status != 200:
                            errors.append(f"再生認可API: HTTP {response.status}")
                            return
                        data = response.json()
                        if isinstance(data, dict) and data.get("url"):
                            responses.append({
                                "url": data.get("url"), "ticket": data.get("ticket", "")})
                        else:
                            errors.append("再生認可APIが動画URLを返しませんでした")
                    elif path.endswith(".m3u8") and response.status == 200:
                        manifests.append(response.url)
                except Exception as e:
                    errors.append(f"再生情報の応答処理: {type(e).__name__}")
            page.on("response", got_response)

            for attempt in range(2):
                if attempt == 0:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
                else:
                    page.reload(wait_until="domcontentloaded", timeout=45000)
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    for item in reversed(responses):
                        uri = urlsplit(item["url"])
                        if uri.scheme == "https" and uri.path.lower().endswith((".m3u8", ".mpd")):
                            return item
                    if manifests:
                        return {"url": manifests[-1], "ticket": ""}
                    page.wait_for_timeout(350)
            reason = "; ".join(errors[-3:]) if errors else "再生認可APIから配信情報を確認できません"
            raise RuntimeError(
                "動画配信情報の取得に失敗しました（ページ再読み込み後も応答なし）。"
                + reason)
        finally:
            browser.close()

def get(session,url,range_header=None,stream=False):
    opts={"timeout":30,"headers":{"Referer":"https://fod.fujitv.co.jp/"}}
    if range_header:opts["headers"]["Range"]="bytes="+range_header
    response=session.get(url,stream=stream,**opts)
    response.raise_for_status()
    if range_header and response.status_code!=206:
        response.close()
        raise RuntimeError("動画サーバーが範囲取得に対応していません")
    return response if stream else response.content

def hls_attributes(line):
    return {k:v.strip('"') for k,v in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]+)',line)}

def hls_download(session,master_url,seconds,tempdir,notify):
    master=get(session,master_url).decode("utf-8-sig")
    lines=[l.strip() for l in master.splitlines() if l.strip()]
    choices=[]
    for i,line in enumerate(lines[:-1]):
        if line.startswith("#EXT-X-STREAM-INF:"):
            meta=hls_attributes(line.split(":",1)[1])
            choices.append((int(meta.get("BANDWIDTH","0")),urljoin(master_url,lines[i+1])))
    playlist_url=max(choices)[1] if choices else master_url
    playlist=get(session,playlist_url).decode("utf-8-sig")
    items=[l.strip() for l in playlist.splitlines() if l.strip()]
    seq=0;dur=None;key_uri=None;iv=None;segments=[]
    for item in items:
        if item.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            seq=int(item.split(":",1)[1])
        elif item.startswith("#EXT-X-KEY:"):
            meta=hls_attributes(item.split(":",1)[1])
            if meta.get("METHOD") not in ("AES-128","NONE"):
                raise RuntimeError("この動画の暗号化方式に未対応です")
            key_uri=urljoin(playlist_url,meta["URI"]) if meta.get("METHOD")=="AES-128" else None
            iv=meta.get("IV")
        elif item.startswith("#EXTINF:"):
            dur=float(item.split(":",1)[1].split(",",1)[0])
        elif not item.startswith("#") and dur is not None:
            segments.append({"url":urljoin(playlist_url,item),"dur":dur,"seq":seq+len(segments),"key":key_uri,"iv":iv})
            dur=None
    if not segments:raise RuntimeError("この動画のセグメントがありません")
    chosen=[];duration=0
    for seg in segments:
        chosen.append(seg);duration+=seg["dur"]
        if seconds is not None and duration>=seconds+1:break
    dest=tempdir/"stream.ts";keys={}
    with dest.open("wb") as outfile:
        for i,item in enumerate(chosen,1):
            encrypted=get(session,item["url"])
            if item["key"]:
                if item["key"] not in keys:keys[item["key"]]=get(session,item["key"])
                key=keys[item["key"]]
                if len(key)!=16 or len(encrypted)%16:raise RuntimeError("暗号化データの形式が正しくありません")
                ivbytes=bytes.fromhex(item["iv"].removeprefix("0x")) if item["iv"] else item["seq"].to_bytes(16,"big")
                decipher=Cipher(algorithms.AES(key),modes.CBC(ivbytes)).decryptor()
                payload=decipher.update(encrypted)+decipher.finalize()
                n=payload[-1]
                if 1<=n<=16 and payload.endswith(bytes([n])*n):payload=payload[:-n]
            else:payload=encrypted
            if payload[:1]!=b"\x47" or len(payload)%188:
                raise RuntimeError("メディアデータの整合性を確認できません")
            outfile.write(payload)
            if (i%max(1,len(chosen)//8)==0 or i==len(chosen)):
                notify(f"取得中：{int(i*100/len(chosen))}%")
    return {"video":dest},len(chosen)

def read_sidx(index,last_byte):
    if index[4:8]!=b"sidx":raise RuntimeError("動画インデックスが不正です")
    version=index[8]; pos=12
    _,scale=struct.unpack_from(">II",index,pos);pos+=8
    if version==0:_,first=struct.unpack_from(">II",index,pos);pos+=8
    elif version==1:_,first=struct.unpack_from(">QQ",index,pos);pos+=16
    else:raise RuntimeError("動画インデックスの形式に未対応です")
    count=struct.unpack_from(">H",index,pos+2)[0];pos+=4
    start=last_byte+1+first;refs=[]
    for i in range(count):
        b,d,_=struct.unpack_from(">III",index,pos+12*i)
        if b&0x80000000:raise RuntimeError("動画インデックスの階層形式に未対応です")
        size=b&0x7fffffff
        refs.append((start,start+size-1,d/scale));start+=size
    return refs

def dash_download(session,mpd_url,root,seconds,tempdir,notify):
    results={}
    for elem in root.iter():
        if not elem.tag.endswith("AdaptationSet"):continue
        mime=elem.attrib.get("mimeType","")
        kind="video" if mime.startswith("video/") else "audio" if mime.startswith("audio/") else None
        if not kind:continue
        rep=next((x for x in elem if x.tag.endswith("Representation")),None)
        if rep is None:continue
        base=next((x.text for x in rep if x.tag.endswith("BaseURL")),None)
        block=next((x for x in rep if x.tag.endswith("SegmentBase")),None)
        if not base or block is None:raise RuntimeError("この動画の配信方式に未対応です")
        init=next((x.attrib.get("range") for x in block if x.tag.endswith("Initialization")),None)
        if not init:raise RuntimeError("動画初期化データがありません")
        start,end=map(int,block.attrib["indexRange"].split("-"))
        media=urljoin(mpd_url,base)
        index=get(session,media,f"{start}-{end}")
        refs=read_sidx(index,end)
        selected=[];total=0
        for a,b,duration in refs:
            selected.append((a,b));total+=duration
            if seconds is not None and total>=seconds+1:break
        if not selected:raise RuntimeError("動画データがありません")
        ini_start,_=map(int,init.split("-"))
        destination=tempdir/f"encrypted_{kind}.mp4"
        with destination.open("wb") as file:
            file.write(get(session,media,f"{ini_start}-{end}"))
            with get(session,media,f"{end+1}-{selected[-1][1]}",stream=True) as response:
                for chunk in response.iter_content(1024*1024):
                    if chunk:file.write(chunk)
        results[kind]=destination
        notify(f"取得中：{50 if kind=='video' else 100}%")
    if not ("video" in results and "audio" in results):
        raise RuntimeError("映像・音声の取得に失敗しました")
    return results,len(results)

def widevine_keys(session,manifest_xml,device_path,ticket):
    protected=next((e for e in manifest_xml.iter() if e.tag.endswith("ContentProtection")
         and WIDEVINE_SCHEME in e.attrib.get("schemeIdUri","")),None)
    pssh=next((x.text.strip() for x in protected if x.tag.lower().endswith("pssh") and (x.text or "").strip()),None) if protected is not None else None
    if not pssh:raise RuntimeError("この動画に必要な保護情報がありません")
    device=Device.load(device_path)
    cdm=Cdm.from_device(device);sid=cdm.open()
    try:
        challenge=cdm.get_license_challenge(sid,PSSH(pssh))
        response=session.post(LICENSE_SERVER,params={"custom_data":ticket},data=challenge,
                 headers={"Content-Type":"application/octet-stream","Origin":"https://fod.fujitv.co.jp"},timeout=20)
        response.raise_for_status()
        cdm.parse_license(sid,response.content)
        keys=[item.key.hex() for item in cdm.get_keys(sid) if str(item.type).upper()=="CONTENT"]
        if not keys:raise RuntimeError("再生ライセンスを取得できませんでした")
        return keys
    finally:cdm.close(sid)



def subtitle_language(language):
    primary=(language or "und").lower().split("-",1)[0].split("_",1)[0]
    return {"ja":"jpn","en":"eng","ko":"kor","zh":"zho",
            "fr":"fra","de":"deu","es":"spa","it":"ita","pt":"por",
            "ru":"rus","und":"und"}.get(primary, primary if len(primary)==3 else "und")


def available_subtitles(session, mode, manifest_url, manifest_xml, folder,
                        seconds_limit, notify):
    """Find accessible subtitle text tracks and prepare a muxable SRT per language."""
    if mode=="hls":
        master=get(session,manifest_url).decode("utf-8-sig")
        choices=hls_tracks(master,manifest_url)
        if not choices and hls_inband_captions(master):
            notify("注意：映像内字幕（CC）が宣言されていますが、独立した字幕ファイルはありません。")
    else:
        choices=dash_tracks(manifest_xml,manifest_url)
    if not choices:
        notify("独立した字幕トラックは検出されませんでした。")
        return [],True
    notify(f"字幕トラックを検出しました：{len(choices)}件")
    results=[]
    errors=[]
    urls=set()
    for idx,track in enumerate(choices[:8]):
        if track.url in urls:
            continue
        urls.add(track.url)
        directory=folder/f"caption_{idx+1}"
        directory.mkdir(mode=0o700,exist_ok=True)
        try:
            path,cue_count=materialize(
                track,lambda url:get(session,url),directory,seconds_limit)
        except Exception as exc:
            errors.append(f"{track.name}: {type(exc).__name__} - {str(exc).split('?')[0][:100]}")
            continue
        results.append({"path":path,"language":subtitle_language(track.language),
                        "name":track.name,"cues":cue_count})
        notify(f"字幕を取得しました：{track.name}（{cue_count}行）")
    if errors:
        for message in errors[:5]:
            notify("字幕の取得に失敗：" + message)
        if not results:
            raise RuntimeError("字幕は検出されましたが取得できませんでした。"
                               "詳細："+"; ".join(errors[:2])+
                               "。字幕なしで続ける場合は --no-subtitles を指定してください")
    return results,True


def transcode(media, output, seconds, keys=None, subtitles=None):
    # The previously selected static ffmpeg can leave an incomplete MP4 when
    # full-episode muxing fails. Keep the final filename untouched until verified.
    ffmpeg_bin = media_executable("ffmpeg")
    candidate = output.with_name("." + output.stem + ".partial.mp4")
    diagnostic = output.with_suffix(".ffmpeg.log")
    candidate.unlink(missing_ok=True)
    cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "warning", "-nostdin", "-y"]
    subtitles=subtitles or []
    if "audio" in media:
        if not keys:
            raise RuntimeError("映像の復号情報がありません")
        cmd += ["-decryption_key", keys[0], "-i", str(media["video"]),
                "-decryption_key", keys[-1], "-i", str(media["audio"])]
        maps=["-map","0:v:0","-map","1:a:0"]
        subtitle_start_input=2
    else:
        cmd += ["-i", str(media["video"])]
        maps=["-map","0:v:0","-map","0:a:0?"]
        subtitle_start_input=1
    for track in subtitles:
        cmd += ["-i",str(track["path"])]
    cmd += maps
    for i,track in enumerate(subtitles):
        cmd += ["-map",f"{subtitle_start_input+i}:0"]
    if seconds is not None:
        cmd += ["-t", str(seconds)]
    cmd += ["-c", "copy"]
    if subtitles:
        cmd += ["-c:s","mov_text"]
        for i,track in enumerate(subtitles):
            cmd += [f"-metadata:s:s:{i}",f"language={track['language']}",
                    f"-metadata:s:s:{i}",f"title={track['name']}"]
    # Only MPEG-TS inputs carry AAC ADTS framing. Applying this filter to
    # already muxed MP4 inputs can silently remove audio packets.
    source_media=Path(media["video"])
    with source_media.open("rb") as handle:
        ts_input=(handle.read(1)==bytes([0x47]))
    if "audio" not in media and ts_input:
        cmd += ["-bsf:a", "aac_adtstoasc"]
    # All modes use an ordinary MP4 with a complete moov sample index.
    # Fragmented MP4 could be reported as just one ~4 s fragment by some players.
    # -movflags +faststart moves the finalized index to the front after muxing.
    cmd += ["-movflags", "+faststart"]
    cmd += ["-f", "mp4", str(candidate)]
    diagnostic.unlink(missing_ok=True)
    try:
        try:
            result = subprocess.run(cmd, capture_output=True,
                                    timeout=3600 if seconds is None else 120)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("MP4保存が時間切れになりました") from exc
        stderr = result.stderr.decode("utf-8", "replace")[-16000:]
        for media_path in media.values():
            stderr = stderr.replace(str(media_path), "[temporary input]")
        if result.returncode != 0:
            details = ("FFmpeg: " + str(ffmpeg_bin) + "\n"
                       + "exit_code: " + str(result.returncode) + "\n"
                       + stderr + "\n")
            diagnostic.write_text(details, encoding="utf-8")
            os.chmod(diagnostic, 0o600)
            reason = stderr.strip().splitlines()[-1] if stderr.strip() else "詳細なし"
            raise RuntimeError(
                f"MP4保存に失敗しました（終了コード={result.returncode}）。"
                f"原因: {reason[:220]}。ログ: {diagnostic}")
        try:
            check = subprocess.run(
                [ffmpeg_bin, "-hide_banner", "-loglevel", "error",
                 "-i", str(candidate), "-t",
                 str(seconds) if seconds is not None else "3",
                 "-f", "null", "-"],
                capture_output=True, timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("生成動画の再生検証が時間切れになりました") from exc
        if check.returncode != 0:
            err = check.stderr.decode("utf-8", "replace")[-2000:]
            diagnostic.write_text("Decode check failed, exit="
                                  + str(check.returncode) + "\n" + err,
                                  encoding="utf-8")
            os.chmod(diagnostic, 0o600)
            raise RuntimeError(
                f"動画検証に失敗しました（終了コード={check.returncode}）。"
                f"ログ: {diagnostic}")
        # Confirm a normal MP4 index and both media tracks before publishing.
        # Fragmented MP4 may show only ~4 seconds in media players despite
        # FFprobe inferring a full program duration from its fragments.
        probe=subprocess.run(
            [media_executable("ffprobe"),"-v","error",
             "-show_entries","format=duration,format_name:stream=codec_type",
             "-of","json",str(candidate)],
            capture_output=True,text=True,timeout=45)
        if probe.returncode!=0:
            raise RuntimeError("保存動画のメタデータを読み取れませんでした")
        metadata=json.loads(probe.stdout)
        stream_types={x.get("codec_type") for x in metadata.get("streams",[])}
        length=float(metadata.get("format",{}).get("duration") or 0)
        if not {"video","audio"}.issubset(stream_types):
            raise RuntimeError("映像と音声の両方が正常に保存されていません")
        if subtitles and sum(track.get("codec_type")=="subtitle"
                             for track in metadata.get("streams",[]))<len(subtitles):
            raise RuntimeError("検出した字幕がMP4に埋め込まれていません")
        if seconds is not None and length<min(seconds*0.85,seconds-0.2):
            raise RuntimeError(f"保存動画の長さが不足しています（{length:.2f}秒）")
        # The short initial MP4 area must contain the full moov sample index
        # and must not start with moof fragments as the previous output did.
        with candidate.open("rb") as handle:
            header=handle.read(min(candidate.stat().st_size,8_000_000))
        if b"moov" not in header or b"moof" in header[:4096]:
            raise RuntimeError("MP4索引の互換性を確認できませんでした")
        os.chmod(candidate, 0o600)
        os.replace(candidate, output)
    finally:
        candidate.unlink(missing_ok=True)


def safe_name(value, max_bytes=140):
    """Remove Jellyfin-reserved and cross-platform filesystem characters."""
    invalid=set('<>:"/|?*') | {chr(92)}
    text="".join(" " if c in invalid or ord(c)<32 or ord(c)==127 else c
                 for c in str(value))
    cleaned=" ".join(text.split()).strip(" .") or "Unknown"
    result=[];size=0
    for char in cleaned:
        length=len(char.encode("utf8"))
        if size+length>max_bytes:
            break
        result.append(char)
        size+=length
    return "".join(result).rstrip(" .") or "Unknown"


def episode_title(label):
    """Remove FOD episode numbering and displayed running time."""
    label=re.sub(r"^\s*第\s*[0-9０-９]+\s*話\s*[-：:・]?\s*",
                 "", label or "")
    label=re.sub(r"\s*(?:[0-9０-９]+時間)?[0-9０-９]+分(?:[0-9０-９]+秒)?\s*$",
                 "", label)
    return safe_name(label,max_bytes=135) if label.strip() else ""


def jellyfin_paths(library_root, series_title, year, season, index, title):
    """TV-show layout: Show (Year)/Season 01/Show S01E01 - Title.mp4."""
    series_title=safe_name(series_title,max_bytes=100)
    show_folder=series_title+(f" ({year})" if year else "")
    season_folder=f"Season {season:02d}"
    prefix=f"{series_title} S{season:02d}E{index:02d}"
    episode=episode_title(title)
    stem=safe_name(prefix+(" - "+episode if episode else ""),max_bytes=215)
    return Path(library_root)/show_folder/season_folder/(stem+".mp4")


def library_root_from_output(output):
    root=Path(output).expanduser().resolve()
    if root.suffix.lower() in (".mp4",".mkv",".avi",".mov"):
        print(f"Jellyfin形式で保存するため、--output はフォルダとして扱います: {root.parent}")
        return root.parent
    if root.exists() and not root.is_dir():
        raise ValueError("--output にはJellyfin用の保存フォルダを指定してください")
    return root


def detect_year(series_body):
    match=re.search(
        r"(?m)^\s*[0-9０-９]+\s*エピソード[^\n]{0,80}?\b((?:19|20)\d{2})\b",
        series_body or "")
    return int(match.group(1)) if match else None


def discover_series(page_url, cookies, series_id):
    """Discover episode links displayed by this specific series page."""
    episodes = []
    seen = set()
    target = re.compile(r"^/title/" + re.escape(series_id) + r"/([0-9a-zA-Z]+)/?$")
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        try:
            context = browser.new_context(locale="ja-JP",timezone_id="Asia/Tokyo")
            context.add_cookies(cookies)
            page = context.new_page()
            page.goto(page_url,wait_until="domcontentloaded",timeout=45000)
            page.wait_for_timeout(4000)
            title=page.title().split("｜",1)[0].strip()
            year=detect_year(page.locator("body").inner_text(timeout=5000))
            for _ in range(5):
                anchors=page.locator("a[href]").evaluate_all(
                    r"""items => items.map(a => ({href:a.getAttribute('href') || '',
                    title:(a.innerText || a.textContent || '').trim().replace(/\s+/g,' ').slice(0,180)}))""")
                for entry in anchors:
                    href=urljoin(page_url,entry["href"])
                    target_url=urlsplit(href)
                    if target_url.hostname!="fod.fujitv.co.jp":
                        continue
                    match=target.fullmatch(target_url.path)
                    if not match or match.group(1) in seen:
                        continue
                    seen.add(match.group(1))
                    episodes.append({
                        "url":urljoin("https://fod.fujitv.co.jp",target_url.path.rstrip("/")+"/"),
                        "episode_id":match.group(1),
                        "title":entry["title"].strip()})
                page.evaluate("window.scrollTo(0,document.body.scrollHeight)")
                page.wait_for_timeout(500)
            if not episodes:
                raise RuntimeError("シリーズページからエピソード一覧を取得できませんでした")
            # FOD usually displays these chronologically, but numeric episode
            # IDs give a stable filename and deterministic resumption order.
            episodes.sort(key=lambda item: item["episode_id"])
            return title, episodes, year
        finally:
            browser.close()


def parse_selected_episodes(spec,total):
    if not spec:
        return set(range(1,total+1))
    indexes=set()
    for item in spec.split(","):
        item=item.strip()
        match=re.fullmatch(r"(\d+)(?:-(\d+))?",item)
        if not match:
            raise ValueError("--episodes には話数を1,3-5形式で指定してください")
        first=int(match.group(1))
        last=int(match.group(2) or first)
        if first<1 or last<first or last>total:
            raise ValueError(f"話数の指定が範囲外です（全{total}話）")
        indexes.update(range(first,last+1))
    return indexes


def valid_existing_mp4(path, requested_seconds):
    if not path.is_file() or path.stat().st_size<16_000:
        return False
    try:
        with path.open("rb") as handle:
            head=handle.read(min(8_000_000,path.stat().st_size))
        if head[4:8]!=b"ftyp" or b"moov" not in head or b"moof" in head[:4096]:
            return False
        cmd=[media_executable("ffprobe"),"-v","error","-show_entries",
             "format=duration:stream=codec_type","-of","json",str(path)]
        data=json.loads(subprocess.run(
            cmd,check=True,capture_output=True,text=True,timeout=40).stdout)
        types={stream.get("codec_type") for stream in data.get("streams",[])}
        dur=float(data.get("format",{}).get("duration") or 0)
        minimum=50 if requested_seconds is None else max(0.5,requested_seconds*0.85)
        return {"video","audio"}<=types and dur>=minimum
    except (OSError,ValueError,subprocess.SubprocessError):
        return False


def download_episode(args,episode_url,dest,jar,cookies, prefix=""):
    begin=time.perf_counter()
    dest=dest.expanduser().resolve()
    dest.parent.mkdir(parents=True,exist_ok=True)
    log=lambda message:print(prefix+message,flush=True)
    report={"status":"failed","video_url_path":urlsplit(episode_url).path,
            "requested_seconds":args.seconds,"output":str(dest)}
    try:
        log("1/3 動画を確認しています…")
        playback=authorized_manifest(episode_url,cookies)
        stream_url=playback["url"]
        ext=urlsplit(stream_url).path.lower()
        if ext.endswith(".mpd"):mode="dash"
        elif ext.endswith(".m3u8"):mode="hls"
        else:raise RuntimeError("動画の配信方式を判別できません")
        session=requests.Session()
        retry=Retry(total=2,connect=2,read=2,status=2,backoff_factor=0.35,
                    status_forcelist=(429,500,502,503,504),
                    allowed_methods=frozenset(("GET","HEAD")))
        session.mount("https://",HTTPAdapter(max_retries=retry))
        session.headers["User-Agent"]="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/154 Safari/537.36"
        session.cookies=jar
        log("2/3 動画データを取得しています…")
        with tempfile.TemporaryDirectory(prefix="fod-demo-",dir=str(dest.parent)) as temp:
            folder=Path(temp)
            if mode=="dash":
                manifest=ET.fromstring(get(session,stream_url))
                keys=widevine_keys(session,manifest,args.wvd,playback["ticket"])
                media,count=dash_download(session,stream_url,manifest,args.seconds,folder,log)
            else:
                keys=None
                media,count=hls_download(session,stream_url,args.seconds,folder,log)
            subtitles=[]
            if not args.no_subtitles:
                subtitles,_=available_subtitles(session,mode,stream_url,
                    manifest if mode=="dash" else None,folder,args.seconds,log)
            report["subtitle_checked"]=not args.no_subtitles
            report["subtitle_tracks"]=[{"language":s["language"],
                                        "name":s["name"],"cues":s["cues"]}
                                       for s in subtitles]
            log("3/3 動画を保存しています…")
            transcode(media,dest,args.seconds,keys,subtitles=subtitles)
        report.update({"status":"success","source_type":mode,"bytes":dest.stat().st_size,
                       "elapsed_seconds":round(time.perf_counter()-begin,2)})
        log("完了しました")
        log("保存先："+str(dest))
        log("処理時間："+str(report["elapsed_seconds"])+"秒")
        return report
    except Exception as exc:
        report.update({"error_type":type(exc).__name__,
                       "error":str(exc).split("?")[0][:180]})
        log("エラー："+str(exc).split("?")[0][:180])
        return report
    finally:
        report["elapsed_seconds"]=round(time.perf_counter()-begin,2)
        path=dest.with_suffix(".json")
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        os.chmod(path,0o600)



def main():
    args=arguments()
    os.umask(0o077)
    try:
        jar,cookies=cookie_list(args.cookie)
        series_url=f"https://fod.fujitv.co.jp/title/{args.series_id}/"
        print("シリーズ情報を確認しています…",flush=True)
        title, all_episodes, detected_year=discover_series(series_url,cookies,args.series_id)
        year=args.year if args.year is not None else detected_year
        root=library_root_from_output(args.output)
        if args.is_series:
            positions=parse_selected_episodes(args.episodes,len(all_episodes))
            chosen=[(i,item) for i,item in enumerate(all_episodes,1) if i in positions]
        else:
            requested=urlsplit(args.url).path.rstrip("/")
            chosen=[(i,item) for i,item in enumerate(all_episodes,1)
                    if urlsplit(item["url"]).path.rstrip("/")==requested]
            if not chosen:
                raise RuntimeError("シリーズ一覧に対象エピソードが見つかりません。正しいシリーズURLを確認してください")
        print(f"作品：{title}"+(f" ({year})" if year else "")+
              f" / Season {args.season:02d} / 全{len(all_episodes)}話 / 対象{len(chosen)}話")
        targets=[(i,item,jellyfin_paths(root,title,year,args.season,i,item["title"]))
                 for i,item in chosen]
        for i,item,path in targets:
            print(f"  {i:02d}: {item['title'][:90] or item['episode_id']} -> {path.name}")

        if args.list_only:
            print("一覧表示が完了しました。")
            return 0
        show_directory=targets[0][2].parent.parent
        summary_path=show_directory/"series_results.json"
        result={"series_id":args.series_id,"series_title":title,
                "year":year,"season":args.season,
                "episode_count":len(all_episodes),"selected":len(chosen),
                "requested_seconds":args.seconds,"episodes":[]}
        failures=0
        for i,item,dest in targets:
            print(f"\n[{i}/{len(all_episodes)}] {item['title'][:80] or item['episode_id']}",flush=True)
            already_valid=(not args.overwrite and valid_existing_mp4(dest,args.seconds))
            if already_valid and not args.no_subtitles:
                try:
                    prior=json.loads(dest.with_suffix(".json").read_text(encoding="utf8"))
                    already_valid=bool(prior.get("subtitle_checked",False))
                except (OSError,ValueError):
                    already_valid=False
            if already_valid:
                print("既に保存済みのためスキップします。")
                entry={"episode":i,"id":item["episode_id"],"status":"skipped",
                       "url":item["url"],"output":str(dest)}
            else:
                report=download_episode(args,item["url"],dest,jar,cookies,prefix="  ")
                entry={"episode":i,"id":item["episode_id"],"url":item["url"],**report}
                if report["status"]!="success":
                    failures+=1
            result["episodes"].append(entry)
            show_directory.mkdir(parents=True,exist_ok=True)
            temporary=summary_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
            os.chmod(temporary,0o600)
            os.replace(temporary,summary_path)
        successes=sum(item["status"] in ("success","skipped") for item in result["episodes"])
        print(f"\n処理結果：{successes}/{len(chosen)}話 成功。保存先：{show_directory}",flush=True)
        return 1 if failures else 0
    except Exception as exc:
        print("エラー："+str(exc).split("?")[0][:200],flush=True)
        return 1


if __name__=="__main__":
    sys.exit(main())
