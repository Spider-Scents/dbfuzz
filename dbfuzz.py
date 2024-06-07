import datetime
import json
import logging
import pickle
import pprint
import shutil
import subprocess
import sys
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace
from collections import Counter
from configparser import ConfigParser
from enum import Enum
from itertools import groupby
from pathlib import Path
from random import shuffle
from typing import Optional

from tqdm import tqdm

import Browser
import Data
import Payload
from Breakage import Breakage, LengthBreakage, UrlBreakage
from Database import ColInfo, Database, DatabaseConfig
from Helper import is_url, write_msg, WRITE_MESSAGES
from Scanner import BlackWidowScanner, NoScanner, Scanner


Sensitive = tuple[str, list[str], list[str], int, int]


class AppConfig(Namespace):
    '''Hold configuration for scanning a web app'''

    def __init__(self, app: str, blacklist: set[str], allowlist: Optional[set[str]],
                 urls_seed: list[str], cookies: str, login: str,
                 credentials: str, args) -> None:
        '''Initialize configuration'''

        self.app                  = app
        self.blacklist            = blacklist
        self.allowlist            = allowlist
        self.urls_seed            = urls_seed
        self.urls                 = []  # initialize later
        self.cookies              = cookies
        self.login                = login
        self.credentials          = credentials
        vargs = vars(args)
        for arg in vargs:
            assert not hasattr(self, arg)
            setattr(self, arg, vargs[arg])

    def __str__(self) -> str:
        ''''''

        return self.app


class AppConfigEncoder(json.JSONEncoder):
    '''Encoder to help write app config to JSON'''

    def default(self, app_config: AppConfig) -> dict:
        ''''''

        d = {}
        for name in dir(app_config):
            value = getattr(app_config, name)
            if name[0] != '_':
                d[name] = str(value)
        return d


class TRAVERSAL(str, Enum):
    '''Traversal types: either iteratively change DB by table, or by column'''

    TABLE  = 'table',
    COLUMN = 'column'


class BREAKAGE(str, Enum):
    '''Breakage types: either compare responses by length, or by link contents'''

    LENGTH = 'length',
    URL    = 'url'


class SCANNER(str, Enum):
    '''Scanner types: either don't scan, or use Black Widow'''

    NONE       = 'none',
    BLACKWIDOW = 'blackwidow'


def read_config(args) -> tuple[DatabaseConfig, AppConfig]:
    '''Read the app and database configs from files specified in program arguments'''

    config = ConfigParser()
    assert len(config.read(args.config)), f'failed to read config {args.config}!'
    mysql       = config["general"]["mysql"]
    mysqldump   = config["general"]["mysqldump"]

    app      = config["target"]["app"]
    database = config["target"]["database"]
    login    = config["target"]["login"]
    creds    = config["target"]["credentials"]

    urls_seed = config["target"]["urls"].split("\n")
    assert len(urls_seed) == len(set(urls_seed))
    cookies = config["target"]["cookies"]

    host        = config["database"]["host"]
    user        = config["database"]["user"]
    password    = config["database"]["password"]
    port        = int(config["database"]["port"])
    # TODO put DB prefix in config
    # TODO put blacklist into config
    blacklist   = set(["phpbb_sessions",  # PhpBB - don't wipe out our currently logged-in session ID...
                       ])
    allowlist   = None #
    # allowlist   = set(["cs_match",
    #                    "cs_team",
    #                    "cs_tipp",
    #                    "cs_tippgroup",
    #                    "cs_users"]) # Example for wp-champions wordpress plugin

    db_config  = DatabaseConfig(host, user, password, database, port, mysql, mysqldump)
    app_config = AppConfig(app, blacklist, allowlist, urls_seed, cookies, login, creds, args)

    return db_config, app_config


def get_urls(scanner: BlackWidowScanner, app_config: AppConfig,
             db: Optional[Database] = None, backup: Optional[bytes] = None) -> list[str]:
    '''Get URLs for a web app'''

    # We can save the URLs from the initial scan, speeds up re-running.
    # Initial scan is run in non-headless (headful) mode
    # > Must take care not to logout during this initial scan
    # > blackwidow not logging out? - string
    # This should no longer be a problem, we login and gen cookies automatically now
    # TODO: blackwidow should return full urls
    # TODO: we should remove login/logout URLs
    urls = []
    cache_file = urls_filename(app_config)
    # assert db is None == backup is None, 'Both db and backup are needed to restore after initial scan'

    if Path(cache_file).exists():
        write_msg("Reading URLs from cache file")
        urls = json.loads(open(cache_file).read())
    else:
        write_msg("Scanning for list of URLs to check")
        urls = app_config.urls_seed[::]
        # don't re-order, is sorted by link-rank

        # nice version, but without logging
        # urls += [url for url in scanner.initialScan(app_config.urls_seed,
        #                                             app_config.initial_scanner_timeout)
        #          if url not in urls
        #             and url.startswith('http')
        #             and 'logout' not in url]

        # less nice version, but with logging
        for url in scanner.initialScan(app_config.urls_seed,
                                       app_config.initial_scanner_timeout):
            if url not in urls:
                if not url.startswith('http'):
                    write_msg(f'{url} is not complete! does not start with http')
                    logging.warning(f'{url} is not complete!')
                elif 'logout' in url:
                    write_msg(f'{url} is a logout URL! contains logout substring')
                    logging.warning(f'{url} is logout!')
                else:
                    urls.append(url)

        write_msg(f"urls: {urls}")
        open(cache_file, "w+").write(json.dumps(urls))
        # can the initial scan log out?
        # then would need to do a database reset or something...
        # or making sure that the initial scan can't log out (blacklist URLs beforehand)
        write_msg('Initial scan might have logged you out...')
        write_msg('Exiting program.')
        if db is not None and backup is not None:
            db.restore_backup(backup)
            write_msg('Restored initial backup')
        else:
            write_msg('Make sure to restore DB before running dbfuzz again.')
        write_msg('Inspect URLs manually! Look for delete etc')
        exit(1) # run another time...
        # remember to restore the DB!

    assert len(urls) == len(set(urls))
    assert len(urls) > 0
    for url in urls:
        assert is_url(url), f'{url} is not a url!'
        assert 'logout' not in url, f"'logout' is in {url}!"
        assert url.startswith('http'), f"'{url} is not a full url!"
    return urls


