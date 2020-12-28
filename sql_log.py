import pymysql
import json


class JarrariumSQL:
    
    def __init__(self):
        self.conn = None

    def connect_to_db(self):
        if self.conn is not None:
            self.conn.close()
        with open('connection_info.json') as conn_file:
            data = json.load(conn_file)['connection']
            self.conn = pymysql.connect(host=data['host'],
                                     user=data['user'],
                                     password=data['password'],
                                     db=data['db'],
                                     charset='utf8mb4',
                                     autocommit=True,
                                     cursorclass=pymysql.cursors.DictCursor)

    def insert_input(self, dt, pH, diss_oxy, temp, ribbon_photo, usb_photo):
        insert_statement = f"""INSERT INTO RecordedInput(`datetime_recorded`,
                          `pH`,
                          `dissolved_oxygen`,
                          `temperature_F`,
                          `ribbon_photo_file_name`,
                          `usb_photo_file_name`) VALUES
                          ('{dt}',
                           {pH},
                           {diss_oxy},
                           {temp},
                           '{ribbon_photo}',
                           '{usb_photo}')"""
        print(insert_statement)
        try:
            try:
                with self.conn.cursor() as cursor:
                    sql = insert_statement
                    cursor.execute(sql)
            finally:
                cursor.close()
        except BaseException as e:
            msg = f"""Insertion into RecordedInput failed with the following query: {insert_statement}\n\n Error: {e}"""
            self.insert_error(dt, msg)
        
    def insert_error(self, dt, error):
        insert_statement = f"""INSERT INTO RecordedErrors(datetime_recorded,
                                                            error_message)
                                                            VALUES ({dt}, {error})"""
        try:
            try:
                with self.conn.cursor() as cursor:
                    sql = insert_statement
                    cursor.execute(sql)
            finally:
                cursor.close()
        except Exception as e:
            msg = f"""Insertion into RecordedError failed with the following query: {insert_statement}\n\n Error: {e}"""
            insert_error(dt, msg)
    
