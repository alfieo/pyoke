# Karaoke Studio

A Flask karaoke web player for local music, KAR/MIDI lyrics, YouTube videos, and song requests from guests on the same network.

## Features

- Local audio/video playback and KAR/MIDI conversion using FluidSynth.
- Synchronized KAR lyrics with syllable highlighting, pause, and seek support.
- YouTube playback through the official embedded player.
- Stable song codes for searching and selecting songs.
- **Play**, **Reserve**, and **Prio-Reserve** actions.
- Shared queue with singer names, reordering, removal, and automatic next-song playback.
- Phone requests through a QR code and mobile guest page.
- Search by title, artist, or code; source filters, favorites, and pagination.
- Admin-only uploads, YouTube additions, song editing, and deletion.
- Batch uploads with progress and individual results.
- Fullscreen playback, lyric appearance controls, and per-song timing adjustments.
- Remembered browser preferences and optional session background photos.

## Requirements

- Ubuntu with Python **3.10 or newer** and the `venv` module.
- FluidSynth and an SF2 SoundFont for KAR/MIDI conversion.
- A modern browser with support for the media formats you use.
- Internet access in the host browser for YouTube playback.

SQLite is included with Python. Local songs work without YouTube access.

## Project structure

```text
flask-karaoke/
├── app.py
├── requirements.txt
├── background.svg
├── README.md
├── templates/
│   ├── index.html
│   └── guest.html
├── uploads/                 # Created automatically
├── soundfonts/
│   └── default.sf2          # Supplied separately
├── karaoke.db               # Created automatically
└── .admin_config.json       # Private; created automatically
```

The database, uploaded media, SoundFont, and admin configuration are local runtime files. They should not be committed to Git.

## Install on Ubuntu

### 1. Install system dependencies

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git fluidsynth fluid-soundfont-gm -y
```

`fluid-soundfont-gm` supplies a General MIDI SoundFont. If the package is unavailable in your Ubuntu repositories, provide another valid, appropriately licensed SF2 file.

### 2. Clone the repository

Replace `YOUR_USERNAME` with the repository owner:

```bash
git clone https://github.com/YOUR_USERNAME/flask-karaoke.git
cd flask-karaoke
```

A private repository requires GitHub authentication. With an authenticated GitHub CLI, you can instead use:

```bash
gh repo clone YOUR_USERNAME/flask-karaoke
cd flask-karaoke
```

### 3. Create the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Activate `.venv` again whenever you open a new terminal to run the app.

### 4. Configure the SoundFont

The app expects a SoundFont at `soundfonts/default.sf2`:

```bash
mkdir -p soundfonts
cp /usr/share/sounds/sf2/FluidR3_GM.sf2 soundfonts/default.sf2
```

The source path can vary. To list SF2 files installed by the package:

```bash
dpkg -L fluid-soundfont-gm | rg '\.sf2$'
```

If `rg` is not installed, use:

```bash
dpkg -L fluid-soundfont-gm | grep '\.sf2$'
```

Copy the actual SoundFont path to `soundfonts/default.sf2`. A SoundFont is only required for KAR/MIDI conversion, not ordinary audio/video or YouTube playback.

### 5. Set the admin password

```bash
python app.py --set-admin
```

Enter and confirm a password of at least **12 characters**. Password input is hidden. There is no default password.

### 6. Start the player

```bash
python app.py
```

The app listens on `0.0.0.0:5050` with debug mode disabled.

- On the server: `http://127.0.0.1:5050`
- On another device: `http://YOUR_SERVER_LAN_IP:5050`

Find the server's addresses with:

```bash
hostname -I
```

Choose the LAN address reachable by your other devices. If UFW is enabled, allow the trusted LAN subnet to access port 5050. Replace this example subnet with yours:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 5050 proto tcp
```

## Using the player

### Add and manage songs

1. Open **Settings → Admin access → Admin login**.
2. Sign in with your admin password.
3. Open **Songs → Add Music**.
4. Upload local files or add a YouTube video link.

For batch uploads, filenames become song titles. The artist field applies to the batch; a custom title applies to a single-file upload. You can edit titles and artists afterward.

Each song receives a stable numeric code, displayed with at least six digits, such as `000001`. Codes remain unchanged after edits and restarts. Deleted codes are not reused.

### Search and choose an action

Search by title, artist, or song code, then click a row to open its options:

| Action | Behavior |
| --- | --- |
| Play | Starts immediately; existing reservations stay in the queue. |
| Reserve | Adds the request to the end of the queue. |
| Prio-Reserve | Adds it to the front without interrupting the current song. |

A new priority reservation takes precedence over earlier queued requests, including previous priority reservations. Enter a singer name if desired.

### Guest requests from phones

1. Open the host player using its **LAN IP**, not `localhost`.
2. Click **Guest QR**.
3. Guests join the same reachable network and scan the code.
4. Each guest enters their name, searches for a song, and confirms the request.

The guest page is also available at `http://YOUR_SERVER_LAN_IP:5050/request`.

The host queue refreshes every five seconds while its browser tab is visible. Guest requests append to the queue. Keep the host player open for playback and automatic next-song handling.