def insert_filename_helper(app_config: AppConfig, basename: str, extension: str):
    '''Helper function to construct a filename for DB backup after inserting rows into empty tables'''

    # empty (instead of insert_empty=False) to maintain backwards compatibility
    options = [f'{app_config.insert_empty=}'] if app_config.insert_empty else []
    return Data.filename_with_options(basename, app_config, options, extension)


def insert_backup_filename(app_config: AppConfig) -> Path:
    '''Make a filename for DB backup after inserting rows into empty tables'''

    return Data.filename_with_options("insert_backup", app_config, [], "sql")


def urls_filename(app_config: AppConfig) -> Path:
    '''Make filename for caching found URLs'''

    # different URLs (so different cache file) if inserting empty or not
    return insert_filename_helper(app_config, "urls", "txt")


def sensitive_rows_filename(app_config : AppConfig) -> Path:
    '''Make filename for storing information about sensitive rows found'''

    return insert_filename_helper(app_config, "sensitive_rows", "pickle")


def get_indices(app_config: AppConfig, tables: list[str], datas: list[list[tuple]],
                col_infos: list[list[ColInfo]], sensitive: list[Sensitive]) -> tuple[list, set, set, set]:
    '''Make the indices defining what to modify in the database, in what order, and how to reset, all based on some strategies / parameters'''

    # encode information for when to do reflection & breakage scans, reset DB changes
    indices = []
    breakage_indices = set()
    reflection_indices = set()
    reset_indices = set()
    # traversal strategies: tables, columns
    # periodic database resets instead of accumulated changes

    table_indices  = []
    table_order    = lambda x: table_indices.index(x[0])
    row_indices    = []
    row_order      = lambda x: row_indices.index((x[0], x[1]))
    column_indices = []
    column_order   = lambda x: column_indices.index((x[0], x[2]))

    sort_indices = []
    sort_order   = lambda x: sys.exit('no sort order!')

    # something here is slow for oscommerce!
    # TODO find out why, fix

    # construct sorting indices
    for i in range(len(tables)):
        if tables[i] in app_config.blacklist:
            continue
        if app_config.allowlist and not tables[i] in app_config.allowlist:
            print("TABLE NOT IN ALLOWLIST", tables[i]) # TODO Remove this
            continue

        table_indices.append(i)
        for j in range(len(datas[i])):
            row_indices.append((i, j))
        for k in range(len(col_infos[i])):
            if Payload.is_fuzzable_col(col_infos[i][k]):
                column_indices.append((i, k))

    # construct fuzzing indices
    if app_config.traversal == TRAVERSAL.TABLE:
        sort_indices = table_indices
        sort_order = table_order
        for i in range(len(tables)):
            if tables[i] in app_config.blacklist:
                continue
            if app_config.allowlist and not tables[i] in app_config.allowlist:
                print("TABLE NOT IN ALLOWLIST", tables[i]) # TODO Remove this
                continue
            for j in range(len(datas[i])):
                for k in range(len(col_infos[i])):
                    if Payload.is_fuzzable_col(col_infos[i][k]):
                        indices.append((i, j, k))
    elif app_config.traversal == TRAVERSAL.COLUMN:
        sort_indices = column_indices
        sort_order = column_order
        for i in range(len(tables)):
            if tables[i] in app_config.blacklist:
                continue
            if app_config.allowlist and not tables[i] in app_config.allowlist:
                print("TABLE NOT IN ALLOWLIST", tables[i]) # TODO Remove this
                continue
            for k in range(len(col_infos[i])):
                if Payload.is_fuzzable_col(col_infos[i][k]):
                    for j in range(len(datas[i])):
                        indices.append((i, j, k))
    else:
        sys.exit('traversal not implemented!')

    if app_config.randomize:
        shuffle(sort_indices)
        shuffle(indices)
        indices = sorted(indices, key=sort_order)

    if app_config.reverse:
        indices = indices[::-1]
        sort_indices = sort_indices[::-1]

    sensitive_indices = list(map(lambda x: (x[3], x[4]), sensitive))

    assert app_config.max_rows == -1 or app_config.max_rows > 0
    visited_rows = dict()

    def remove_max_and_sensitive(pos: tuple[int, int, int]) -> bool:
        i, j, _ = pos
        if (i, j) in sensitive_indices:
            return False
        if i in visited_rows:
            if app_config.max_rows == -1 or len(visited_rows[i]) + 1 < app_config.max_rows:
                visited_rows[i].add(j)
        else:
            visited_rows[i] = {j}
        return j in visited_rows[i]

    indices = list(filter(remove_max_and_sensitive, indices))
    if app_config.max_rows != -1:  # sanity check
        assert all(map(lambda i: len(visited_rows[i]) <= app_config.max_rows, visited_rows))

    groups = groupby(indices, key=sort_order)
    for _, group in groups:
        l1 = list(group)
        for i in l1:
            # add breakage check after each cell change
            breakage_indices.add(i)
        # add scanner check after table or column
        reflection_indices.add(l1[-1])
        reset_indices.add(l1[-1])

        # could optimize solution
        assert app_config.max_cell_scan == -1 or app_config.max_cell_scan > 0
        if app_config.max_cell_scan != -1:
            for i in l1[::app_config.max_cell_scan][1:]:  # don't add the 0 index
                # add scanner check after MAX_CELL_SCAN cell changes
                reflection_indices.add(i)
                reset_indices.add(i)

        # could optimize solution
        assert app_config.max_row_scan == -1 or app_config.max_row_scan > 0
        if app_config.max_row_scan != -1:
            groups2 = groupby(l1, key=row_order)
            # this is slow for oscommerce! why? 3 million cells, 2 million are fuzzable
            rows = 0
            for _, group2 in groups2:
                l2 = list(group2)
                rows += 1  # each group is changes to one row
                if rows >= app_config.max_row_scan:
                    # add scanner check after MAX_ROW_SCAN row changes
                    reflection_indices.add(l2[-1])
                    reset_indices.add(l2[-1])
                    rows -= app_config.max_row_scan

    return indices, breakage_indices, reflection_indices, reset_indices


