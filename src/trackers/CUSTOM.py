import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import requests

import cli_ui

from src.bbcode import BBCodeTemplateContext, format_c411, format_ygg
from src.console import console
from src.trackers.COMMON import COMMON


class CustomUploadError(RuntimeError):
    pass


def _env(tracker: str, key: str) -> Optional[str]:
    tracker = (tracker or "").strip().upper()
    candidates = [
        f"{tracker}_{key}",
        f"{tracker}_{key}".replace("-", "_"),
    ]
    for c in candidates:
        v = os.environ.get(c)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return None


def _parse_json_env(value: Optional[str]) -> dict[str, Any]:
    value = (value or "").strip()
    if not value:
        return {}
    data = json.loads(value)
    if not isinstance(data, dict):
        raise CustomUploadError("FORM_FIELDS_JSON doit être un objet JSON")
    return {str(k): v for k, v in data.items()}


def _parse_csv_env(value: Optional[str]) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip() != ""]


def _parse_hidden_input(html: str, field_names: list[str]) -> Optional[tuple[str, str]]:
    for name in field_names:
        pattern = (
            r'<input[^>]+type=["\']hidden["\'][^>]+name=["\']'
            + re.escape(name)
            + r'["\'][^>]+value=["\']([^"\']+)["\']'
        )
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return name, match.group(1)
    return None


@dataclass(frozen=True)
class CustomTrackerProfile:
    tracker: str
    source_flag: str
    announce_url: str
    upload_url: str
    upload_page_url: Optional[str] = None
    torrent_field: str = "torrent"
    nfo_field: str = "nfo"
    description_field: str = "description"
    csrf_field_names: list[str] = field(default_factory=lambda: ["csrf_token", "_token", "csrf", "authenticity_token"])
    success_regex: Optional[str] = None


class CustomTrackerUploader:
    def __init__(self, config, profile: CustomTrackerProfile) -> None:
        self.config = config
        self.profile = profile
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def _load_cookies(self) -> None:
        cookie_header = _env(self.profile.tracker, "COOKIE")
        if cookie_header:
            self.session.headers["Cookie"] = cookie_header
            return
        cookie_json = _env(self.profile.tracker, "COOKIE_JSON")
        if cookie_json:
            cookie_dict = json.loads(cookie_json)
            if not isinstance(cookie_dict, dict):
                raise CustomUploadError("COOKIE_JSON doit être un objet JSON")
            self.session.cookies.update({str(k): str(v) for k, v in cookie_dict.items()})
            return

    def _fetch_csrf(self) -> dict[str, str]:
        if not self.profile.upload_page_url:
            return {}
        resp = self.session.get(self.profile.upload_page_url, timeout=45)
        if resp.status_code >= 400:
            raise CustomUploadError(f"Impossible de charger la page d'upload ({resp.status_code})")
        parsed = _parse_hidden_input(resp.text, self.profile.csrf_field_names)
        if not parsed:
            return {}
        name, token = parsed
        return {name: token}

    def upload_files(
        self,
        torrent_path: Path,
        nfo_path: Path,
        description_bbcode: str,
        extra_fields: Optional[Mapping[str, Any]] = None,
    ) -> requests.Response:
        self._load_cookies()
        csrf_fields = self._fetch_csrf()

        data: dict[str, Any] = {}
        data.update(csrf_fields)
        if extra_fields:
            data.update(dict(extra_fields))
        data[self.profile.description_field] = description_bbcode

        files = {
            self.profile.torrent_field: (torrent_path.name, torrent_path.read_bytes(), "application/x-bittorrent"),
            self.profile.nfo_field: (nfo_path.name, nfo_path.read_bytes(), "text/plain"),
        }

        resp = self.session.post(
            self.profile.upload_url,
            data=data,
            files=files,
            timeout=90,
            allow_redirects=True,
        )
        if resp.status_code >= 400:
            raise CustomUploadError(f"Upload échoué ({resp.status_code})")
        if self.profile.success_regex and not re.search(self.profile.success_regex, resp.text, flags=re.IGNORECASE):
            raise CustomUploadError("Réponse d'upload non reconnue (success_regex non match)")
        return resp


