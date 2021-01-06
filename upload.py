# Google Photos
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

# Capture photos from webcams
from picamera import PiCamera
import subprocess

from sql_log import JarrariumSQL
from i2c import get_devices
from datetime import datetime, timedelta
from decimal import Decimal
from astral.sun import sun
from astral import LocationInfo

import logging
import pymysql
import json
import os
import argparse
import logging
import time
import pytz
import re


def parse_args(arg_input=None):
    parser = argparse.ArgumentParser(description='Upload photos to Google Photos.')
    parser.add_argument('--auth ', metavar='auth_file', dest='auth_file',
                    help='file for reading/storing user authentication tokens')
    parser.add_argument('--album', metavar='album_name', dest='album_name',
                    help='name of photo album to create (if it doesn\'t exist). Any uploaded photos will be added to this album.')
    parser.add_argument('--log', metavar='log_file', dest='log_file',
                    help='name of output file for log messages')
    parser.add_argument('photos', metavar='photo',type=str, nargs='*',
                    help='filename of a photo to upload')
    return parser.parse_args(arg_input)


def auth(scopes):
    flow = InstalledAppFlow.from_client_secrets_file(
        'client_id.json',
        scopes=scopes)

    credentials = flow.run_local_server(host='localhost',
                                        port=8080,
                                        authorization_prompt_message="",
                                        success_message='The auth flow is complete; you may close this window.',
                                        open_browser=True)

    return credentials

def get_authorized_session(auth_token_file):

    scopes=['https://www.googleapis.com/auth/photoslibrary',
            'https://www.googleapis.com/auth/photoslibrary.sharing']

    cred = None

    if auth_token_file:
        try:
            cred = Credentials.from_authorized_user_file(auth_token_file, scopes)
        except OSError as err:
            logging.debug("Error opening auth token file - {0}".format(err))
        except ValueError:
            logging.debug("Error loading auth tokens - Incorrect format")


    if not cred:
        cred = auth(scopes)

    session = AuthorizedSession(cred)

    if auth_token_file:
        try:
            save_cred(cred, auth_token_file)
        except OSError as err:
            logging.debug("Could not save auth tokens - {0}".format(err))

    return session


def save_cred(cred, auth_file):

    cred_dict = {
        'token': cred.token,
        'refresh_token': cred.refresh_token,
        'id_token': cred.id_token,
        'scopes': cred.scopes,
        'token_uri': cred.token_uri,
        'client_id': cred.client_id,
        'client_secret': cred.client_secret
    }

    with open(auth_file, 'w') as f:
        print(json.dumps(cred_dict), file=f)

# Generator to loop through all albums

def getAlbums(session, appCreatedOnly=False):

    params = {
            'excludeNonAppCreatedData': appCreatedOnly
    }

    while True:

        albums = session.get('https://photoslibrary.googleapis.com/v1/albums', params=params).json()

        logging.debug("Server response: {}".format(albums))

        if 'albums' in albums:

            for a in albums["albums"]:
                yield a

            if 'nextPageToken' in albums:
                params["pageToken"] = albums["nextPageToken"]
            else:
                return

        else:
            return

def create_or_retrieve_album(session, album_title):

# Find albums created by this app to see if one matches album_title

    for a in getAlbums(session, True):
        if a["title"].lower() == album_title.lower():
            album_id = a["id"]
            logging.info("Uploading into EXISTING photo album -- \'{0}\'".format(album_title))
            return album_id

# No matches, create new album

    create_album_body = json.dumps({"album":{"title": album_title}})
    #print(create_album_body)
    resp = session.post('https://photoslibrary.googleapis.com/v1/albums', create_album_body).json()

    logging.debug("Server response: {}".format(resp))

    if "id" in resp:
        logging.info("Uploading into NEW photo album -- \'{0}\'".format(album_title))
        return resp['id']
    else:
        logging.error("Could not find or create photo album '\{0}\'. Server Response: {1}".format(album_title, resp))
        return None