def main(args: Namespace) -> None:
    '''Main script functionality'''

    db_config, app_config, = read_config(args)
    app_config.urls = app_config.urls_seed # need something for breakage check in sensitive_rows

    ############
    # DATABASE #
    ############

    db = Database(db_config)

    backup = None
    sensitive = []
    if not app_config.no_backup:
        backup = db.make_backup()
        with open(app_config.backup, "wb") as file:
            file.write(backup)

    CACHE_REGEN_INSERT_SENSITIVE = True
    # turn on if you want to cache the results
    # for inserting rows into empty tables
    # and checking for sensitive rows

    ###############
    # INSERT ROWS #
    ###############

    insert_backup = backup  # need to run sensitive rows after
    # this does a restore of this backup (after deleting the db)

    # add rows!
    if app_config.insert_empty:
        if app_config.no_backup:
            sys.exit('cannot insert rows into empty tables without backup!')

        insert_backup_file = insert_backup_filename(app_config)

        if insert_backup_file.exists() and CACHE_REGEN_INSERT_SENSITIVE:
            write_msg(f'cache file for inserts into empty tables found at "{insert_backup_file}", restoring that...')
            with open(insert_backup_file, 'rb') as file:
                insert_backup = file.read()
            db.restore_backup(insert_backup)
        else:
            insert_rows(db, app_config)
            insert_backup = db.make_backup()
            with open(insert_backup_file, 'wb') as file:
                file.write(insert_backup)
            write_msg(f'wrote cache file for inserts into empty tables at "{insert_backup_file}"')


    ##################
    # SENSITIVE ROWS #
    ##################

    if app_config.sensitive_rows:
        if app_config.no_backup:
            sys.exit('cannot find sensitive rows without backup!')

        sensitive_rows_file = sensitive_rows_filename(app_config)

        if sensitive_rows_file.exists() and CACHE_REGEN_INSERT_SENSITIVE:
            write_msg(f'cache file for sensitive rows found at "{sensitive_rows_file}", loading that...')
            with open(sensitive_rows_file, 'rb') as file:
                sensitive = pickle.load(file)
        else:
            sensitive = find_sensitive_rows(db, app_config, insert_backup)
            with open(sensitive_rows_file, 'wb') as file:
                pickle.dump(sensitive, file, pickle.HIGHEST_PROTOCOL)
            write_msg(f'wrote cache file for sensitive rows at "{sensitive_rows_file}"')

        # if done before login, would wipe out those cookies in the database
        # also needs to be done after insert empty!


    ########################
    # BREAKAGE AND SCANNER #
    ########################

    scanner  = get_scanner(app_config)

    user_agent = None  # use default

    if not app_config.no_login:
        cookies_useragent = Browser.login(app_config.login, app_config.credentials,
                                          headless=not app_config.headful, auto=True)
        write_msg(f'cookies, user agent, and login URL: {cookies_useragent}')

        app_config.cookies = cookies_useragent["cookie_str"]
        scanner.cookies = cookies_useragent["cookie_str"]
        # login_url = cookies_useragent["url"]
        # app_config.urls_seed.insert(0, login_url)

        user_agent = cookies_useragent["user_agent"]

    if app_config.scanner == SCANNER.BLACKWIDOW:
        assert isinstance(scanner, BlackWidowScanner)

        app_config.urls = get_urls(scanner, app_config, db, backup)
    else:
        app_config.urls = app_config.urls_seed

    # exit(1)  # inspect URLs

    # special handling for CMS Made Simple
    # in general, match from cookies to URL params?
    # could add to config.ini TODO (cookie, url param)
    # TODO parse URL better - https://docs.python.org/3/library/urllib.parse.html
    if app_config.app == 'cmsms':
        # need to replace '__c' in URLs, based on what is in login cookies
        cookie = Breakage.cookiestr_to_dict(app_config.cookies)['__c']
        new_urls = []
        for url in app_config.urls:
            if '__c' in url:  # always seems to be at end (19 chars? weird number)
                new_url = f"{url[:url.index('__c')]}__c={cookie}"
                new_urls.append(new_url)
            else:
                new_urls.append(url)
        app_config.urls = new_urls
    # special handling for phpBB
    elif app_config.app == 'phpbb':
        # need to replace 'sid' in URLs, based on what is in login cookies
        cookie = Breakage.cookiestr_to_dict(app_config.cookies)['phpbb3_94zq3_sid']
        new_urls = []
        for url in app_config.urls:
            if 'sid' in url:  # seems to have 32 character long ids
                new_url = f"{url[:url.index('sid')]}sid={cookie}{url[url.index('sid')+33:]}"
                new_urls.append(new_url)
            else:
                new_urls.append(url)
        app_config.urls = new_urls
        write_msg(pprint.pformat(new_urls))

    with open(args.info, 'w') as f:
        s = json.dumps(app_config, cls=AppConfigEncoder, sort_keys=True, indent=4)
        f.write(s)

    breakage = get_breakage(app_config, user_agent=user_agent)

    assert app_config.cookies == scanner.cookies

    if not app_config.no_breakage_cookies:
        assert breakage.cookies == scanner.cookies

    xss_found    = []
    tokens_found = []

    ############
    # STRATEGY #
    ############

    # prefetch all data so that we don't fuzz added rows (from webapp interaction) in later tables
    # is it good to fuzz rows as they are added? maybe... but more complex
    tables    = db.get_tables()
    datas     = [db.get_data(table) for table in tables]
    columnss  = [db.get_columns(table) for table in tables]
    col_infos = [db.get_columns_info(table) for table in tables]
    key_infos = [db.get_key_info(table) for table in tables]
    len_rows  = [db.get_length(t) for t in tables]
    for i in range(len(tables)):
        assert len_rows[i] == len(datas[i])

    indices, breakage_indices, reflection_indices, reset_indices = \
        get_indices(app_config, tables, datas, col_infos, sensitive)

    write_msg(f'tables ({len(tables)}): {tables}')
    write_msg(f'scanning will take up to {datetime.timedelta(seconds=app_config.scanner_timeout * len(reflection_indices))}')
    write_msg(f'scanner will run {len(reflection_indices)} times for {app_config.scanner_timeout} seconds each time')
    total_cells = sum(len_rows[i]*len(columnss[i]) for i in range(len(tables)))
    write_msg(f'out of {total_cells} total cells, {len(indices)} are fuzzable')

    scans = 0

    changes = dict()  # use to reset database

    for index in tqdm(indices, disable=not WRITE_MESSAGES):
        i, j, k = index

        table    = tables[i]
        columns  = columnss[i]
        data     = datas[i]
        row      = data[j]
        col_info = col_infos[i]
        key_info = key_infos[i]

        ###########
        # FUZZING #
        ###########

        write_msg(f'fuzzing {table}[{j}][{k}]')

        if not db.is_row_in_table(table, row, col_info, key_info, primary=app_config.primary_keys):
            write_msg(f'row not in {table}, skipping fuzzing: {row}')
            logging.warning(f'row not in {table}: {row}')
        else:
            new = Payload.update_payload(db, table, row,
                                         columns, col_info, key_info,
                                         (j, k), scans,
                                         advanced=not app_config.no_advanced_payload,
                                         primary=app_config.primary_keys)
            latest = Payload.ids[-1]
            old_new = row

            if (i, j) not in changes:
                changes[(i, j)] = (row, new)
            else:
                old_new = changes[(i, j)][1]
                changes[(i, j)] = (changes[(i, j)][0], new)
            assert len(changes[(i, j)][0]) == len(changes[(i, j)][1])
            datas[i][j] = new  # IMPORTANT: update view of database with payload
            write_msg(f"{table}[{j}][{k}] changed to {new[k]} from {row[k]}")

            ##################
            # BREAKAGE CHECK #
            ##################

            if index in breakage_indices and breakage.broken(id=latest):
                write_msg(f'reverting! {new[k]} --> {row[k]}')
                if db.update_row(table, new, row, columns, col_info, key_info, primary=app_config.primary_keys) == 1:
                    datas[i][j] = row  # IMPORTANT: revert view of database
                    changes[(i, j)] = (changes[(i, j)][0], old_new)  # can't remove, I think, if multiple changes etc.
                    write_msg('successful revert!')
                else:
                    new_length = db.get_length(table)
                    if new_length != len_rows[i]:
                        write_msg(f"webapp has changed! table {table} now contains {new_length} rows instead of {len_rows[i]}!!!")
                        write_msg("deleting duplicate row...")
                        db.delete_row(table, row, col_info, key_info, primary=True)

                        write_msg(f'retry reverting! {new[k]} --> {row[k]}')
                        if db.update_row(table, new, row, columns, col_info, key_info, primary=app_config.primary_keys) == 1:
                            datas[i][j] = row  # IMPORTANT: revert view of database
                            changes[(i, j)] = (changes[(i, j)][0], old_new)  # can't remove, I think, if multiple changes etc.
                            write_msg('successful revert!')
                        else:
                            write_msg('failed revert!')
                            logging.warning(f'failed revert with delete {table}[{j}]: {row} => {new}')
                    else:
                        write_msg('failed revert!')
                        logging.warning(f'failed revert without delete {table}[{j}]: {row} => {new}')

        ####################
        # REFLECTION CHECK #
        ####################

        if index in reflection_indices:  # need to scan even if not fuzzed (at this index)
            # These are not the urls from the config file, these are updated automatically
            assert app_config.max_scanner_urls > 0 or app_config.max_scanner_urls == -1
            reflection_urls = app_config.urls
            if app_config.max_scanner_urls != -1:
                reflection_urls = reflection_urls[:app_config.max_scanner_urls]
            reflections = scanner.scan(reflection_urls, tokens=[], timeout=app_config.scanner_timeout)
            scans += 1
            if reflections and reflections[0] != "TIMEOUT":
                write_msg("Got something! :)")
                for r in reflections:
                    if r == "TIMEOUT":
                        continue
                    url = r['url']
                    if 'xss_ids' in r:
                        xss_ids = r['xss_ids']  # array of ints
                        for xss_id in xss_ids:
                            Data.print_reflection(Payload.context, xss_id, url, is_token=False, log_errors=True)
                            xss_found.append((xss_id, url, scans))
                    if 'token_ids' in r:
                        token_ids = [int(t) for t in r['token_ids']]  # array of strings
                        for token_id in token_ids:
                            Data.print_reflection(Payload.context, token_id, url, is_token=True, log_errors=True)
                            tokens_found.append((token_id, url, scans))

            savefile = Data.save_data(xss_found, tokens_found, scans, app_config, final=False)
            write_msg(f'Data from scan {scans} saved to {savefile}')

        #################
        # RESET CHANGES #
        #################

        if app_config.reset_scanning and index in reset_indices:  # need to reset even if not fuzzed (at this index)
            assert len(set(loc[0] for loc in changes)) <= 1, 'all reset indices should be within the same table!'
            if app_config.max_row_scan != -1:  # sanity check
                assert len(set(loc[1] for loc in changes)) <= app_config.max_row_scan
            if app_config.max_cell_scan != -1:  # sanity check
                assert len(changes) <= app_config.max_cell_scan

            for loc in changes:
                i, j = loc
                row, new = changes[loc]
                if tuple(row) == tuple(new):  # should be tuples, but being paranoid... [] != ()
                    continue  # no need to reset if no actual changes (eg. already reset by revert)
                # not the same table and column as current index!
                table = tables[i]
                columns = columnss[i]
                col_info = col_infos[i]
                key_info = key_infos[i]

                if db.update_row(table, new, row, columns, col_info, key_info, primary=app_config.primary_keys) == 1:
                    write_msg(f'reset {table}[{j}]')
                    # need to change data back!
                    datas[i][j] = row
                else:
                    write_msg(f'failed resetting {table}[{j}]')
                    logging.warning(f'failed reset {table}[{j}]: {row} => {new}')

                    # try to reset again
                    # this will not work if the saved data can't be trusted! eg. dates as None, so on
                    write_msg(f'retry resetting! {new} --> {row}')
                    # this assert does not always work...
                    # probably because the reset (update) can fail due to not having the row
                    # assert db.delete_row(table, new, col_info, key_info, primary=True) or \
                    #        db.delete_row(table, row, col_info, key_info, primary=True)
                    # could do an existence check before?
                    # is it dangerous? deleting something unintended? probably not...
                    db.delete_row(table, new, col_info, key_info, primary=True)
                    db.delete_row(table, row, col_info, key_info, primary=True)
                    if db.insert_row(table, row):
                        datas[i][j] = row
                        write_msg('successful reset!')
                    else:
                        write_msg('failed reset!')
                        logging.warning(f'failed reset with delete {table}[{j}]: {row} => {new}')

            changes = dict()  # clear out changes
            assert len(changes) == 0  # make sure that there are no changes

    savefile = Data.save_data(xss_found, tokens_found, scans, app_config, final=True)
    write_msg(f'Final data saved to {savefile}')

    if app_config.reset_fuzzing:
        assert backup is not None
        db.restore_backup(backup)