class _CUSTOM_BASE:
    def __init__(self, config, tracker: str, default_source_flag: str) -> None:
        self.config = config
        self.tracker = tracker
        self.source_flag = _env(tracker, "SOURCE_FLAG") or default_source_flag
        self.signature = None
        self.banned_groups = [""]

    def _profile(self) -> CustomTrackerProfile:
        announce_url = _env(self.tracker, "ANNOUNCE_URL")
        upload_url = _env(self.tracker, "UPLOAD_URL")
        upload_page_url = _env(self.tracker, "UPLOAD_PAGE_URL")
        torrent_field = _env(self.tracker, "TORRENT_FIELD") or "torrent"
        nfo_field = _env(self.tracker, "NFO_FIELD") or "nfo"
        description_field = _env(self.tracker, "DESCRIPTION_FIELD") or "description"
        csrf_field_names = _parse_csv_env(_env(self.tracker, "CSRF_FIELD_NAMES")) or ["csrf_token", "_token", "csrf", "authenticity_token"]
        success_regex = _env(self.tracker, "SUCCESS_REGEX")

        if not announce_url:
            raise CustomUploadError(f"{self.tracker}_ANNOUNCE_URL manquant")
        if not upload_url:
            raise CustomUploadError(f"{self.tracker}_UPLOAD_URL manquant")

        return CustomTrackerProfile(
            tracker=self.tracker,
            source_flag=self.source_flag,
            announce_url=announce_url,
            upload_url=upload_url,
            upload_page_url=upload_page_url,
            torrent_field=torrent_field,
            nfo_field=nfo_field,
            description_field=description_field,
            csrf_field_names=csrf_field_names,
            success_regex=success_regex,
        )

    def _template_text(self) -> Optional[str]:
        direct = _env(self.tracker, "BBCODE_TEMPLATE")
        if direct:
            return direct
        template_path = _env(self.tracker, "BBCODE_TEMPLATE_PATH")
        if template_path and os.path.exists(template_path):
            return Path(template_path).read_text(encoding="utf-8")
        return None

    def _extra_fields(self) -> dict[str, Any]:
        fields = _parse_json_env(_env(self.tracker, "FORM_FIELDS_JSON"))
        return fields

    def _find_or_make_nfo(self, meta) -> Path:
        content_path = Path(meta["path"])
        search_dir = content_path if content_path.is_dir() else content_path.parent
        candidates = sorted(search_dir.glob("*.nfo"))
        if candidates:
            return candidates[0]

        mi_path = Path(meta["base_dir"]) / "tmp" / meta["uuid"] / "MEDIAINFO.txt"
        nfo_out = Path(meta["base_dir"]) / "tmp" / meta["uuid"] / f"[{self.tracker}]{meta['clean_name']}.nfo"
        if mi_path.exists():
            nfo_out.write_text(mi_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            return nfo_out
        nfo_out.write_text("", encoding="utf-8")
        return nfo_out

    async def validate_credentials(self, meta) -> bool:
        try:
            _ = self._profile()
        except Exception as e:
            console.print(f"[red]{e}")
            return False
        cookie = _env(self.tracker, "COOKIE") or _env(self.tracker, "COOKIE_JSON")
        if not cookie:
            console.print(f"[red]{self.tracker}: COOKIE manquant (env {self.tracker}_COOKIE ou {self.tracker}_COOKIE_JSON)")
            return False
        return True

    async def search_existing(self, meta):
        return []

    async def edit_desc(self, meta):
        mi_path = Path(meta["base_dir"]) / "tmp" / meta["uuid"] / "MEDIAINFO.txt"
        mediainfo = ""
        if mi_path.exists():
            mediainfo = mi_path.read_text(encoding="utf-8", errors="replace").strip()

        poster = meta.get("rehosted_poster") or meta.get("poster") or ""
        imdb_url = ""
        if str(meta.get("imdb_id", "0")) not in ("0", "", None):
            imdb_url = f"https://www.imdb.com/title/tt{meta['imdb_id']}"
        tmdb_url = ""
        if str(meta.get("tmdb", "0")) not in ("0", "", None):
            tmdb_url = f"https://www.themoviedb.org/{meta['category'].lower()}/{meta['tmdb']}"

        ctx = BBCodeTemplateContext(
            title=str(meta.get("title", "")),
            year=str(meta.get("year", "")),
            overview=str(meta.get("overview", "")),
            poster_url=str(poster),
            mediainfo=str(mediainfo),
            imdb_url=str(imdb_url),
            tmdb_url=str(tmdb_url),
        )
        template_text = self._template_text()
        if self.tracker == "YGG":
            desc = format_ygg(ctx, template_text=template_text)
        else:
            desc = format_c411(ctx, template_text=template_text)

        out_path = Path(meta["base_dir"]) / "tmp" / meta["uuid"] / f"[{self.tracker}]DESCRIPTION.txt"
        out_path.write_text(desc, encoding="utf-8")

    async def upload(self, meta):
        common = COMMON(config=self.config)
        profile = self._profile()
        await common.add_tracker_torrent(meta, self.tracker, profile.source_flag, profile.announce_url, "")
        await self.edit_desc(meta)

        torrent_path = Path(meta["base_dir"]) / "tmp" / meta["uuid"] / f"[{self.tracker}]{meta['clean_name']}.torrent"
        if not torrent_path.exists():
            raise CustomUploadError(f".torrent introuvable: {torrent_path}")

        nfo_path = self._find_or_make_nfo(meta)
        desc_path = Path(meta["base_dir"]) / "tmp" / meta["uuid"] / f"[{self.tracker}]DESCRIPTION.txt"
        description = desc_path.read_text(encoding="utf-8", errors="replace")

        uploader = CustomTrackerUploader(self.config, profile)
        resp = uploader.upload_files(
            torrent_path=torrent_path,
            nfo_path=nfo_path,
            description_bbcode=description,
            extra_fields=self._extra_fields(),
        )
        if meta.get("unattended", False) is False:
            cli_ui.info_section(cli_ui.green, f"{self.tracker} Upload OK")
        return resp


class YGG(_CUSTOM_BASE):
    def __init__(self, config):
        super().__init__(config=config, tracker="YGG", default_source_flag="ygg")


class C411(_CUSTOM_BASE):
    def __init__(self, config):
        super().__init__(config=config, tracker="C411", default_source_flag="c411")

