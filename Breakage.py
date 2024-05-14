import logging
import pprint
from http.cookies import SimpleCookie
from re import findall
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import requests

from Helper import write_msg

Urls     = list[str]
WebPages = dict[str, list[str]]

DEFAULT_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/109.0.5414.119 Safari/537.36'

DEBUG = False


class Breakage(object):
    """Use Breakage to detect website breakage"""

    def __init__(self, urls: Urls, threshold: int,
                 verbose: bool = True, cookies: str = '',
                 user_agent: Optional[str] = None) -> None:
        """Initialize a Breakage object"""

        self.urls = urls
        assert len(self.urls) > 0
        self.verbose = verbose
        self.threshold = threshold
        self.cookies = cookies
        # 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36'
        # 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/109.0.5414.119 Safari/537.36'
        if user_agent is None:
            self.user_agent = DEFAULT_USER_AGENT
        else:
            self.user_agent = user_agent

        self.debug_counter = 0

        self.baseline()

    def baseline(self) -> None:
        """Make a baseline measurement for a working website"""

        raise NotImplementedError

    def broken(self, id=-1):
        """Check if a website is broken, compared to the baseline"""

        raise NotImplementedError

    def print(self, message: str) -> None:
        """Helper method for printing or not"""

        if self.verbose:
            write_msg(message)

    def pprint(self, x) -> None:
        """Helper method for pprinting or not"""

        if self.verbose:
            write_msg(pprint.pformat(x))

    @staticmethod
    def cookiestr_to_dict(cookies: str) -> dict:
        """Make a dictionary from a standard cookie string"""

        # is there a library definition of this function? yes
        # d = dict()
        # for cookie in cookies.split("; "):
        #     # print(f'cookie = {cookie}')
        #     if len(cookie.strip()) == 0:
        #         continue
        #     (k,v) = cookie.strip().split("=", 1)  # values can include '='
        #     d[k] = v
        # return d
        cookie = SimpleCookie()
        cookie.load(cookies)
        return {k: v.value for k, v in cookie.items()}


# TODO use get_webpages
class LengthBreakage(Breakage):
    """Breakage defined on content length and status codes"""

    def baseline(self):
        self.baselines = []
        for url in self.urls:
            self.print(url)
            baseline = self.get_webpage(url)
            assert baseline is not None
            self.print(f"baseline status code: {baseline.status}")
            self.print(f"baseline headers: {baseline.headers}")
            self.print(f"baseline content: {baseline.read()}")
            self.print(f"baseline content length: {len(baseline.read())}")
            self.baselines.append(baseline)

    def broken(self, id=-1):
        broken = False
        for j in range(len(self.urls)):
            if self.is_broken(self.urls[j], self.baselines[j]):
                self.print(f'{self.urls[j]} is broken')
                broken = True
                break
        return broken

    def get_webpage(self, url: str) -> Any:
        """Helper method to get a webpage"""

        req = Request(url)
        response = None
        try:
            response = urlopen(req)
        except HTTPError as e:
            self.print(f'The server couldn\'t fulfill the request to {url}.')
            self.print(f'Error code: {e.code}')
        except URLError as e:
            self.print('We failed to reach a server.')
            self.print(f'Reason: {e.reason}')
        return response

    def compare_broken(self, baseline: Any, current: Any) -> bool:
        """Helper method to compare against baseline for breakage"""

        if baseline.status != current.status:
            return True

        assert self.threshold > 0
        if len(current.read()) < self.threshold:
            return True
        return False

    def is_broken(self, url: str, baseline) -> bool:
        """Helper method to check a single URL for breakage"""

        state = self.get_webpage(url)
        if state is None:
            return True
        return self.compare_broken(baseline, state)


