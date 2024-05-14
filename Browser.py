import os
import re
import shutil
import time

from selenium import webdriver
from selenium.webdriver.common.keys import Keys

from Helper import is_url, write_msg

COOKIE_DIR = 'cookies'
# CREDENTIAL_REGEX = r'(\S+)=(\S+),(\S+)=(\S+)'  # old format
BACKWARDS_COMPATIBLE = 'match=0,'
NEW_CREDENTIAL_REGEX = r'match=([0-9]+),(\S+)=(\S+),(\S+)=(\S+)'  # refer to config_sample.ini

# Credentials should contain username/password fields and values
# E.g. for wordpress
# log=admin,pwd=admin
def login(url: str, credentials: str, headless: bool = True, auto: bool = True) -> dict[str, str]:
    """Login to a webpage in a browser to get cookies, user agent, and returned URL"""

    assert is_url(url)
    if not re.match(NEW_CREDENTIAL_REGEX, credentials):  # backwards compatibility (match=0)
        credentials = BACKWARDS_COMPATIBLE + credentials
        write_msg(f'BACKWARDS COMPATIBILITY: adding {BACKWARDS_COMPATIBLE} to credentials')
    assert re.match(NEW_CREDENTIAL_REGEX, credentials), f'{credentials} does not match format {NEW_CREDENTIAL_REGEX}'

    if os.path.exists(COOKIE_DIR):
        shutil.rmtree(COOKIE_DIR)
    os.mkdir(COOKIE_DIR)

    write_msg(f'login - url {url} - credentials {credentials}')

    chrome_options = webdriver.ChromeOptions()
    # chrome_options.add_argument("window-size=1200x600")

    # can't be headless for manual login...
    actually_headless = auto and headless

    if actually_headless:
        # https://www.selenium.dev/blog/2023/headless-is-going-away/
        # old headless method does not support extensions
        # also weird extra stuff to allow downloads, get different names, etc.
        # chrome_options.add_argument("headless")  # old method
        chrome_options.add_argument("headless=new")  # new method

    if auto:
        # https://stackoverflow.com/questions/34515328/how-to-set-default-download-directory-in-selenium-chrome-capabilities
        prefs = {}
        prefs["download.default_directory"] = os.path.join(os.getcwd(), COOKIE_DIR)  # needs to be non-relative (ie. not '.')
        write_msg(str(prefs))
        chrome_options.add_experimental_option("prefs", prefs)

        # https://chromedriver.chromium.org/extensions
        # load packed extension
        # chrome_options.add_extension('cookie_extension.crx')
        # load unpacked extension (directory)
        chrome_options.add_argument(f"load-extension={os.path.join(os.getcwd(), 'cookie_extension')}")
        # this saves only cookies for the domain. could save all, if necessary

        # will download, probably multiple, cookie.txt
        # appears as 'cookie.txt', 'cookie (1).txt', etc
        # can either select the latest based on timestamp, or the number

        # an alternate solution would be to use DevTools
        # https://www.selenium.dev/documentation/webdriver/bidirectional/chrome_devtools/

    driver = webdriver.Chrome(chrome_options=chrome_options, service_args=["--verbose"])

    driver.set_window_position(200, 10, windowHandle='current')

    driver.get(url)

    user_agent = driver.execute_script("return navigator.userAgent")

    if not auto:
        write_msg("1. Login")
        write_msg("2. Open network tab")
        write_msg("3. Refresh page (if login worked)")
        write_msg("4. Right-click on first request and 'Copy as cURL')")
        write_msg("5. Paste here")

        cookie = None
        while True:
            curl_data = input("Paste curl data (follow by empty line): ")
            if "cookie" in curl_data.lower():
                cookie = curl_data

            if not curl_data:
                break
        assert cookie is not None
        write_msg("\n\n-------------")
        start = cookie.find("Cookie: ")+len("Cookie: ")
        end = cookie.find("'",start+1)
        cookie = cookie.replace("%", "%%")
        login_url = driver.current_url
        return {"cookie_str": cookie[start:end], "user_agent": user_agent, "url": login_url}
    else:
        # TODO use regex capture groups
        (matchpart, userpart, passpart) = credentials.split(",")
        (_, match) = matchpart.split("=")
        match = int(match, base=10)  # just in case there's a starting 0...
        (user_field, username) = userpart.split("=")
        (pass_field, password) = passpart.split("=")

        # write_msg("Waiting 5 seconds for the page to load")
        # time.sleep(5)

        # input()  # debugging...

        user_element = driver.find_elements("name", user_field)[match]
        user_element.send_keys(username)
        pwd = driver.find_elements("name", pass_field)[match]
        pwd.send_keys(password)
        # Send ENTER to submit form.
        pwd.send_keys(Keys.RETURN)

        write_msg("Waiting 5 seconds for login")
        time.sleep(5)

        login_url = driver.current_url
        write_msg(f"login URL: {login_url}")

        # write_msg(driver.get_log('driver'))
        # write_msg(driver.get_log('browser'))
        # write_msg(driver.get_log('client'))
        # write_msg(driver.get_log('server'))

        # Look for newest cookies
        # Not great, but based on latest modification date
        # should be safe, as there are only cookies in COOKIE_DIR
        # and previous ones are deleted before this run

        os.chdir(COOKIE_DIR)

        files = sorted([f for f in os.listdir(".") if os.path.isfile(f)], key=lambda f : -os.path.getmtime(f))
        assert len(files) > 0
        # Construct cookie string
        cookie_str = ""
        for line in open(files[0], "r"):
            if line[0] == "#":
                continue
            parts = line.split("\t")
            cookie_str += parts[5] + "=" + parts[6][:-1] + "; "

        os.chdir("..")

        return {"cookie_str": cookie_str[:-2],  # -2 for last '; '
                "user_agent": user_agent,
                "url" : login_url}
