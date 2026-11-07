# fb-dl

**English** · [Tiếng Việt](README.vi.md)

> [!WARNING]
> **This project is for educational purposes only.** Only download content you are allowed to see and keep.
> Do not use it to re-upload or sell other people's content.

Download **everything** a Facebook profile or page has posted, from the very first post to today, in the
best quality, neatly sorted into folders:

- **Posts**: the text of every post, with its link, date, reactions, comments and shares
- **Photos** at full size, including big albums where Facebook only shows the first few
- **Videos and reels** in the best quality
- **Stories** of the last 24 hours
- The **Photos** and **Albums** tabs, the **avatar** and the **cover photo**

It reads the timeline in a hidden browser window, the same way you would scroll it yourself. Tested on a
profile with 942 posts going back to 2009.

## Contents

1. [Quick start](#quick-start)
2. [Install, step by step](#install-step-by-step)
3. [Log in](#log-in)
4. [Download a profile or page](#download-a-profile-or-page)
5. [What you get](#what-you-get)
6. [Stop, continue, update](#stop-continue-update)
7. [All options](#all-options)
8. [Privacy and safety](#privacy-and-safety)
9. [Log out and remove your data](#log-out-and-remove-your-data)
10. [Problems and questions](#problems-and-questions)

## Quick start

Already have Python? Open a terminal in the `fb-dl` folder and run:

```bash
pip install -r requirements.txt
python fb-dl.py --login
python fb-dl.py https://www.facebook.com/nasa
```

Put `aria2c.exe` and `ffmpeg.exe` in the same folder first for the best speed and quality
(see [step 4](#4-get-aria2c-and-ffmpeg)). Files are saved in `downloads/nasa/`.

## Install, step by step

These steps are for **Windows**. macOS and Linux work too: install `aria2` and `ffmpeg` with your
package manager (`brew install aria2 ffmpeg`, `sudo apt install aria2 ffmpeg`).

### 1. Install Python

1. Download Python 3.10 or newer from https://www.python.org/downloads/
2. Run the installer and **tick "Add python.exe to PATH"** at the bottom of the first screen, then
   click **Install Now**.
3. Check it: open **Command Prompt** or **PowerShell** and type `python --version`. You should see
   something like `Python 3.13.0`.

### 2. Get fb-dl

- **With Git:** `git clone https://github.com/loooveee/fb-dl.git`
- **Without Git:** on the GitHub page click **Code** → **Download ZIP**, then unzip it.

Then open a terminal **inside the `fb-dl` folder**. In File Explorer, open the folder, click the
address bar, type `cmd` and press Enter.

### 3. Install the Python packages

```bash
pip install -r requirements.txt
```

### 4. Get aria2c and ffmpeg

- **aria2c** downloads many photos at once, which is much faster.
- **ffmpeg** joins the best video and the best sound into one MP4. Without it, videos are saved in a
  lower quality.

fb-dl still works without them, only slower and with lower video quality.

| Tool | Download | Which file to copy into the `fb-dl` folder |
|---|---|---|
| aria2c | https://github.com/aria2/aria2/releases (the `win-64bit` zip) | `aria2c.exe` |
| ffmpeg | https://www.gyan.dev/ffmpeg/builds/ (`ffmpeg-release-essentials.zip`) | `bin\ffmpeg.exe` |

Your folder should then look like this:

```
fb-dl/
├── fb-dl.py
├── aria2c.exe
├── ffmpeg.exe
├── requirements.txt
└── README.md
```

### 5. A browser

fb-dl uses **Microsoft Edge** (already on every Windows 10 / 11) or **Google Chrome**. If you have
neither, run:

```bash
python -m playwright install chromium
```

## Log in

Facebook only shows a few posts to people who are not logged in, so log in once:

```bash
python fb-dl.py --login
```

1. A browser window opens on the Facebook login page.
2. Log in there yourself, as usual (2FA works too).
3. The window closes by itself. Your session is saved in `fb-session.json`.

fb-dl **never sees your password**: you type it into Facebook's own page, and only the login cookies
are saved. Check that it worked:

```bash
python fb-dl.py --check-login
```

```
✓ Logged in as N*** T*** B***
```

Your name is masked on purpose, so a screenshot of your terminal does not reveal your account.

> [!CAUTION]
> `fb-session.json` works like your password: never share it. A **secondary account** is safer,
> because Facebook can limit accounts that scroll a lot. See [Privacy and safety](#privacy-and-safety).

**Other ways to log in:** if you already exported your Facebook cookies with a browser extension
(Netscape `cookies.txt` or JSON), use `--cookies cookies.txt` instead of `--login`.

## Download a profile or page

Open the profile or page in your browser and copy the link from the address bar, then:

```bash
python fb-dl.py https://www.facebook.com/nasa
```

That's all. By default fb-dl saves **everything**, from the first post to today, in the best quality.
Any of these work:

```bash
python fb-dl.py nasa
python fb-dl.py https://www.facebook.com/nasa
python fb-dl.py https://www.facebook.com/profile.php?id=123456789012345
python fb-dl.py 123456789012345
```

You can also give a single post, reel or video link: `/posts/...`, `/share/p/...`, `/reel/...`,
`/watch?v=...`, `/photo/?fbid=...` or `fb.watch/...`.

**What you see while it runs** (example):

```
━━ nasa ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  NASA - National Aeronautics and Space Administration · 28M followers · id 100044561550831
  Logged in as N*** T*** B***
  Reading the timeline and downloading at the same time → D:\fb-dl\downloads\nasa

  ✓ [1 photo] 2026-11-06_1679274853567884_Nice shades. 😎 This structure, called a sunshade,  414.8 KB
  ✓ [1 reel] 2026-11-05_1678344756994227_NASA astronaut Anil Menon and CSA (Canadian Space  5.1 MB
  ⠹ Scrolling · 640 found, back to 2016-03  │  ━━━━━━╸━━━━━━━━━━━━  120/640 saved  │  1.9 GB · 12.4 MB/s  │  0 failed
```

fb-dl **reads and downloads at the same time**: as soon as the scroll finds a post, it is downloaded in
the background, so you do not wait for the whole timeline first. The line at the bottom tells you how
far back the scroll has come (`back to 2016-03`), how many posts were found and how many are saved.
A profile with many years of posts can take 20-30 minutes to scroll. Once the scroll reaches the first
post, the line becomes a normal progress bar with a percentage and the time left:

```
  ⠹ ━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━   72%  910/1250 saved  │  3.4 GB · 11.8 MB/s  │  ETA 04:51  │  0 failed
```

Then the stories and the Photos / Albums tabs are saved, and a summary is shown:

```
  ━━ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ 1250 posts, 2 story files, 3400 photos from the Photos / Albums tabs   ✗ 0 failed · 6.1 GB new in 52:10
  Folder: D:\fb-dl\downloads\nasa  (posts.csv: 1250)
```

If the window is narrow, the less important parts of the line (speed, time left) are hidden.

**Common examples:**

| Command | What it does |
|---|---|
| `python fb-dl.py nasa` | Everything (default) |
| `python fb-dl.py nasa -n 50` | Only the 50 newest posts |
| `python fb-dl.py nasa --since 2025-01-01` | Only posts from 1 Jan 2025 on |
| `python fb-dl.py nasa --since 2025-01-01 --until 2025-06-30` | Only posts in that period |
| `python fb-dl.py nasa --update` | Only the new posts since your last run (fast) |
| `python fb-dl.py nasa --no-all-photos` | Skip the Photos / Albums tabs (much faster on big profiles) |
| `python fb-dl.py nasa --no-videos` | Text and photos only |
| `python fb-dl.py nasa --metadata-only` | Only the list of posts (CSV + JSON), no files |
| `python fb-dl.py nasa -o D:\Facebook` | Save somewhere else |
| `python fb-dl.py page1 page2 page3` | Several profiles / pages one after another |
| `python fb-dl.py nasa --lang vi` | Messages in Vietnamese |

> [!TIP]
> In **PowerShell**, put links that contain `&` or `?` in quotes:
> `python fb-dl.py "https://www.facebook.com/profile.php?id=123456789012345"`

## What you get

```
downloads/nasa/
├── posts/        one .txt per post: link, date, stats, text, and the list of its files
├── images/       photos of the posts (posts with several photos: ..._01.jpg, ..._02.jpg, ...)
├── videos/       videos of the posts
├── reels/        reels
├── stories/      stories of the last 24 hours
├── photos/       the Photos tab (every photo the profile uploaded), as <photo id>.jpg
├── albums/       the Albums tab, one folder per album
├── metadata/     one JSON file per post (everything fb-dl knows about it)
├── posts.csv     every post in one table, opens in Excel
├── stories.json  the stories saved so far
├── profile.json  name, id, username, followers
├── avatar.jpg    profile picture, full size
├── cover.jpg     cover photo, full size
└── failed.txt    only when something could not be downloaded
```

All files of one post start with the same name, `<date>_<post id>_<start of the text>`, so a text in
`posts/` and its photos / videos are easy to match. File dates are set to the post date, so sorting by
date in File Explorer shows the posts in order.

A post's `.txt` file looks like this:

```
https://www.facebook.com/nasa/posts/pfbid0iFttxes1ypW77...
2026-11-06 19:55 · NASA - National Aeronautics and Space Administration
Reactions 228 · Comments 9 · Shares 21
Files: ../images/2026-11-06_1679274853567884_Nice shades. 😎 This structure, called a sunshade,.jpg

Nice shades. 😎
This structure, called a sunshade, will fly on ...
```

fb-dl keeps what really is on the timeline: the owner's posts, posts others wrote on the wall, posts the
owner is tagged in, and collaboration posts. It skips ads and unrelated posts Facebook mixes in
(`--include-others` keeps them).

### How it works

1. A hidden Edge / Chrome window opens the profile with your session and scrolls down to the very first
   post, the same way you would.
2. Every post it finds is saved right away (text + info), and its photos and videos are downloaded in the
   background while the scrolling goes on.
3. Then the stories are saved, and the Photos and Albums tabs are read. A photo you already have (from a
   post) is not downloaded again.
4. Everything done is remembered in `.progress.db`, so a second run only fetches what is missing.

## Stop, continue, update

- **Stop anytime** with `Ctrl+C`.
- **Continue:** run the same command again. Posts already downloaded are skipped.
- **Get new posts later:** add `--update`. It stops scrolling as soon as it reaches posts you already
  have, so it only takes a minute.
- **Something failed?** It is shown on screen with the link and the reason, and listed in
  `failed.txt`:
  ```
  https://www.facebook.com/nasa/posts/pfbid0abc...
      video not downloaded (HTTP Error 403: Forbidden)
  ```
  Run the same command again to retry. `failed.txt` disappears once everything is fine.

## All options

Run `python fb-dl.py -h` to see them in your terminal.

**What to download** (default: everything)

| Option | What it does |
|---|---|
| `-n`, `--limit N` | Only the N newest posts (and the first N photos of the Photos tab and of each album) |
| `--since YYYY-MM-DD` | Only posts from this day on (scrolling stops there). Not applied to the Photos / Albums tabs |
| `--until YYYY-MM-DD` | Only posts up to this day. Not applied to the Photos / Albums tabs |
| `--update` | Stop scrolling after 10 posts in a row that you already have |
| `--no-photos` | No photos at all (also no Photos / Albums tabs, avatar or cover) |
| `--no-videos` | No videos or reels |
| `--no-text` | No `.txt` files |
| `--no-stories` | No stories |
| `--no-all-photos` | Skip the Photos and Albums tabs (only the posts' own photos are saved) |
| `--metadata-only` | Only `posts.csv` and `metadata/`, no files |
| `--include-others` | Also keep ads and unrelated posts mixed into the timeline |
| `--raw` | Also keep Facebook's raw data in `metadata/*.json` (your own account is removed from it) |
| `-o`, `--output FOLDER` | Where to save (default: `downloads`) |

**Quality and speed**

| Option | What it does |
|---|---|
| `--fast-photos` | Only the photos shown on the timeline: faster, but big albums are cut |
| `--direct-video` | Download the timeline MP4 instead of using yt-dlp (faster, often only 720p) |
| `-j`, `--jobs N` | Files downloaded at once (default: 16) |
| `-x`, `--connections N` | Connections per file (default: 8) |
| `--video-jobs N` | Videos downloaded at once (default: 3) |
| `-w`, `--workers N` | Threads reading photo pages (default: 4) |
| `--wait SEC` | Pause between photo page requests (default: 0.5) |
| `--batch N` | Posts per download batch (default: 30) |

**Browser and scrolling**

| Option | What it does |
|---|---|
| `--browser auto\|msedge\|chrome\|chromium` | Which browser reads the timeline (default: Edge, then Chrome, then Chromium) |
| `--show-browser` | Show the browser window while it scrolls |
| `--scroll-wait SEC` | Pause between scrolls (default: 1.5) |
| `--max-idle N` | Stop after N scrolls without new posts (default: 25) |

**Login**

| Option | What it does |
|---|---|
| `--login` | Log in in a browser window and save the session |
| `--check-login` | Check that the saved session still works |
| `--logout` | Delete the saved session |
| `--cookies FILE` | Use a cookie export instead of the saved session |
| `--no-login` | Ignore the saved session |

**Display**

| Option | What it does |
|---|---|
| `--lang en\|vi` | Message language (default: your system language) |
| `--no-color` | Plain text, no colors (or set `NO_COLOR=1`) |
| `-V`, `--version` | Show the version |

## Privacy and safety

- **`fb-session.json` works like your password.** Never share it, upload it or send it to anyone. It
  is in `.gitignore`, so Git never uploads it. If you zip the `fb-dl` folder to share it, leave this
  file out.
- **Use a secondary account.** Facebook can ask to verify, or limit, accounts that scroll a lot.
- **Your account stays private.** The screen only shows a masked name (`N*** T*** B***`) and never
  your id. Your account is not written to any output file: if a timeline holds a post you wrote or are
  tagged in, its author is saved as `(you)`. `--raw` also removes your id and name from Facebook's raw
  data (other text, such as a comment mentioning you, is kept as it is).
- **Your cookies stay in memory.** Apart from `fb-session.json`, fb-dl never writes your cookies to a
  file and never puts them on a command line.
- **Stories:** fb-dl opens the story page and only reads it. It does not click "view" and does not move
  on to other people's stories, so it only saves the stories of the profile / page you asked for.
  Facebook may still count a visit.
- **Private profiles:** you only get what your account is allowed to see. Respect people's privacy.

## Log out and remove your data

**1. Delete the saved session**

```bash
python fb-dl.py --logout
```

This deletes `fb-session.json`. Nothing else holds your login: fb-dl uses a fresh, empty browser profile
every time and never writes your cookies anywhere else.

**2. End the session on Facebook too**

Deleting the file does not log the session out on Facebook's side. To do that:

1. On Facebook, open **Settings & privacy** → **Settings** → **Accounts Center**
2. **Password and security** → **Where you're logged in**
3. Pick the session fb-dl used (a Windows device with Edge / Chrome, from the time you ran `--login`)
   and choose **Log out**

Changing your Facebook password logs out every session at once.

**3. Delete cookie exports**

If you used `--cookies`, delete that `cookies.txt` / JSON file too.

**4. Remove downloaded data and packages (optional)**

- The output folder (`downloads/` by default). Each profile folder also holds a hidden `.progress.db`
  file that remembers what was downloaded.
- The packages:
  ```bash
  pip uninstall playwright yt-dlp imageio-ffmpeg
  ```

## Problems and questions

**Only a few posts were found.**
You are not logged in, or the session expired. Run `python fb-dl.py --check-login`, then `--login`
again if needed.

**"Facebook wants you to verify your account".**
Open facebook.com in your normal browser, finish the check, then run `--login` again.

**It stopped scrolling before the oldest posts.**
Facebook was slow to load. Run again with `--scroll-wait 3 --max-idle 50`. Posts you already have are
skipped. Add `--show-browser` to watch what happens.

**It takes very long.**
Big profiles have thousands of posts, and the Photos / Albums tabs are scrolled page by page too.
Use `--no-all-photos` to skip the tabs, or `--since` to stop at a date. You can stop with `Ctrl+C` and
continue later.

**Some videos fail.**
Update yt-dlp (`pip install -U yt-dlp`) and run again, or try `--direct-video`.

**A video does not play.**
Facebook often sends AV1 video. Use VLC, a recent browser, or the Windows Media Player app.

**The same photo is in `images/` and `photos/`.**
`images/` holds the photos of posts, `photos/` the whole Photos tab and `albums/` the albums, so they
overlap. A photo is downloaded only once: the other copies are hard links to the same file, so they take
no extra disk space (on drives that do not support hard links, such as FAT32 / exFAT USB sticks, they
are real copies). Use `--no-all-photos` if you only want the posts.

**"Skipped N ads / posts of other pages".**
These are ads or posts that have nothing to do with the profile. Add `--include-others` to keep them.

**"Could not start a browser".**
Install Edge or Chrome, or run `python -m playwright install chromium`.

**`python` is not recognized.**
Python is not in PATH. Reinstall it and tick **"Add python.exe to PATH"**, or use `py` instead of
`python`.

**`pip` is not recognized.**
Use `python -m pip install -r requirements.txt` instead (or `py -m pip ...`).

**Does it work for groups?**
No, only profiles and pages (and single posts from anywhere).

**How do I update fb-dl itself?**

- **With Git:** `git pull` in the `fb-dl` folder, then `pip install -U -r requirements.txt`.
- **Without Git:** download the ZIP again and copy the new `fb-dl.py` over yours. Keep your
  `fb-session.json`, `aria2c.exe` and `ffmpeg.exe`.

If videos start failing, update yt-dlp first: `pip install -U yt-dlp`.

## Disclaimer

**This is for educational purposes only.** You are responsible for how you use it.
Respect the creators' copyright, people's privacy and Facebook's Terms of Service.

This project is not affiliated with Facebook or Meta. The author is not responsible for any misuse.

## License

MIT © loooveee
