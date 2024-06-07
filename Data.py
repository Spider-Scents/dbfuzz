import pickle
import re
import shutil
from csv import DictWriter
from hashlib import sha256
from itertools import groupby
from logging import warning
from operator import itemgetter
from pathlib import Path
from typing import Optional

from graphviz import Digraph

import Payload
from dbfuzz import AppConfig
from Helper import write_msg

from Database import ColInfo, Database, KeyInfo

Found   = tuple[int, str, int] # (xss_id, url, scans)
Context = dict[int, Payload.DbId]


def graph_reflection_summary(context: Context, xss_found: list[Found], tokens_found: list[Found],
                             app_config: AppConfig, folder: Optional[Path] = None):
    """Graph a summary of reflections found, with database modifications connected to webpage reflections"""

    ADD_UNKNOWN     = True  # add unknown findings to the graph, connected to '???' DB node
    SHORTEN_DB      = True  # shorten database node IDs
    PRUNE_IDS       = True  # remove unconnected id (DB) nodes
    ENFORCE_COLUMNS = True  # enforce separate columns for DB and web nodes
    XSS_IMPLY_TOKEN = True  # assume that XSS implies tokens, and only display the XSS edge
    ADD_TOKENS      = True  # add tokens to the graph

    if not ADD_TOKENS: tokens_found = []

    # REMOVE = [
    #     'cms_siteprefs.sitepref_value', 'cms_content.metadata', 'cms_content.content_alias', 'cms_layout_stylesheets.media_type', 'cms_layout_stylesheets.media_query', 'cms_module_news_categories.news_category_name', 'cms_content.content_name', 'cms_module_news.news_data', 'cms_module_news.summary', 'cms_module_news.news_extra', 'mybb_templates.template', 'wp_users.display_name', 'tbldoctor.FullName', 'tbldoctor.Email'
    # ]
    REMOVE = [] # add any DB nodes to remove to simplify/clean up graph visualization

    REVERSE_REMOVE  = False # only keep from REMOVE, instead of the normal other-way-around
    DO_REMOVE       = True # actually remove stuff

    if not DO_REMOVE:
        REMOVE = []

    remove_func = lambda e: e in REMOVE
    if REVERSE_REMOVE:
        remove_func = lambda e: e not in REMOVE

    options = [f'{ADD_UNKNOWN=}', f'{SHORTEN_DB=}', f'{PRUNE_IDS=}', f'{ENFORCE_COLUMNS=}', f'{XSS_IMPLY_TOKEN=}']
    filename = filename_with_options('graph', app_config, options, folder=folder)

    def nodeid(s: str) -> str:
        """ URLs are not valid node identifier """
        m = sha256()
        m.update(s.encode())
        return m.hexdigest()

    def dbid(s: Payload.DbId|str) -> str:
        ss = str(s)  # may be a DbId
        c = '['
        if not SHORTEN_DB or c not in ss:
            return ss
        return ss[:ss.index(c)]

    dot = Digraph(comment='Tokens and XSS')
    dot.graph_attr["rankdir"] = "LR"  # left -> right graph direction

    xss_found    = sorted(xss_found)
    tokens_found = sorted(tokens_found)

    id_nodes = set()
    for id in context:
        unknown_link = not any(map(lambda x: x[0] == id, tokens_found + xss_found))
        if PRUNE_IDS and unknown_link:  # not found while scanning
            continue
        if remove_func(dbid(context[id])):
            continue
        dot.node(dbid(context[id]), dbid(context[id]), group="DB")
        id_nodes.add(id)

    unknown_links = False
    for id, url, scan in tokens_found + xss_found:
        if id not in context:
            print(f'unknown id: {id}, url: {url}')
            unknown_links = True
        if unknown_links:
            break
    if ADD_UNKNOWN and unknown_links:  # don't add the unknown DB node if not needed
        dot.node("???", "???", group="DB")

    nodes = set()
    for id, url, _ in xss_found:
        if remove_func(dbid(context[id])):
            continue
        nodes.add(url)
    for id, url, _ in tokens_found:
        nodes.add(url)

    for node in nodes:
        dot.node(nodeid(node), node, group="WEB")

    # Now in RED for XSS.
    edges_2 = set()
    for id, url, _ in xss_found:
        if id in context:
            if remove_func(dbid(context[id])):
                continue
            if not (dbid(context[id]), nodeid(url)) in edges_2:
                dot.edge(dbid(context[id]), nodeid(url), color="RED")
                edges_2.add((dbid(context[id]), nodeid(url)))
        elif ADD_UNKNOWN:
            if not ("???", nodeid(url)) in edges_2:
                dot.edge("???", nodeid(url), color="RED")
                edges_2.add(("???", nodeid(url)))

    # A bit easier to see with unique edges, but lose info about number of
    # reflections per page.
    edges_1 = set()
    for id, url, _ in tokens_found:
        # How to handle unknown IDs? Just a "???" node perhaps.
        if id in context:
            if XSS_IMPLY_TOKEN and (dbid(context[id]), nodeid(url)) in edges_2:
                continue
            if not (dbid(context[id]), nodeid(url)) in edges_1:
                dot.edge(dbid(context[id]), nodeid(url))
                edges_1.add((dbid(context[id]), nodeid(url)))
        elif ADD_UNKNOWN:
            if not ("???", nodeid(url)) in edges_1:
                dot.edge("???", nodeid(url))
                edges_1.add(("???", nodeid(url)))

    if ENFORCE_COLUMNS:
        # add invisible nodes & edges for unconnected nodes (enforce columns - one for DB, another for URLs)
        # https://stackoverflow.com/questions/1476241/how-to-force-all-nodes-in-the-same-column-in-graphviz
        dot.node('invis_url', 'invis_url', group="WEB", style='invis')
        dot.node('invis_db', 'invis_db', group="DB", style='invis')
        for id in id_nodes:
            if not any(map(lambda e: e[0] == dbid(context[id]), edges_1.union(edges_2))):
                dot.edge(dbid(context[id]), 'invis_url', style='invis')
        for n in nodes:
            if not any(map(lambda e: e[1] == nodeid(n), edges_1.union(edges_2))):
                dot.edge('invis_db', nodeid(n), style='invis')

    # TODO check connected

    dot.format = 'pdf'
    dot.render(filename, view=True)


    short_filename = filename_with_options('graph', app_config, [], folder=folder)
    dot.render(short_filename, view=False)


