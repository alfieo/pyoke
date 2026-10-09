from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, send_file, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import timedelta
import secrets
import os
import time
import getpass
import sys
import tempfile
from pathlib import Path
from contextlib import contextmanager
import sqlite3
import uuid
import subprocess
import json
import mido
import io
import qrcode
import re
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / 'uploads'
SOUNDFONT = BASE_DIR / 'soundfonts' / 'default.sf2'
DATABASE = BASE_DIR / 'karaoke.db'
ALLOWED_EXTENSIONS = {'mp3', 'mp4', 'webm', 'ogg', 'wav', 'm4a', 'kar', 'mid', 'midi'}
MIDI_EXTENSIONS = {'kar', 'mid', 'midi'}
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
AUTH_FILE = BASE_DIR / '.admin_config.json'
def load_auth_config():
    try:
        return json.loads(AUTH_FILE.read_text())
    except FileNotFoundError:
        config = {'secret_key': secrets.token_hex(32), 'password_hash': None, 'version': secrets.token_hex(16)}
        try:
            with os.fdopen(os.open(AUTH_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file:
                json.dump(config, file)
        except FileExistsError:
            return json.loads(AUTH_FILE.read_text())
        return config
app.secret_key = load_auth_config()['secret_key']
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('KARAOKE_HTTPS') == '1', PERMANENT_SESSION_LIFETIME=timedelta(hours=8))

def is_admin():
    config = load_auth_config()
    return bool(config.get('password_hash') and session.get('admin') and session.get('auth_version') == config['version'])

def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']

def valid_csrf():
    expected = session.get('csrf')
    supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    return bool(expected and supplied and secrets.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8')))

def admin_required(function):
    @wraps(function)
    def protected(*args, **kwargs):
        if not is_admin():
            return jsonify({'error': 'Admin login required'}), 401
        if not valid_csrf():
            return jsonify({'error': 'Session verification failed. Refresh and sign in again.'}), 403
        return function(*args, **kwargs)
    return protected


@contextmanager
def get_db():
    db = sqlite3.connect(DATABASE, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

def init_db():
    with get_db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS songs (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, artist TEXT NOT NULL, filename TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS admin_attempts (ip TEXT PRIMARY KEY, failures INTEGER NOT NULL, since REAL NOT NULL)')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(songs)')}
        for name in ('source_filename', 'lyrics_json'):
            if name not in columns:
                db.execute(f'ALTER TABLE songs ADD COLUMN {name} TEXT')
        if 'favorite' not in columns:
            db.execute('ALTER TABLE songs ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0')
        if 'source_type' not in columns:
            db.execute("ALTER TABLE songs ADD COLUMN source_type TEXT NOT NULL DEFAULT 'local'")
        if 'youtube_id' not in columns:
            db.execute('ALTER TABLE songs ADD COLUMN youtube_id TEXT')
        db.execute("CREATE TABLE IF NOT EXISTS queue (id INTEGER PRIMARY KEY AUTOINCREMENT, song_id INTEGER NOT NULL, singer TEXT NOT NULL DEFAULT 'Guest', FOREIGN KEY(song_id) REFERENCES songs(id))")

        queue_columns = {row['name'] for row in db.execute('PRAGMA table_info(queue)')}
        if 'position' not in queue_columns:
            db.execute('ALTER TABLE queue ADD COLUMN position INTEGER NOT NULL DEFAULT 0')
            db.execute('UPDATE queue SET position = id')

def extract_lyrics(path):
    """Read one lyric track, honoring the tempo map across all tracks."""
    midi = mido.MidiFile(path, charset='latin1')
    if midi.type == 2 or midi.ticks_per_beat <= 0:
        raise ValueError('Asynchronous or SMPTE MIDI timing is not supported')
    seconds_at_tick = {0: 0.0}
    tick = 0
    seconds = 0.0
    tempo = 500000
    for message in mido.merge_tracks(midi.tracks):
        tick += message.time
        seconds += mido.tick2second(message.time, midi.ticks_per_beat, tempo)
        seconds_at_tick[tick] = seconds
        if message.type == 'set_tempo':
            tempo = message.tempo
    candidates = []
    for track in midi.tracks:
        tick = 0
        events = {'lyrics': [], 'text': []}
        for message in track:
            tick += message.time
            if message.type in events and message.text and not message.text.lstrip().startswith('@'):
                events[message.type].append((seconds_at_tick[tick], message.text))
        for kind, values in events.items():
            if any(text.strip(' /\\\r\n\x00') for _, text in values):
                # Prefer explicit lyric events; otherwise a marked KAR text track.
                marked = any('/' in text or '\\' in text for _, text in values)
                candidates.append(((kind == 'lyrics', marked, len(values)), values))
    if not candidates:
        return []
    events = max(candidates, key=lambda item: item[0])[1]
    lines = []
    parts = []
    def flush():
        nonlocal parts
        if parts and ''.join(p['text'] for p in parts).strip():
            lines.append({'start': parts[0]['time'], 'parts': parts})
        parts = []
    for time, text in events:
        # Soft Karaoke: / is a new line; backslash starts a new paragraph.
        text = text.replace('\x00', '').replace('\\', '\n').replace('/', '\n').replace('\r\n', '\n').replace('\r', '\n')
        for index, fragment in enumerate(text.split('\n')):
            if index:
                flush()
            if fragment:
                parts.append({'time': round(time, 6), 'text': fragment})
    flush()
    return lines

@app.route('/')
def index():
    with get_db() as db:
        songs = db.execute('SELECT * FROM songs ORDER BY title').fetchall()
        queue = db.execute('SELECT queue.id, songs.title, songs.artist, queue.singer FROM queue JOIN songs ON queue.song_id = songs.id ORDER BY queue.position, queue.id').fetchall()
    return render_template('index.html', songs=songs, queue=queue)

@app.route('/upload', methods=['POST'])
@admin_required
def upload_song():
    file = request.files.get('file')
    title = request.form.get('title', '').strip()
    artist = request.form.get('artist', '').strip() or 'Unknown Artist'
    if not file or not file.filename or not title:
        return 'File and song title are required', 400
    extension = secure_filename(file.filename).rsplit('.', 1)[-1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return 'Unsupported file type', 400
    source_name = f'{uuid.uuid4().hex}.{extension}'
    source_path = UPLOAD_FOLDER / source_name
    playable_name = source_name
    output_path = None
    lyrics = []
    try:
        file.save(source_path)
        if extension in MIDI_EXTENSIONS:
            if not SOUNDFONT.is_file():
                source_path.unlink(missing_ok=True)
                return 'SoundFont missing: soundfonts/default.sf2', 400
            lyrics = extract_lyrics(source_path)
            playable_name = f'{uuid.uuid4().hex}.wav'
            output_path = UPLOAD_FOLDER / playable_name
            subprocess.run(['fluidsynth', '-ni', '-r', '44100', '-T', 'wav', '-F', str(output_path), str(SOUNDFONT), str(source_path)], check=True, capture_output=True, text=True, timeout=180)
            if not output_path.exists() or output_path.stat().st_size <= 44:
                raise RuntimeError('FluidSynth did not produce audio')
        with get_db() as db:
            cursor = db.execute('INSERT INTO songs (title, artist, filename, source_filename, lyrics_json) VALUES (?, ?, ?, ?, ?)', (title, artist, playable_name, source_name, json.dumps(lyrics, ensure_ascii=False)))
    except Exception:
        source_path.unlink(missing_ok=True)
        if output_path:
            output_path.unlink(missing_ok=True)
        app.logger.exception('Song upload failed')
        return 'Upload failed. Check the Flask console for MIDI parsing, FluidSynth, or database errors.', 500
    if request.headers.get('X-Requested-With') == 'fetch':
        return jsonify({'song': {'id': cursor.lastrowid, 'title': title, 'artist': artist, 'code': str(cursor.lastrowid).zfill(6)}}), 201
    return redirect(url_for('index'))

@app.route('/queue/add/<int:song_id>', methods=['POST'])
def add_to_queue(song_id):
    singer = request.form.get('singer', '').strip() or 'Guest'
    with get_db() as db:
        if db.execute('SELECT id FROM songs WHERE id = ?', (song_id,)).fetchone() is None:
            return 'Song not found', 404
        db.execute('INSERT INTO queue (song_id, singer, position) VALUES (?, ?, (SELECT COALESCE(MAX(position), 0) + 1 FROM queue))', (song_id, singer))
    if request.headers.get('X-Requested-With') == 'fetch':
        return jsonify({'ok': True})
    return redirect(url_for('index'))

@app.route('/api/queue')
def queue_state():
    with get_db() as db:
        rows = db.execute('SELECT queue.id, songs.title, songs.artist, queue.singer FROM queue JOIN songs ON queue.song_id = songs.id ORDER BY queue.position, queue.id').fetchall()
    return jsonify({'queue': [dict(row) for row in rows]})

@app.route('/api/next', methods=['POST'])
def next_song():
    with get_db() as db:
        db.execute('BEGIN IMMEDIATE')
        entry = db.execute('SELECT queue.id AS queue_id, songs.id AS song_id, queue.singer, songs.title, songs.artist, songs.filename, songs.lyrics_json, songs.source_type, songs.youtube_id FROM queue JOIN songs ON queue.song_id = songs.id ORDER BY queue.position, queue.id LIMIT 1').fetchone()
        if entry is None:
            return jsonify({'song': None})
        db.execute('DELETE FROM queue WHERE id = ?', (entry['queue_id'],))
    return jsonify({'song': playback_payload(entry, entry['singer'], entry['song_id'])})

@app.route('/media/<path:filename>')
def media(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/api/library')
def library():
    with get_db() as db:
        rows = db.execute('SELECT id, title, artist, source_type, favorite, source_filename, filename FROM songs ORDER BY title').fetchall()
    return jsonify({'songs': [{'id': row['id'], 'title': row['title'], 'artist': row['artist'], 'source_type': row['source_type'], 'favorite': row['favorite'], 'code': str(row['id']).zfill(6), 'media_type': 'YouTube' if row['source_type'] == 'youtube' else ('MIDI' if Path(row['source_filename'] or row['filename']).suffix.lower() in {'.kar', '.mid', '.midi'} else 'Local')} for row in rows]})

@app.route('/api/play/<int:song_id>', methods=['POST'])
def play_song(song_id):
    with get_db() as db:
        song = db.execute('SELECT * FROM songs WHERE id = ?', (song_id,)).fetchone()
    if song is None:
        return jsonify({'error': 'Song not found'}), 404
    return jsonify({'song': playback_payload(song, request.form.get('singer', '').strip() or 'Guest', song['id'])})

@app.route('/api/play-code/<code>', methods=['POST'])
def play_by_code(code):
    # Codes derive from the persistent AUTOINCREMENT song ID.
    # They remain stable across restarts and deleted codes are never reassigned.
    if not code.isascii() or not code.isdecimal() or not 1 <= len(code) <= 12:
        return jsonify({'error': 'Enter a numeric song code, for example 000001'}), 400
    return play_song(int(code))

@app.route('/api/songs/<int:song_id>', methods=['PATCH'])
@admin_required
def edit_song(song_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Send a title and artist'}), 400
    title, artist = data.get('title'), data.get('artist', '')
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        return jsonify({'error': 'Title must contain 1 to 200 characters'}), 400
    if not isinstance(artist, str) or len(artist) > 200:
        return jsonify({'error': 'Artist must be at most 200 characters'}), 400
    with get_db() as db:
        updated = db.execute('UPDATE songs SET title = ?, artist = ? WHERE id = ?', (title.strip(), artist.strip() or 'Unknown Artist', song_id))
        if not updated.rowcount:
            return jsonify({'error': 'Song not found'}), 404
    return jsonify({'ok': True, 'code': str(song_id).zfill(6)})

@app.route('/api/songs/<int:song_id>', methods=['DELETE'])
@admin_required
def delete_song(song_id):
    with get_db() as db:
        song = db.execute('SELECT * FROM songs WHERE id = ?', (song_id,)).fetchone()
        if song is None:
            return jsonify({'error': 'Song not found'}), 404
        db.execute('DELETE FROM queue WHERE song_id = ?', (song_id,))
        db.execute('DELETE FROM songs WHERE id = ?', (song_id,))
        files = {song['filename'], song['source_filename']} - {None, ''}
        for name in files:
            used = db.execute('SELECT 1 FROM songs WHERE filename = ? OR source_filename = ?', (name, name)).fetchone()
            if not used and Path(name).name == name:
                try:
                    (UPLOAD_FOLDER / name).unlink(missing_ok=True)
                except OSError:
                    app.logger.exception('Could not remove unused media file')
    return jsonify({'ok': True})

@app.route('/api/queue/<int:entry_id>', methods=['DELETE'])
def remove_queue(entry_id):
    with get_db() as db:
        db.execute('DELETE FROM queue WHERE id = ?', (entry_id,))
    return jsonify({'ok': True})

@app.route('/api/queue/<int:entry_id>/move', methods=['POST'])
def move_queue(entry_id):
    direction = request.form.get('direction')
    if direction not in ('up', 'down'):
        return jsonify({'error': 'Invalid direction'}), 400
    with get_db() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute('SELECT id FROM queue ORDER BY position, id').fetchall()
        ids = [row['id'] for row in rows]
        if entry_id not in ids:
            return jsonify({'error': 'Request not found'}), 404
        index = ids.index(entry_id)
        target = index + (-1 if direction == 'up' else 1)
        if 0 <= target < len(ids):
            ids[index], ids[target] = ids[target], ids[index]
        for position, identifier in enumerate(ids, 1):
            db.execute('UPDATE queue SET position = ? WHERE id = ?', (position, identifier))
    return jsonify({'ok': True})

@app.route('/background.svg')
def background():
    return send_from_directory(BASE_DIR, 'background.svg')


@app.route('/request')
def guest_page():
    return render_template('guest.html')

@app.route('/join-qr')
def join_qr():
    image = qrcode.make(url_for('guest_page', _external=True))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png', max_age=0)

@app.route('/api/requests', methods=['POST'])
def guest_request():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Enter your name and select a song'}), 400
    singer, code = data.get('singer'), data.get('code')
    if not isinstance(singer, str) or not singer.strip() or len(singer) > 80:
        return jsonify({'error': 'Enter a singer name of 1 to 80 characters'}), 400
    if not isinstance(code, str) or not code.isascii() or not code.isdecimal() or not 1 <= len(code) <= 12:
        return jsonify({'error': 'Enter a valid numeric song code'}), 400
    with get_db() as db:
        db.execute('BEGIN IMMEDIATE')
        song = db.execute('SELECT id, title FROM songs WHERE id = ?', (int(code),)).fetchone()
        if song is None:
            return jsonify({'error': 'Song not found. Refresh the song list.'}), 404
        cursor = db.execute('INSERT INTO queue (song_id, singer, position) VALUES (?, ?, (SELECT COALESCE(MAX(position), 0) + 1 FROM queue))', (song['id'], singer.strip()))
    return jsonify({'ok': True, 'request_id': cursor.lastrowid, 'title': song['title'], 'code': str(song['id']).zfill(6)}), 201


def playback_payload(song, singer, song_id):
    return {'code': str(song_id).zfill(6), 'title': song['title'], 'artist': song['artist'], 'singer': singer, 'source_type': song['source_type'], 'youtube_id': song['youtube_id'], 'url': url_for('media', filename=song['filename']) if song['source_type'] == 'local' else None, 'lyrics': json.loads(song['lyrics_json'] or '[]')}

def youtube_video_id(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
        return None
    host = parsed.hostname
    parts = parsed.path.strip('/').split('/')
    video_id = None
    if host == 'youtu.be' and len(parts) == 1:
        video_id = parts[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'www.youtube-nocookie.com'):
        if parsed.path == '/watch':
            video_id = parse_qs(parsed.query).get('v', [''])[0]
        elif len(parts) == 2 and parts[0] in ('embed', 'shorts', 'live'):
            video_id = parts[1]
    return video_id if video_id and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id) else None

@app.route('/api/youtube', methods=['POST'])
@admin_required
def add_youtube():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Enter a YouTube URL and title'}), 400
    video_id = youtube_video_id(data.get('url'))
    title, artist = data.get('title'), data.get('artist', '')
    if not video_id:
        return jsonify({'error': 'Enter a valid YouTube video link'}), 400
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        return jsonify({'error': 'Enter a title of 1 to 200 characters'}), 400
    if not isinstance(artist, str) or len(artist) > 200:
        return jsonify({'error': 'Artist must be at most 200 characters'}), 400
    with get_db() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT id, title FROM songs WHERE source_type = ? AND youtube_id = ?', ('youtube', video_id)).fetchone()
        if existing:
            return jsonify({'song': {'code': str(existing['id']).zfill(6), 'title': existing['title']}, 'existing': True})
        cursor = db.execute('INSERT INTO songs (title, artist, filename, lyrics_json, source_type, youtube_id) VALUES (?, ?, ?, ?, ?, ?)', (title.strip(), artist.strip() or 'Unknown Artist', '', '[]', 'youtube', video_id))
    return jsonify({'song': {'code': str(cursor.lastrowid).zfill(6), 'title': title.strip()}, 'existing': False}), 201


@app.route('/api/songs/<int:song_id>/favorite', methods=['PATCH'])
def favorite_song(song_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('favorite'), bool):
        return jsonify({'error': 'Send favorite as true or false'}), 400
    with get_db() as db:
        cursor = db.execute('UPDATE songs SET favorite = ? WHERE id = ?', (int(data['favorite']), song_id))
        if not cursor.rowcount:
            return jsonify({'error': 'Song not found'}), 404
    return jsonify({'ok': True, 'favorite': data['favorite']})


@app.route('/api/reserve-code', methods=['POST'])
def reserve_by_code():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Enter a song code'}), 400
    code = data.get('code')
    singer = data.get('singer', '')
    priority = data.get('priority', False)
    if not isinstance(code, str) or not code.isascii() or not code.isdecimal() or not 1 <= len(code) <= 12:
        return jsonify({'error': 'Enter a numeric song code'}), 400
    if not isinstance(singer, str) or len(singer) > 80 or not isinstance(priority, bool):
        return jsonify({'error': 'Invalid singer or priority selection'}), 400
    with get_db() as db:
        db.execute('BEGIN IMMEDIATE')
        song = db.execute('SELECT id, title FROM songs WHERE id = ?', (int(code),)).fetchone()
        if song is None:
            return jsonify({'error': 'Song code not found'}), 404
        if priority:
            position = db.execute('SELECT COALESCE(MIN(position), 0) - 1 FROM queue').fetchone()[0]
        else:
            position = db.execute('SELECT COALESCE(MAX(position), 0) + 1 FROM queue').fetchone()[0]
        cursor = db.execute('INSERT INTO queue (song_id, singer, position) VALUES (?, ?, ?)', (song['id'], singer.strip() or 'Guest', position))
    return jsonify({'ok': True, 'request_id': cursor.lastrowid, 'title': song['title'], 'code': str(song['id']).zfill(6), 'priority': priority}), 201


@app.route('/api/auth')
def auth_status():
    response = jsonify({'admin': is_admin(), 'configured': bool(load_auth_config().get('password_hash')), 'csrf': csrf_token()})
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    if not valid_csrf():
        return jsonify({'error': 'Refresh the page before signing in'}), 403
    config = load_auth_config()
    if not config.get('password_hash'):
        return jsonify({'error': 'Set an admin password on the server with: python app.py --set-admin'}), 503
    data = request.get_json(silent=True)
    password = data.get('password') if isinstance(data, dict) else None
    if not isinstance(password, str) or len(password) > 1024:
        return jsonify({'error': 'Invalid password'}), 400
    ip, now = request.remote_addr or 'unknown', time.time()
    with get_db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM admin_attempts WHERE since < ?', (now - 900,))
        entry = db.execute('SELECT failures FROM admin_attempts WHERE ip = ?', (ip,)).fetchone()
        if entry and entry['failures'] >= 5:
            return jsonify({'error': 'Too many failed attempts. Try again in 15 minutes.'}), 429
        if not check_password_hash(config['password_hash'], password):
            db.execute('INSERT INTO admin_attempts (ip, failures, since) VALUES (?, 1, ?) ON CONFLICT(ip) DO UPDATE SET failures = failures + 1', (ip, now))
            return jsonify({'error': 'Incorrect admin password'}), 401
        db.execute('DELETE FROM admin_attempts WHERE ip = ?', (ip,))
    session.clear()
    session.permanent = True
    session['admin'] = True
    session['auth_version'] = config['version']
    return jsonify({'admin': True, 'csrf': csrf_token()})

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    if not valid_csrf():
        return jsonify({'error': 'Session verification failed'}), 403
    session.clear()
    return jsonify({'admin': False, 'csrf': csrf_token()})

init_db()
if __name__ == '__main__':
    if '--set-admin' in sys.argv:
        password = getpass.getpass('New admin password (at least 12 characters): ')
        confirmation = getpass.getpass('Confirm password: ')
        if len(password) < 12 or len(password) > 1024 or password != confirmation:
            raise SystemExit('Passwords must match and contain 12 to 1024 characters.')
        config = load_auth_config()
        config['password_hash'] = generate_password_hash(password)
        config['version'] = secrets.token_hex(16)
        descriptor, temporary = tempfile.mkstemp(dir=BASE_DIR, prefix='.admin-')
        try:
            with os.fdopen(descriptor, 'w') as file:
                json.dump(config, file)
            os.replace(temporary, AUTH_FILE)
        finally:
            Path(temporary).unlink(missing_ok=True)
        print('Admin password saved. Previous admin sessions are invalidated.')
        raise SystemExit(0)
    app.run(host='0.0.0.0', port=5050, debug=False)