def get_breakage(app_config: AppConfig, user_agent: Optional[str] = None, verbose: bool = True) -> Breakage:
    '''Make a breakage detector'''

    assert app_config.max_breakage_urls > 0 or app_config.max_breakage_urls == -1, 'breakage check needs at least one URL!'
    breakage_urls = app_config.urls
    if app_config.max_breakage_urls != -1:
        breakage_urls = breakage_urls[:app_config.max_breakage_urls]
    cookies = '' if app_config.no_breakage_cookies else app_config.cookies
    if app_config.breakage == BREAKAGE.LENGTH:
        return LengthBreakage(breakage_urls,
                              threshold=app_config.breakage_threshold,
                              verbose=verbose,
                              cookies=cookies,
                              user_agent=user_agent)
    elif app_config.breakage == BREAKAGE.URL:
        return UrlBreakage(breakage_urls,
                           threshold=app_config.breakage_threshold,
                           verbose=verbose,
                           cookies=cookies,
                           user_agent=user_agent)
    else:
        sys.exit('breakage not implemented!')


def get_scanner(app_config: AppConfig) -> Scanner:
    '''Make a reflection scanner'''

    if app_config.scanner == SCANNER.NONE:
        return NoScanner()
    elif app_config.scanner == SCANNER.BLACKWIDOW:
        cookies = None if app_config.no_scanner_cookies else app_config.cookies
        return BlackWidowScanner(cookies, app_config.headful)
    else:
        sys.exit('scanner not implemented!')


