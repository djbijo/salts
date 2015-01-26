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
import abc
import urllib2
import urllib
import urlparse
import cookielib
import xbmc
import xbmcaddon
import xbmcgui
import os
import re
import time
from StringIO import StringIO
import gzip
from salts_lib import log_utils
from salts_lib.db_utils import DB_Connection
from salts_lib.constants import VIDEO_TYPES
from salts_lib.constants import USER_AGENT
from salts_lib.constants import QUALITIES
from salts_lib.constants import HOST_Q
from salts_lib.constants import Q_ORDER
from salts_lib.constants import BLOG_Q_MAP

BASE_URL=''
CAPTCHA_BASE_URL = 'http://www.google.com/recaptcha/api'
COOKIEPATH=xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))

Q_LIST = [item[0] for item in sorted(Q_ORDER.items(), key=lambda x:x[1])]

abstractstaticmethod = abc.abstractmethod
class abstractclassmethod(classmethod):

    __isabstractmethod__ = True

    def __init__(self, callable):
        callable.__isabstractmethod__ = True
        super(abstractclassmethod, self).__init__(callable)

DEFAULT_TIMEOUT=30

class Scraper(object):
    __metaclass__ = abc.ABCMeta
    base_url=BASE_URL
    
    def __init__(self, timeout=DEFAULT_TIMEOUT):
        self.db_connection = DB_Connection()

    @abstractclassmethod
    def provides(cls):
        """
        Must return a list/set/frozenset of VIDEO_TYPES that are supported by this scraper. Is a class method so that instances of the class 
        don't have to be instantiated to determine they are not useful
        
        * Datatypes set or frozenset are preferred as existence checking is faster with sets
        """
        raise NotImplementedError
        
    @abstractclassmethod
    def get_name(cls):
        """
        Must return a string that is a name that will be used through out the UI and DB to refer to urls from this source
        Should be descriptive enough to be recognized but short enough to be presented in the UI
        """
        raise NotImplementedError

    @abc.abstractmethod 
    def resolve_link(self, link):
        """
        Must return a string that is a urlresolver resolvable link given a link that this scraper supports
        
        link: a url fragment associated with this site that can be resolved to a hoster link 

        * The purpose is many streaming sites provide the actual hoster link in a separate page from link
        on the video page.
        * This method is called for the user selected source before calling urlresolver on it.
        """
        raise NotImplementedError

    @abc.abstractmethod 
    def format_source_label(self, item):
        """
        Must return a string that is to be the label to be used for this source in the "Choose Source" dialog
        
        item: one element of the list that is returned from get_sources for this scraper
        """
        raise NotImplementedError

    @abc.abstractmethod 
    def get_sources(self, video):
        """
        Must return a list of dictionaries that are potential link to hoster sites (or links to links to hoster sites)
        Each dictionary must contain elements of at least:
            * multi-part: True if this source is one part of a whole
            * class: a reference to an instance of the scraper itself
            * host: the hostname of the hoster
            * url: the url that is a link to a hoster, or a link to a page that this scraper can resolve to a link to a hoster
            * quality: one of the QUALITIES values, or None if unknown; users can sort sources by quality
            * views: count of the views from the site for this source or None is unknown; Users can sort sources by views
            * rating: a value between 0 and 100; 0 being worst, 100 the best, or None if unknown. Users can sort sources by rating.
            * direct: True if url is a direct link to a media file; False if not. If not present; assumption is direct 
            * other keys are allowed as needed if they would be useful (e.g. for format_source_label)
        
        video is an object of type ScraperVideo:
            video_type: one of VIDEO_TYPES for whatever the sources should be for
            title: the title of the tv show or movie
            year: the year of the tv show or movie
            season: only present for tv shows; the season number of the video for which sources are requested
            episode: only present for tv shows; the episode number of the video for which sources are requested
            ep_title: only present for tv shows; the episode title if available        
        """
        raise NotImplementedError

    @abc.abstractmethod 
    def get_url(self, video):
        """
        Must return a url for the site this scraper is associated with that is related to this video.
        
        video is an object of type ScraperVideo:
            video_type: one of VIDEO_TYPES this url is for (e.g. EPISODE urls might be different than TVSHOW urls)
            title: the title of the tv show or movie
            year: the year of the tv show or movie
            season: only present for season or episode VIDEO_TYPES; the season number for the url being requested
            episode: only present for season or episode VIDEO_TYPES; the episode number for the url being requested
            ep_title: only present for tv shows; the episode title if available        
        
        * Generally speaking, domain should not be included
        """
        raise NotImplementedError
    
    def _default_get_url(self, video):
        temp_video_type=video.video_type
        if video.video_type == VIDEO_TYPES.EPISODE: temp_video_type=VIDEO_TYPES.TVSHOW
        url = None

        result = self.db_connection.get_related_url(temp_video_type, video.title, video.year, self.get_name())
        if result:
            url=result[0][0]
            log_utils.log('Got local related url: |%s|%s|%s|%s|%s|' % (temp_video_type, video.title, video.year, self.get_name(), url))
        else:
            results = self.search(temp_video_type, video.title, video.year)
            if results:
                url = results[0]['url']
                self.db_connection.set_related_url(temp_video_type, video.title, video.year, self.get_name(), url)

        if url and video.video_type==VIDEO_TYPES.EPISODE:
            result = self.db_connection.get_related_url(VIDEO_TYPES.EPISODE, video.title, video.year, self.get_name(), video.season, video.episode)
            if result:
                url=result[0][0]
                log_utils.log('Got local related url: |%s|%s|%s|' % (video, self.get_name(), url))
            else:
                show_url = url
                url = self._get_episode_url(show_url, video)
                if url:
                    self.db_connection.set_related_url(VIDEO_TYPES.EPISODE, video.title, video.year, self.get_name(), url, video.season, video.episode)
        
        return url

    @abc.abstractmethod 
    def search(self, video_type, title, year):
        """
        Must return a list of results returned from the site associated with this scraper when doing a search using the input parameters
        
        If it does return results, it must be a list of dictionaries. Each dictionary must contain at least the following:
            * title: title of the result
            * year: year of the result
            * url: a url fragment that is the url on the site associated with this scraper for this season result item
        
        video_type: one of the VIDEO_TYPES being searched for. Only tvshows and movies are expected generally
        title: the title being search for
        year: the year being search for
        
        * Method must be provided, but can raise NotImplementedError if search not available on the site
        """
        raise NotImplementedError

    @classmethod
    def get_settings(cls):
        """
        Returns a list of settings to be used for this scraper. Settings are automatically checked for updates every time scrapers are imported
        The list returned by each scraper is aggregated into a big settings.xml string, and then if it differs from the current settings xml in the Scrapers category
        the existing settings.xml fragment is removed and replaced by the new string
        """
        name=cls.get_name()
        return ['         <setting id="%s-enable" type="bool" label="%s Enabled" default="true" visible="true"/>' % (name, name),
                    '         <setting id="%s-base_url" type="text" label="     Base Url" default="%s" visible="eq(-1,true)"/>' % (name, cls.base_url),
                    '         <setting id="%s-sub_check" type="bool" label="     Include in Page Existence checks?" default="true" visible="eq(-2,true)"/>' % (name),
                    '         <setting id="%s_try" type="number" default="0" visible="false"/>' % (name),
                    '         <setting id="%s_fail" type="number" default="0" visible="false"/>' % (name),
                    '         <setting id="%s_check" type="number" default="0" visible="false"/>' % (name),]
    
    @classmethod
    def _disable_sub_check(cls, settings):
        for i in reversed(xrange(len(settings))):
            if 'sub_check' in settings[i]:
                settings[i]=settings[i].replace('default="true"', 'default="false"')
        return settings
        
    def _cached_http_get(self, url, base_url, timeout, cookies=None, data=None, headers=None, cache_limit=8):
        if cookies is None: cookies={}
        if timeout == 0: timeout = None
        if headers is None: headers={}
        referer = headers['Referer'] if 'Referer' in headers else url
        log_utils.log('Getting Url: %s cookie=|%s| data=|%s| extra headers=|%s|' % (url, cookies, data, headers))
        db_connection = DB_Connection()
        _, html = db_connection.get_cached_url(url, cache_limit)
        if html:
            log_utils.log('Returning cached result for: %s' % (url), xbmc.LOGDEBUG)
            return html
        
        try:
            cj = self._set_cookies(base_url, cookies)
            if data is not None: data=urllib.urlencode(data, True)    
            request = urllib2.Request(url, data=data)
            request.add_header('User-Agent', USER_AGENT)
            request.add_unredirected_header('Host', request.get_host())
            request.add_unredirected_header('Referer', referer)
            for key in headers: request.add_header(key,headers[key])
            response = urllib2.urlopen(request, timeout=timeout)
            cj.save(ignore_discard=True, ignore_expires=True)
            if response.info().get('Content-Encoding') == 'gzip':
                buf = StringIO( response.read())
                f = gzip.GzipFile(fileobj=buf)
                html = f.read()
            else:
                html=response.read()
        except Exception as e:
            log_utils.log('Error (%s) during scraper http get: %s' % (str(e), url), xbmc.LOGWARNING)
            return ''
        
        db_connection.cache_url(url, html)
        return html

    def _set_cookies(self, base_url, cookies):
        domain=urlparse.urlsplit(base_url).hostname
        cookie_file = os.path.join(COOKIEPATH,'%s_cookies.lwp' % (self.get_name()))
        cj=cookielib.LWPCookieJar(cookie_file)
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
        urllib2.install_opener(opener)
        for key in cookies:
            c=cookielib.Cookie(0, key, cookies[key], port=None, port_specified=False, domain=domain, domain_specified=True,
                                domain_initial_dot=False, path='/', path_specified=True, secure=False, expires=None, discard=False, comment=None, 
                                comment_url=None, rest={})
            cj.set_cookie(c)
        try: cj.load(ignore_discard=True)
        except: pass
        return cj

    def _do_recaptcha(self, key, tries=None, max_tries=None):
        challenge_url = CAPTCHA_BASE_URL + '/challenge?k=%s' % (key)
        html = self._cached_http_get(challenge_url, CAPTCHA_BASE_URL, timeout=DEFAULT_TIMEOUT, cache_limit=0)
        match = re.search("challenge\s+\:\s+'([^']+)", html)
        captchaimg = 'http://www.google.com/recaptcha/api/image?c=%s' % (match.group(1))
        img = xbmcgui.ControlImage(450,0,400,130,captchaimg)
        wdlg = xbmcgui.WindowDialog()
        wdlg.addControl(img)
        wdlg.show()
        header = 'Type the words in the image'
        if tries and max_tries:
            header += ' (Try: %s/%s)' % (tries, max_tries)
        kb = xbmc.Keyboard('', header, False)
        kb.doModal()
        solution=''
        if kb.isConfirmed():
            solution = kb.getText()
            if not solution:
                raise Exception ('You must enter text in the image to access video')
        wdlg.close()
        return {'recaptcha_challenge_field':match.group(1),'recaptcha_response_field':solution}
    
    def _default_get_episode_url(self, show_url, video, episode_pattern, title_pattern=''):
        log_utils.log('Default Episode Url: |%s|%s|%s|' % (self.base_url, show_url, str(video).decode('utf-8', 'replace')), xbmc.LOGDEBUG)
        url = urlparse.urljoin(self.base_url, show_url)
        html = self._http_get(url, cache_limit=2)
        if html:
            force_title = self._force_title(video)
            
            if not force_title: 
                match = re.search(episode_pattern, html, re.DOTALL)
                if match:
                    url = match.group(1)
                    return url.replace(self.base_url, '')
            else:
                log_utils.log('Skipping S&E matching as title search is forced on: %s' % (video.slug), xbmc.LOGDEBUG)
            
            if (force_title or xbmcaddon.Addon().getSetting('title-fallback')=='true') and video.ep_title and title_pattern:
                norm_title = self._normalize_title(video.ep_title)
                for match in re.finditer(title_pattern, html, re.DOTALL | re.I):
                    url, title = match.groups()
                    if norm_title == self._normalize_title(title):
                        return url.replace(self.base_url, '')

    def _force_title(self, video):
            slug_str = xbmcaddon.Addon().getSetting('force_title_match')
            slug_list = slug_str.split('|') if slug_str else []
            return video.slug in slug_list
    
    def _normalize_title(self, title):
        new_title=title.upper()
        new_title=re.sub('\W', '', new_title)
        #log_utils.log('In title: |%s| Out title: |%s|' % (title,new_title), xbmc.LOGDEBUG)
        return new_title

    def _blog_get_quality(self, video, q_str, host):
        """
        Use the q_str to determine the post quality; then use the host to determine host quality
        allow the host to drop the quality but not increase it
        """
        q_str.replace(video.title, '')
        q_str.replace(str(video.year), '')
        q_str = q_str.upper()
        
        post_quality = None
        for key in Q_LIST:
            if any(q in q_str for q in BLOG_Q_MAP[key]):
                post_quality=key
        
        return self._get_quality(video, host, post_quality)

    def _get_quality(self, video, host, base_quality=None):
        # Assume movies are low quality, tv shows are high quality
        if base_quality is None:
            if video.video_type == VIDEO_TYPES.MOVIE:
                quality = QUALITIES.LOW
            else:
                quality = QUALITIES.HIGH
        else:
            quality = base_quality
        
        host_quality=None
        if host:
            for key in HOST_Q:
                if any(host in hostname for hostname in HOST_Q[key]):
                    host_quality=key
        
        #log_utils.log('q_str: %s, host: %s, post q: %s, host q: %s' % (q_str, host, post_quality, host_quality), xbmc.LOGDEBUG)
        if host_quality is not None and Q_ORDER[host_quality] < Q_ORDER[quality]:
            quality=host_quality

        return quality
    
    def _width_get_quality(self, width):
        width=int(width)
        if width>=1280:
            quality=QUALITIES.HD
        elif width>640:
            quality=QUALITIES.HIGH
        elif width>320:
            quality=QUALITIES.MEDIUM
        else:
            quality=QUALITIES.LOW
        return quality

    def _height_get_quality(self, height):
        height=int(height)
        if height>=500:
            quality=QUALITIES.HD
        elif height>=400:
            quality=QUALITIES.HIGH
        elif height>200:
            quality=QUALITIES.MEDIUM
        else:
            quality=QUALITIES.LOW
        return quality
    