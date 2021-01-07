import json
import logging

import pymysql


class DBLog:
    def __init__(self):
        self.conn = None

    def connect_to_db(self):
        if self.conn is not None:
            self.conn.close()
        with open("connection_info.json") as conn_file:
            data = json.load(conn_file)["connection"]
            self.conn = pymysql.connect(
                host=data["host"],
                user=data["user"],
                password=data["password"],
                db=data["db"],
                charset="utf8mb4",
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )

    def insert_input(self, dt, pH, diss_oxy, temp, ribbon_photo, usb_photo):
        insert_statement = f"""INSERT INTO RecordedInput (datetime_recorded,
                          pH,
                          dissolved_oxygen,
                          temperature_F,
                          ribbon_photo_file_name,
                          usb_photo_file_name) VALUES
                          (%s, %s, %s, %s, %s, %s)"""
        try:
            cursor = self.conn.cursor()
            num_rows_affected = cursor.execute(
                insert_statement, (dt, pH, diss_oxy, temp, ribbon_photo, usb_photo)
            )
            self.conn.commit()
        except BaseException as e:
            logging.exception(
                f"""Insertion into RecordedInput failed with the following values:
                                datetime_recorded={dt},
                                pH={pH},
                                dissolved_oxyen={diss_oxy},
                                temperature_F={temp},
                                ribbon_photo_file_name={ribbon_photo},
                                usb_photo_file_name={usb_photo}
                                
                                \n\n Error: {e}"""
            )
        finally:
            cursor.close()
        return ""

    def insert_error(self, dt, error):
        insert_statement = f"""INSERT INTO RecordedErrors(datetime_recorded,error_message) VALUES (%s, %s)"""
        try:
            with self.conn.cursor() as cursor:
                sql = insert_statement
                cursor.execute(sql, (dt, error))
        except Exception as e:
            logging.exception(
                f"""Insertion into RecordedError failed with the following query: {insert_statement}\n\n Error: {e}"""
            )
        finally:
            cursor.close()
