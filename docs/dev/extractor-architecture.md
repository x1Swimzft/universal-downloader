# Extractor architecture (Phase 2, step 2.0)

Status: **proposed, awaiting approval.** No call site has been switched yet; `extractor.py` still
runs the app exactly as it did in 0.7.1. This step only adds `adapters/base.py`,
`adapters/registry.py`, `services/errors.py` (enum only) and a registry test.

Facts as of `v0.7.1` (`ef4071f`):

- `backend/app/services/extractor.py` — 2,588 lines, 101 top-level definitions, 90,637 bytes.
- Public surface used by the rest of the app: `extract_info`, `inspect_entries`,
  `download_media`, `get_direct_stream_url`, `resolve_music`, `update_*`, `classify_error`,
  `error_action`, plus preset/filename helpers.
- Call sites: `api/routes.py:124,154,545,609` and `services/queue_manager.py:364`.
- Regression net: 152 tests / 143 subtests, including the Phase 1 characterization fixtures.
  **None of them may be edited in Phase 2.**

## 1. Two things that already exist (scope corrections)

**Error classification is already implemented.** `extractor.classify_error()` (+
`diagnostic_message`, `error_action`, `_ERROR_MESSAGES`) already returns stable codes that the
API exposes as `error_code` and the frontend maps in `DownloadCard.tsx:15-21` and
`page.tsx:355-359`. Task 2.D is therefore an *extension*, not a greenfield build. Renaming
those codes would break the frontend and the Phase 1 tests, so they stay.

**Extractor updating is already implemented.** `services/extractor_update.py` (vendored wheel
install into the user dir, bundled fallback) plus the Settings "Update extractor" button
(`SettingsView.tsx:130`). Task 2.F becomes *verify + document*, not build. If verification
passes, 2.F ships only `docs/dev/extractor-update.md`; the handoff's "new updater module"
would duplicate working code.

## 2. Target shape

```
backend/app/services/
  extractor.py          # thin facade: public API, unchanged names; delegates to registry
  errors.py             # ErrorCode enum (2.0), classification + detail (2.D)
  mediaops.py           # presets, ffmpeg args, postprocess, filenames, clip parsing
  adapters/
    base.py             # protocol + DownloadOptions/DownloadContext  [step 2.0]
    registry.py         # register/resolve                             [step 2.0]
    common.py           # shared HTTP + on-disk photo helpers           [2.C]
    tiktok.py           # 2.A
    instagram.py        # 2.B
    music.py            # 2.C (Spotify + Apple)
    generic.py          # 2.C (yt-dlp pipeline, fallback for everything)
```

Dependency direction: `extractor → registry → adapters → base/common/mediaops`. Adapters never
import `extractor`, so there is no cycle and no lazy import.

## 3. Interface

```python
# adapters/base.py
@dataclass(frozen=True)
class DownloadOptions:
    fmt: str                      # mp3 | m4a | opus | mp4 | images
    quality: str                  # "1080", "320", ...
    preset: str | None = None     # edit_ready | audio_norm | audio_lossless | social_bypass
    social_bypass: bool = False
    start_time: float | None = None
    end_time: float | None = None

@dataclass
class DownloadContext:
    url: str
    options: DownloadOptions
    tmp_dir: str
    job_id: str
    job_store: dict
    cancel_event: asyncio.Event | None = None
    search_query: str | None = None      # music bridge
    music_metadata: dict | None = None   # tagging

class Adapter(Protocol):
    name: str
    def matches(self, url: str) -> bool: ...
    async def probe(self, url: str) -> MediaInfo | None: ...
    async def entries(self, url: str) -> list[dict] | None: ...
    async def download(self, ctx: DownloadContext) -> tuple[str, str] | None: ...
```

`None` means **"not my job, fall through"** — never an error. `probe`/`entries` returning
`None` sends the caller to `generic`; `download` returning `None` sends the job to
`generic.download()`.

Registry: ordered list, first `matches()` wins, `generic` is not registered and is the
documented fallback. `resolve(url) -> Adapter | None`.

### Why not `extract(url) → DownloadPlan`

The handoff sketched `extract → DownloadPlan → download`. I am not doing that, because a plan
type means re-deriving options that `download_media` currently computes inline (audio
forcing, `ytsearch1:` rewrite, photo ZIP branch, preset suppression). That is a rewrite of
protected logic, which Phase 2 forbids ("cut/paste, not rewritten"). `DownloadContext` is the
same information without reordering the code that uses it.

