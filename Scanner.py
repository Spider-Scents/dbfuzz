import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from Helper import write_msg

BW_DIR = 'bw'  # black widow runtime file directory
BW = str(Path().joinpath('blackwidow', 'crawl.py').absolute())
assert os.path.exists(BW)


class Scanner(object):
    '''Reflection scanner'''

    def __init__(self, cookies: Optional[str] = None, headful: bool = False) -> None:
        '''Initialize'''

        self.cookies  = cookies
        self.headless = not headful

    def scan(self, urls: list[str], tokens: list, timeout: int) -> list:
        '''Scan for some tokens in some URLs'''
        raise NotImplementedError


class NoScanner(Scanner):
    '''No reflection scanner'''

    def scan(self, urls, tokens, timeout):
        return []


class BlackWidowScanner(Scanner):
    '''Use Black Widow as the reflection scanner'''

    def scan(self, urls, tokens=None, timeout=30):
        bw_cmd = ['python3', '-u', BW, '--debug']

        if self.headless:
            bw_cmd += ['--headless']

        # Create a tmp file with URLs for the scanner
        fp = tempfile.NamedTemporaryFile(delete=False)
        for url in urls:
            if url:
                fp.write((url + "\n").encode())
        fp.close()

        bw_cmd += ['--urls_file', fp.name]

        if self.cookies:
            bw_cmd += ["--cookies", self.cookies]

        if tokens:
            # Create a tmp file with tokens for the scanner
            fp_tokens = tempfile.NamedTemporaryFile(delete=False)
            for token in tokens:
                if token:
                    fp_tokens.write((token + "\n").encode())
            fp_tokens.close()

            bw_cmd += ["--tokens_file", fp_tokens.name]

        write_msg("RUNNING BW COMMAND: ")
        write_msg(str(bw_cmd))
        write_msg('')
        output = subprocess.Popen(bw_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=BW_DIR)

        self.output = output
        res = self.getBlackWidowOutput(timeout)
        return res

    def initialScan(self, urls: list[str], timeout: int = 300) -> list[str]:
        """
        Given a list of URLs, BW will perform a shallow scan, using
        the first URL in the list, searching for a
        list of URLs to check in scan()
        """

        url = urls[0]
        write_msg(f"Initial Scanning {url}")

        bw_cmd = ['python3', '-u', BW, '--shallow', url]
        if self.cookies is not None:
            bw_cmd = bw_cmd + ["--cookies", self.cookies]

        write_msg(" ".join(bw_cmd))

        print(" ".join(bw_cmd))
        output = subprocess.Popen(bw_cmd, stdout=subprocess.PIPE, cwd=BW_DIR)

        self.output = output
        # default: 5 min for initial scan
        results = self.getBlackWidowOutput(timeout)

        urls = [result['seen_url'] for result in results
                if 'seen_url' in result]

        return urls

    def getBlackWidowOutput(self, timeout: int = 30) -> list:
        '''Read output of tokens found from Black Widow'''

        res = []
        output = self.output
        # Read line-by-line output from BW
        start_time = time.time()
        time_diff = float('-inf')

        assert output.stdout is not None
        for line in output.stdout:
            write_msg(f"BW: {line}")

            # Timeout in case scanner gets stuck
            time_diff = time.time() - start_time
            if time_diff > timeout:
                # Need to also kill all chrome windows, maybe from BW?
                # Writing "1" to the txt file tells BW to terminate.
                write_msg(f"TIME TO KILL {output} {output.pid}")
                open(f"{BW_DIR}/please_die_bw.txt", "w+").write("1")
                max_tries = 10  # increased, WordPress
                while open(f"{BW_DIR}/please_die_bw.txt").read() == "1":
                    write_msg("still alive.., waiting 2 seconds")
                    time.sleep(2)

                    max_tries -= 1
                    if max_tries < 0:
                        input("Couldn't kill BW... :(")

                # Currently returning everything we found + TIMEOUT
                res.append("TIMEOUT")
                # data on which URLs were actually checked? TODO
                logging.debug(('dbfuzz', 'bw_scanner', 'get_output', 'timeout', True))
                break

            # Extract data from lines starting with DBFUZZHEADER
            if line[:12].decode() == 'DBFUZZHEADER':
                data = json.loads(line[12:].decode())

                write_msg(f"GOT DATA FROM BW: {data}")

                if "done" in data:
                    logging.debug(('dbfuzz', 'bw_scanner', 'get_output', 'timeout', False))
                    break

                res.append(data)

        write_msg(f'BW ran for {time_diff} seconds!')
        logging.debug(('dbfuzz', 'bw_scanner', 'get_output', 'time', time_diff))
        return res
