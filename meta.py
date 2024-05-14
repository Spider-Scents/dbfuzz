import csv
import datetime  # needed for analyze_data to eval
import glob
import os
import pprint
import shutil
import statistics
import subprocess
import sys
from argparse import ArgumentParser
from collections import defaultdict

from tqdm import tqdm

from Data import (DBSOURCE, DESCRIPTION, FIELDNAMES, ID, PAYLOAD,
                  REFLECTIONSINK, WEBAPP)


def run_dbfuzz() -> None:
    """Run dbfuzz script repeatedly with various combinations of options"""

    config = 'config mybb.ini'

    base_cmd = ['python3', '-u', 'dbfuzz.py']
    assert os.path.exists('dbfuzz.py')
    base_cmd += ['--config', config, '--reset-fuzzing']  # parameters that should definitely be used
    base_cmd += ['--reset-scanning', '--insert-empty', '--sensitive-rows', '--primary-keys']  # parameters that should probably be used
    # base_cmd += ['--no-breakage-cookies']  # seems to get logged out? then lots of missing URLs (admin)
    # base_cmd += ['--headful']  # helps debugging sometimes

    # TODO which parameters?
    boolean_opts = [
        # ['--reset-scanning'],
        # ['--insert-empty'],
        # ['--randomize'],
        ['--reverse'],
        ['--traversal', 'column'],
    ]

    range_opts = [
        (['--breakage-threshold'], [25, 50, 75]),
        (['--max-rows'],           [10, 100, -1]),
        # (['--max-row-scan'],       [5, 50, 100]),
        # (['--max-cell-scan'],      [10, 50, 200]),
        # (['--scanner-timeout'],    [10, 30, 60]),
    ]

    cmds = [base_cmd]

    for opt in boolean_opts:
        cmds2 = []
        for cmd in cmds:
            cmds2.append(cmd[::])    # off
            cmds2.append(cmd + opt)  # on
        cmds = cmds2

    for opt, vals in range_opts:
        cmds2 = []
        for cmd in cmds:
            for val in vals:
                cmds2.append(cmd + opt + [str(val)])
        cmds = cmds2

    for cmd in cmds:
        tqdm.write(' '.join(cmd))

        name = ' '.join(cmd[len(base_cmd):])
        if os.path.exists(name):
            tqdm.write(f"'{name} exists, skipping")
            continue

        if os.path.exists('output'):
            shutil.rmtree('output')
        if os.path.exists('errors.log'):
            os.remove('errors.log')

        # subprocess.run(cmd)
        with subprocess.Popen(cmd,
                              stdout=subprocess.PIPE,
                              bufsize=1,
                              universal_newlines=True) as p:
            assert p.stdout is not None
            for line in p.stdout:
                tqdm.write(line, end='')

        shutil.copytree('output', name)


def combine_csv() -> None:
    """Combine CSV results"""

    dirs = [
        '.'
    ]

    RowKey = tuple[str, str]
    Row    = list[str]

    def row_key(row: Row) -> RowKey:
        return row[0], row[1]

    combined: dict[RowKey, list[tuple[str, Row]]] = dict()

    for dir in dirs:
        tqdm.write(dir)
        curr = os.getcwd()
        os.chdir(dir)
        files = glob.glob('**/*.{}'.format('csv'), recursive=True)
        tqdm.write(str(files))
        assert len(files) > 0, 'expected at least one file, found 0'
        for f in files:
            if f.endswith('combined.csv'):
                continue  # skip previous results of combining CSVs
            if 'ONLY_XSS=True' not in f:
                continue  # skip CSVs that do not purely consist of XSS findings
            with open(f, newline='', mode='r') as file:
                reader = csv.reader(file)
                next(reader)  # skip header
                for row in reader:
                    key = row_key(row)
                    if key not in combined:
                        combined[key] = []
                    combined[key].append((f, row))
        os.chdir(curr)

    with open('combined.csv', newline='', mode='w') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        for key in combined:
            webapp, dbsource = key
            reflectionsink = ''
            id = ''
            payload = ''
            description = ''

            for part in combined[key]:
                name, data = part
                _, _, data_reflectionsink, data_id, data_payload, data_description = data
                reflectionsink += f'{name}\n{data_reflectionsink}\n\n'
                id += f'{name}\n{data_id}\n\n'
                payload += f'{name}\n{data_payload}\n\n'
                description += f'{name}\n{data_description}\n\n'

            row = {WEBAPP: webapp, DBSOURCE: dbsource,
                   REFLECTIONSINK: reflectionsink, ID: id.strip(),
                   PAYLOAD: payload.strip(), DESCRIPTION: description.strip()}
            writer.writerow(row)

    tqdm.write('\nXSS:')
    tqdm.write(pprint.pformat(sorted(combined.keys())))
    tqdm.write('')

