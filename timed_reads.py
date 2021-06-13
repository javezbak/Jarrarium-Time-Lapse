import json
import logging
import os
import time
from datetime import datetime, timedelta

import pytz
from astral import LocationInfo
from astral.sun import sun

from db_log import DBLog
from gphoto import GPhoto
from webcam import Webcam


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
        time.sleep(120)  # if you lower this value and there is a critical error in your code your pi could get stuck in an infinite reboot loop!
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

            # capture photos from both webcams
            resources.wb.time = present_dt.strftime("%Y-%m-%d %H_%M_%S")
            resources.wb.capture_usb_photo()
            resources.wb.capture_ribbon_photo()

            # send the jpgs to google photos and then delete them off local storage
            resources.gphotos.upload_all_photos_in_dir(resources.wb.base_dir_ribbon, "ribbon")
            resources.gphotos.upload_all_photos_in_dir(resources.wb.base_dir_usb, "usb")

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
