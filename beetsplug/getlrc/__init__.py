"""Beets plugin to fetch synced .lrc lyrics from lrclib.net."""

from beets.plugins import BeetsPlugin
from beets.ui import Subcommand, decargs
from beets.util import bytestring_path, syspath
import requests
import urllib.parse
import os
import logging
import time
import sys
from datetime import datetime, timedelta


class _C:
    """ANSI color codes."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


class Stats:
    """Track fetch results for summary reporting."""
    def __init__(self):
        self.created = 0
        self.skipped = 0
        self.not_found = 0
        self.no_synced = 0
        self.missing_meta = 0
        self.errors = 0
        self.cached = 0

    @property
    def total(self):
        return (self.created + self.skipped + self.not_found +
                self.no_synced + self.missing_meta + self.errors + self.cached)

    def print_summary(self, use_color=False):
        c = _C if use_color else type('_NoColor', (), {k: '' for k in dir(_C) if not k.startswith('_')})()
        lines = [
            '',
            f"{c.BOLD}{'─'*50}{c.RESET}",
            f"  {c.GREEN}{'Created:':<<20}{c.RESET} {self.created}",
            f"  {'Skipped (exists):':<<20} {self.skipped}",
            f"  {'Cached skip:':<<20} {self.cached}",
            f"  {c.RED}{'Not found (404):':<<20}{c.RESET} {self.not_found}",
            f"  {c.RED}{'No synced lyrics:':<<20}{c.RESET} {self.no_synced}",
            f"  {c.YELLOW}{'Missing metadata:':<<20}{c.RESET} {self.missing_meta}",
            f"  {c.RED}{'Errors:':<<20}{c.RESET} {self.errors}",
            f"{c.BOLD}{'─'*50}{c.RESET}",
            f"  {c.BOLD}{'Total processed:':<<20}{c.RESET} {self.total}",
        ]
        print('\n'.join(lines))


class GetLrcPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self._log = logging.getLogger('beets.getlrc')
        self._use_color = sys.stderr.isatty() and not os.environ.get('NO_COLOR')

        self.config.add({
            'auto': True,
            'overwrite': False,
            'timeout': 30,
            'retries': 3,
            'delay': 0.5,
            'cache_results': True,
            'recheck_days': 30,
            'stats': True
        })

        if self.config['auto']:
            self.register_listener('item_imported', self.item_imported)
            self.register_listener('album_imported', self.album_imported)

    def _fmt(self, status, item, color=''):
        """Format a log line: Status + Artist - Album - Title."""
        artist = item.albumartist or item.artist or 'Unknown'
        album = item.album or 'Unknown Album'
        title = item.title or 'Unknown'

        if self._use_color and color:
            return (
                f"{color}{status}:{_C.RESET} "
                f"{_C.BLUE}{artist} - {album}{_C.RESET} - {title}"
            )
        return f"{status}: {artist} - {album} - {title}"

    def _print(self, status, item, color=''):
        """Print directly to stdout with color (bypasses beets logging)."""
        artist = item.albumartist or item.artist or 'Unknown'
        album = item.album or 'Unknown Album'
        title = item.title or 'Unknown'

        if self._use_color and color:
            print(
                f"{color}{status}:{_C.RESET} "
                f"{_C.BLUE}{artist} - {album}{_C.RESET} - "
                f"{_C.CYAN}{title}{_C.RESET}"
            )
        else:
            print(f"{status}: {artist} - {album} - {title}")

    def commands(self):
        cmd = Subcommand('getlrc',
                         help='Fetch synced .lrc lyrics from lrclib.net')
        cmd.parser.add_option('-f', '--force', action='store_true',
                              dest='force', help='Overwrite existing .lrc files')
        cmd.parser.add_option('-a', '--album', action='store_true',
                              dest='album', help='Match albums instead of tracks')
        cmd.parser.add_option('-p', '--pretend', action='store_true',
                              dest='pretend', help='Show what would be fetched without writing')
        cmd.parser.add_option('-s', '--stats', action='store_true',
                              dest='stats', help='Print summary stats when done')
        cmd.func = self.command
        return [cmd]

    def _request_with_retry(self, url, timeout, retries):
        for attempt in range(1, retries + 1):
            try:
                return requests.get(url, timeout=timeout)
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt == retries:
                    raise
                wait = 2 ** attempt
                self._log.debug(f'Attempt {attempt} failed ({e}), retrying in {wait}s...')
                time.sleep(wait)
        return None

    def _should_skip_cached(self, item, force):
        if force or not self.config['cache_results']:
            return False
        status = item.get('getlrc_status')
        checked_str = item.get('getlrc_checked')
        if not status or not checked_str:
            return False

        # Only skip negative results — positive results are handled by
        # the filesystem .lrc check, so deleting a file allows immediate
        # re-fetch without waiting for cache expiry.
        if status in ('created', 'exists'):
            return False

        try:
            checked = datetime.fromisoformat(checked_str)
            recheck = timedelta(days=self.config['recheck_days'].get(int))
            if datetime.now() - checked < recheck:
                self._log.debug(self._fmt(f'Cached skip ({status})', item))
                return True
        except ValueError:
            pass
        return False

    def _update_cache(self, item, status):
        if not self.config['cache_results']:
            return
        item['getlrc_status'] = status
        item['getlrc_checked'] = datetime.now().isoformat()
        item.store()

    def fetch_lrc(self, item, force=False, pretend=False, stats=None):
        base = os.path.splitext(item.path)[0]
        lrc_path = bytestring_path(base + b'.lrc')

        if not force and os.path.exists(syspath(lrc_path)):
            self._log.debug(self._fmt('Skip (exists)', item))
            self._update_cache(item, 'exists')
            if stats:
                stats.skipped += 1
            return False

        if self._should_skip_cached(item, force):
            if stats:
                stats.cached += 1
            return False

        artist = item.albumartist or item.artist or 'Unknown'
        title = item.title or 'Unknown'
        duration = int(item.length) if item.length else None

        if not item.title or not duration:
            self._log.warning(self._fmt('Skip (missing metadata)', item, _C.YELLOW))
            self._update_cache(item, 'missing')
            if stats:
                stats.missing_meta += 1
            return False

        params = {
            'artist_name': artist,
            'track_name': title,
            'duration': duration,
        }
        url = 'https://lrclib.net/api/get?' + urllib.parse.urlencode(params)

        if pretend:
            self._print('Would fetch', item, _C.CYAN)
            return True

        timeout = self.config['timeout'].get(int)
        retries = self.config['retries'].get(int)

        try:
            self._log.debug(self._fmt('Querying lrclib', item))
            response = self._request_with_retry(url, timeout, retries)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            self._log.warning(self._fmt('Timeout', item, _C.YELLOW))
            self._update_cache(item, 'timeout')
            if stats:
                stats.errors += 1
            return False
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                self._print('Not found', item, _C.RED)
                self._update_cache(item, 'not_found')
                if stats:
                    stats.not_found += 1
            else:
                code = e.response.status_code if e.response else '?'
                self._log.warning(self._fmt(f'HTTP {code}', item, _C.RED))
                self._update_cache(item, 'error')
                if stats:
                    stats.errors += 1
            return False
        except requests.RequestException:
            self._log.warning(self._fmt('Network error', item, _C.RED))
            self._update_cache(item, 'error')
            if stats:
                stats.errors += 1
            return False
        except ValueError:
            self._log.warning(self._fmt('Bad response', item, _C.RED))
            self._update_cache(item, 'error')
            if stats:
                stats.errors += 1
            return False

        synced = data.get('syncedLyrics')
        if not synced or synced in (None, 'null', 'None'):
            self._print('No synced lyrics', item, _C.RED)
            self._update_cache(item, 'no_synced')
            if stats:
                stats.no_synced += 1
            return False

        try:
            with open(syspath(lrc_path), 'w', encoding='utf-8') as f:
                f.write(synced)
            self._print('Created', item, _C.GREEN)
            self._update_cache(item, 'created')
            if stats:
                stats.created += 1
            return True
        except OSError as e:
            self._log.error(self._fmt('Write failed', item, _C.RED) + f' ({e})')
            self._update_cache(item, 'error')
            if stats:
                stats.errors += 1
            return False

    def item_imported(self, lib, item):
        self.fetch_lrc(item, force=self.config['overwrite'].get(bool))
        time.sleep(self.config['delay'].get(float))

    def album_imported(self, lib, album):
        for item in album.items():
            self.fetch_lrc(item, force=self.config['overwrite'].get(bool))
            time.sleep(self.config['delay'].get(float))

    def command(self, lib, opts, args):
        force = opts.force or self.config['overwrite'].get(bool)
        pretend = opts.pretend
        show_stats = opts.stats
        stats = Stats() if show_stats else None

        if opts.album:
            for album in lib.albums(decargs(args)):
                for item in album.items():
                    self.fetch_lrc(item, force=force, pretend=pretend, stats=stats)
                    time.sleep(self.config['delay'].get(float))
        else:
            for item in lib.items(decargs(args)):
                self.fetch_lrc(item, force=force, pretend=pretend, stats=stats)
                time.sleep(self.config['delay'].get(float))

        if show_stats and stats:
            stats.print_summary(use_color=self._use_color)