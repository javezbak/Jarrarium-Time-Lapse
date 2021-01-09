import logging
import os
import re
import subprocess

from picamera import PiCamera


class Webcam:
    def __init__(self, time):
        self.usb_cam_file = None
        self.usb_cam_photo_path = None
        self.ribbon_cam_file = None
        self.ribbon_cam_photo_path = None

        self.base_dir_ribbon = "./cam-photos/ribbon/"
        self.base_dir_usb = "./cam-photos/usb/"

        self.time = time

        self.ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

        # initialize ribbon camera
        self._camera = PiCamera()
        self._camera.resolution = (3280, 2464)

    @property
    def time(self):
        return self._time

    @time.setter
    def time(self, time_str):
        self._time = time_str

        self.usb_cam_file = f"USB-Cam {time_str}.jpg"
        self.usb_cam_photo_path = f"{self.base_dir_usb}{self.usb_cam_file}"

        self.ribbon_cam_file = f"Ribbon-Cam {time_str}.jpg"
        self.ribbon_cam_photo_path = f"{self.base_dir_ribbon}{self.ribbon_cam_file}"

    def clear_usb(self):
        self.usb_cam_file = None
        self.usb_cam_photo_path = None

    def clear_ribbon(self):
        self.ribbon_cam_file = None
        self.ribbon_cam_photo_path = None

    def capture_usb_photo(self):
        webcam_devices_proc = subprocess.run(
            ["v4l2-ctl", "--list-devices"], text=True, capture_output=True
        )
        if webcam_devices_proc.returncode == 0:
            matches = re.search(
                r"HD Webcam C525 \(\S+\):\n\t(\/dev\/video\d{1,2})",
                webcam_devices_proc.stdout,
            )
            if matches:
                device = matches.group(1)
                completed_process = subprocess.run(
                    [
                        "fswebcam",
                        "-d",
                        f"{device}",
                        "-r",
                        "1920x1080",
                        "-S",
                        "20",  # discard first 20 images, camera needs time to adjust to brightness
                        "--no-banner",
                        self.usb_cam_photo_path,
                    ],
                    text=True,
                    capture_output=True,
                )
                if completed_process.returncode != 0:
                    usbcam_error = (
                        self.ansi_escape.sub("", completed_process.stderr) + "\n\n"
                    )
                    logging.error(
                        f"Could not capture image from usb webcam, error: {usbcam_error} \n\n"
                    )
                    self.clear_usb()
                if not os.path.exists(self.usb_cam_photo_path):
                    logging.error(
                        f"Photo at {self.usb_cam_photo_path} was not found.\n\n"
                    )
                    self.clear_usb()
            else:
                logging.error(
                    f"The regex could not find the device code for the webcam in the v4l2-ctl --list-devices output. \nOutput: {webcam_devices_proc.stdout}\n\n"
                )
                self.clear_usb()
        else:
            error = self.ansi_escape.sub("", webcam_devices_proc.stderr) + "\n\n"
            logging.error(
                f"Could not run the v4l2-ctrl --list devices command, error: {error}"
            )
            self.clear_usb()

    def capture_ribbon_photo(self):
        try:
            self._camera.capture(self.ribbon_cam_photo_path)
        except BaseException as e:
            logging.exception(
                "Something went wrong while trying to capture the photo from the ribbon camera."
            )
            self.clear_ribbon()
        if not os.path.exists(self.ribbon_cam_photo_path):
            logging.error(f"Photo at {self.ribbon_cam_photo_path} was not found.\n\n")
            self.clear_ribbon()