def upload_photos(session, photo_file_name, album_name):

    album_id = create_or_retrieve_album(session, album_name) if album_name else None

    # interrupt upload if an upload was requested but could not be created
    if album_name and not album_id:
        return

    session.headers["Content-type"] = "application/octet-stream"
    session.headers["X-Goog-Upload-Protocol"] = "raw"

    try:
        photo_file = open(photo_file_name, mode='rb')
        photo_bytes = photo_file.read()
    except OSError as err:
        logging.error("Could not read file \'{0}\' -- {1}".format(photo_file_name, err))
        return

    session.headers["X-Goog-Upload-File-Name"] = os.path.basename(photo_file_name)

    logging.info("Uploading photo -- \'{}\'".format(photo_file_name))

    upload_token = session.post('https://photoslibrary.googleapis.com/v1/uploads', photo_bytes)

    if (upload_token.status_code == 200) and (upload_token.content):

        create_body = json.dumps({"albumId":album_id, "newMediaItems":[{"description":"","simpleMediaItem":{"uploadToken":upload_token.content.decode()}}]}, indent=4)

        resp = session.post('https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate', create_body).json()

        logging.debug("Server response: {}".format(resp))

        if "newMediaItemResults" in resp:
            status = resp["newMediaItemResults"][0]["status"]
            if status.get("code") and (status.get("code") > 0):
                logging.error("Could not add \'{0}\' to library -- {1}".format(os.path.basename(photo_file_name), status["message"]))
            else:
                logging.info("Added \'{}\' to library and album \'{}\' ".format(os.path.basename(photo_file_name), album_name))
        else:
            logging.error("Could not add \'{0}\' to library. Server Response -- {1}".format(os.path.basename(photo_file_name), resp))

    else:
        logging.error("Could not upload \'{0}\'. Server Response - {1}".format(os.path.basename(photo_file_name), upload_token))

    try:
        del(session.headers["Content-type"])
        del(session.headers["X-Goog-Upload-Protocol"])
        del(session.headers["X-Goog-Upload-File-Name"])
    except KeyError:
        pass

def time_until_daylight(dt_sunrise, dt_sunset, loc):
    present = datetime.now(pytz.timezone(loc.timezone))
    
    # currently bewteen sunrise and sunset, it's already daylight
    if dt_sunrise <= present <= dt_sunset:
        return 0
    
    # if there hasn't been a sunrise for the day yet, wait for it
    elif present < dt_sunrise:
        return (dt_sunrise - present).total_seconds()
    
    # if the day is past sunset, wait for tommorow's sunrise
    elif present > dt_sunset:
        tommorrow = datetime.today() + timedelta(days=1)
        tmrw_times = sun(loc.observer, tommorrow, tzinfo=loc.timezone)
        return (tmrw_times["sunrise"] - present).total_seconds()
    
    raise Exception("No possible criteria for time until daylight was met.")


def upload_all_photos(directory, session, album_name):
    for entry in os.scandir(directory):
        if entry.path.endswith(".jpg"):
            try:
                upload_photos(session, entry.path, album_name)
            except BaseException as e:
                logging.error(f'Failed to upload {entry.path} to Google Photos, error: {e}')
            finally:
                os.remove(entry.path)        