WEBAPP         = 'web app'
DBSOURCE       = 'DB source'
REFLECTIONSINK = 'reflection sink'
ID             = 'id'
PAYLOAD        = 'payload'
DESCRIPTION    = 'description'
FIELDNAMES = [WEBAPP, DBSOURCE, REFLECTIONSINK, ID, PAYLOAD, DESCRIPTION]


def csv_reflection_summary(context: Context, xss_found: list[Found], tokens_found: list[Found],
                           scans: int, app_config: AppConfig, folder: Optional[Path] = None) -> None:
    """Make a CSV summarizing reflections found"""

    def csv_reflection(founds):
        id, _, _, _ = founds[0]
        payload_ = Payload.payload(id)
        dbsource = '?' if id not in context else str(context[id])
        description = 'NOT FUZZED'
        if id in context:
            description = f'{context[id].details()}\nfuzzed after scan {context[id].step} / {scans}'
        scans_found = set()
        for found in founds:
            _, _, scan, token = found
            if scan not in scans_found:
                description += f"\nfound as {'TOKEN' if token else 'XSS'} in scan {scan} / {scans}"
                scans_found.add(scan)
        urls = '\n'.join(sorted(set(found[1] for found in founds)))
        row = {WEBAPP: app_config.app, DBSOURCE: dbsource,
               REFLECTIONSINK: urls, ID: id,
               PAYLOAD: payload_, DESCRIPTION: description}
        return row

    COMBINE_REFLECTIONS = True
    ONLY_XSS            = True

    options = [f'{COMBINE_REFLECTIONS=}', f'{ONLY_XSS=}']
    filename = filename_with_options('reflections', app_config, options, 'csv', folder=folder)

    with open(filename, 'w', newline='') as csvfile:
        writer = DictWriter(csvfile, fieldnames=FIELDNAMES)
        writer.writeheader()

        xss_found_    = map(lambda x: x + (False,), xss_found)    # mark as not tokens
        tokens_found_ = map(lambda x: x + (True,), tokens_found)  # mark as tokens
        if ONLY_XSS:
            tokens_found_ = []

        if not COMBINE_REFLECTIONS:
            writer.writerows(map(csv_reflection, xss_found_))
            writer.writerows(map(csv_reflection, tokens_found_))
        else:
            sorted_founds = sorted(list(xss_found_) + list(tokens_found_), key=itemgetter(0))
            groups = groupby(sorted_founds, key=itemgetter(0))
            for _id, group in groups:
                g = list(group)
                writer.writerow(csv_reflection(g))
    short_filename = filename_with_options('reflections', app_config, [], 'csv', folder=folder)
    shutil.copyfile(filename, short_filename)