def analyze_data(filename: str) -> None:
    """Analyze scan log data to answer some questions"""

    tqdm.write(f'Analyzing data from {filename}')

    data = []
    with open(filename, 'r') as file:
        for line in file.readlines():
            if line.startswith('DEBUG:root:('):
                string = line[len('DEBUG:root:'):-1]
                datum = eval(string)  # no danger here :)
                # ast.literal_eval did not work for some reason...
                data.append(datum)

    # Questions about breakage:
    # 1) How often do webpages break?
    # 2) How much do webpages break?
    # 3) What webpages are breaking?
    # 4) Are certain groups of links breaking together?
    # 5) What DB changes are causing breakage?

    # More questions?...

    base_urls = dict()  # dictionary from baseline url ==> (# missing, # present)
    base_links = dict()  # dictionary from baseline (url, link) ==> (# missing, # present)
    new_links = defaultdict(lambda: 0)  # dictionary from new (not baseline) (url, link) ==> # present
    ids_missing_urls = defaultdict(list)  # dictionary from DbId ==> missing baseline url
    ids_missing_links = defaultdict(list)  # dictionary from DbId ==> missing baseline (url, link)
    ids_new_links = defaultdict(list) # dictionary from DbId ==> new (not baseline) (url, link)

    for datum in data:
        if datum[1] == 'url_breakage' and datum[2] == 'baseline' and datum[3] == 'url':
            # logging.debug(('dbfuzz', 'url_breakage', 'baseline', 'url', url))
            base_urls[datum[4]] = [0, 0]
        elif datum[1] == 'url_breakage' and datum[2] == 'baseline' and datum[3] == 'link':
            # logging.debug(('dbfuzz', 'url_breakage', 'baseline', 'link', url, link))
            base_links[(datum[4], datum[5])] = [0, 0]
        elif datum[1] == 'url_breakage' and datum[2] == 'broken' and datum[3] == 'url' and datum[4] == 'missing':
            # logging.debug(('dbfuzz', 'url_breakage', 'broken', 'url', 'missing', url, id))
            base_urls[datum[5]][0] = base_urls[datum[5]][0] + 1
            ids_missing_urls[datum[6]].append(datum[5])
        elif datum[1] == 'url_breakage' and datum[2] == 'broken' and datum[3] == 'url' and datum[4] == 'present':
            # logging.debug(('dbfuzz', 'url_breakage', 'broken', 'url', 'present', url, id))
            base_urls[datum[5]][1] = base_urls[datum[5]][1] + 1
        elif datum[1] == 'url_breakage' and datum[2] == 'broken' and datum[3] == 'link' and datum[4] == 'missing':
            # logging.debug(('dbfuzz', 'url_breakage', 'broken', 'link', 'missing', url, link, id))
            base_links[(datum[5], datum[6])][0] = base_links[(datum[5], datum[6])][0] + 1
            ids_missing_links[datum[7]].append((datum[5], datum[6]))
        elif datum[1] == 'url_breakage' and datum[2] == 'broken' and datum[3] == 'link' and datum[4] == 'present':
            # logging.debug(('dbfuzz', 'url_breakage', 'broken', 'link', 'present', url, link, id))
            base_links[(datum[5], datum[6])][1] = base_links[(datum[5], datum[6])][1] + 1
        elif datum[1] == 'url_breakage' and datum[2] == 'broken' and datum[3] == 'link' and datum[4] == 'new':
            # logging.debug(('dbfuzz', 'url_breakage', 'broken', 'link', 'new', url, link, id))
            new_links[(datum[5], datum[6])] += 1
            ids_new_links[datum[7]].append((datum[5], datum[6]))


    # tqdm.write(pprint.pformat(base_links))
    # tqdm.write(pprint.pformat(new_links))
    # tqdm.write(pprint.pformat(ids_missing_links))
    for id in ids_missing_links:
        tqdm.write(f'DbId {id} caused {len(ids_missing_links[id])} links to break')
        if len(ids_missing_links[id]) < 10:
            tqdm.write(str(ids_missing_links[id]))

    scanner_timeouts = []
    scanner_times = []

    for datum in data:
        if datum[1] == 'bw_scanner' and datum[2] == 'get_output' and datum[3] == 'timeout':
            # logging.debug(('dbfuzz', 'bw_scanner', 'get_output', 'timeout', True))
            scanner_timeouts.append(datum[4])
        elif datum[1] == 'bw_scanner' and datum[2] == 'get_output' and datum[3] == 'time':
            # logging.debug(('dbfuzz', 'bw_scanner', 'get_output', 'time', time_diff))
            scanner_times.append(datum[4])

    tqdm.write(f'scanner timeouts ({len(scanner_timeouts)}): {scanner_timeouts}')
    tqdm.write(f'scanner times ({len(scanner_times)}): {scanner_times}')
    tqdm.write(f'average scanner time: {statistics.mean(scanner_times)}')
    tqdm.write(f'scanner time range: {min(scanner_times)}-{max(scanner_times)}')


if __name__ == '__main__':

    parser = ArgumentParser(description='DBFuzz meta')
    parser.add_argument("--run", action='store_true', help="Run dbfuzz with various combinations of parameters")
    parser.add_argument("--combine-csv", action='store_true', help="Combine result CSVs from various runs of dbfuzz")
    parser.add_argument("--statistics", type=str, default="", help="Generate statistics")
    args = parser.parse_args()

    if not len(sys.argv) > 1:
        tqdm.write('no argument provided!')
        parser.print_help()

    if args.run:
        run_dbfuzz()
    if args.combine_csv:
        combine_csv()
    if args.statistics != "":
        analyze_data(args.statistics)