def find_sensitive_rows(db: Database, app_config: AppConfig, backup: Optional[bytes]) -> list[Sensitive]:
    '''Find the sensitive rows in the database'''

    tables    = db.get_tables()
    datas     = [db.get_data(table) for table in tables]
    columnss  = [db.get_columns(table) for table in tables]
    col_infos = [db.get_columns_info(table) for table in tables]
    key_infos = [db.get_key_info(table) for table in tables]

    breakage = get_breakage(app_config, verbose=False)
    # this is currently not logged in! perhaps we want to check while logged in

    sensitive = []
    for i in tqdm(range(len(tables)), disable=not WRITE_MESSAGES):
        table    = tables[i]
        columns  = columnss[i]
        col_info = col_infos[i]
        key_info = key_infos[i]
        data     = datas[i]

        write_msg(f'fuzzing(delete) {table}: {len(data)} rows')
        if table in app_config.blacklist:
            write_msg(f"SKIPPING TABLE {table}")
            continue
        if app_config.allowlist and not tables[i] in app_config.allowlist:
            write_msg(f"SKIPPING TABLE {table} NOT IN ALLOWLIST")
            continue

        write_msg(str(key_info))
        keys = [i for i in range(len(key_info)) if key_info[i][1] == "PRIMARY"]
        if len(keys) == 0:
            write_msg('NO PRIMARY KEYS, SKIPPING TABLE')
            continue
        write_msg(f'PRIMARY KEYS: {[key_info[i][0] for i in keys]}')
        for j in range(len(data)):  # ignore max rows
            row = data[j]
            if not db.is_row_in_table(table, row, col_info, key_info, primary=True):
                write_msg(f'row not in {table}, skipping: {row}')
                logging.warning(f'row not in {table}: {row}')
                continue
            if db.invalid_row_date(row, col_info):
                write_msg(f'invalid date in {row}, skipping (and the rest of table)!')
                break

            write_msg(f'fuzzing(delete) {row}')
            assert db.delete_row(table, row, col_info, key_info, primary=True)

            breakage.broken(id=-1)  # just to visit the webpage

            if not db.insert_row(table, row):  # already existed! must be sensitive?
                write_msg(f'sensitive found! {table}.{columns[keys[0]]} = {row[keys[0]]}')
                sensitive.append((table, [columns[i] for i in keys], [row[i] for i in keys], i, j))

                # delete the webapp-added row
                # fix for WordPress - unique non-key columns
                # use the error code/message? how to recover?
                # could form a new 'key' based on unique columns... but not all of them
                # or could simply delete the table, put back rows as we know them
                if db.delete_row(table, row, col_info, key_info, primary=True):
                    write_msg('deleted webapp-inserted row, inserting original')
                    # put back the original row
                    # this won't work if the row data can't be trusted! date = none
                    assert db.insert_row(table, row)

                else:
                    write_msg("couldn't delete webapp-inserted row, deleting all & restoring")
                    db.delete_all_rows(table)
                    for row in data:
                        assert db.insert_row(table, row)


    if backup is not None:
        db.restore_backup(backup)

    write_msg('SENSITIVE DATABASE ROWS')
    for table, col, val, i, j in sensitive:
        write_msg(f'{table}.{col}={val} @({i}, {j})')
    return sensitive


