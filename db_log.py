import json
import logging
import csv
import pymysql


class DBLog:
    def __init__(self):
        self.conn = None
        self.local_sensor_data = {}
        self.local_errors = {}

    def connect_to_db(self):
        if self.conn is not None and self.conn.open:
            self.conn.close()
        with open("connection_info.json") as conn_file:
            data = json.load(conn_file)["connection"]
            try:
                self.conn = pymysql.connect(
                    host=data["host"],
                    user=data["user"],
                    password=data["password"],
                    db=data["db"],
                    charset="utf8mb4",
                    connect_timeout=60,
                    read_timeout=10,
                    write_timeout=10,
                    autocommit=True,
                    cursorclass=pymysql.cursors.DictCursor,
                )
            except BaseException as e:
                logging.exception("Could not create a connection to the database \n\n")

    def insert_input(self, dt, pH, diss_oxy, temp, ribbon_photo, usb_photo):
        insert_statement = f"""INSERT INTO RecordedInput (datetime_recorded,
                          pH,
                          dissolved_oxygen,
                          temperature_F,
                          ribbon_photo_file_name,
                          usb_photo_file_name) VALUES
                          (%s, %s, %s, %s, %s, %s)"""
        try:
            with self.conn.cursor() as cursor:
                num_rows_affected = cursor.execute(
                    insert_statement, (dt, pH, diss_oxy, temp, ribbon_photo, usb_photo)
                )
                if num_rows_affected != 1:
                    logging.exception(
                        self.create_insert_input_error_message(
                            dt,
                            pH,
                            diss_oxy,
                            temp,
                            ribbon_photo,
                            usb_photo,
                            f"Number of rows affected after insertion was {num_rows_affected}",
                        )
                    )
        except pymysql.err.InterfaceError as e:
            logging.error(
                self.create_insert_input_error_message(
                    dt,
                    pH,
                    diss_oxy,
                    temp,
                    ribbon_photo,
                    usb_photo,
                    "Could not connect to the database when trying to insert sensor data",
                )
            )
            self.local_sensor_data[dt] = (pH, diss_oxy, temp, ribbon_photo, usb_photo)
            self.connect_to_db()
        except BaseException as e:
            logging.exception(
                self.create_insert_input_error_message(
                    dt, pH, diss_oxy, temp, ribbon_photo, usb_photo
                )
            )
            self.local_sensor_data[dt] = (pH, diss_oxy, temp, ribbon_photo, usb_photo)

    def create_insert_input_error_message(
        self, dt, pH, diss_oxy, temp, ribbon_photo, usb_photo, error_msg
    ):
        base_error = f"""Insertion into RecordedInput failed with the following values:
                                datetime_recorded={dt},
                                pH={pH},
                                dissolved_oxyen={diss_oxy},
                                temperature_F={temp},
                                ribbon_photo_file_name={ribbon_photo},
                                usb_photo_file_name={usb_photo} \n\n """
        if error_msg:
            return f"{base_error}{error_msg}\n\n"
        return base_error

    def insert_error(self, dt, error):
        insert_statement = f"""INSERT INTO RecordedErrors(datetime_recorded,error_message) VALUES (%s, %s)"""
        try:
            with self.conn.cursor() as cursor:
                sql = insert_statement
                num_rows_affected = cursor.execute(sql, (dt, error[:16777214]))
                if num_rows_affected != 1:
                    self.local_errors[dt] = self.create_insert_error_message(
                        dt,
                        error,
                        f"Number of rows affected after insertion was {num_rows_affected}",
                    )
        except pymysql.err.InterfaceError as e:
            self.local_errors[dt] = self.create_insert_error_message(
                dt,
                error,
                "Could not connect to the database when trying to insert error data",
            )
            self.connect_to_db()
        except BaseException as e:
            self.local_errors[dt] = self.create_insert_error_message(dt, error)

    def create_insert_error_message(self, dt, error, error_msg=None):
        base_error = f"""Insertion into RecordedErrors failed with the following values:
                                datetime_recorded={dt},
                                error_message={error}\n\n
                                """
        if error_msg:
            return f"{base_error}\n\n{error_msg}\n\n"
        return base_error
