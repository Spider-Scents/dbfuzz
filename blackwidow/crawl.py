from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.action_chains import ActionChains
import json
import pprint
import argparse
from pathlib import Path

from Classes import *

parser = argparse.ArgumentParser(description='Crawler')
parser.add_argument('--wivet', help="Run a wivet challenge, use 0 to run all")
parser.add_argument('--debug', action='store_true',  help="Dont use path deconstruction")
parser.add_argument("--url", help="Custom URL to crawl")
parser.add_argument('--urls_file', help='Path to list of URLs. One per line')
parser.add_argument('--tokens_file', help='Path to list of tokens. One per line')
parser.add_argument('--cookies', help='Cookie string copied from network tab')
parser.add_argument('--shallow', help='Quick scan for links.')
parser.add_argument('--headless', action='store_true', help="Run in headless")

args = parser.parse_args()

# Clean form_files/dynamic
root_dirname = os.path.dirname(__file__)
dynamic_path = os.path.join(root_dirname, 'form_files', 'dynamic')
Path(dynamic_path).mkdir(parents=True, exist_ok=True)
for f in os.listdir(dynamic_path):
    os.remove(os.path.join(dynamic_path, f))

WebDriver.add_script = add_script


chrome_options = webdriver.ChromeOptions()
chrome_options.add_argument("--disable-web-security")
chrome_options.add_argument("--disable-xss-auditor")

# add headless mode argument to black widow?
if args.headless:
    # https://www.selenium.dev/blog/2023/headless-is-going-away/
    # chrome_options.add_argument("headless")  # old method
    chrome_options.add_argument("headless=new")  # new method

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning) # live dangerously
# launch Chrome
driver = webdriver.Chrome(chrome_options = chrome_options) # TODO why is this a TODO?

driver.set_window_position(200, 10, windowHandle='current')


#driver.set_window_position(-1700,0)

# Read scripts and add script which will be executed when the page starts loading
# Thanks to Dennis and Miriam
# https://github.com/mirdeger/bw
driver.add_script( open( str( os.path.join(root_dirname,"js/lib.js")), "r").read() )
driver.add_script( open( str( os.path.join(root_dirname,"js/property_obs.js")), "r").read() )
driver.add_script( open( str( os.path.join(root_dirname,"js/md5.js")), "r").read() )
driver.add_script( open( str( os.path.join(root_dirname,"js/addeventlistener_wrapper.js")), "r").read() )
driver.add_script( open( str( os.path.join(root_dirname,"js/timing_wrapper.js")), "r").read() )
driver.add_script( open( str( os.path.join(root_dirname,"js/window_wrapper.js")), "r").read() )
driver.add_script( open( str( os.path.join(root_dirname,"js/forms.js")), "r").read() )
driver.add_script( open( str( os.path.join(root_dirname,"js/xss_xhr.js")), "r").read() )
driver.add_script( open( str( os.path.join(root_dirname,"js/remove_alerts.js")), "r").read() )

if args.wivet:
    challenge = int(args.wivet)
    if challenge > 0:
        url = "http://localhost/wivet/pages/" + str(challenge) + ".php"
    else:
        url = "http://localhost/wivet/menu.php"

    Crawler(driver, url).start()
elif args.url:
    url = args.url
    Crawler(driver, url).start(args.debug)
elif args.urls_file:
    urls = open(args.urls_file).read().split("\n")

    if args.tokens_file:
        tokens = open(args.tokens_file).read().split("\n")
        # Remove empty
        tokens = [token for token in tokens if token]
    else:
        tokens = []

    cookies = args.cookies
    Crawler(driver, urls[0], urls, cookies, tokens).start(args.debug)
elif args.shallow:
    shallow = args.shallow
    cookies = args.cookies
    c = Crawler(driver, shallow, None, cookies)
    c.shallow = True
    c.start(args.debug)
else:
    print("Please use --wivet or --url")




