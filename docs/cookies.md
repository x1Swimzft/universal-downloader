# Cookies and sign-in-required links

Some public posts cannot be read anonymously: Instagram gate their embed, YouTube asks
for age confirmation, private or member-only videos need a session. Universal Downloader
can borrow cookies from a browser you are already signed in to.

Cookies stay on your machine. They are read by the local backend, used for the request
yt-dlp makes, and are never uploaded anywhere.

## Enable browser cookies

1. Settings → **Browser cookies** → pick the browser you use (**Chrome**, **Edge**,
   **Brave**, **Firefox**).
2. Close that browser completely. Chromium locks its cookie database while running; the
   app will report `COOKIE_LOCKED` if it cannot read it.
3. Paste the link again and press **Fetch**.

## Or use a cookies.txt file

Useful for browsers without direct support, or when you do not want to close the
browser.

1. Export cookies for the site with a `cookies.txt` extension or `yt-dlp --cookies-from-browser`.
2. Settings → **Cookie file** → choose the `.txt` file.
3. The file must be on a local drive; network paths are rejected.

## Which errors mean "cookies"

| Code | What to do |
|---|---|
| `COOKIE_REQUIRED` | Turn on browser cookies, or supply `cookies.txt`, then retry. |
| `AUTH_403` | The site refused the request. Cookies usually fix it; a VPN may be needed if your region is blocked. |
| `COOKIE_LOCKED` | Close Chrome/Edge/Firefox and retry, or use `cookies.txt`. |
| `RATE_LIMIT` | Wait a minute, then retry. Cookies reduce the chance of this. |

## Privacy and safety

- Cookies are only read when you enable the setting.
- Logging out of the browser does not immediately invalidate the exported file; delete
  it when you no longer need it.
- Never share a `cookies.txt`. It is equivalent to a signed-in session.
