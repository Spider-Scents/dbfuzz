import json
from enum import Enum
from logging import warning
from random import randint
from re import findall, search
from typing import Any, Optional
# from urllib.parse import urlparse

import cssutils
import defusedxml.ElementTree as ET
from bs4 import BeautifulSoup

from Database import ColInfo, Database, KeyInfo
from Helper import write_msg

Columns = list[str]
Pos     = tuple[int, int]


class DbId(object):
    """Holds all relevant information about a particular change in the database"""

    def __init__(self, database: str, table: str, column: str, position: Pos, step: int, old: list, new: list) -> None:
        """Initialize"""

        self.database = database
        self.table    = table
        self.column   = column
        self.position = tuple(position) # row, column
        self.step     = step            # which part of the scan (only makes sense without resets)
        self.old      = old[::]         # old contents
        self.new      = new[::]         # new contents

    def __str__(self) -> str:
        """String representation"""

        return f'{self.table}.{self.column}'

    def pos(self) -> str:
        """Get string about the location of the change"""

        return f'{self.database}.{self.table}.{self.column}[{self.position[0]}][{self.position[1]}]'

    def details(self) -> str:
        """Get a detailed summary of this change"""

        return \
            f'''
            {self.pos()}
            original row: {self.old}
            fuzzed row: {self.new}
            change: '{self.old[self.position[1]]}' => '{self.new[self.position[1]]}'
            '''


# GLOBAL VARIABLES
ids     = [-1]  # randomized IDs
context = {-1: DbId("", "", "", (-1, -1), -1, [], [])}  # map from IDs to database info

# '9' + 5 random digits
ID_LENGTH = 6


def payload(i: int) -> str:
    """Make an XSS payload containing an ID"""

    assert i >= 0
    return f"\"'><script>xss({i:0{ID_LENGTH}})</script>"
    # return f"\"'><script>console.log(\"{i:0{ID_LENGTH}}\")</script>"


PAYLOAD_LENGTH = len(payload(0))


def is_fuzzable_col(c: ColInfo) -> bool:
    """Check if a column is fuzzable"""

    column, column_type, column_size, column_values = c
    column_size = Database.sql_string_type_size(column_type, column_size)
    return Database.is_type_string(column_type) and \
           column_size is not None and column_size >= PAYLOAD_LENGTH and \
           column_type not in {'enum', 'set'}


def get_id() -> int:
    """Get a new randomized ID"""

    r = ids[0]
    assert len(context) < (10 ** PAYLOAD_LENGTH) - 1
    while r in context:
        # avoid interpretation as octal with leading zeros
        # 9s are also rare as leading digit: https://en.wikipedia.org/wiki/Benford%27s_law
        # can use this to distinguish our IDs later
        r = 9 * (10 ** (ID_LENGTH - 1)) + randint(0, 10 ** (ID_LENGTH - 1))
    ids.append(r)
    return r


def get_payload() -> str:
    """Get a payload with a new randomized ID"""

    i = get_id()
    return payload(i)


class Datatype(Enum):  # structured data type
    """Different possible datatypes for structured data stored in a string-like database cell"""
    NONE = 1
    PHP = 2
    IMG = 3
    FILE = 4  # TODO
    URL = 5  # TODO
    HTML = 6
    CSS = 7
    JS = 8  # TODO
    JSON = 9
    XML = 10


def get_datatype(data: str) -> set[Datatype]:
    """Get possible structured datatypes for a database cell"""

    datatypes = set()
    # TODO nested types?

    if findall('s:(\\d+):"(.+?)"', data):
        datatypes.add(Datatype.PHP)

    if search('([a-zA-Z0-9]\\.(png|jpg|jpeg|gif))$', data):
        datatypes.add(Datatype.IMG)

    try:
        if BeautifulSoup('what', "html.parser").find():
            datatypes.add(Datatype.HTML)
            # TODO less strict parser?
    except:  # being paranoid, haven't tested
        pass

    try:
        css_parser = cssutils.CSSParser(raiseExceptions=True)
        css_parser.parseString(data)  # TODO adjust validation?
        datatypes.add(Datatype.CSS)
    except:  # xml.dom.SyntaxErr
        pass

    try:
        j = json.loads(data)
        if isinstance(j, dict):  # only care about JSON objects
            datatypes.add(Datatype.JSON)
    except:  # json.decoder.JSONDecodeError
        pass

    try:
        ET.fromstring(data)
        datatypes.add(Datatype.XML)  # seems to find some HTML?
        # examples from prestashop: ['<p>product description</p>', '<p>product summary</p>']
    except:  # xml.etree.ElementTree.ParseError
        pass

    return datatypes


def detect_payload_datatype(data: Any) -> Optional[str]:
    """
    Tries to find a payload matching the format of data.
    Returns the new payload or None if not format is found.
    """

    # E.g. if value is NULL in DB. Just pick generic payload.
    if not data:
        return None

    # Sometimes we get binary data?
    if type(data) is not str:
        # can be 'bytes', 'bytearray'
        try:
            data = data.decode()
        except Exception:
            write_msg("Failed to decode data, falling back to general payload")
            warning(f'Failed to decode data of type {type(data)}: {data}')
            return None

    # Serialized objects
    # TODO replace all? might want to iterate over possible changes, or just choose 1
    matches = findall('s:(\\d+):"(.+?)"', data)
    if matches:
        write_msg(str(matches))
        for m in matches:
            payload = get_payload()
            pl = len(payload)
            data = data.replace(f's:{m[0]}:"{m[1]}"', f's:{pl}:"{payload}"')
        write_msg(f"Serialized Payload: {data}")
        return data

    # Img onload
    match = search('([a-zA-Z0-9]\\.(png|jpg|jpeg|gif))$', data)
    if match:
        id = get_id()
        # To -1 to ensure we get onerror
        # Because we can't know the order of quotes.
        # Could be useful if <script> tags are filtered.
        data = data[:-1] + f"\"' onerror='xss({id})' "
        return data

    # Date format
    # Need to escape payload, e.g.
    # y-m-d \<\s\c\r\i\p\t\>\a\l\e\r\t\(\1\)\<\/\s\c\r\i\p\t\> Y

    # HTML. Maybe too boring? Could be interesting cases perhaps.

    return None


def update_payload(db: Database, table: str, row: tuple,
                   columns: Columns, col_info: list[ColInfo], key_info: list[KeyInfo],
                   pos: Pos, scan: int,
                   advanced: bool = True, primary: bool = False) -> tuple:
    """Update a database cell with a payload"""

    _, c_i = pos
    payload = detect_payload_datatype(row[c_i]) if advanced else None
    if payload is None:
        payload = get_payload()
    new = list(row)
    new[c_i] = payload
    if db.update_row(table, row, tuple(new), columns, col_info, key_info, primary=primary) != 1:
        del ids[-1]
        write_msg(f'old: {row}')
        write_msg(f'new: {new}')
        write_msg('failure!')
        warning(f"failed to update {db}.{table} row at {pos} from {row} to {new}")
        return row
    else:
        context[ids[-1]] = DbId(database=db.config.database,
                                table=table,
                                column=columns[c_i],
                                position=pos,
                                step=scan,
                                old=list(row),
                                new=list(new))
        write_msg(f'success! {ids[-1]}')
        return tuple(new)