## 4. Error codes

`services/errors.py` gets an `ErrorCode(str, Enum)` in 2.0. **Existing wire values are kept**;
the handoff's names are the same concepts under different labels:

| Handoff (2.D) | Wire code (kept) | Status |
|---|---|---|
| `COOKIE_REQUIRED` | `COOKIE_REQUIRED` | exists |
| — | `AUTH_403`, `COOKIE_LOCKED`, `RATE_LIMIT` | exists, stay |
| `NETWORK` | `NETWORK_TRANSIENT` | exists, not renamed |
| `UNSUPPORTED` | `UNSUPPORTED_URL` | exists, not renamed |
| `LINK_EXPIRED` | `LINK_EXPIRED` | **new** (2.D) |
| `PLATFORM_CHANGED` | `PLATFORM_CHANGED` | **new** (2.D) |
| `UNKNOWN` | `UNKNOWN` | exists |

The existing cookie wording is untouched, as required. 2.D adds the two new codes, emits a
machine-readable `detail`, and updates the frontend map. A registry test asserts every code
`classify_error()` can return exists in `ErrorCode`.

## 5. Function → module map

Moved **verbatim**; each move is one commit with the suite green before and after.

| Destination | Functions |
|---|---|
| `adapters/tiktok.py` | `_TIKTOK_MOBILE_UA`, `_TIKTOK_AWEME_RE`, `_tiktok_first_url`, `_tiktok_image_urls`, `_tiktok_title`, `_parse_tiktok_photo_html`, `_tiktok_fetch_html`, `_fetch_tiktok_photos`, `_tiktok_photo_info` |
| `adapters/instagram.py` | `_IG_EMBED_UA`, `_IG_SHORTCODE_RE`, `_IG_MEDIA_KEYS`, `_instagram_shortcode`, `_json_string_after`, `_json_object_after`, `_instagram_context_payload`, `_ig_media_url`, `_ig_resource_area`, `_ig_best_image`, `_ig_is_video`, `_ig_duration`, `_ig_caption`, `_ig_owner`, `_ig_media_nodes`, `_ig_row_text`, `_ig_clean_og_title`, `_instagram_media_info`, `_instagram_html`, `_instagram_embed_info`, `_instagram_preview_entry` |
| `adapters/music.py` | `_SPOTIFY_PATH_RE`, `is_music_url`, `_spotify_target`, `_spotify_artists`, `_spotify_cover`, `_find_spotify_entity`, `_spotify_entity_track`, `_spotify_entry`, `_spotify_oembed`, `_resolve_spotify`, `_apple_target`, `_collect_apple_songs`, `_apple_artwork`, `_apple_entry`, `_resolve_apple`, `resolve_music`, `_music_media_info`, `_music_entry`, `_unique_music_url`, `_music_collection`, `_music_duration`, `_positive_int`, `_search_query`, `_parse_script_json`, `_meta_content`, `_get_text`, `_safe_cover_url`, `MUSIC_TIMEOUT`, `_music_ffmpeg_args`, `_download_music_cover`, `_embed_music_metadata` |
| `adapters/generic.py` | `_get_base_opts`, `_build_ydl_opts`, `extract_info` body, `inspect_entries` body, `_flat_info`, `_single_entry`, `_collect_entries`, `_collect_images`, `_best_thumbnail_url`, `_find_key`, `_has_playable_format`, `_is_audio_only`, `_audio_format`, `_audio_formats`, `_find_output_file`, `download_media` body, `get_direct_stream_url`, `_clean_url`, `_extract_platform`, `_is_photo_url`, `_upgrade_pinterest_image`, `_fetch_pinterest_image`, `_pinterest_image_info` |
| `adapters/common.py` | `TIKTOK_UA`, `_photo_referer`, `_image_extension`, `_download_photo_post`, `_fetch_public_html` |
| `services/mediaops.py` | `parse_timestamp`, `validate_clip_range`, `_normalize_preset`, `_preset_output_ext`, `_preset_ffmpeg_args`, `_ffmpeg_executable`, `_postprocess_file`, `sanitize_name`, `format_audio_filename`, `AUDIO_FILENAME_TEMPLATES`, `PRESET_CHOICES` |
| stays in `extractor.py` | `is_private_or_loopback_ip`, `validate_url_not_private`, cookie prefs, `_friendly_error`, `_clean_error_text`, `classify_error`, `diagnostic_message`, `error_action`, and the public facade functions (`extract_info`, `inspect_entries`, `download_media`, `get_direct_stream_url`, `resolve_music`) which delegate |