def print_reflection_summary(context: Context, ids: list[int], xss_found: list[Found],
                             tokens_found: list[Found], scans: int) -> None:
    """Print a summary of reflections found"""

    xss_found    = sorted(xss_found)
    tokens_found = sorted(tokens_found)

    write_msg("ALL REFLECTIONS:")
    for id, url, scan in xss_found:
        print_reflection(context, id, url, is_token=False, log_errors=False)
    for id, url, scan in tokens_found:
        print_reflection(context, id, url, is_token=True, log_errors=False)

    write_msg("\nREFLECTIONS FOUND PER SCAN")
    for i in range(1, scans + 1):
        write_msg(f'SCAN {i}:')
        for id, url, scan in xss_found:
            if scan == i:
                print_reflection(context, id, url, is_token=False, log_errors=False)
        for id, url, scan in tokens_found:
            if scan == i:
                print_reflection(context, id, url, is_token=True, log_errors=False)

    write_msg("\nREFLECTIONS FOUND PER KNOWN ID")
    for i in sorted(ids[1:]):
        print_reflection_id(context, i, xss_found, tokens_found, scans)

    write_msg("\nREFLECTIONS FOUND PER UNKNOWN ID")
    unknown_xss = [xss for xss in xss_found if xss[0] not in context]
    unknown_tokens = [token for token in tokens_found if token[0] not in context]
    for i in sorted(set([xss[0] for xss in unknown_xss] + [token[0] for token in unknown_tokens])):
        print_reflection_id(context, i, xss_found, tokens_found, scans)

    write_msg("\nREFLECTIONS FOUND PER ID")
    for i in sorted(set([xss[0] for xss in xss_found] + [token[0] for token in tokens_found])):
        print_reflection_id(context, i, xss_found, tokens_found, scans)


def print_reflection(context: Context, id: int, url: str,
                     is_token: bool = False, log_errors: bool = True) -> None:
    """Print a single reflection"""

    type = "token" if is_token else "XSS"
    if id not in context and log_errors:
        warning(f"reflection id error: {id}")
    db_loc = "???" if id not in context else context[id]
    write_msg(f'{type}:\tid={id},\tdb={db_loc},\turl={url}')


def print_reflection_id(context: Context, i: int, xss_found: list[Found],
                        tokens_found: list[Found], scans: int) -> None:
    """Print a single reflection based on ID used"""

    xss_i = [xss for xss in xss_found if xss[0] == i]
    xss_scans = set(xss[2] for xss in xss_i)
    tokens_i = [token for token in tokens_found if token[0] == i]
    token_scans = set(token[2] for token in tokens_i)
    first_scan  = 1 if i not in context else context[i].step
    if len(xss_i) + len(tokens_i) > 0:
        write_msg(f"ID {i} found as XSS {len(xss_scans)}/{scans-first_scan+1} as token {len(token_scans)}/{scans-first_scan+1}")
        if i in context:
            write_msg(f"db loc: {context[i]}")
            write_msg(f"first scan: {first_scan}")
    if len(xss_i) > 0:
        write_msg("\tXSS found in:")
        for url in sorted(set(xss[1] for xss in xss_found if xss[0] == i)):
            print(f'\t\t{url}')
    if len(tokens_i) > 0:
        write_msg("\ttoken found in:")
        for url in sorted(set(token[1] for token in tokens_found if token[0] == i)):
            write_msg(f'\t\t{url}')


def filename_with_options(basename: str, app_config: AppConfig, options: list[str],
                          extension: Optional[str] = None, folder: Optional[Path] = None) -> Path:
    """Make a filename that includes options used"""

    if folder is None:
        folder = Path()  # current directory
    filename = f'{basename} {app_config}'
    for option in options:
        filename += f' {option}'
    if extension is not None:
        filename += f'.{extension}'
    return folder.joinpath(filename)