class UrlBreakage(Breakage):
    """Breakage defined on links and status code"""

    def baseline(self):
        self.baselines = self.get_webpages()
        self.pprint(self.baselines)
        self.print(f"baseline checked URLS: {len(self.baselines)}")
        logging.debug(('dbfuzz', 'url_breakage', 'baseline', 'urls', 'length', len(self.baselines)))
        self.print(f"baseline total found links: {sum([len(v) for v in self.baselines.values()])}")
        for url in self.baselines:
            logging.debug(('dbfuzz', 'url_breakage', 'baseline', 'url', url))
            for link in self.baselines[url]:
                logging.debug(('dbfuzz', 'url_breakage', 'baseline', 'link', url, link))

    def broken(self, id=-1):
        try:
            state = self.get_webpages()  # throws exception
            broken = self.broken_state(state, id)
            return broken
        except (ConnectionError,  # built-in, necessary?
                requests.exceptions.SSLError,
                requests.exceptions.TooManyRedirects,
                requests.exceptions.ConnectionError,
                requests.exceptions.InvalidURL):
            # fuzzing can turn SSL on... (WordPress, PrestaShop)
            # fuzzing can change the site URL (PrestaShop)
            return True
        # maybe want to handle more exceptions?
        # these are the only ones I have seen so far

    def get_webpages(self) -> WebPages:
        """Helper method to get a set of webpages"""

        # throws exception when any webpage cannot be connected to
        # state = URL -> links from that URL
        state = {}
        for url in self.urls:
            self.print(f"checking {url} {self.debug_counter}")
            try:
                assert len(self.user_agent) > 0
                headers = {'user-agent': self.user_agent}
                req = requests.get(url,
                                   cookies=self.cookiestr_to_dict(self.cookies),
                                   headers=headers)
                links = findall('href="(.*?)"', req.content.decode())
                state[url] = links
                if DEBUG:
                    # could sanitize more...
                    sanitized_url = url.translate({ord(i): None for i in ':/'})
                    with open(f'output/{sanitized_url}-{self.debug_counter}.html', 'w') as f:
                        f.write(req.text)
                self.debug_counter += 1
            except requests.exceptions.SSLError as e:
                self.print(f'webpage {url} had a SSL error: {e}')
                logging.warning(f'webpage {url} had a SSL error: {e}')
                raise e
            except requests.exceptions.TooManyRedirects as e:
                self.print(f'webpage {url} had too many redirects: {e}')
                logging.warning(f'webpage {url} had too many redirects: {e}')
                raise e
            except (ConnectionError, requests.exceptions.ConnectionError) as e:
                self.print(f'webpage {url} is missing: {e}')
                logging.warning(f'webpage {url} is missing: {e}')
                raise e
            except requests.exceptions.InvalidURL as e:
                self.print(f'webpage {url} is invalid: {e}')
                logging.warning(f'webpage {url} is invalid: {e}')
                raise e
        return state

    def broken_state(self, state: WebPages, id: int) -> bool:
        """Helper method to compare against a baseline, and check if broken"""

        # Here we can reason about the state difference.
        # Perhaps we want to clean up the URLs, ignoring anchors, queries etc.
        # TODO function instead of exact equality
        total_links = 0
        missing_links = 0

        broken = False  # no short-circuiting with return, want complete stats
        for url in self.baselines:
            if url not in state:
                self.print(f"New state is missing scan of {url}. Fully broken?")
                logging.debug(('dbfuzz', 'url_breakage', 'broken', 'url', 'missing', url, id))
                broken = True
            else:
                logging.debug(('dbfuzz', 'url_breakage', 'broken', 'url', 'present', url, id))
                for link in self.baselines[url]:
                    total_links += 1
                    if link not in state[url]:
                        self.print(f"New state is missing {link} in {url}.")
                        logging.debug(('dbfuzz', 'url_breakage', 'broken', 'link', 'missing', url, link, id))
                        missing_links += 1
                    else:
                        logging.debug(('dbfuzz', 'url_breakage', 'broken', 'link', 'present', url, link, id))
                for link in state[url]:
                    if link not in self.baselines[url]:
                        logging.debug(('dbfuzz', 'url_breakage', 'broken', 'link', 'new', url, link, id))

        if broken:
            return True

        assert self.threshold > 0 and self.threshold < 100
        frac_threshold = self.threshold / 100.0
        frac_missing = float(missing_links) / float(total_links)

        self.print(f"Missing: {missing_links} / {total_links} = {frac_missing:.3f}, vs {frac_threshold:.3f} threshold")
        return  frac_missing > frac_threshold
