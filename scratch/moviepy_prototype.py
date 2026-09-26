# pip install yt-dlp moviepy sanitize-filename rich
# pip install -U yt-dlp

import os
import yt_dlp
import json
import csv
import concurrent.futures
from sanitize_filename import sanitize
from moviepy import VideoFileClip, AudioFileClip, vfx, afx, CompositeVideoClip, CompositeAudioClip
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, DownloadColumn
import concurrent.futures

# Get the absolute path of the directory containing this script
script_dir = os.path.dirname(os.path.abspath(__file__))

# Safely join it with your filename
settings_path = os.path.join(script_dir, 'settings.json')

# Load JSON settings
with open(settings_path, 'r', encoding='utf-8') as f:
    json_file = json.load(f)

settings = json_file.get('settings', {})
fade_duration = settings.get('fade_duration', 2) # seconds with 2 as default
cd_url = settings.get('countdown_url')
cd_start = settings.get('countdown_start_time', 0)
cd_end = settings.get('countdown_end_time', 0)
cd_fade = settings.get('countdown_fade_duration', 1)
cd_start_offset = settings.get('countdown_start_offset', 0)
cd_end_offset = settings.get('countdown_end_offset', 0)

# Convert column letters to indices
columns = json_file.get('columns', {})
for key, value in columns.items():
    if isinstance(value, str) and len(value) == 1:
        columns[key] = ord(value.upper()) - ord('A')

# Validate file format
is_mp3_only = settings.get('mp3_only', False)
file_format = 'mp3' if is_mp3_only else 'mp4'

# Format start and end times helper
def time_to_seconds(timestr):
    parts = [int(p) for p in timestr.strip().split(':')]
    return sum(p * 60**i for i, p in enumerate(reversed(parts)))

# Fetch songs list from CSV
songs = []
with open('data/entry.csv', newline='', encoding='utf-8') as csvfile:
    reader = csv.reader(csvfile)
    for i, row in enumerate(reader):
        if i < 1 or len(row) < columns['end_ts']:
            continue  # skip header or incomplete rows
        song_name = sanitize(row[columns['song_name']])  # column C
        song_artist = sanitize(row[columns['song_artist']])  # column D
        url = row[columns['url']]  # column J
        start_ts = row[columns['start_ts']]  # column K
        end_ts = row[columns['end_ts']]    # column L
        is_mirrored = (False if row[columns['is_mirrored']] == "ใช่" else True) if len(row) > columns['is_mirrored'] else True  # column P, if exists

        if not url or not song_name or not start_ts or not end_ts:
            break  # skip if URL or song details are missing
        
        songs.append({
            'file_name': f"{song_name} - {song_artist}".strip(),
            'url': url,
            'start_time': time_to_seconds(start_ts),
            'end_time': time_to_seconds(end_ts),
            'is_mirrored': is_mirrored
        })

# Create directories if they don't exist
os.makedirs("downloads", exist_ok=True)
os.makedirs("final", exist_ok=True)

