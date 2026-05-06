import logging
from datetime import datetime
import json
import threading
import time
import requests

LOG = logging.getLogger("JELLYFIN." + __name__)

def quick_connect(conn_mgr, server_url, callback):
    if not server_url:
        raise AttributeError("server url cannot be empty")

    # Check if quick connect is enabled before starting the process
    if (not _quick_connect_enabled(conn_mgr.API, server_url, conn_mgr.session)):
        LOG.warning("Quick connect is not enabled for %s" % (server_url))
        return {}

    LOG.info("Attempting to initiate quick connect to %s" % (server_url))

    # Initiate quick connect and get the secret and pin
    data = _initiate_quick_connect(conn_mgr.API, server_url, conn_mgr.session)

    if not data:
        LOG.info("Failed to initiate quick connect")
        return {}

    secret = data.get("Secret")
    if not secret:
        LOG.info("Failed to retrieve quick connect secret")
        return {}

    pin = data.get("Code")
    if not pin:
        LOG.info("Failed to retrieve quick connect pin")
        return {}

    # Start a thread to poll the quick connect status
    thread = threading.Thread(
        target=_poll_quick_connect,
        args=(conn_mgr, server_url, callback, secret),
        daemon=True,
    )
    thread.start()

    return pin

def _initiate_quick_connect(granular_api, server_url, session=None):
    path = "QuickConnect/Initiate"

    headers = granular_api.get_default_headers()
    headers.update({"Content-type": "application/json"})

    try:
        LOG.info("Trying to login to %s/%s" % (server_url, path))
        response = granular_api.send_request(
            server_url,
            path,
            method="post",
            headers=headers,
            timeout=(5, 30),
            session=session,
        )

        if response.status_code == 200:
            return response.json()
        else:
            LOG.error(
                "Failed to initiate quick connect with status code: "
                + str(response.status_code)
            )
            LOG.error("Server Response:\n" + str(response.content))
            LOG.debug(headers)

            return {}
    except Exception as e:
        LOG.error(e)

    return {}

def _quick_connect_enabled(granular_api, server_url, session=None):
    path = "QuickConnect/Enabled"
    headers = granular_api.get_default_headers()
    headers.update({"Content-type": "application/json"})

    try:
        LOG.info(
            "Checking if quick connect is enabled for %s/%s" % (server_url, path)
        )
        response = granular_api.send_request(
            server_url,
            path,
            method="get",
            headers=headers,
            timeout=(5, 30),
            session=session,
        )

        if response.status_code == 200:
            return response.json()
        else:
            LOG.error(
                "Failed to check if quick connect is enabled with status code: "
                + str(response.status_code)
            )
            LOG.error("Server Response:\n" + str(response.content))
            LOG.debug(headers)

            return {}
    except Exception as e:
        LOG.error(e)

    return {}

def _poll_quick_connect(conn_mgr, server_url, callback, secret):
    tries = 30

    while True:
        time.sleep(3)

        LOG.info("Polling quick connect status for %s" % (server_url))
        # Check if the user has authenticated with the pin yet
        data = _check_quick_connect_status(
            conn_mgr.API, server_url, secret, conn_mgr.session
        )  # returns empty dict on failure
        tries -= 1

        if tries <= 0:
            LOG.info("Quick connect timed out after 30 tries")
            callback({})
            return

        if data.get("Authenticated") is True:
            break

    data = _quick_connect_login(
        conn_mgr.API, server_url, secret, conn_mgr.session
    )  # returns empty dict on failure

    if not data:
        LOG.info("Failed to login with quick connect")
        callback({})
        return

    LOG.info("Succesfully logged in as %s" % (data["User"]["Name"]))
    credentials = conn_mgr.credentials.get()

    conn_mgr.config.data["auth.user_id"] = data["User"]["Id"]
    conn_mgr.config.data["auth.token"] = data["AccessToken"]

    for server in credentials["Servers"]:
        if server["Id"] == data["ServerId"]:
            found_server = server
            break
    else:
        callback({})  # No server found
        return

    found_server["DateLastAccessed"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    found_server["UserId"] = data["User"]["Id"]
    found_server["AccessToken"] = data["AccessToken"]

    conn_mgr.credentials.add_update_server(credentials["Servers"], found_server)

    info = {"Id": data["User"]["Id"], "IsSignedInOffline": True}
    conn_mgr.credentials.add_update_user(server, info)

    conn_mgr.credentials.set_credentials(credentials)

    callback(data)

def _quick_connect_login(granular_api, server_url, secret, session=None):
    path = "Users/AuthenticateWithQuickConnect"
    authData = {"secret": secret}

    headers = granular_api.get_default_headers()
    headers.update({"Content-type": "application/json"})

    try:
        LOG.info("Trying to login to %s/%s" % (server_url, path))
        response = granular_api.send_request(
            server_url,
            path,
            method="post",
            headers=headers,
            data=json.dumps(authData),
            timeout=(5, 30),
            session=session,
        )

        if response.status_code == 200:
            return response.json()
        else:
            LOG.error(
                "Failed to login to server with status code: "
                + str(response.status_code)
            )
            LOG.error("Server Response:\n" + str(response.content))
            LOG.debug(headers)

            return {}
    except Exception as e:
        LOG.error(e)

    return {}

def _check_quick_connect_status(
    granular_api, server_url, secret, session=None
):
    path = "QuickConnect/Connect"
    authData = {"secret": secret}

    headers = granular_api.get_default_headers()
    headers.update({"Content-type": "application/json"})

    try:
        LOG.info("Checking quick connect status for %s/%s" % (server_url, path))
        response = _send_request(
            granular_api,
            server_url,
            path,
            method="get",
            headers=headers,
            data=authData,
            timeout=(5, 30),
            session=session,
        )

        if response.status_code == 200:
            return response.json()
        else:
            LOG.error(
                "Failed to check quick connect status with status code: "
                + str(response.status_code)
            )
            LOG.error("Server Response:\n" + str(response.content))
            LOG.debug(headers)

            return {}
    except (
        Exception
    ) as e:  # Find exceptions for likely cases i.e, server timeout, etc
        LOG.error(e)

    return {}

def _send_request(
    granular_api,
    url,
    path,
    method="get",
    timeout=None,
    headers=None,
    data=None,
    session=None,
):
    request_method = getattr(session or requests, method.lower())
    url = "%s/%s" % (url, path)
    request_settings = {
        "timeout": timeout or granular_api.default_timeout,
        "headers": headers or granular_api.get_default_headers(),
        "params": data,
    }

    if granular_api.config.data.get("auth.ssl") is False:
        request_settings["verify"] = False

    LOG.info("Sending %s request to %s" % (method, path))
    LOG.debug(request_settings["timeout"])
    LOG.debug(request_settings["headers"])

    return request_method(url, **request_settings)