### Lyrics and appearance

KAR/MIDI files must contain embedded lyric or text events to show synchronized lyrics. Supported common conventions include Soft Karaoke line breaks and MIDI tempo changes.

Under **Settings → Lyrics**, adjust size, highlight color, timing, and the Up Next banner. Positive timing adjustments show lyrics earlier; negative values delay them. Timing is remembered separately for each local song.

YouTube lyrics are part of the video and do not use the local lyric controls. YouTube videos may require clicking Play inside the embedded player.

## Supported sources

| Source | Notes |
| --- | --- |
| `.kar`, `.mid`, `.midi` | Converted to WAV using FluidSynth; lyrics displayed when embedded. |
| `.mp3`, `.mp4`, `.webm`, `.ogg`, `.wav`, `.m4a` | Played directly when the browser supports the codec. |
| YouTube links | Watch, short-link, embed, Shorts, and live video URLs are accepted. |

Uploads are limited to **500 MiB per file**. MIDI conversion has a **180-second timeout**. No YouTube API key is required for link playback. The app does not download videos or search YouTube's catalog.

YouTube availability and embedding restrictions are determined during playback. Live streams may not support normal seeking or end-of-song behavior.

## Admin access and security

Adding local/YouTube songs, editing metadata, and deleting songs require an admin session and CSRF verification on the server. Hiding the controls is an additional UI measure.

- Passwords are stored as hashes.
- The server generates a private session-signing secret.
- Session cookies use `HttpOnly` and `SameSite=Lax`.
- Admin sessions have an eight-hour inactivity lifetime.
- Login is limited after five failed attempts from an IP within 15 minutes.

Reset the password by stopping the server, running `python app.py --set-admin`, and restarting. This invalidates previous admin sessions.

Keep `.admin_config.json` private and retain it between restarts. Removing it resets admin configuration and invalidates sessions.

**Deployment scope:** this release is intended for a trusted LAN and uses Flask's development server. Search, playback controls, queue actions, guest requests, and favorite changes remain public. Admin-only library management does not restrict host playback controls.

For public or untrusted-network deployment, add HTTPS, a production server, and a host-control access policy. Plain HTTP does not encrypt passwords. When serving over HTTPS, set:

```bash
export KARAOKE_HTTPS=1
python app.py
```

Do not enable this setting while accessing the app over plain HTTP: Secure cookies will not be sent.

## Persistence and backups

| Data | Stored in |
| --- | --- |
| Library, queue, favorites, login-attempt limits | `karaoke.db` |
| Uploaded media and original KAR/MIDI files | `uploads/` |
| Admin hash and session-signing secret | `.admin_config.json` |
| Volume, autoplay, lyric appearance and timing | Browser storage for the current site address |
| Selected background photo | Current browser session only |

Stop the server before copying the SQLite database. Back up `karaoke.db`, `uploads/`, `soundfonts/`, `.admin_config.json`, and the project source together. Protect backup files because they contain private configuration and media.

Use one active host player. Multiple host browsers consume the shared queue independently; their playback states are not synchronized.

## Updating

Stop the server and back up your project before updating:

```bash
source .venv/bin/activate
git pull --ff-only
python -m pip install -r requirements.txt
python app.py
```

If Git reports local changes or divergent branches, resolve those before updating; do not overwrite your runtime files. Database schema updates run automatically. Keep the existing database, uploads, SoundFont, and admin configuration. Hard-refresh the browser with **Ctrl + Shift + R** after frontend updates.

## Troubleshooting

| Problem | Check |
| --- | --- |
| SoundFont missing | Confirm `soundfonts/default.sf2` exists and is a valid SF2 file. |
| KAR/MIDI conversion fails | Check FluidSynth installation, the SoundFont, and the Flask console. |
| KAR has no lyrics | The file may lack lyric events. Legacy uploads made before lyric tracking need reuploading. |
| Phone cannot connect | Use the server LAN IP; check Wi-Fi isolation, routing, and firewall port 5050. |
| QR opens the wrong address | Generate it after opening the host using its LAN IP rather than localhost. |
| YouTube does not play | Check internet access, embedding permissions, browser blockers, and the displayed error. |
| Admin controls are missing | Set the password, then sign in through Settings. |
| Login is temporarily locked | Wait for the 15-minute failed-attempt window to expire. |
| Old layout still appears | Restart the correct Flask process and hard-refresh the browser. |
| Preferences disappeared | Use the same browser and site address; private browsing may discard stored preferences. |

## Final smoke test

- Play a local song and a KAR file with lyrics.
- Pause and seek; confirm lyrics follow the audio.
- Add a YouTube link and test embedded playback.
- Reserve two songs and add a priority reservation; confirm queue order.
- Submit a request from a phone through Guest QR.
- Sign in as admin, upload/edit/delete a test song, then log out.
- Confirm library management is blocked when logged out.

## License

No project license has been selected yet. Add a `LICENSE` file before distributing the project under a specific license. Media, SoundFonts, and YouTube videos remain subject to their respective rights and terms.