def main():

    logging.basicConfig(format='%(asctime)s - %(message)s', filename='app.log')

    # create a session with Google Photos
    args = parse_args() # --auth client_id.json --album test
    session = get_authorized_session(args.auth_file)

    # initialize ribbon camera
    camera = PiCamera()
    camera.resolution = (3280, 2464)

    # get current location
    with open('location.json') as loc_file:
        data = json.load(loc_file)
        loc = LocationInfo()
        loc.timezone = data['general']['timezone']
        loc.latitude = data['coordinates']['latitude'] 
        loc.longitude = data['coordinates']['longitude']
        
    # get sunrise and sunset times    
    times = sun(loc.observer, date=datetime.now(), tzinfo=loc.timezone)
    
    # determine time until next daylight, sleep until then
    sleep_time = time_until_daylight(times["sunrise"], times["sunset"], loc)
    if sleep_time != 0:
        time.sleep(sleep_time)
    
    sql_store = JarrariumSQL()
    sql_store.connect_to_db()
    
    usb_webcam_device_finder = re.compile(r'HD Webcam C525 \(\S+\):\n\t(\/dev\/video\d{1,2})')
    ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
    
    while True:
        present_dt = datetime.now()
        
        # get readings from sensors
        parsed_sensor_readings = dict()
        device_list = get_devices()
        for device in device_list:
            
            # empty reading
            device_reading = device.query('R') # ask atlas team diff between this and doing it manually?
            if not device_reading:
                logging.error(f'Tyring to read from {device} yielded an empty result\n\n')
                continue
            
            device_reading = device_reading.replace("\x00", "")  # remove empty bytes
            
            # parse the successful reading
            if device_reading.startswith('Success'):
                matches = re.match(r'(Success) (DO 97|pH 99|RTD 102) : (\d+\.?\d*)$', device_reading)
                if matches:
                    sensor_type = matches.group(2)
                    sensor_val =  matches.group(3)
                    if sensor_type == 'RTD 102':
                        sensor_val = str((Decimal(sensor_val) * Decimal(9)/Decimal(5)) + 32) # convert celcius to farenheit
                    parsed_sensor_readings[sensor_type] = sensor_val
                else:
                    logging.error(f'One of the sensors had a reading that did not match the regex. Reading was: {device_reading} \n\n')
    
            # faulty reading
            elif device_reading.startswith('Error'):
                logging.error(f'An error occured!: {device_reading}\n\n')
            else:
                logging.error(f'Sensor reading returned something unexpected: {device_reading}\n\n')
        
        # paths for each jpg file
        camera_time_format = present_dt.strftime("%Y-%m-%d %H_%M_%S") # no colons, since files on Windows can't handle that
        
        usb_cam_file = f"USB-Cam {camera_time_format}.jpg"
        usb_cam_photo_path = f'./cam-photos/usb/{usb_cam_file}'
        
        ribbon_cam_file = f"Ribbon-Cam {camera_time_format}.jpg"
        ribbon_cam_photo_path = f'./cam-photos/ribbon/{ribbon_cam_file}'
        
        # capture photo from usb cam
        
        # find out what device the usb cam is listed as
        webcam_devices_proc = subprocess.run(['v4l2-ctl', '--list-devices'], text=True, capture_output=True)
        if webcam_devices_proc.returncode == 0:
            matches = re.search(r'HD Webcam C525 \(\S+\):\n\t(\/dev\/video\d{1,2})', webcam_devices_proc.stdout)
            if matches:
                device = matches.group(1)
                # discard first 20 images, since it takes a while for the webcam to adjust to brightness
                completed_process = subprocess.run(["fswebcam", "-d",f"{device}", "-r", "1920x1080", "-S", "20", "--no-banner", usb_cam_photo_path], text=True, capture_output=True)
                if completed_process.returncode != 0:
                    usbcam_error = ansi_escape.sub('', completed_process.stderr) + '\n\n' 
                    logging.error(f'Could not capture image from usb webcam, error: {usbcam_error} \n\n')
                if not os.path.exists(usb_cam_photo_path):
                    logging.error(f'Photo at {usb_cam_photo_path} was not found.\n\n')
                    usb_cam_file = None
                    usb_cam_photo_path = None
            else:
                logging.error(f'The regex could not find the device code for the webcam in the v4l2-ctl --list-devices output. \nOutput: {output}\n\n')            
        else:
            error = ansi_escape.sub('', webcam_devices_proc.stderr) + '\n\n'
            logging.error(f'Could not run the v4l2-ctrl --list devices command, error: {error}' )
    
        
        # capture photo from ribbon cam
        try:
            camera.capture(ribbon_cam_photo_path)
        except BaseException as e:
             logging.exception("Something went wrong while trying to capture the photo from the ribbon camera.")
        if not os.path.exists(ribbon_cam_photo_path):
            logging.error(f'Photo at {ribbon_cam_photo_path} was not found.\n\n')
            ribbon_cam_file = None
            ribbon_cam_photo_path = None
        
        # send the jpgs to google photos and then delete them off local storage
        upload_all_photos('./cam-photos/ribbon/', session, args.album_name)
        upload_all_photos('./cam-photos/usb/', session, args.album_name)

        # log recorded sensor readings and names of the photos 
        sql_store.insert_input(present_dt,#present_dt.strftime("%Y-%m-%d %H:%M:%S"),
                       parsed_sensor_readings.get('pH 99', None),
                       parsed_sensor_readings.get('DO 97', None),
                       parsed_sensor_readings.get('RTD 102', None),
                       ribbon_cam_file,
                       usb_cam_file)
        
        # TODO: BACKLOG ALL SENSOR READING AND ERROR MESSAGES NOT PUT INTO SQL
        
        # log any errors encountered during execution of this cycle into the database
        if os.path.isfile('./app.log') and os.path.getsize('./app.log') > 0:
            with open("./app.log", 'r') as f:
                error_message = f.read()
                sql_store.insert_error(present_dt.strftime("%Y-%m-%d %H:%M:%S"), error_message)
        
        # regular sleep interval is 5 minutes, otherwise sleep until next sunrise
        sleep_time = time_until_daylight(times["sunrise"], times["sunset"], loc)
        if sleep_time == 0:
            time.sleep(30)
        else:
            time.sleep(sleep_time)

        # clear out the log
        with open("./app.log", 'w') as f:
            pass        
        

if __name__ == '__main__':
  main()
