import re
from typing import Optional


EPISODE_RE = re.compile(r'\bS(\d{2})E(\d{2})\b', re.IGNORECASE)
RESOLUTION_RE = re.compile(r'\b(720p|1080p|2160p)\b', re.IGNORECASE)
TOONSHUB_PREFIX_RE = re.compile(r'^\[(ToonsHub)\]\s*', re.IGNORECASE)
VARYG_SUFFIX_RE = re.compile(r'-\s*(VARYG)\b', re.IGNORECASE)

_HASHTAG_RE = re.compile(r'(?<!\w)#([^\s#]+)')
_TG_MESSAGE_LINK_RE = re.compile(
    r'Онлайн\s+в\s+телеграм(?:і|i)?\s*:\s*.*?(?:https?://)?(t\.me/[A-Za-z0-9_]+/\d+)',
    re.IGNORECASE | re.MULTILINE,
)
_EPISODE_RE = re.compile(
    r'(?:(\d+)\s*сезон\s*)?\[(\d{1,2})\s*з\s*(?:\d+|[XХxх]{1,2})\]',
    re.IGNORECASE,
)
_UKRAINIAN_TITLE_RE = re.compile(r'^\s*(.*?)\s*\[', re.DOTALL)

_MVO_TAG = "Рідний_Голос_MVO"
_SUB_TAG = "Рідний_Голос_SUB"


def normalize_title(title: str) -> str:
    return re.sub(r'[^a-z0-9]', '', title.lower())


def detect_group(release_title: str) -> str | None:
    prefix_match = TOONSHUB_PREFIX_RE.search(release_title)
    if prefix_match:
        return prefix_match.group(1)

    suffix_match = VARYG_SUFFIX_RE.search(release_title)
    if suffix_match:
        return suffix_match.group(1)

    return None


def parse_episode_code(release_title: str) -> tuple[int, int, str] | None:
    match = EPISODE_RE.search(release_title)
    if not match:
        return None

    season = int(match.group(1))
    episode = int(match.group(2))
    episode_code = f"S{season:02d}E{episode:02d}"
    return season, episode, episode_code


def extract_raw_title(release_title: str) -> str | None:
    title = release_title.strip()
    title = TOONSHUB_PREFIX_RE.sub('', title)

    episode_match = EPISODE_RE.search(title)
    if not episode_match:
        return None

    raw_title = title[:episode_match.start()].strip()
    return raw_title


def detect_resolution(release_title: str) -> str | None:
    match = RESOLUTION_RE.search(release_title)
    if match:
        return match.group(1).lower()
    return None


def is_dub_release(release_title: str) -> bool:
    lowered = release_title.lower()
    return any(keyword in lowered for keyword in [
        "dual-audio",
        "dual audio",
        "dub",
        "dubbed"
    ])


def is_multi_sub_release(release_title: str) -> bool:
    lowered = release_title.lower()
    return "multi-subs" in lowered or "multi subs" in lowered


def parse_release(release_title: str) -> dict | None:
    episode_info = parse_episode_code(release_title)
    raw_title = extract_raw_title(release_title)

    if not episode_info or not raw_title:
        return None

    season, episode, episode_code = episode_info
    group = detect_group(release_title)

    return {
        "original_title": release_title,
        "group": group,
        "title": raw_title,
        "normalized_title": normalize_title(raw_title),
        "season": season,
        "episode": episode,
        "episode_code": episode_code,
        "resolution": detect_resolution(release_title),
        "is_dub": is_dub_release(release_title),
        "is_multi_sub": is_multi_sub_release(release_title),
    }

# ----------------rss

SXXE01_PATTERN = re.compile(r"\bS\d{2}E01\b", re.IGNORECASE)
SXX_ONLY_PATTERN = re.compile(r"\bS\d{2}(?!E\d)\b", re.IGNORECASE)
MOVIE_KEYWORD_PATTERN = re.compile(r"\bmovie\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\(\d{4}\)")


def is_first_episode_release(title: str) -> bool:
    return bool(SXXE01_PATTERN.search(title or ""))


def is_season_batch_release(title: str) -> bool:
    return bool(SXX_ONLY_PATTERN.search(title or ""))


def is_movie_release(title: str) -> bool:
    # Explicit "Movie" keyword
    if MOVIE_KEYWORD_PATTERN.search(title or ""):
        return True

    # Year-based heuristic: (YYYY) present and no season marker Sxx
    if YEAR_PATTERN.search(title or ""):
        if not SXX_ONLY_PATTERN.search(title):
            return True

    return False


def is_new_dub_candidate(title: str) -> bool:
    return (
        is_first_episode_release(title)
        or is_season_batch_release(title)
        or is_movie_release(title)
    )


def classify_release(title: str) -> Optional[str]:
    if is_first_episode_release(title):
        return "first_episode"
    if is_season_batch_release(title):
        return "season_batch"
    if is_movie_release(title):
        return "movie"
    return None


# ---------------- tg


def _extract_hashtags(text: str) -> list[str]:
    if not text:
        return []
    return _HASHTAG_RE.findall(text)


def has_mvo_release_tag(text: str) -> bool:
    hashtags = set(_extract_hashtags(text))
    return _MVO_TAG in hashtags and _SUB_TAG not in hashtags


def has_cyrillic(tag: str) -> bool:
    return any("\u0400" <= ch <= "\u04FF" for ch in tag)


def _cleanup_tag_title(tag: str) -> str:
    return tag.replace("_", " ").strip()


def _cleanup_ukrainian_title(title: str) -> str:
    title = re.sub(r'\s+', ' ', title).strip()
    title = title.rstrip(" -–—:;,")
    return title.strip()


def extract_show_romaji_name(text: str) -> Optional[str]:
    if not has_mvo_release_tag(text):
        return None

    for tag in _extract_hashtags(text):
        if tag in {_MVO_TAG, _SUB_TAG}:
            continue
        if not tag.endswith("_MVO"):
            continue
        if has_cyrillic(tag):
            continue

        romaji_name = tag[:-4]
        if romaji_name:
            return _cleanup_tag_title(romaji_name)

    return None


def extract_show_ukrainian_title(text: str) -> Optional[str]:
    if not text:
        return None

    match = _UKRAINIAN_TITLE_RE.search(text)
    if not match:
        return None

    title = _cleanup_ukrainian_title(match.group(1))
    return title or None


def extract_normalized_show_title(text: str) -> Optional[str]:
    romaji_name = extract_show_romaji_name(text)
    if not romaji_name:
        return None
    return normalize_title(romaji_name)


def extract_telegram_message_link(text: str) -> Optional[str]:
    if not text:
        return None

    match = _TG_MESSAGE_LINK_RE.search(text)
    if not match:
        return None

    return f"https://{match.group(1)}"


def extract_episode_code(text: str) -> Optional[str]:
    if not text:
        return None

    match = _EPISODE_RE.search(text)
    if not match:
        return None

    season = int(match.group(1)) if match.group(1) else 1
    episode = int(match.group(2))

    return f"S{season:02d}E{episode:02d}"