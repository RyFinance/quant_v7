# Meridian for Mac

A native Mac window for the Meridian dashboard (http://127.0.0.1:8420/), so it opens from the Dock instead of a browser tab.

```bash
app/build.sh --install     # builds app/build/Meridian.app and copies it to /Applications
```

Needs the Xcode command line tools (`xcode-select --install`). Build it from the repo you run
Meridian from: the app remembers that folder.

- If nothing answers at http://127.0.0.1:8420/, the app starts the server itself (`scripts/desk.sh` in `.`)
  and stops it again when you quit. A server that's already running is left alone.
- Server output: `~/Library/Logs/Meridian-app.log` (View → Show Server Log).
- ⌘R reload · ⇧⌘H home · ⌘[ / ⌘] back / forward · ⌘= / ⌘- zoom · ⇧⌘O open in browser.
  Closing the window keeps the app running; click the Dock icon to bring it back.
- Downloads go to ~/Downloads; external links open in your browser.
- Settings: `app.json` (name, URL, start command, icon). Rebuild after editing.
