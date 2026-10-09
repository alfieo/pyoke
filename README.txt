KAR lyrics player update

1. Stop your existing Flask process and back up app.py, templates/index.html and karaoke.db.
2. Copy app.py and templates/index.html from this package into your existing project.
   Keep your existing uploads/, soundfonts/ and karaoke.db.
3. Activate the virtual environment you normally use, then run:
   python -m pip install -r requirements.txt
4. Your working FluidSynth installation and soundfonts/default.sf2 are still required.
5. Start: python app.py
6. Open http://YOUR_SERVER_IP:5050 and hard-refresh the page.
7. Upload a KAR again, queue it and click Play Next.

The database is migrated automatically with two additional columns; existing songs
are preserved. Old converted songs have no recorded link to the original KAR, so
reupload them for lyrics. Ordinary media and MIDI files without lyric events show
'No embedded lyrics available for this song.'

Lyrics support explicit MIDI lyric events and common Soft Karaoke text events,
including @ metadata, slash line breaks, backslash paragraph breaks and tempo
changes. One lyric track is selected to avoid duplicated text/lyrics. Unusual
encodings, unmarked text metadata and nonstandard KAR dialects may need adjustments.
Timing adjustment resets per song: positive makes lyrics appear earlier, negative
later. Highlighting follows event start times, usually syllables, rather than
interpolating continuous word highlighting. Pause and seeking follow currentTime.
Use 'Fullscreen + Lyrics' to include lyrics; native video fullscreen excludes them.

Adding to the queue no longer reloads the page. Uploading still reloads it, so upload
before playback. This remains the local/LAN starter, without authentication or
multi-device playback control. Do not expose it to the public internet.
