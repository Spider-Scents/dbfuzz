import logging
import re
import subprocess
import sys
from typing import Any, Optional

from mysql.connector import Error, connect

from Helper import write_msg

ColInfo = tuple[str, str, int, list]
KeyInfo = tuple[str, str]


class DatabaseConfig(object):
    """Holds the configuration for a database connection"""

    def __init__(self, host: str, user: str, password: str,
                 database: str, port: int = 3306,
                 mysql: str = "mysql", mysqldump: str = "mysqldump") -> None:
        """Initialize"""

        self.host      = host
        self.user      = user
        self.password  = password
        self.database  = database
        self.port      = port
        self.mysql     = mysql
        self.mysqldump = mysqldump


class Database(object):
    """Class through which the SQL database can be accessed"""

    def __init__(self, config: DatabaseConfig) -> None:
        """Initialize a connection based on a config"""

        self.config     = config
        self.connection = self.create_server_connection()

    def create_server_connection(self) -> Any:
        """Helper method to create a connection"""
        return connect(
            host=self.config.host,
            user=self.config.user,
            passwd=self.config.password,
            database=self.config.database,
            port=self.config.port)

    def execute_query(self, query: str, params: Optional[tuple] = None) -> int:
        """Helper method to execute a query"""

        cursor = self.connection.cursor()
        logging.debug(('dbfuzz', 'database', 'execute', 'sql', query, params))
        try:
            cursor.execute(query, params)
            self.connection.commit()
            return cursor.rowcount
        except Error as err:
            write_msg(f"SQL error: '{err}'")
            logging.warning(f"{self.execute_query.__name__}: {err}")
            logging.debug(('dbfuzz', 'database', 'execute', 'error', query, params, str(err)))
            return -1

    def read_query(self, query: str, params: Optional[tuple] = None) -> Optional[list[tuple]]:
        """Helper method to read a query"""

        cursor = self.connection.cursor()
        logging.debug(('dbfuzz', 'database', 'read', 'sql', query, params))
        result = None
        try:
            cursor.execute(query, params)
            result = cursor.fetchall()
            return result
        except Error as err:
            write_msg(f"SQL error: '{err}'")
            logging.warning(f"{self.read_query.__name__}: {err}")
            logging.debug(('dbfuzz', 'database', 'read', 'error', query, params, str(err)))
            return None

    # don't allow SQL errors
    def read_query_(self, query: str, params: Optional[tuple] = None) -> list[tuple]:
        """Helper method to read a query, while not allowing errors"""

        ret = self.read_query(query, params)
        assert ret is not None
        return ret

    def get_tables(self) -> list[str]:
        """Get the tables in the database"""

        # https://dev.mysql.com/doc/refman/8.0/en/information-schema-tables-table.html
        query = f"""
            SELECT `TABLE_NAME`
            FROM `INFORMATION_SCHEMA`.`TABLES`
            WHERE `TABLE_SCHEMA`='{self.config.database}';"""
        result = self.read_query_(query)
        return [i[0] for i in result]

    def get_columns(self, table: str) -> list[str]:
        """Get the columns in a table"""

        # https://dev.mysql.com/doc/refman/8.0/en/information-schema-columns-table.html
        query = f"""
            SELECT `COLUMN_NAME`
            FROM `INFORMATION_SCHEMA`.`COLUMNS`
            WHERE `TABLE_SCHEMA`='{self.config.database}'
                AND `TABLE_NAME`='{table}';"""
        result = self.read_query_(query)
        return [i[0] for i in result]

    # [(column, type, length, values)]
    def get_columns_info(self, table: str) -> list[ColInfo]:
        """Get information about the columns in a table"""

        # https://dev.mysql.com/doc/refman/8.0/en/information-schema-columns-table.html
        query = f"""
            SELECT `COLUMN_NAME`, `DATA_TYPE`, `CHARACTER_MAXIMUM_LENGTH`, `COLUMN_TYPE`
            FROM `INFORMATION_SCHEMA`.`COLUMNS`
            WHERE `TABLE_SCHEMA`='{self.config.database}'
                AND `TABLE_NAME`='{table}';"""

        def process(column: tuple) -> ColInfo:
            name, type, length, longtype = column
            values = []
            if type in {'enum', 'set'}:
                values = [val[1:-1] for val in longtype[len(type) + 1:-1].split(',')]
            return name, type, length, values

        raw = self.read_query_(query)
        processed = list(map(process, raw))
        return processed

    # [(column, constraint)]
    def get_key_info(self, table: str) -> list[KeyInfo]:
        """Get information about the keys in a table"""

        # https://dev.mysql.com/doc/refman/8.0/en/information-schema-key-column-usage-table.html
        # https://dev.mysql.com/doc/refman/8.0/en/information-schema-general-table-reference.html
        query = f"""
            SELECT `COLUMN_NAME`, `CONSTRAINT_NAME`
            FROM `INFORMATION_SCHEMA`.`KEY_COLUMN_USAGE`
            WHERE `TABLE_SCHEMA`='{self.config.database}'
                AND `TABLE_NAME`='{table}';"""
        return self.read_query_(query)

    def get_primary_keys(self, key_info: list[KeyInfo]) -> list[str]:
        """Get primary keys from a table's key information"""

        keys = []
        for (col, constraint) in key_info:
            if constraint == "PRIMARY":
                keys.append(col)
        # assert len(keys) > 0, f'no primary keys for {table}: {key_info}'
        return keys

    def get_data(self, table: str) -> list[tuple]:
        """Get all row data from a table"""

        query = f"""
            SELECT *
            FROM {table};"""
        return self.read_query_(query)

    def get_length(self, table: str) -> int:
        """Get the length, in terms of number of rows, from a table"""

        query = f"""
            SELECT COUNT(*)
            FROM {table}"""
        result = self.read_query_(query)
        return result[0][0]

    @staticmethod
    def format_columns_params(columns: list[str], sep: str) -> str:
        """Helper method to format columns equaling some future value for a query"""

        return sep.join(f"`{col}` = (%s)" for col in columns)

    def invalid_row_date(self, row: tuple, col_info: list[ColInfo], index: Optional[int] = None) -> bool:
        """Check whether a row contains a date that cannot be handled well in Python"""

        def invalid_helper(i: int) -> bool:
            return Database.is_type_temporal(col_info[i][1]) and row[i] is None

        if index is not None:
            return invalid_helper(index)
        for i in range(len(col_info)):
            if invalid_helper(i):
                return True
        return False

    def format_where_params_helper(self, row: tuple,
                                   col_info: list[ColInfo], key_info: list[KeyInfo],
                                   primary: bool = False) -> tuple[str, tuple]:
        """Helper method to format a query to identify a row"""

        columns = []
        values = []
        for i in range(len(col_info)):
            # don't match Dates of None!
            # could be a fault in Python parsing
            # does not necessarily mean the cell value is null
            # or even that the column accepts null values!
            # TODO could add is_nullable to get_columns_info query, and check against that
            # but this would still not guarantee that it is truly a null value, it could be a failure in parsing
            # https://github.com/PyMySQL/PyMySQL/issues/520
            # could get around this by casting from datetime to varchar on the way out from DB
            # and from varchar to datetime on the way in
            # but this will produce complicated SQL queries
            if self.invalid_row_date(row, col_info, i):
                pass
            columns.append(col_info[i][0])
            values.append(row[i])
        if primary:
            keys = [key for key in self.get_primary_keys(key_info)
                    if key in columns]  # don't use None dates!
            indices = [columns.index(p) for p in keys]
            vals = tuple(values[i] for i in indices)
            if len(keys) > 0:  # don't use primary keys as where if there are none...
                return Database.format_where_params(keys, vals)
        return Database.format_where_params(columns, tuple(values))

    @staticmethod
    def format_where_params(columns: list[str], values: tuple) -> tuple[str, tuple]:
        """Format a query to identify a row where columns are a set of values"""

        assert len(columns) == len(values), f'len({columns}) != len({values})'
        wheres = []
        not_null_vals = []
        for i in range(len(values)):
            # '{columns[i]} = (%s) OR ((%s) IS NULL AND {columns[i]} IS NULL)'
            if values[i] is None:
                wheres.append(f'`{columns[i]}` is NULL')
            else:
                wheres.append(f'`{columns[i]}` = (%s)')
                not_null_vals.append(values[i])
        return " AND ".join(wheres), tuple(not_null_vals)

    def update_row(self, table: str, old: tuple, new: tuple,
                   columns: list[str], col_info: list[ColInfo], key_info: list[KeyInfo],
                   primary: bool = False) -> int:
        """Update a particular row's contents in a table"""

        where_str, not_null_vals = self.format_where_params_helper(old, col_info, key_info, primary)
        # only need to update values that have changed!
        diff_col = []
        diff_val = []
        for i in range(len(columns)):
            if old[i] != new[i]:
                diff_col.append(columns[i])
                diff_val.append(new[i])
        assert len(diff_col) == len(diff_val)
        assert len(diff_col) > 0
        query = f"""
            UPDATE {table}
            SET {Database.format_columns_params(diff_col, ", ")}
            WHERE {where_str};"""
        rows = self.execute_query(query, tuple(diff_val) + not_null_vals)
        # assert rows != 0, f'updated {rows} rows!!!'
        return rows

    def delete_row(self, table: str, row: tuple,
                   col_info: list[ColInfo], key_info: list[KeyInfo],
                   primary: bool = False) -> bool:
        """Delete a particular row in a table"""

        where_str, not_null_vals = self.format_where_params_helper(row, col_info, key_info, primary)
        query = f"""
            DELETE FROM {table}
            WHERE {where_str};"""
        rows = self.execute_query(query, not_null_vals)
        return rows == 1

    def delete_all_rows(self, table: str) -> int:
        """Delete all rows in a table"""

        query = f"DELETE FROM {table}"
        rows = self.execute_query(query)
        return rows

    def insert_row(self, table: str, row: tuple) -> bool:
        """Insert a row into a table"""

        # TODO this won't work well when we don't trust the row data
        # for example, null dates...
        # this will also apply to update_row, or anything that puts data into db
        query = f"""
            INSERT INTO {table}
            VALUES ({", ".join(["%s"] * len(row))});"""
        rows = self.execute_query(query, tuple(row))
        return rows == 1

    def is_row_in_table(self, table: str, row: tuple,
                        col_info: list[ColInfo], key_info: list[KeyInfo],
                        primary: bool = False) -> bool:
        """Check if a row is in a particular table"""

        where_str, not_null_vals = self.format_where_params_helper(row, col_info, key_info, primary)
        query = f"""
            SELECT COUNT(1)
            FROM {table}
            WHERE {where_str};"""
        result = self.read_query_(query, not_null_vals)
        return result[0][0] == 1

    def make_backup(self) -> bytes:
        """Make a string backup of the database"""

        return subprocess.check_output(
            [self.config.mysqldump,
             f"--host={self.config.host}",
             f"--port={self.config.port}",
             f"--user={self.config.user}",
             f"--password={self.config.password}",
             "--protocol=tcp",
             self.config.database])

    def restore_backup(self, backup: bytes) -> subprocess.CompletedProcess:
        """Restore a string backup of the database"""

        self.execute_query(f"DROP DATABASE {self.config.database};")
        self.execute_query(f"CREATE DATABASE {self.config.database};")
        ret = subprocess.run([self.config.mysql,
                              f"--host={self.config.host}",
                              f"--port={self.config.port}",
                              f"--user={self.config.user}",
                              f"--password={self.config.password}",
                              f"--database={self.config.database}",
                              "--protocol=tcp"],
                             stdout=subprocess.PIPE,
                             input=backup)
        self.connection = self.create_server_connection()  # needs a new connection
        return ret

    @staticmethod
    def generate_row(col_info: list[ColInfo], i: int = 0) -> tuple:
        """Generate a row, where values in that row are some increment from a base set of values"""

        row = []
        for _, type, _, values in col_info:
            if Database.is_type_numeric(type):
                row.append(i)
            elif Database.is_type_string(type):
                if type in {'enum', 'set'}:
                    row.append(values[min(len(values) - 1, i)])
                else:
                    row.append(chr(ord('a') + i))
            elif Database.is_type_temporal(type):
                row.append(f'1970-01-01 00:00:0{1 + i}') # warn that i must be small!
            else:
                sys.exit(f'generating row for type {col_info} is not implented!')
        return tuple(row)

    @staticmethod
    def is_type_numeric(t: str) -> bool:
        """Check if a SQL type is numeric"""

        # https://dev.mysql.com/doc/refman/8.0/en/numeric-types.html
        # https://dev.mysql.com/doc/refman/8.0/en/other-vendor-data-types.html
        standard = "integer|int|smallint|decimal|dec|fixed|numeric|float|double precision|bit"
        nonstandard = "tinyint|mediumint|bigint|double|real|bool|boolean|serial|fixed|int1|int2|int3|int4|int8|middleint"
        return re.match(f"^({standard}|{nonstandard})$", t, re.IGNORECASE) is not None

    @staticmethod
    def is_type_temporal(t: str) -> bool:
        """Check if a SQL type is temporal"""

        # https://dev.mysql.com/doc/refman/8.0/en/date-and-time-types.html
        standard = "date|time|datetime|timestamp|year"
        return re.match(f"^({standard})$", t, re.IGNORECASE) is not None

    @staticmethod
    def is_type_string(t: str) -> bool:
        """Check if a SQL type is string-like"""

        # https://dev.mysql.com/doc/refman/8.0/en/string-types.html
        # https://dev.mysql.com/doc/refman/8.0/en/other-vendor-data-types.html
        standard = "char|varchar|binary|varbinary|blob|text|enum|set"
        nonstandard = "tinyblob|tinytext|mediumblob|mediumtext|longblob|longtext|character varying|long varbinary|long varchar|long"
        return re.match(f"^({standard}|{nonstandard})$", t, re.IGNORECASE) is not None

    @staticmethod
    def is_type_spatial(t: str) -> bool:
        """Check if a SQL type is spatial"""

        # https://dev.mysql.com/doc/refman/8.0/en/spatial-types.html
        standard = "geometry|point|linestring|polygon|multipoint|multilinestring|multipolygon|geometrycollection"
        return re.match(f"^({standard})$", t, re.IGNORECASE) is not None

    @staticmethod
    def is_type_json(t: str) -> bool:
        """Check if a SQL type is JSON"""

        # https://dev.mysql.com/doc/refman/8.0/en/json.html
        return re.match("^json$", t, re.IGNORECASE) is not None

    @staticmethod
    def sql_string_type_size(sql_string_type: str, size: Optional[int]) -> Optional[int]:
        "Get a conservative size bound for a SQL string-like type"

        # https://mariadb.com/kb/en/string-data-types/  # using this as it has easier to find sizes than mysql docs
        # only taking the mysql types however
        # standard = "char|varchar|binary|varbinary|blob|text|enum|set"
        # nonstandard = "tinyblob|tinytext|mediumblob|mediumtext|longblob|longtext|character varying|long varbinary|long varchar|long"
        # some disagreements - eg. json is a string type according to mariadb

        # explicit_size = [
        #     'binary',
        #     'varbinary',
        #     'varchar',
        #     'character varying'  # synonym to 'varchar'
        # ]
        implicit_size = {
            'blob' : 65535,  # default value
            'char' : 1,  # default value
            'text' : 65535,  # default value
            'tinyblob' : 255,
            'mediumblob' : 16777215,
            'long varbinary' : 16777215,  # synonym to 'mediumblob'
            'longblob' : 4294967295,
            'tinytext' : 255,
            'mediumtext' : 16777215,
            'long' : 16777215,  # synonym to 'mediumtext'
            'long varchar' : 16777215,  # synonym to 'mediumtext'
            'longtext' : 4294967295,
            'enum' : 0,  # not fuzzable in practice
            'set' : 0  # not fuzzable in practice
        }
        if not Database.is_type_string(sql_string_type) or size is not None:
            return size
        return implicit_size[sql_string_type]

    @staticmethod
    def test() -> None:
        # basic tests of SQL types
        assert Database.is_type_numeric("real")
        assert not Database.is_type_numeric("char")
        assert Database.is_type_temporal("date")
        assert not Database.is_type_temporal("numeric")
        assert Database.is_type_string("tinyblob")
        assert not Database.is_type_string("datetime")
        assert Database.is_type_spatial("geometry")
        assert not Database.is_type_spatial("datetime")


if __name__ == "__main__":
    Database.test()