def insert_rows(db: Database, app_config: AppConfig) -> None:
    '''Insert rows into empty tables in the database'''

    tables = db.get_tables()
    col_infos = [db.get_columns_info(table) for table in tables]
    key_infos = [db.get_key_info(table) for table in tables]

    breakage = get_breakage(app_config, verbose=False)
    # TODO improve for phpbb - all show as broken - need to be logged in?

    for i in tqdm(range(len(tables)), disable=not WRITE_MESSAGES):
        table = tables[i]
        col_info = col_infos[i]
        key_info = key_infos[i]

        write_msg(f'fuzzing(insert) {table}')
        if table in app_config.blacklist:
            write_msg(f"SKIPPING BLACKLISTED TABLE {table}")
            continue
        elif app_config.allowlist and not tables[i] in app_config.allowlist:
            write_msg(f"SKIPPING TABLE {table} NOT IN ALLOWLIST")
            continue
        elif len(db.get_data(table)) > 0:
            write_msg("SKIPPING NONEMPTY TABLE")
            continue

        write_msg(str(col_info))

        # handle auto-increment? often starts at 1 (sometimes)
        # want to have matching keys across tables
        # (0, ...) may be incremented to (1, ...), then will not match up
        # (1, ...) will then fail (but will match up)
        # (2, ...) should match up
        for j in range(3):
            row = db.generate_row(col_info, j)
            write_msg(f'generated row {row}')

            if db.insert_row(table, row):
                write_msg(f'inserted row {row} in {table}')
            else:
                write_msg(f'failed to insert row {row} in {table}')
                logging.warning(f'failed to insert {row} in {table}')

            if breakage.broken(id=-1):
                write_msg(f'broken after insertion... deleting')
                logging.warning(f'broken after inserting {row} in {table}')
                if db.delete_row(table, row, col_info, key_info, primary=False):
                    write_msg('successful delete!')
                    logging.warning(f'removed the inserted broken {row} in {table}')
                else:
                    # often will fail, as the row has been auto-incremented
                    write_msg(f'failed delete! deleting all rows in {table}')
                    write_msg(f'deleting all rows: {db.delete_all_rows(table)}')
                    logging.warning(f'failed removing the inserted broken {row} in {table}, removing all rows')
                    break  # don't try to add more after breaking


