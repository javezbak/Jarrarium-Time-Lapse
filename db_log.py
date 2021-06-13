import os
import json
import logging
import pymysql


class DBLog:
    def __init__(self):
        self.conn = None
        self.local_sensor_data = {}

    def connect_to_db(self):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        if self.conn is not None and self.conn.open:
            self.conn.close()
        with open(os.path.join(dir_path, 'connection_info.json')) as conn_file:
            data = json.load(conn_file)["connection"]
            try:
                self.conn = pymysql.connect(
                    host=data["host"],
                    user=data["user"],
                    password=data["password"],
                    db=data["db"],
                    charset="utf8mb4",
                    connect_timeout=60,
                    read_timeout=30,
                    write_timeout=30,
                    autocommit=True,
                    cursorclass=pymysql.cursors.DictCursor,
                )
            except BaseException as e:
                logging.exception("Could not create a connection to the database in connect_to_db() function \n\n")
                logging.debug('Failed to connect to DB')

    def insert_error(self, dt, error):
        insert_statement = f"""INSERT INTO RecordedErrors(datetime_recorded,error_message) VALUES (%s, %s)"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(insert_statement, (dt, error[:16777214]))
        except BaseException as e:
            logging.debug('Failed to insert the error into recordedErrors table')
