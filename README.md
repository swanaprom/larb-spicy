# **Let's Assemble Random Bops : LARB** <br> Spicy Variant 🌶️🔥🔥
### Utility for EN Hip Dance Club KKU

## Overview
**This project facilitates the process of creating 'Random Dance' audios/videos.**

It uses Python script batches to download, trim, and crossfade songs from online sources,
and combine them together with countdowns in between, in regard to the songs list table.

This variant offers reliability, maintainability, and efficientcy; 
Hence the variant name, **Spicy~**

## Quick Start

You need **git** and an internet connection. Everything else (the right Python, the libraries,
FFmpeg) is found or set up by the scripts, inside this folder. They ask before installing
anything outside it.

**1. Clone** the repository (any folder, spaces in the path are fine):

```
git clone <this repository's URL>
cd larb-spicy
```

**2. Set up, once** (a few minutes the first time: about 200 MB for FFmpeg):

| Windows | Linux / Mac |
| --- | --- |
| double-click `setup_once.bat`, or run `setup_once.bat` | `./setup_once.sh` |

If no suitable Python is found, it says which version to get (it installs alongside any Python
you already have) and offers to install it: `winget` on Windows, Homebrew on Mac. On Linux it
prints the command to run. After installing, open a **new** terminal and run setup again.
Running setup again later is safe and quick: it only rebuilds what's missing.

**3. Run:**

| Windows | Linux / Mac |
| --- | --- |
| `run.bat "<Google Sheet URL>"` | `./run.sh "<Google Sheet URL>"` |

On Windows you can also double-click `run.bat`: it asks for the sheet URL and keeps the window
open at the end. Options: `--rows 2-40` (only those sheet rows), `--countdown <file or YouTube
URL>`, `--verbose`. Settings are in `config/config.toml` (created on the first run from
`config/example.toml`, which explains each setting). The output lands in `workspace/output/`.

The sheet must be shared as **"Anyone with the link"** (viewer is enough).

Each run first updates yt-dlp (the YouTube downloader), because an old one is what breaks when
YouTube changes. Problems? See [docs/HANDOFF.md](docs/HANDOFF.md).