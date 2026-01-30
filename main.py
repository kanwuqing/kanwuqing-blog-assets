#!/usr/bin/env python3
import os
import json
import re
import requests
from mutagen import File
from mutagen.id3 import ID3, APIC, TIT2, TPE1
from pathlib import Path
from collections import Counter

class SmartMusicManager:
    def __init__(self, music_dir="~/Music", output_dir="./music_repo"):
        self.music_dir = Path(music_dir).expanduser()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # 创建子目录
        (self.output_dir / "audio").mkdir(exist_ok=True)
        (self.output_dir / "covers").mkdir(exist_ok=True)
        (self.output_dir / "lyrics").mkdir(exist_ok=True)
        
        # 配置音乐API
        self.api_base = "http://music.163.com/api"
        
        # 常见歌手列表（可以扩展）
        self.common_artists = {
            "周杰伦", "林俊杰", "孙燕姿", "陈奕迅", "王菲", "梁静茹",
            "Taylor Swift", "Ed Sheeran", "Adele", "Bruno Mars",
            "邓紫棋", "李荣浩", "薛之谦", "毛不易", "华晨宇"
        }
        
        # 用于收集文件名中的艺术家候选
        self.artist_candidates = Counter()
        
        # 第一次扫描：收集所有可能的艺术家
        self._collect_artist_candidates()
    
    def _collect_artist_candidates(self):
        """第一次扫描，收集所有文件名中可能的艺术家"""
        print("🔍 第一阶段：分析文件名模式...")
        
        music_files = list(self.music_dir.glob("**/*.mp3")) + \
                     list(self.music_dir.glob("**/*.flac")) + \
                     list(self.music_dir.glob("**/*.wav")) + \
                     list(self.music_dir.glob("**/*.m4a"))
        
        for file_path in music_files:
            filename = file_path.stem
            parts = self._split_filename(filename)
            
            # 将每个部分都作为艺术家候选
            for part in parts:
                if len(part) > 1:  # 排除太短的部分
                    self.artist_candidates[part] += 1
        
        print(f"  收集到 {len(self.artist_candidates)} 个艺术家候选")
    
    def _split_filename(self, filename):
        """智能分割文件名，支持多种分隔符"""
        # 支持的分隔符：空格+横线+空格、横线、下划线、点等
        separators = r'[~\-_\s\.—–]+'
        parts = re.split(separators, filename)
        return [p.strip() for p in parts if p.strip()]
    
    def _is_likely_artist(self, text):
        """判断文本是否可能是艺术家名字"""
        # 策略1：检查是否在常见艺术家列表中
        if text in self.common_artists:
            return True
        
        # 策略2：检查是否包含常见艺术家关键字
        artist_keywords = ['乐队', '组合', '乐团', '合唱团', '&', 'and', 'feat', 'ft', 'featuring']
        for keyword in artist_keywords:
            if keyword in text:
                return True
        
        # 策略3：检查在候选艺术家中的频率
        if self.artist_candidates.get(text, 0) > 2:
            return True
        
        # 策略4：中文名通常2-4个字符，英文名可能包含空格
        if 2 <= len(text) <= 4 and not any(char.isdigit() for char in text):
            return True
        
        return False
    
    def _is_likely_song_title(self, text):
        """判断文本是否可能是歌曲标题"""
        # 歌名通常更长，可能包含数字、括号等
        if len(text) >= 3 and not self._is_likely_artist(text):
            return True
        
        # 包含特殊字符的更可能是歌名
        special_chars = ['(', ')', '[', ']', '《', '》', '！', '？']
        for char in special_chars:
            if char in text:
                return True
        
        return False
    
    def _parse_filename_intelligently(self, filename):
        """智能解析文件名，识别歌手和歌名"""
        parts = self._split_filename(filename)
        
        if len(parts) == 1:
            # 只有一个部分，可能是纯歌名
            return None, parts[0]
        
        elif len(parts) == 2:
            # 有两个部分，需要判断哪个是歌手哪个是歌名
            part1, part2 = parts
            
            # 计算每种可能性的得分
            score_artist_first = 0
            score_title_first = 0
            
            # 可能性1：part1是歌手，part2是歌名
            if self._is_likely_artist(part1):
                score_artist_first += 2
            if self._is_likely_song_title(part2):
                score_artist_first += 1
            
            # 可能性2：part2是歌手，part1是歌名
            if self._is_likely_artist(part2):
                score_title_first += 2
            if self._is_likely_song_title(part1):
                score_title_first += 1
            
            # 根据得分决定
            if score_artist_first > score_title_first:
                return part1, part2
            elif score_title_first > score_artist_first:
                return part2, part1
            else:
                # 平局，默认第一部分是歌手
                return part1, part2
        
        elif len(parts) >= 3:
            # 有三个或更多部分，可能是"歌手-歌名-其他"或"歌名-歌手-其他"
            # 先找出最可能是艺术家的部分
            artist_scores = []
            for i, part in enumerate(parts):
                score = 0
                if self._is_likely_artist(part):
                    score += 3
                if self.artist_candidates.get(part, 0) > 1:
                    score += 2
                if i == 0:  # 第一个位置更可能是艺术家
                    score += 1
                artist_scores.append((score, i, part))
            
            # 按得分排序
            artist_scores.sort(reverse=True)
            
            # 取最高得分作为艺术家
            best_artist_idx = artist_scores[0][1]
            artist = parts[best_artist_idx]
            
            # 剩余部分作为歌名
            title_parts = []
            for i, part in enumerate(parts):
                if i != best_artist_idx:
                    title_parts.append(part)
            
            # 清理歌名：移除重复的艺术家名
            title = " ".join(title_parts)
            title = re.sub(r'\b' + re.escape(artist) + r'\b', '', title).strip()
            title = re.sub(r'[~\-_\s\.—–]+', ' ', title).strip()
            
            # 如果歌名为空，使用第一个非艺术家部分
            if not title and title_parts:
                title = title_parts[0]
            
            return artist, title
        
        return None, filename
    
    def _clean_title(self, title, artist):
        """清理歌名，移除重复的艺术家信息"""
        if not artist or artist == "Various Artists":
            return title
        
        # 移除歌名中重复的艺术家名
        patterns = [
            r'\b' + re.escape(artist) + r'\b',
            r'[-~\s]*' + re.escape(artist) + r'[-~\s]*',
        ]
        
        cleaned_title = title
        for pattern in patterns:
            cleaned_title = re.sub(pattern, '', cleaned_title).strip()
        
        # 清理多余的分隔符
        cleaned_title = re.sub(r'[~\-_\s\.—–]+$', '', cleaned_title).strip()
        cleaned_title = re.sub(r'^[~\-_\s\.—–]+', '', cleaned_title).strip()
        
        return cleaned_title if cleaned_title else title
    
    def extract_metadata(self, file_path):
        """从音频文件提取元数据，智能选择最佳歌手信息"""
        try:
            audio = File(file_path)
            info = {
                "title": None,
                "artist": None,
                "album": None,
                "duration": 0,
                "artist_source": None
            }
            
            if audio:
                # MP3文件
                if file_path.suffix.lower() == '.mp3' and audio.tags:
                    tags = audio.tags
                    
                    # 提取标题
                    if tags.get("TIT2"):
                        info["title"] = str(tags["TIT2"]).strip()
                    elif tags.get("TIT1"):
                        info["title"] = str(tags["TIT1"]).strip()
                    elif tags.get("TIT3"):
                        info["title"] = str(tags["TIT3"]).strip()
                    
                    # 智能提取歌手
                    if tags.get("TPE1"):
                        artist = str(tags["TPE1"]).strip()
                        if '/' in artist:
                            artist = artist.split('/')[0].strip()
                        elif ';' in artist:
                            artist = artist.split(';')[0].strip()
                        info["artist"] = artist
                        info["artist_source"] = "TPE1_tag"
                        
                    elif tags.get("TPE2"):
                        info["artist"] = str(tags["TPE2"]).strip()
                        info["artist_source"] = "TPE2_tag"
                    
                    # 提取专辑
                    if tags.get("TALB"):
                        info["album"] = str(tags["TALB"]).strip()
                        
                # 获取时长
                if hasattr(audio.info, 'length'):
                    info["duration"] = int(audio.info.length)
            
            # 如果标签中没有歌手或标题，从文件名解析
            filename_artist, filename_title = self._parse_filename_intelligently(file_path.stem)
            
            if not info["title"] and filename_title:
                info["title"] = filename_title
                info["artist_source"] = "filename_parse_title"
            
            if (not info["artist"] or info["artist"] == "未知艺术家") and filename_artist:
                info["artist"] = filename_artist
                if not info["artist_source"]:
                    info["artist_source"] = "filename_parse_artist"
            
            # 如果没有标题，使用文件名
            if not info["title"]:
                info["title"] = file_path.stem
            
            # 清理标题中的重复艺术家信息
            if info["artist"] and info["title"]:
                info["title"] = self._clean_title(info["title"], info["artist"])
            
            # 如果没有艺术家，使用Various Artists
            if not info["artist"]:
                info["artist"] = "Various Artists"
                if not info["artist_source"]:
                    info["artist_source"] = "default"
            
            return info
        except Exception as e:
            print(f"  元数据提取失败: {e}")
            # 尝试从文件名解析
            filename_artist, filename_title = self._parse_filename_intelligently(file_path.stem)
            return {
                "title": filename_title or file_path.stem,
                "artist": filename_artist or "Various Artists",
                "artist_source": "error_fallback"
            }
    
    def search_lyrics(self, title, artist):
        """从公开API搜索歌词"""
        try:
            search_url = f"{self.api_base}/search/get"
            params = {
                "s": f"{title} {artist}",
                "type": 1,
                "limit": 1
            }
            response = requests.get(search_url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("result") and data["result"].get("songs"):
                    song_id = data["result"]["songs"][0]["id"]
                    
                    lrc_url = f"{self.api_base}/song/lyric?id={song_id}&lv=1"
                    lrc_resp = requests.get(lrc_url, timeout=5)
                    
                    if lrc_resp.status_code == 200:
                        lrc_data = lrc_resp.json()
                        if lrc_data.get("lrc"):
                            return lrc_data["lrc"]["lyric"]
        except:
            pass
        return None
    
    def search_cover(self, title, artist):
        """搜索专辑封面"""
        try:
            search_url = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
            params = {
                "w": f"{title} {artist}",
                "format": "json",
                "n": 3
            }
            response = requests.get(search_url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("data") and data["data"].get("song"):
                    songs = data["data"]["song"]["list"]
                    
                    # 尝试精确匹配
                    for song in songs:
                        song_title = song.get("songname", "")
                        song_artist = song.get("singer", [{}])[0].get("name", "")
                        
                        if (title in song_title or song_title in title) and \
                           (artist in song_artist or song_artist in artist):
                            album_id = song.get("albummid")
                            if album_id:
                                return f"https://y.qq.com/music/photo_new/T002R300x300M000{album_id}.jpg"
                    
                    # 使用第一个结果
                    if songs and songs[0].get("albummid"):
                        return f"https://y.qq.com/music/photo_new/T002R300x300M000{songs[0]['albummid']}.jpg"
        except:
            pass
        
        return None
    
    def sanitize_filename(self, name):
        """清理文件名，移除非法字符"""
        illegal_chars = r'[<>:"/\\|?*\x00-\x1f]'
        name = re.sub(illegal_chars, '', name)
        return name[:100].strip()
    
    def process_directory(self):
        """处理整个音乐目录"""
        music_files = list(self.music_dir.glob("**/*.mp3")) + \
                     list(self.music_dir.glob("**/*.flac")) + \
                     list(self.music_dir.glob("**/*.wav")) + \
                     list(self.music_dir.glob("**/*.m4a"))
        
        music_list = []
        
        print(f"\n🎵 找到 {len(music_files)} 个音频文件")
        print("=" * 60)
        
        for file_path in music_files:
            try:
                print(f"处理: {file_path.name}")
                
                # 提取元数据
                metadata = self.extract_metadata(file_path)
                title = metadata["title"] or file_path.stem
                artist = metadata["artist"] or "Various Artists"
                
                print(f"  解析结果: 歌手={artist}, 歌名={title}")
                
                # 清理文件名
                safe_title = self.sanitize_filename(title)
                safe_artist = self.sanitize_filename(artist)
                
                # 生成最终文件名
                if artist != "Various Artists":
                    base_filename = f"{safe_artist} - {safe_title}"
                else:
                    base_filename = safe_title
                
                # 处理重名文件
                audio_ext = file_path.suffix.lower()
                final_filename = f"{base_filename}{audio_ext}"
                audio_dest = self.output_dir / "audio" / final_filename
                
                counter = 1
                while audio_dest.exists():
                    final_filename = f"{base_filename}_{counter}{audio_ext}"
                    audio_dest = self.output_dir / "audio" / final_filename
                    counter += 1
                
                # 复制音频文件
                audio_dest.write_bytes(file_path.read_bytes())
                
                # 获取歌词
                lrc_content = None
                lrc_file = file_path.with_suffix('.lrc')
                if lrc_file.exists():
                    lrc_content = lrc_file.read_text(encoding='utf-8', errors='ignore')
                else:
                    lrc_content = self.search_lyrics(title, artist)
                    
                if lrc_content:
                    lrc_filename = f"{Path(final_filename).stem}.lrc"
                    lrc_dest = self.output_dir / "lyrics" / lrc_filename
                    lrc_dest.write_text(lrc_content, encoding='utf-8')
                    lrc_url = f"lyrics/{lrc_filename}"
                else:
                    lrc_url = None
                
                # 获取封面
                cover_url = self.search_cover(title, artist)
                if not cover_url:
                    cover_url = "/music/default_cover.jpg"
                
                # 添加到列表
                music_list.append({
                    "name": title,
                    "artist": artist,
                    "url": f"audio/{final_filename}",
                    "cover": cover_url,
                    "lrc": lrc_url,
                    "duration": metadata["duration"],
                    "artist_source": metadata.get("artist_source", "unknown"),
                    "original_filename": file_path.name
                })
                
                print(f"  ✓ 保存为: {final_filename}")
                print("-" * 40)
                
            except Exception as e:
                print(f"  处理失败: {e}")
                continue
        
        return music_list
    
    def generate_json(self, music_list):
        """生成播放列表JSON"""
        json_path = self.output_dir / "playlist.json"
        
        clean_list = []
        for song in music_list:
            clean_song = {
                "name": song["name"],
                "artist": song["artist"],
                "url": song["url"],
                "cover": song["cover"],
                "lrc": song["lrc"],
                "duration": song["duration"]
            }
            clean_list.append(clean_song)
        
        json_path.write_text(
            json.dumps(clean_list, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        print("\n" + "=" * 60)
        print("✅ 处理完成！")
        print(f"📊 共处理歌曲: {len(music_list)} 首")
        
        # 统计
        artist_sources = {}
        for song in music_list:
            source = song.get("artist_source", "unknown")
            artist_sources[source] = artist_sources.get(source, 0) + 1
        
        print(f"\n🎤 歌手信息来源统计:")
        for source, count in artist_sources.items():
            print(f"   {source}: {count} 首")
        
        with_lyrics = sum(1 for song in music_list if song.get("lrc"))
        print(f"\n📝 歌词统计: 有歌词 {with_lyrics} 首, 无歌词 {len(music_list)-with_lyrics} 首")
        
        print(f"\n💾 播放列表: {json_path}")
        
        # 显示前10首作为示例
        print(f"\n🎵 前10首歌曲示例:")
        for i, song in enumerate(music_list[:10]):
            print(f"  {i+1:2d}. {song['name'][:20]:20} - {song['artist'][:15]:15} (原: {song['original_filename'][:20]})")

if __name__ == "__main__":
    manager = SmartMusicManager(
        music_dir="./",  # 修改为你的路径
        output_dir="./music_repo"
    )
    
    print("🎵 智能音乐管理器启动")
    print("📁 正在处理音乐文件...")
    
    music_list = manager.process_directory()
    manager.generate_json(music_list)