def save_data(xss_found: list[Found], tokens_found: list[Found], scans: int, app_config: AppConfig, final=True) -> str:
    """Save scan data to a pickle"""

    xss_tokens_data = (xss_found, tokens_found, scans, Payload.context, Payload.ids, app_config)

    filename = app_config.print
    if not final:
        filename = f'{app_config.print}{scans}'

    with open(filename, 'wb') as f:
        # no point to use 'human-readable' procotol (protocol=0), still unreadable
        pickle.dump(xss_tokens_data, f, pickle.HIGHEST_PROTOCOL)

    with open(filename, 'rb') as f:  # test loading
        xss_tokens_data = pickle.load(f)

    return filename


def load_data(filename: str) -> tuple[list[Found], list[Found], int, dict[int, Payload.DbId], list[int], AppConfig]:
    """Load scan data from a pickle"""

    with open(filename, 'rb') as f:
        xss_tokens_data = pickle.load(f)

    xss_found, tokens_found, scans, context, ids, app_config = xss_tokens_data
    for id, url, scan in xss_found:
        assert len(str(id)) == Payload.ID_LENGTH
        assert scan <= scans
    tokens_found_ = []
    for id, url, scan in tokens_found:
        assert len(str(id)) <= Payload.ID_LENGTH - 1  # 9 is not in the capture group in BW!
        assert scan <= scans
        tokens_found_.append((int(f'9{id:0{Payload.ID_LENGTH-1}}'), url, scan))  # handle leading zeroes missing (after missing 9)

    return (xss_found, tokens_found_, scans, context, ids, app_config)


def parse_sql_file(sqlfile: str) -> dict:
  """Parse a SQL file to a dictionary with type and sizes per column for each table in the database"""

  db = {}
  table = None
  for line in open(sqlfile, encoding='utf-8', errors="ignore"):
    m = re.search("CREATE TABLE `(.+?)`", line)
    if m:
      table = m.group(1)
      if not table in db:
        db[table] = {}
      continue

    # E.g. `scheduleId` int(11) NOT NULL AUTO_INCREMENT,
    if line[:3] == "  `":
      parts = line.split()
      column = parts[0][1:-1]
      type = parts[1]

      size = None
      size_m = re.search(r"\((\d+)\)", type)
      if size_m:
        size = int(size_m.group(1))
        type = type[:-(2+len(size_m.group(1)))]

      db[table][column] = (type, size)

  return db


