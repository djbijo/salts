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
import json
from salts_lib.db_utils import DB_Connection
from salts_lib.constants import VIDEO_TYPES
from salts_lib.constants import QUALITIES

BASE_URL = 'http://movietv.to'

class MovieTV_Scraper(scraper.Scraper):
    base_url = BASE_URL

    def __init__(self, timeout=scraper.DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.db_connection = DB_Connection()
        self.base_url = xbmcaddon.Addon().getSetting('%s-base_url' % (self.get_name()))

    @classmethod
    def provides(cls):
        return frozenset([VIDEO_TYPES.TVSHOW, VIDEO_TYPES.EPISODE, VIDEO_TYPES.MOVIE])

    @classmethod
    def get_name(cls):
        return 'movietv.to'

    def resolve_link(self, link):
        return link

    def format_source_label(self, item):
        label = '[%s] %s ' % (item['quality'], item['host'])
        return label

    def get_sources(self, video):
        source_url = self.get_url(video)
        hosters = []
        if source_url:
            url = urlparse.urljoin(self.base_url, source_url)
            html = self._http_get(url, cache_limit=1)
            if video.video_type == VIDEO_TYPES.MOVIE:
                pattern = 'show.start\((.*?)\);'
                quality = QUALITIES.HD
            else:
                pattern = 'vars\.links\s*=\s*(.*?);'
                quality = QUALITIES.HIGH

            match = re.search(pattern, html)
            if match:
                js_data = json.loads(match.group(1))
                if video.video_type == VIDEO_TYPES.EPISODE:
                    js_data = js_data[str(video.episode)][0] if str(video.episode) in js_data else {}

                if 'url' in js_data:
                    stream_url = js_data['url'] + '|referer=%s' % (url)
                    hoster = {'multi-part': False, 'host': 'movietv.to', 'class': self, 'url': stream_url, 'quality': quality, 'views': None, 'rating': None, 'direct': True}
                    hosters.append(hoster)
        return hosters

    def get_url(self, video):
        return super(MovieTV_Scraper, self)._default_get_url(video)

    def _get_episode_url(self, show_url, video):
        season_url = '%s/seasons/%s' % (show_url, video.season)
        return season_url

    def search(self, video_type, title, year):
        results = []
        html = self._http_get(self.base_url)
        r = re.search("token\s*:\s*'([^']+)", html)
        if r:
            url = urlparse.urljoin(self.base_url, '/titles1/paginate?_token=%s&query=' % (r.group(1)))
            url += urllib.quote_plus(title)
            if video_type == VIDEO_TYPES.MOVIE:
                url += '&type=movie'
            else:
                url += '&type=series'
            url += '&order=mc_num_of_votesDesc'
            html = self._http_get(url, headers={'X-Requested-With': 'XMLHttpRequest'}, cache_limit=.25)

            if html:
                try:
                    js_results = json.loads(html)
                    for item in js_results['items']:
                        if not year or not item['year'] or int(year) == int(item['year']):
                            if video_type == VIDEO_TYPES.MOVIE:
                                url = '/movies'
                            else:
                                url = '/series'
                            url += '/%s-%s' % (item['id'], item['title'].lower().replace(' ', '-'))
                            result = {'url': url, 'title': item['title'], 'year': item['year']}
                            results.append(result)
                except:
                    pass

        return results

    def _http_get(self, url, data=None, headers=None, cache_limit=8):
        return super(MovieTV_Scraper, self)._cached_http_get(url, self.base_url, self.timeout, data=data, headers=headers, cache_limit=cache_limit)
