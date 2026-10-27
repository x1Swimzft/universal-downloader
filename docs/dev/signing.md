# Code signing

v1.0.0 ships **unsigned**. Windows SmartScreen will warn on first run; the installer and
portable build are otherwise identical to a signed one.

## Why nothing is enforced yet

`electron-builder` and `electron-updater` can both be told to require a publisher
signature. While the build is unsigned, enforcing either would make the app reject its
own updates:

- `win.publisherName` / `verifyUpdateCodeSignature` must stay **unset**.
- `electron-updater` keeps its default behaviour (SHA-512 from `latest.yml` only).

Do not add them until a certificate exists and a signed build has been published **and**
verified once end to end, otherwise `0.9.0 → 1.0.0` and later updates fail validation.

## Sign-ready pipeline

Both build paths already accept the standard electron-builder variables and simply build
unsigned when they are absent:

| Variable | Meaning |
|---|---|
| `WIN_CSC_LINK` | base64 of the `.pfx`, or a path to it |
| `WIN_CSC_KEY_PASSWORD` | certificate password |
| `CSC_LINK` / `CSC_KEY_PASSWORD` | aliases accepted by electron-builder |

`release.yml` maps the two `WIN_*` repository secrets into `CSC_LINK` /
`CSC_KEY_PASSWORD` at build time. Unset secrets = unsigned build, no failure. The
local pipeline can do the same:

```powershell
$env:CSC_LINK = "C:\path\to\certificate.pfx"
$env:CSC_KEY_PASSWORD = "..."
npx electron-builder --publish never
```

## What you need to provide

1. An **OV or EV code-signing certificate** (`.pfx`), or an Azure Trusted Signing /
   cloud-signing account supported by electron-builder 26.
2. Repository secrets `WIN_CSC_LINK` (base64: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))`)
   and `WIN_CSC_KEY_PASSWORD`.
3. A signed release tested on a clean machine: SmartScreen should stay quiet, and
   `0.9.0 → 1.0.0` auto-update must be re-verified.

## Verification after signing

```powershell
(Get-AuthenticodeSignature .\Universal-Downloader-Setup-1.0.0.exe).Status   # Valid
(Get-AuthenticodeSignature .\Universal-Downloader-Setup-1.0.0.exe).SignerCertificate.Subject
```

Only then add `publisherName` to the build config, in a separate change with its own
install + update test.
