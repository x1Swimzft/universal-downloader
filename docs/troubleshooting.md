# Troubleshooting

Errors shown in the app carry a stable code. This table maps each code to the cause and
the action the app offers.

| Code | Meaning | What to do |
|---|---|---|
| `COOKIE_REQUIRED` | The post needs a signed-in session (private, gated, age-restricted, members-only). | Settings → Browser cookies, or a `cookies.txt` file. See [cookies.md](cookies.md). |
| `AUTH_403` | The site returned 403 Forbidden. | Enable browser cookies; if your region is blocked, try another network/VPN. |
| `COOKIE_LOCKED` | The browser cookie database is locked or unreadable. | Close Chrome/Edge/Firefox completely, then retry; or use `cookies.txt`. |
| `RATE_LIMIT` | The site is throttling requests. | Wait a minute and retry. |
| `NETWORK_TRANSIENT` | Timeout, DNS or 5xx from the site. | Check the connection and retry. The queue retries twice automatically. |
| `UNSUPPORTED_URL` | The link is not supported, or the media is unavailable/removed. | Check the link in a browser. |
| `LINK_EXPIRED` | A signed or temporary URL has expired. | Copy a fresh link from the site and retry. |
| `PLATFORM_CHANGED` | The site changed its page and this version cannot read it. | Update the app (Settings → App updates). If it still fails, copy diagnostics and report it. |
| `UNKNOWN` | Anything not classified. | Copy diagnostics from Settings and report the code with the link. |

## Diagnostics

Settings → **Copy diagnostics** puts a redacted snapshot on the clipboard: app, OS,
Python and extractor versions, the last platform-health result and the last error code.
Signed URL values, token headers and your Windows username are removed before copying.
Nothing is sent automatically.

## Platform health

Settings → **Test platforms** probes TikTok, Instagram and YouTube without downloading.
Use it when a site stops working: a single failing platform points at the site; all three
failing usually points at your network or an outdated app.

## Updating

- Settings → App updates → **Check for updates** → **Install update**.
- The app closes and restarts to finish. Running downloads stop, and the confirmation
  dialog says so before anything is downloaded.
- Updates older than 0.7.1 must be installed manually once.

## Where files live

| What | Where |
|---|---|
| Downloads | The folder chosen in Settings |
| History | `%LOCALAPPDATA%\UniversalDownloader\history.json` |
| Extractor updates | `%LOCALAPPDATA%\UniversalDownloader\bin` |
| Settings (desktop) | `%APPDATA%\Universal Downloader\settings.json` |