The facade keeps every current name and signature, so `routes.py` and `queue_manager.py` do not
change. `mediaops` names are re-exported from `extractor` during migration, so existing imports
(and the 152 tests) keep working.

## 6. Protected logic — moved, never edited

| Behaviour | Location today | Test that pins it |
|---|---|---|
| audio jobs ignore `social_bypass` | `_normalize_preset` 202-215, `download_media` 2466-2473 | `test_audio_gating.py` (54 subtests) |
| `_find_output_file` prefers audio ext | 2207-2225 | `test_audio_gating.py` |
| Spotify/Apple forced audio (`ytsearch1:`) | `download_media` 2442-2488 | `test_audio_gating.py` |
| TikTok photo chain desktop → mobile → embed | `_fetch_tiktok_photos` 765-785 | `test_extractor.py::TestTikTokPhoto`, `TestCapturedTikTokFixtures` |
| Instagram embed fallback + crawler UA | `_instagram_embed_info` 1790-1808 | `TestInstagramEmbedFallback`, `TestCapturedInstagramFixtures` |
| preset ffmpeg args | `_preset_ffmpeg_args` 227-251 | `TestClipAndPresets` |
| playlist folders / concurrency | `queue_manager.py` | `test_playlist.py` (untouched in Phase 2) |

Rule for every fan-out agent: if a Phase 1 test has to change, **stop and report** instead.

## 7. Migration order

Each step ends with the full suite green and a commit; the app behaves identically until step 5.

1. **2.0** base + registry + `errors.py` enum + registry test. *(this step)*
2. **2.C-music** `music.py` + `mediaops.py`; facade delegates `resolve_music`/`is_music_url`.
   Includes the Spotify cover fix **with its regression test**.
3. **2.A** `tiktok.py`; `extract_info`/`inspect_entries` try the TikTok adapter first for
   photo URLs. Re-attempt the `embed/v2` capture only from a real response.
4. **2.B** `instagram.py`; same wiring for Instagram URLs.
5. **2.C-generic** `generic.py` + `common.py`; move the yt-dlp/photo/download bodies. This is
   the step that actually switches `download_media` onto the registry.
6. **2.D** error codes `LINK_EXPIRED` / `PLATFORM_CHANGED` + `detail` + frontend map.
7. **2.E / 2.G / 2.H** as scoped below (frontend merges serialized).

Steps 2–4 are additive (probe-only), so a regression is easy to bisect; step 5 is the only one
that can affect downloads for URLs no adapter claims.

## 8. Ownership for the fan-out

| ID | Owns (may edit) | Must not touch |
|---|---|---|
| 2.A | `adapters/tiktok.py`, `tests/test_adapter_tiktok.py`, `tests/fixtures/tiktok/**` | `extractor.py`, other adapters, `base.py` |
| 2.B | `adapters/instagram.py`, `tests/test_adapter_instagram.py` | `extractor.py`, other adapters |
| 2.C | `adapters/music.py`, `adapters/generic.py`, `adapters/common.py`, `services/mediaops.py`, their tests | `base.py`, `registry.py`, `errors.py` |
| 2.D | `services/errors.py` (after 2.0), API error response layer, frontend error display | adapters' extraction logic |
| 2.E | `backend/app/api/health_platforms.py` (new), Settings "Test platforms" component | `PreviewCard.tsx`, adapters |
| 2.F | `docs/dev/extractor-update.md` only, unless verification fails | `extractor_update.py` without approval |
| 2.G | diagnostics module + Settings button | network code |
| 2.H | `desktop/*`, `SettingsView.tsx` install section only, new tests | adapters, other Settings sections |

Serialized merges: 2.D → 2.E → 2.G (Settings), and 2.H last (it touches `SettingsView.tsx`
too).

## 9. Decisions this doc asks you to approve

1. **Keep the existing error codes** instead of renaming to the handoff's vocabulary.
2. **`DownloadContext` instead of `DownloadPlan`** (§3).
3. **`mediaops.py` + `common.py`** as shared modules, so adapters never import `extractor`.
4. **2.F is verification, not implementation** — the updater already exists.
5. **Facade stays** — `extractor.py` keeps its public names; only internals move.
