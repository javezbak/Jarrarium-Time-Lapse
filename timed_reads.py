import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from astral import LocationInfo
from astral.sun import sun

from db_log import DBLog
from gphoto import GPhoto
from i2c import get_devices
from webcam import Webcam


def read_sensor_data(device, cmd):
    device_reading = device.query(cmd)
    if not device_reading:
        logging.error(f"Tyring to read from {device} yielded an empty result\n\n")
        return None

    device_reading = device_reading.replace("\x00", "")  # remove empty bytes

    # parse the successful reading
    if device_reading.startswith("Success"):
        matches = re.match(
            r"(Success) (pH 99|RTD 102) : (\d+\.?\d*)$", device_reading
        )
        if matches:
            return matches
        else:
            logging.error(
                f"One of the sensors had a reading that did not match the regex. Reading was: {device_reading} \n\n"
            )

    # faulty reading
    elif device_reading.startswith("Error"):
        logging.error(f"An error occured!: {device_reading}\n\n")
    else:
        logging.error(
            f"Sensor reading returned something unexpected: {device_reading}\n\n"
        )

    return None


def get_sensor_data():
    parsed_sensor_readings = dict()
    device_list = get_devices()
    
    # get temperature
    for device in device_list:
        if device.address == 102:
            output = read_sensor_data(device, 'R')
            if output is not None:
                celcius_temp = output.group(3)
                sensor_type = output.group(2)
                sensor_val = str(
                        (Decimal(output.group(3)) * Decimal(9) / Decimal(5)) + 32
                    )  # convert celcius to farenheit
                parsed_sensor_readings[sensor_type] = sensor_val
            else:
                raise ValueError('Could not get a reading from the temperature sensor!')
            
    # get pH with temperature comepnsation        
    for device in device_list:
        if device.address != 102 and device.address != 97:
            if output is not None:                
                output = read_sensor_data(device, f'RT,{celcius_temp}')
                sensor_type = output.group(2)
                sensor_val = output.group(3)
                parsed_sensor_readings[sensor_type] = sensor_val
            else:
                raise ValueError(f'Something went wrong when trying to read from device {device.address}')

    return parsed_sensor_readings


def time_until_daylight(dt_sunrise, dt_sunset, loc):
    present = datetime.now(pytz.timezone(loc.timezone))

    # currently between sunrise and sunset, it's already daylight
    if dt_sunrise <= present <= dt_sunset:
        return 0

    # if there hasn't been a sunrise for the day yet, wait for it
    elif present < dt_sunrise:
        return (dt_sunrise - present).total_seconds()

    # if the day is past sunset, wait for tomorrow's sunrise
    elif present > dt_sunset:
        tommorrow = datetime.today() + timedelta(days=1)
        tmrw_times = sun(loc.observer, tommorrow, tzinfo=loc.timezone)
        return (tmrw_times["sunrise"] - present).total_seconds()

    raise Exception("No possible criteria for time until daylight was met.")


class Resources:
    
    def __init__(self):
        self.gphotos = GPhoto()
        self.sql_store = DBLog()
        self.sql_store.connect_to_db()
        self.wb = Webcam('')
        
    def release(self):
        self.sql_store.conn.close()
        self.wb._camera.close()
        self.gphotos._session.close()
        

def main():

    try:
        # need time to get internet connection once pi starts up
        time.sleep(120) # if you lower this value and there is a critical error in your code your pi could get stuck in an infinite reboot loop!
        dir_path = os.path.dirname(os.path.realpath(__file__))
        
        logging.basicConfig(filename=os.path.join(dir_path, "app.log"))

        # get current location
        with open(os.path.join(dir_path, 'location.json')) as loc_file:
            data = json.load(loc_file)
            loc = LocationInfo()
            loc.timezone = data["general"]["timezone"]
            loc.latitude = data["coordinates"]["latitude"]
            loc.longitude = data["coordinates"]["longitude"]

        # get sunrise and sunset times
        times = sun(loc.observer, date=datetime.now(), tzinfo=loc.timezone)

        # determine time until next daylight, sleep until then
        sleep_time = time_until_daylight(times["sunrise"], times["sunset"], loc)
        if sleep_time != 0:
            time.sleep(sleep_time)
            
        resources = Resources()        

        while True:
            
            present_dt = datetime.now()

            # pull pH and temperature data
            parsed_sensor_readings = get_sensor_data()

            # capture photos from both webcams
            resources.wb.time = present_dt.strftime("%Y-%m-%d %H_%M_%S")
            resources.wb.capture_usb_photo()
            resources.wb.capture_ribbon_photo()

            # send the jpgs to google photos and then delete them off local storage
            resources.gphotos.upload_all_photos_in_dir(resources.wb.base_dir_ribbon, "ribbon")
            resources.gphotos.upload_all_photos_in_dir(resources.wb.base_dir_usb, "usb")

            # log any old locally stored sensor data
            if resources.sql_store.local_sensor_data:
                for dt in list(resources.sql_store.local_sensor_data): 
                    size_of_error_log = os.path.getsize("./app.log")
                    sensor_data = resources.sql_store.local_sensor_data[dt]
                    sql_store.insert_input(
                                        dt,
                                        sensor_data[0],
                                        sensor_data[1],
                                        sensor_data[2],
                                        sensor_data[3]
                                    )
                    updated_size_of_error_log = os.path.getsize("./app.log")
                    if size_of_error_log == updated_size_of_error_log:
                        del resources.sql_store.local_sensor_data[dt] 

            # log recorded sensor readings and names of the photos
            resources.sql_store.insert_input(
                present_dt,
                parsed_sensor_readings.get("pH 99", None),
                parsed_sensor_readings.get("RTD 102", None),
                resources.wb.ribbon_cam_file,
                resources.wb.usb_cam_file,
            )      

            # log any errors encountered during execution of this cycle into the database
            if os.path.getsize("./app.log") > 0:
                with open("./app.log", "r") as f:
                    error_message = f.read()
                    resources.sql_store.insert_error(
                        present_dt.strftime("%Y-%m-%d %H:%M:%S"), error_message
                    )

            # clear out the log
            with open("./app.log", "w") as f:
                pass

            # regular sleep interval is 5 minutes, otherwise sleep until next sunrise
            sleep_time = time_until_daylight(times["sunrise"], times["sunset"], loc)
            if sleep_time == 0:
                time.sleep(300)
            else:
                resources.release()
                time.sleep(sleep_time)
                resources = Resources()
                times = sun(loc.observer, date=datetime.now(), tzinfo=loc.timezone)
                
            
    except BaseException as e:
        logging.exception('Something went wrong in the __main__ script. Restarting the pi.\n')
        os.system('sudo reboot')


if __name__ == "__main__":
    main()