# Download helper
def download_youtube(file_name, url, progress_context=None, task_id=None):
    out_path = f"downloads/{file_name}" + (f".{file_format}" if not is_mp3_only else "")

    # Check if file already exists
    if os.path.exists(out_path + (f".{file_format}" if is_mp3_only else "")):
        if progress_context and task_id is not None:
            # Print a permanent log above the live bars
            progress_context.console.print(f"[dim green]Already exists:[/dim green] {file_name}")
            # Hide the progress bar to free up space
            progress_context.update(task_id, visible=False)
        else:
            print(f"Already exists: {file_name}")
        return out_path + (f".{file_format}" if is_mp3_only else "")

    # This hook intercepts yt-dlp's internal progress to feed the 'rich' bars
    def yt_dlp_hook(d):
        if not (progress_context and task_id is not None):
            return 
            
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            if total > 0:
                progress_context.start_task(task_id)
                progress_context.update(task_id, description=f"[yellow]Downloading: {file_name[:20]}...", total=total, completed=downloaded)
        elif d['status'] == 'finished':
            # Print a permanent log and hide the bar
            progress_context.console.print(f"[bold green]Done:[/bold green] {file_name}")
            progress_context.update(task_id, visible=False)

    # Set up yt-dlp options
    ydl_opts = {
        'outtmpl': out_path, 
        'quiet': True,
        # Hide default terminal spam if we are using the rich progress bars
        'noprogress': True if progress_context else False, 
        'compat-options': ['filename-sanitization'],
        'noplaylist': True,
        'extractor_args': {'youtube': ['player_client=default']},
    }
    
    # Attach the spy hook so the progress bar actually updates
    if progress_context and task_id is not None:
        ydl_opts['progress_hooks'] = [yt_dlp_hook]

    # Force the format to mp3 or mp4 (fixes the slow WebM issue)
    if is_mp3_only:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '0',
            }],
        })
    else:
        ydl_opts['format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if not progress_context:
            print(f"Successfully downloaded: {file_name}")
    except Exception as e:
        if progress_context and task_id is not None:
            # Print error as a permanent log and hide the broken bar
            progress_context.console.print(f"[bold red]Error downloading {file_name}:[/bold red] {e}")
            progress_context.update(task_id, visible=False)
        else:
            print(f"Error downloading {file_name}: {e}")

    return out_path + (f".{file_format}" if is_mp3_only else "")

# Define a wrapper function specifically for the thread pool
def download_worker(song_dict, progress_context):
    # Create the task ONLY when the thread actually starts processing this song
    task_id = progress_context.add_task(f"[cyan]Checking: {song_dict['file_name'][:20]}...", start=False)
    download_youtube(song_dict['file_name'], song_dict['url'], progress_context, task_id)


# ==========================================
# PHASE 1: MULTI-THREADED DOWNLOADS
# ==========================================
print("\n--- PHASE 1: Fetching Media ---")

print("Fetching countdown clip...")
countdown_path = download_youtube("!countdown", cd_url)

# Setup the Rich visual interface
progress = Progress(
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    DownloadColumn(),
    TimeRemainingColumn()
)

# Run the threaded downloads with visual bars
with progress:
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for song in songs:
            # Send the task to the worker pool WITHOUT creating a visual bar yet
            futures.append(executor.submit(download_worker, song, progress))
        
        # Wait for all 5 parallel lanes to finish
        concurrent.futures.wait(futures)

print("\n--- All Downloads Complete ---")

# ==========================================
# PHASE 2: SEQUENTIAL VIDEO EDITING
# ==========================================
print("\n--- PHASE 2: Processing Video Queue ---")

countdown_raw = VideoFileClip(countdown_path) if not is_mp3_only else AudioFileClip(countdown_path)
countdown_duration = countdown_raw.duration
cd_end = min(cd_end, countdown_duration)
base_countdown_clip = countdown_raw.subclipped(cd_start, cd_end)
base_countdown_clip = base_countdown_clip.with_effects([vfx.FadeIn(cd_fade), vfx.FadeOut(cd_fade),  afx.AudioNormalize(), afx.AudioFadeOut(cd_fade)]) if not is_mp3_only else base_countdown_clip.with_effects([afx.AudioNormalize(), afx.AudioFadeOut(cd_fade)])

final_clips = []

# Process each downloaded song
for song in songs:
    file_name = song['file_name']
    
    # We construct the expected path since we already downloaded it in Phase 1
    expected_path = f"downloads/{file_name}.{file_format}"
    
    if not os.path.exists(expected_path):
        print(f"Skipping {file_name}, file not found (download may have failed).")
        continue

    print(f"Editing {file_name}...")
    start_time = song.get('start_time', 0)
    end_time = song.get('end_time', 0)
    is_mirrored = song.get('is_mirrored', False)
    
    clip = VideoFileClip(expected_path) if not is_mp3_only else AudioFileClip(expected_path)
    duration = clip.duration

    start_time = max(0, start_time - fade_duration)
    end_time = min(duration, end_time + fade_duration)
    clip = clip.subclipped(start_time, end_time)

    clip = clip.with_effects(
        [
            vfx.FadeIn(fade_duration),
            vfx.FadeOut(fade_duration),
            afx.AudioNormalize(),
            afx.AudioFadeIn(fade_duration),
            afx.AudioFadeOut(fade_duration)
        ]
    ) if not is_mp3_only else clip.with_effects(
        [
            afx.AudioNormalize(), 
            afx.AudioFadeIn(fade_duration), 
            afx.AudioFadeOut(fade_duration)
        ]
    )

    if not is_mirrored and not is_mp3_only:
        clip = clip.with_effects([vfx.MirrorX()])
    
    countdown = base_countdown_clip.copy()
    if len(final_clips) >= 2:
        countdown = countdown.with_start(final_clips[-1].end - cd_start_offset)
    final_clips.append(countdown)
    
    clip = clip.with_start(countdown.end - cd_end_offset)
    final_clips.append(clip)

# Concatenate all final clips
if not final_clips:
    print("No clips to process. Exiting.")
    exit(0)
    
print("\n--- PHASE 3: Rendering Final File ---")
final_video = CompositeVideoClip(final_clips) if not is_mp3_only else CompositeAudioClip(final_clips)

if not is_mp3_only:
    final_video_path = f"final/final_output.{file_format}"
    final_video.write_videofile(final_video_path)
    print(f"Exporting final video to {final_video_path}...")
    
    final_audio_path = f"final/final_output.mp3"
    final_video.audio.write_audiofile(final_audio_path)
    print(f"Exporting final audio to {final_audio_path}...")
else:
    final_audio_path = f"final/final_output.{file_format}"
    final_video.write_audiofile(final_audio_path)
    print(f"Exporting final audio to {final_audio_path}...")

# Clean up downloaded and processed files
print("\nCleaning up temporary files...")
for clip in final_clips:
    clip.close()

for song in songs:
    file_name = song['file_name']
    path_to_remove = f"downloads/{file_name}.{file_format}"
    if os.path.exists(path_to_remove):
        os.remove(path_to_remove)