def calculate_database_coverage(context: Context, xss_found: list[Found],
                                tokens_found: list[Found], sqlfile: str,
                                app_config: AppConfig, folder: Optional[Path] = None) -> None:
    """Prints database coverage (how much we modify) for a scan"""

    db = parse_sql_file(sqlfile)
    csv_rows = []

    # Based on is_fuzzable from payload.py, but without length
    def possibly_fuzzable(c) -> bool:
      column, column_type, column_size, column_values = c
      return Database.is_type_string(column_type) and \
             column_type not in {'enum', 'set'}

    def db_coverage(found: list[Found]) -> dict[str, dict[str, set[int]]]:
        coverage = {}
        for id, _, _ in found:
            if id not in context:
                continue

            table = context[id].table
            column = context[id].column

            if table in db:
                if not table in coverage:
                    coverage[table] = {}

            if column in db[table]:
                if not column in coverage[table]:
                    coverage[table][column] = set()
                # Not sure we need to save the ids...
                coverage[table][column].add(id)
        return coverage

    xss_db_coverage = db_coverage(xss_found)
    tokens_db_coverage = db_coverage(xss_found + tokens_found)

    # Compare coverage
    no_xss = set()
    no_tokens = set()
    fuzzable_columns = set() # To compare with other scanners
    possibly_fuzzable_columns = set() # The "max" in comparison
    total_columns = 0
    not_fuzzable = 0
    covered_columns = 0
    for table in db:
      for column in db[table]:

        col = table + "." + column
        total_columns += 1

        # Check column type and size
        column_type, column_size = db[table][column]
        # write_msg(f'{table} {column} {db[table][column]}')

        col_info = (column, column_type, column_size, [])
        if possibly_fuzzable(col_info):
          possibly_fuzzable_columns.add(col)

        if not Payload.is_fuzzable_col(col_info):
          not_fuzzable += 1
        else:
            fuzzable_columns.add(col)

            covered = False

            # Check XSS coverage
            if table not in xss_db_coverage:
                no_xss.add(col)
            elif column not in xss_db_coverage[table]:
                no_xss.add(col)
            else:
                covered = True

            # Check token coverage
            if table not in tokens_db_coverage:
                no_tokens.add(col)
            elif column not in tokens_db_coverage[table]:
                no_tokens.add(col)
            else:
                covered = True

            if covered:
                covered_columns += 1

        if col in possibly_fuzzable_columns:
            csv_rows.append({
                'Column' : col,
                'Type' : column_type,
                'Size' : column_size,
                'Fuzzed' : col in fuzzable_columns,
                'XSS' : col in fuzzable_columns and col not in no_xss,
                'Token' : col in fuzzable_columns and col not in no_tokens
            })

    write_msg("\nDatabase Coverage (in terms of XSS/reflections)")
    write_msg(f"We cover {covered_columns} columns out of total {total_columns}")
    write_msg(f"We cover {covered_columns} columns out of fuzzable {total_columns-not_fuzzable}")
    # no XSS means either - protected column, or not found
    write_msg(f"Manual/Further check these (no XSS): {no_xss}")
    # no tokens found indicates either: scanner failure (not found), or just uninteresting
    write_msg(f"Manual/Further check these (not reflected): {no_tokens}")
    # protected columns
    write_msg(f"Manual/Further check these (protected): {no_xss - no_tokens}")
    print("All fuzzable: ")
    print(fuzzable_columns)

    print("Possibly fuzzable: ")
    print(possibly_fuzzable_columns)

    # write to CSV
    filename = filename_with_options('coverage', app_config, [], 'csv', folder=folder)
    with open(filename, 'w', newline='') as csvfile:
        writer = DictWriter(csvfile, fieldnames=['Column', 'Type', 'Size', 'Fuzzed', 'XSS', 'Token'])
        writer.writeheader()
        for row in csv_rows:
            writer.writerow(row)


def look_for(context: Context, xss_found: list[Found], tokens_found: list[Found], scans: int,
             a_look_id: int, a_look_table: str, a_look_column: str, a_look_row: str) -> None:
    """Prints information present in a scan about a specific ID"""

    if a_look_id != -1:
        write_msg('\n')
        if a_look_id not in context:
            write_msg(f'id {a_look_id} not found!')
        else:
            write_msg(f'id {a_look_id}:\n{context[a_look_id].details()}')
            print_reflection_id(context, a_look_id, xss_found, tokens_found, scans)
    if a_look_table != '':
        write_msg('\n')
        ids = []
        for i in context:
            if context[i].table == a_look_table:
                ids.append([context[i].position, i])
        write_msg(f'table {a_look_table}: {sorted(i[1] for i in ids)}')
        for i in sorted(ids):
            write_msg(f'{i[1]}: {context[i[1]].pos()}')
            print_reflection_id(context, i[1], xss_found, tokens_found, scans)
    if a_look_column != '':
        try:
            look_table = a_look_column[:a_look_column.index('.')]
            look_column = a_look_column[a_look_column.index('.')+1:]
            write_msg('\n')
            ids = []
            for i in context:
                if context[i].table == look_table and context[i].column == look_column:
                    ids.append([context[i].position, i])
            write_msg(f'column {look_table}.{look_column}: {sorted(i[1] for i in ids)}')
            for i in sorted(ids):
                write_msg(f'{i[1]}: {context[i[1]].pos()}')
                print_reflection_id(context, i[1], xss_found, tokens_found, scans)
        except:
            write_msg(f'invalid format {a_look_column}')
    if a_look_row != '':
        try:
            look_table = a_look_row[:a_look_row.index('.')]
            look_row = int(a_look_row[a_look_row.index('.')+1:])
            write_msg('\n')
            ids = []
            for i in context:
                if context[i].table == look_table and context[i].position[0] == look_row:
                    ids.append([context[i].position, i])
            write_msg(f'row {look_table}.{look_row}: {sorted(i[1] for i in ids)}')
            for i in sorted(ids):
                write_msg(f'{i[1]}: {context[i[1]].pos()}')
                write_msg(context[i[1]].details())
                print_reflection_id(context, i[1], xss_found, tokens_found, scans)
        except:
            write_msg(f'invalid format {a_look_row}')
