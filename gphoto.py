import argparse
import json
import logging
import os

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


class GPhoto:
    def __init__(self):
        self.dir_path = os.path.dirname(os.path.realpath(__file__))
        self._session = self._get_authorized_session(os.path.join(self.dir_path, 'client_id.json'))

    def auth(self, scopes):
        flow = InstalledAppFlow.from_client_secrets_file(
            os.path.join(self.dir_path, "client_id.json"), scopes=scopes
        )

        credentials = flow.run_local_server(
            host="localhost",
            port=8080,
            authorization_prompt_message="",
            success_message="The auth flow is complete; you may close this window.",
            open_browser=True,
        )

        return credentials

    def _get_authorized_session(self, auth_token_file):
        scopes = [
            "https://www.googleapis.com/auth/photoslibrary",
            "https://www.googleapis.com/auth/photoslibrary.sharing",
        ]

        cred = None

        if auth_token_file:
            try:
                cred = Credentials.from_authorized_user_file(auth_token_file, scopes)
            except OSError:
                logging.exception(f"Error opening auth token file\n")
            except ValueError:
                logging.exception("Error loading auth tokens - Incorrect format\n")

        if not cred:
            cred = self.auth(scopes)

        session = AuthorizedSession(cred)

        if auth_token_file:
            try:
                self.save_cred(cred, auth_token_file)
            except OSError as err:
                logging.error(f"Could not save auth tokens - {err}")

        return session

    def save_cred(self, cred, auth_file):

        cred_dict = {
            "token": cred.token,
            "refresh_token": cred.refresh_token,
            "id_token": cred.id_token,
            "scopes": cred.scopes,
            "token_uri": cred.token_uri,
            "client_id": cred.client_id,
            "client_secret": cred.client_secret,
        }

        with open(auth_file, "w") as f:
            print(json.dumps(cred_dict), file=f)

    def get_albums(self, app_created_only=False):
        params = {"excludeNonAppCreatedData": app_created_only}
        while True:
            albums = self._session.get(
                "https://photoslibrary.googleapis.com/v1/albums", params=params
            ).json()

            logging.debug("Server response: {}".format(albums))

            if "albums" in albums:
                for a in albums["albums"]:
                    yield a
                if "nextPageToken" in albums:
                    params["pageToken"] = albums["nextPageToken"]
                else:
                    return
            else:
                return

    def create_or_retrieve_album(self, album_title):

        # Find albums created by this app to see if one matches album_title
        for a in self.get_albums(True):
            if a["title"].lower() == album_title.lower():
                album_id = a["id"]
                logging.info(f"Uploading into EXISTING photo album -- '{album_title}'")
                return album_id

        # No matches, create new album
        create_album_body = json.dumps({"album": {"title": album_title}})
        resp = self._session.post(
            "https://photoslibrary.googleapis.com/v1/albums", create_album_body
        ).json()
        logging.debug(f"Server response: {resp}")

        if "id" in resp:
            logging.info(f"Uploading into NEW photo album -- {album_title}")
            return resp["id"]
        else:
            logging.error(
                f"Could not find or create photo album {album_title}. Server Response: {resp}"
            )
            return None

    def upload_photos(self, photo_file_name, album_name):

        album_id = self.create_or_retrieve_album(album_name) if album_name else None

        # interrupt upload if an upload was requested but could not be created
        if album_name and not album_id:
            return

        self._session.headers["Content-type"] = "application/octet-stream"
        self._session.headers["X-Goog-Upload-Protocol"] = "raw"

        try:
            photo_file = open(photo_file_name, mode="rb")
            photo_bytes = photo_file.read()
        except OSError as err:
            logging.error("Could not read file {photo_file_name} -- {err}")
            return

        self._session.headers["X-Goog-Upload-File-Name"] = os.path.basename(
            photo_file_name
        )

        logging.info(f"Uploading photo -- {photo_file_name}")

        upload_token = self._session.post(
            "https://photoslibrary.googleapis.com/v1/uploads", photo_bytes
        )

        if (upload_token.status_code == 200) and upload_token.content:
            create_body = json.dumps(
                {
                    "albumId": album_id,
                    "newMediaItems": [
                        {
                            "description": "",
                            "simpleMediaItem": {
                                "uploadToken": upload_token.content.decode()
                            },
                        }
                    ],
                },
                indent=4,
            )

            resp = self._session.post(
                "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate",
                create_body,
            ).json()

            logging.debug(f"Server response: {resp}")

            if "newMediaItemResults" in resp:
                status = resp["newMediaItemResults"][0]["status"]
                if status.get("code") and (status.get("code") > 0):
                    logging.error(
                        f"Could not add {os.path.basename(photo_file_name)} to library -- {status['message']}"
                    )
                else:
                    logging.info(
                        f"Added {os.path.basename(photo_file_name)} to library and album {album_name}"
                    )
            else:
                logging.error(
                    f"Could not add {os.path.basename(photo_file_name)} to library. Server Response -- {resp}"
                )

        else:
            logging.error(
                f"Could not upload {os.path.basename(photo_file_name)}. Server Response - {upload_token}"
            )

        try:
            del self._session.headers["Content-type"]
            del self._session.headers["X-Goog-Upload-Protocol"]
            del self._session.headers["X-Goog-Upload-File-Name"]
        except KeyError:
            pass

    def upload_all_photos_in_dir(self, directory, album_name):
        for entry in os.scandir(directory):
            if entry.path.endswith(".jpg"):
                try:
                    self.upload_photos(entry.path, album_name)
                    os.remove(entry.path)
                except BaseException as e:
                    logging.exception(
                        f"Failed to upload {entry.path} to Google Photos"
                    )

