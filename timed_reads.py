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


def get_sensor_data():
    parsed_sensor_readings = dict()
    device_list = get_devices()
    for device in device_list:

        # empty reading
        device_reading = device.query(
            "R"
        )  # ask atlas team diff between this and doing it manually?
        if not device_reading:
            logging.error(f"Tyring to read from {device} yielded an empty result\n\n")
            continue

        device_reading = device_reading.replace("\x00", "")  # remove empty bytes

        # parse the successful reading
        if device_reading.startswith("Success"):
            matches = re.match(
                r"(Success) (DO 97|pH 99|RTD 102) : (\d+\.?\d*)$", device_reading
            )
            if matches:
                sensor_type = matches.group(2)
                sensor_val = matches.group(3)
                if sensor_type == "RTD 102":
                    sensor_val = str(
                        (Decimal(sensor_val) * Decimal(9) / Decimal(5)) + 32
                    )  # convert celcius to farenheit
                parsed_sensor_readings[sensor_type] = sensor_val
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


def main():

    logging.basicConfig(format="%(asctime)s - %(message)s", filename="app.log")

    # establish connection with Google Photos
    gphotos = GPhoto("--auth client_id.json --album test")

    # get current location
    with open("location.json") as loc_file:
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

    sql_store = DBLog()
    sql_store.connect_to_db()

    while True:
        present_dt = datetime.now()

        # pull pH, dO, and temperature data
        parsed_sensor_readings = get_sensor_data()

        # capture photos from both webcams
        camera_time_formatted = present_dt.strftime("%Y-%m-%d %H_%M_%S")
        wb = Webcam(camera_time_formatted)
        wb.capture_usb_photo()
        wb.capture_ribbon_photo()

        # send the jpgs to google photos and then delete them off local storage
        gphotos.upload_all_photos_in_dir(wb.base_dir_ribbon, "test")
        gphotos.upload_all_photos_in_dir(wb.base_dir_usb, "test")

        # log recorded sensor readings and names of the photos
        sql_store.insert_input(
            present_dt,
            parsed_sensor_readings.get("pH 99", None),
            parsed_sensor_readings.get("DO 97", None),
            parsed_sensor_readings.get("RTD 102", None),
            wb.ribbon_cam_file,
            wb.usb_cam_file,
        )

        # TODO: BACKLOG ALL SENSOR READING AND ERROR MESSAGES NOT PUT INTO SQL

        # log any errors encountered during execution of this cycle into the database
        if os.path.isfile("./app.log") and os.path.getsize("./app.log") > 0:
            with open("./app.log", "r") as f:
                error_message = f.read()
                sql_store.insert_error(
                    present_dt.strftime("%Y-%m-%d %H:%M:%S"), error_message
                )

        # regular sleep interval is 5 minutes, otherwise sleep until next sunrise
        sleep_time = time_until_daylight(times["sunrise"], times["sunset"], loc)
        if sleep_time == 0:
            time.sleep(30)
        else:
            time.sleep(sleep_time)

        # clear out the log
        with open("./app.log", "w") as f:
            pass


if __name__ == "__main__":
    main()
