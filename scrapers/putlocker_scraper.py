"""
    SALTS XBMC Addon
    Copyright (C) 2014 tknorris

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import scraper
import re
import urllib
import urlparse
import xbmcaddon
from salts_lib.db_utils import DB_Connection
from salts_lib.constants import VIDEO_TYPES
from salts_lib.constants import QUALITIES

QUALITY_MAP = {'DVD': QUALITIES.HIGH, 'TS': QUALITIES.MEDIUM, 'CAM': QUALITIES.LOW}
BASE_URL = 'http://putlocker.is'

class Putlocker_Scraper(scraper.Scraper):
    base_url = BASE_URL

    def __init__(self, timeout=scraper.DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.db_connection = DB_Connection()
        self.base_url = xbmcaddon.Addon().getSetting('%s-base_url' % (self.get_name()))

    @classmethod
    def provides(cls):
        return frozenset([VIDEO_TYPES.TVSHOW, VIDEO_TYPES.SEASON, VIDEO_TYPES.EPISODE, VIDEO_TYPES.MOVIE])

    @classmethod
    def get_name(cls):
        return 'Putlocker'

    def resolve_link(self, link):
        return link

    def format_source_label(self, item):
        label = '[%s] %s' % (item['quality'], item['host'])
        return label

    def get_sources(self, video):
        source_url = self.get_url(video)
        hosters = []
        if source_url:
            url = urlparse.urljoin(self.base_url, source_url)
            html = self._http_get(url, cache_limit=.5)
            
            for match in re.finditer('<a[^>]+href="([^"]+)[^>]+>Version \d+</a>', html):
                url = match.group(1)
                host = urlparse.urlsplit(url).hostname.replace('embed.', '')
                hoster = {'multi-part': False, 'host': host, 'class': self, 'quality': self._get_quality(video, host, QUALITIES.HIGH), 'views': None, 'rating': None, 'url': url, 'direct': False}
                hosters.append(hoster)

        return hosters

    def get_url(self, video):
        return super(Putlocker_Scraper, self)._default_get_url(video)

    def search(self, video_type, title, year):
        search_url = urlparse.urljoin(self.base_url, '/search/advanced_search.php?q=%s' % (urllib.quote_plus(title)))
        if not year: year = 'Year'
        search_url += '&year_from=%s&year_to=%s' % (year, year)
        if video_type in [VIDEO_TYPES.TVSHOW, VIDEO_TYPES.EPISODE]:
            search_url += '&section=2'
        else:
            search_url += '&section=1'

        html = self._http_get(search_url, cache_limit=.25)
        results = []
        if 'Sorry, we could not find' not in html:
            r = re.search('Search Results For: "(.*?)</table>', html, re.DOTALL)
            if r:
                fragment = r.group(1)
                pattern = r'<a\s+href="([^"]+)"\s+title="([^"]+)'
                for match in re.finditer(pattern, fragment):
                    url, title_year = match.groups('')
                    match = re.search('(.*)\s+\((\d{4})\)', title_year)
                    if match:
                        match_title, match_year = match.groups()
                    else:
                        match_title = title_year
                        match_year = ''
                    
                    result = {'url': url.replace(self.base_url, ''), 'title': match_title, 'year': match_year}
                    results.append(result)
        results = dict((result['url'], result) for result in results).values()
        return results

    def _get_episode_url(self, show_url, video):
        episode_pattern = 'href="([^"]+season-%s-episode-%s-[^"]+)' % (video.season, video.episode)
        title_pattern = 'href="([^"]+season-\d+-episode-\d+-[^"]+).*?&nbsp;\s+(.*?)</td>'
        return super(Putlocker_Scraper, self)._default_get_episode_url(show_url, video, episode_pattern, title_pattern)

    def _http_get(self, url, cache_limit=8):
        return super(Putlocker_Scraper, self)._cached_http_get(url, self.base_url, self.timeout, cache_limit=cache_limit)