def datatype_scan(args: Namespace) -> None:
    '''Scan the database for structured datatypes'''

    db_config, app_config, = read_config(args)
    db = Database(db_config)

    tables    = db.get_tables()
    datas     = [db.get_data(table) for table in tables]
    # columnss  = [db.get_columns(table) for table in tables]
    col_infos = [db.get_columns_info(table) for table in tables]
    # key_infos = [db.get_key_info(table) for table in tables]

    counter = Counter()

    examples = dict()
    for datatype in Payload.Datatype:
        examples[datatype] = []

    for i in range(len(tables)):
        # table    = tables[i]
        # columns  = columnss[i]
        col_info = col_infos[i]
        # key_info = key_infos[i]
        data     = datas[i]
        for k in range(len(col_info)):
            if not Payload.is_fuzzable_col(col_info[k]):
                continue
            for j in range(len(data)):
                cell = data[j][k]
                if not cell:
                    continue
                if type(cell) is not str:
                    try:
                        cell = cell.decode()
                    except:
                        pass
                datatypes = Payload.get_datatype(cell)
                counter.update(datatypes)
                assert len(datatypes) <= 1
                for datatype in datatypes:
                    examples[datatype].append(cell)

    write_msg(str(counter))
    # write_msg(str(examples))

if __name__ == "__main__":
    # not just errors in this file - also statistics data
    if Path('errors.log').exists():
        shutil.move('errors.log', 'errors.old.log')
    if WRITE_MESSAGES:
        logging.basicConfig(filename='errors.log', level=logging.DEBUG)
    else:
        logging.basicConfig(filename='errors.log', level=logging.CRITICAL)

    # default output directory
    DEFAULT_OUTPUTDIR = "output"

    # print defaults
    parser = ArgumentParser(description='DBFuzz', formatter_class=ArgumentDefaultsHelpFormatter)

    # booleans arguments always default to false, true if provided
    bool_group = parser.add_argument_group('Boolean flags')
    bool_group.add_argument("--headful",        action='store_true', help="Run scanner in non-headless mode (if supported)")
    bool_group.add_argument("--insert-empty",   action='store_true', help="Insert default values into empty tables")
    bool_group.add_argument("--no-fuzz",        action='store_true', help="Don't fuzz the web app database")
    bool_group.add_argument("--reset-fuzzing",  action='store_true', help="Reset the database once after fuzzing")
    bool_group.add_argument("--reset-scanning", action='store_true', help="Reset the database continually after scanning")
    bool_group.add_argument("--sensitive-rows", action='store_true', help="Avoid sensitive rows during fuzzing")
    bool_group.add_argument("--randomize",      action='store_true', help="Randomize fuzzing traversal")
    bool_group.add_argument("--reverse",        action='store_true', help="Reverse fuzzing traversal")
    bool_group.add_argument("--mapping",        action='store_true', help="Mapping scan using original database")  # TODO
    bool_group.add_argument("--datatype",      action='store_true', help="Scan for structured datatypes in the database")  # TODO
    bool_group.add_argument("--primary-keys",   action='store_true', help="Match based on only primary keys, not entire row")
    bool_group.add_argument("--no-login",            action='store_true', help="Don't login automatically to the web app")
    bool_group.add_argument("--no-advanced-payload", action='store_true', help="Don't use advanced payload generation")
    bool_group.add_argument("--no-backup",           action='store_true', help="Don't backup the database before fuzzing")
    bool_group.add_argument("--no-scanner-cookies",  action='store_true', help="Don't use cookies in the reflection scanner")
    bool_group.add_argument("--no-breakage-cookies", action='store_true', help="Don't use cookies in the breakage check")

    int_group = parser.add_argument_group('Integer arguments')
    int_group.add_argument("--breakage-threshold", type=int, default=50,  help="Sensitivity of breakage check")
    int_group.add_argument("--max-rows",           type=int, default=-1, help="Maximum rows to fuzz per table (-1 infinite)")
    int_group.add_argument("--max-row-scan",       type=int, default=50,  help="Maximum rows to fuzz before scanning (-1 infinite)")
    int_group.add_argument("--max-cell-scan",      type=int, default=200, help="Maximum cells to fuzz before scanning (-1 infinite)")
    int_group.add_argument("--scanner-timeout",    type=int, default=120,  help="Timeout (sec) for reflection scanner")
    int_group.add_argument("--initial-scanner-timeout", type=int, default=300, help="Timeout (sec) for initial URL scan")
    # -1 makes the most sense (use all URLs for reflection scan), but is slow...
    int_group.add_argument("--max-scanner-urls",   type=int, default=50, help="Maximum # of URLs for reflection scanner (-1 infinite)")
    # -1 makes the most sense (use all URLs for breakage check), but is slow...
    int_group.add_argument("--max-breakage-urls",  type=int, default=20, help="Maximum # of URLs for breakage check (-1 infinite)")
    int_group.add_argument("--look-id",  type=int, default=-1, help="Identify the row an id was used in (-1 none)")

    string_group = parser.add_argument_group('String arguments (mostly file locations)')
    string_group.add_argument("--backup", type=str, default="backup.sql",        help="Backup the database")
    string_group.add_argument("--config", type=str, default="config.ini",        help="Fuzzer configuration")
    string_group.add_argument("--print",  type=str,
                              default=Path(DEFAULT_OUTPUTDIR).joinpath('xss_tokens.pickle'),
                              help="Print the fuzzing results")
    string_group.add_argument("--info",   type=str,
                              default=Path(DEFAULT_OUTPUTDIR).joinpath('information.txt'),
                              help="Save the fuzzing information")
    int_group.add_argument("--look-table",  type=str, default='', help="Identify the ids used in a table 'table' ('' none)")
    int_group.add_argument("--look-column",  type=str, default='', help="Identify the ids used in a column 'table.column' ('' none)")
    int_group.add_argument("--look-row",  type=str, default='', help="Identify the ids used in a row 'table.row' ('' none)")

    enum_group = parser.add_argument_group("Enum arguments ('ENUM.CHOICE' becomes 'choice'")
    enum_group.add_argument("--breakage",  type=BREAKAGE,  choices=BREAKAGE,  default=BREAKAGE.URL,       help="Breakage check used")
    enum_group.add_argument("--scanner",   type=SCANNER,   choices=SCANNER,   default=SCANNER.BLACKWIDOW, help="Reflection scanner")
    enum_group.add_argument("--traversal", type=TRAVERSAL, choices=TRAVERSAL, default=TRAVERSAL.TABLE,    help="Fuzzing traversal strategy")

    args = parser.parse_args()

    Path('bw').mkdir(parents=True, exist_ok=True)
    Path(DEFAULT_OUTPUTDIR).mkdir(parents=True, exist_ok=True)

    path = Path(args.print)
    parent = path.parent.absolute()
    parent.mkdir(parents=True, exist_ok=True)

    if args.datatype:
        datatype_scan(args)

    if not args.no_fuzz:
        # store git log and git diff for reproducability
        # with open(parent.joinpath('git_log.txt'), 'w') as f:
        #     gitlog = subprocess.run(['git', 'log'], capture_output=True, text=True)
        #     assert len(gitlog.stderr) == 0
        #     f.write(gitlog.stdout)
        # with open(parent.joinpath('git_diff.txt'), 'w') as f:
        #     gitdiff = subprocess.run(['git', 'diff'], capture_output=True, text=True)
        #     assert len(gitdiff.stderr) == 0
        #     f.write(gitdiff.stdout)

        start_fuzz = datetime.datetime.now()
        write_msg(f'fuzzing started at {start_fuzz}')

        main(args)

        end_fuzz = datetime.datetime.now()
        write_msg(f'fuzzing ended at {end_fuzz}')
        write_msg(f'fuzzing took {end_fuzz - start_fuzz}')


    if Path(args.print).exists():
        xss_found, tokens_found, scans, context, ids, app_config = Data.load_data(args.print)
        write_msg(str(xss_found))
        write_msg(str(tokens_found))


        if not args.no_fuzz:  # don't copy files if just analyzing existing pickle
            if Path(args.backup).exists():
                try:
                    shutil.copy2(args.backup, parent)
                except shutil.SameFileError:
                    pass

            if Path(args.config).exists():
                shutil.copy2(args.config, parent)

            if Path('errors.log').exists():
                try:
                    shutil.copy2('errors.log', parent)
                except shutil.SameFileError:
                    pass

            urls_file = urls_filename(app_config)
            if urls_file.exists():
                shutil.copy2(urls_file, parent)

            insert_backup_file = insert_backup_filename(app_config)
            if insert_backup_file.exists() and args.insert_empty:
                shutil.copy2(insert_backup_file, parent)

            sensitive_rows_file = sensitive_rows_filename(app_config)
            if sensitive_rows_file.exists() and args.sensitive_rows:
                shutil.copy2(sensitive_rows_file, parent)



        Data.print_reflection_summary(context, ids, xss_found, tokens_found, scans - 1)
        Data.graph_reflection_summary(context, xss_found, tokens_found, app_config, folder=parent)
        Data.csv_reflection_summary(context, xss_found, tokens_found, scans - 1, app_config, folder=parent)

        # Calculate Database Coverage
        Data.calculate_database_coverage(context, xss_found, tokens_found, args.backup, app_config, folder=parent)

        # Look for specific things
        Data.look_for(context, xss_found, tokens_found, scans - 1,
                      args.look_id, args.look_table, args.look_column, args.look_row)