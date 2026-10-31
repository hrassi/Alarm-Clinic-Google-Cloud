# ============================================================
# ESP3 LIGHT ALARM CONTROLLER — MAIN.PY
# ============================================================
# Hardware:
#   GPIO35 : Digital input
#   GPIO13 : Door sensor (1 = open, 0 = closed)
#   GPIO14 : Window sensor (1 = open, 0 = closed)
#   GPIO34 : Potentiometer / analog input
#   GPIO25 : LED output (also controlled by the vintage interface)
#   GPIO26 : LED output
#   GPIO27 : LED output
#
# Compatible with:
#   - user_interface5_revised.py (GPIO25 vintage switch + gauge)
#   - technician_dashboard_universal.py (all 3 outputs and all inputs)
#   - Existing wifi_connect.py, telegram.py, clock.py and cloud_storage.py
#
# Cloud objects:
#   esp3.json                 = status written by this ESP
#   esp3_command.json         = requested output states written by Pythonista
#   esp3_alarm_config.json    = manually edited alarm settings (read only)
#
# Safety:
#   - All three LEDs start OFF.
#   - A failed cloud command read never changes any output.
#   - Only GPIO25/26/27 are controlled as outputs.
# ============================================================


# ============================================================
# DEVICE CONFIGURATION — EDIT THIS SECTION
# ============================================================

DEVICE_ID = "ESP3"

GPIO25_POWER_ON_STATE = "OFF"  # "OFF", "ON", or "LAST_STATE"
GPIO26_POWER_ON_STATE = "OFF"  # "OFF", "ON", or "LAST_STATE"
GPIO27_POWER_ON_STATE = "OFF"  # "OFF", "ON", or "LAST_STATE"

# Fill these from your existing local configuration.
# Do not paste private keys or bot tokens into shared messages.
WIFI_SSID = "Rassi Net3"
WIFI_PASSWORD = "H********t"

# This ESP's own Telegram bot
TELEGRAM_TOKEN = "8*********************************4A8_s"

# Destination: Pythonista Controller Bot
TELEGRAM_CHAT_ID = "8806959712"

# Destination: Sam's personal Telegram chat (urgent alerts)
SAM_CHAT_ID = "8368702577"

# Google Cloud Storage
GCS_ACCESS_ID = "GOO****************************************PWZ"
GCS_SECRET_KEY = "3Y******************************************j5u"

GCS_BUCKET = "sam_cloud_1"
GCS_REGION = "us-central1"


STATUS_FILE = "esp3.json"
COMMAND_FILE = "esp3_command.json"


# ============================================================
# RUNTIME SETTINGS
# ============================================================

import time
import clock

from machine import Pin, ADC, WDT
from wifi_connect import wifi_loop
from telegram import send_telegram, send_notification, receive_telegram
from cloud_storage import sync_time, write_json, read_json

WATCHDOG_TIMEOUT_MS = 30000
TELEGRAM_CHECK_INTERVAL_MS = 2000
LOOP_DELAY_MS = 100

# Upload status periodically even if no input changes.
CLOUD_REFRESH_INTERVAL_MS = 5 * 60 * 1000

# Upload the potentiometer only when it changes by at least this amount.
ANALOG_CHANGE_THRESHOLD = 32

# Periodic command polling is off by default. Pythonista sends Telegram
# REFRESH after writing a command; polling can be enabled in command JSON.
DEFAULT_FALLBACK_ENABLED = False
DEFAULT_FALLBACK_INTERVAL_SECONDS = 30
MIN_FALLBACK_INTERVAL_SECONDS = 5

telegram_update_offset = 0
last_telegram_check = time.ticks_ms()
last_cloud_refresh = time.ticks_ms()
last_command_poll = time.ticks_ms()

fallback_enabled = DEFAULT_FALLBACK_ENABLED
fallback_interval_seconds = DEFAULT_FALLBACK_INTERVAL_SECONDS

# ============================================================
# DOOR/WINDOW ALARM — CONFIGURATION IS READ ONLY
# ============================================================
# Edit esp3_alarm_config.json manually in Google Cloud Storage.
# This firmware never creates, writes, or refreshes that file.
# If it cannot load a valid config at startup, the alarm stays disarmed.

ALARM_CONFIG_FILE = "esp3_alarm_config.json"
DOOR_ALERT_MIN_INTERVAL_SECONDS = 60
WINDOW_ALERT_MIN_INTERVAL_SECONDS = 60

alarm_mode = "disarm"
alarm_start_hour = 19
alarm_end_hour = 9
alarm_config_valid = False

last_door_open = 0
last_window_open = 0
door_alert_sent = False
door_alert_sent_time = 0
window_alert_sent = False
window_alert_sent_time = 0


# ============================================================
# HARDWARE
# ============================================================

# Keep the familiar onboard indicators available for troubleshooting.
boot_btn = Pin(0, Pin.IN, Pin.PULL_UP)
led = Pin(2, Pin.OUT, value=0)

gpio25 = Pin(25, Pin.OUT, value=0)
gpio26 = Pin(26, Pin.OUT, value=0)
gpio27 = Pin(27, Pin.OUT, value=0)

# Digital inputs. GPIO35 is input-only and has no internal pull-up/down.
# Make sure the external button wiring gives each input a defined level.
input35 = Pin(35, Pin.IN)
input13 = Pin(13, Pin.IN)
input14 = Pin(14, Pin.IN)

pot = ADC(Pin(34))
pot.atten(ADC.ATTN_11DB)
pot.width(ADC.WIDTH_12BIT)


# ============================================================
# CLOUD STATUS
# ============================================================

cloud_state = {
    "device": DEVICE_ID,
    "updated": "",
    "online": True,

    "gpio25": 0,
    "gpio26": 0,
    "gpio27": 0,

    "input35": 0,
    "input13": 0,
    "input14": 0,

    "analog34": 0
}


# ============================================================
# STATUS AND CLOUD FUNCTIONS
# ============================================================

def update_output_status():
    """Record actual output states and current digital input states."""
    cloud_state["gpio25"] = gpio25.value()
    cloud_state["gpio26"] = gpio26.value()
    cloud_state["gpio27"] = gpio27.value()

    cloud_state["input35"] = input35.value()
    cloud_state["input13"] = input13.value()
    cloud_state["input14"] = input14.value()


def save_cloud_state():
    """Upload current ESP3 status to esp3.json."""
    update_output_status()
    cloud_state["analog34"] = pot.read()
    cloud_state["updated"] = clock.get_date_time()
    cloud_state["online"] = True

    result = write_json(
        GCS_ACCESS_ID,
        GCS_SECRET_KEY,
        GCS_BUCKET,
        GCS_REGION,
        STATUS_FILE,
        cloud_state
    )
    return result is True


def initialize_gpios():
    """Apply configured startup states; missing saved state falls back OFF."""
    saved_state = None

    if "LAST_STATE" in (
        GPIO25_POWER_ON_STATE,
        GPIO26_POWER_ON_STATE,
        GPIO27_POWER_ON_STATE
    ):
        try:
            saved_state = read_json(
                GCS_ACCESS_ID, GCS_SECRET_KEY,
                GCS_BUCKET, GCS_REGION, STATUS_FILE
            )
        except Exception as error:
            print("[Cloud] Saved state read failed:", error)

        if not isinstance(saved_state, dict):
            print("[Cloud] No saved state; LAST_STATE outputs will start OFF")

    settings = (
        (gpio25, "gpio25", GPIO25_POWER_ON_STATE),
        (gpio26, "gpio26", GPIO26_POWER_ON_STATE),
        (gpio27, "gpio27", GPIO27_POWER_ON_STATE)
    )

    for pin, key, power_on_state in settings:
        value = 0

        if power_on_state == "ON":
            value = 1
        elif power_on_state == "LAST_STATE":
            if isinstance(saved_state, dict) and saved_state.get(key) in (0, 1):
                value = saved_state[key]
            else:
                value = 0
        elif power_on_state != "OFF":
            print("[Config] Invalid startup setting for", key, "- using OFF")

        pin.value(value)
        cloud_state[key] = pin.value()
        print("[System]", key, "startup:", "ON" if value else "OFF")




def process_cloud_refresh():
    """Refresh alarm config and publish status every five minutes."""
    global last_cloud_refresh

    now = time.ticks_ms()
    if time.ticks_diff(now, last_cloud_refresh) < CLOUD_REFRESH_INTERVAL_MS:
        return

    last_cloud_refresh = now

    # Reload the manually maintained alarm configuration.
    if load_alarm_config():
        print("[Alarm] Config refreshed successfully")
    else:
        print("[Alarm] Config refresh failed; previous valid settings retained")

    # Continue the existing routine status upload.
    if save_cloud_state():
        print("[Cloud] Periodic status upload successful")
    else:
        print("[Cloud] Periodic status upload failed")



# ============================================================
# TELEGRAM MESSAGING
# ============================================================

def send_message(message):
    send_telegram(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DEVICE_ID, message)


def telegram_notification(message):
    send_notification(TELEGRAM_TOKEN, SAM_CHAT_ID, DEVICE_ID, message)


# ============================================================
# PUSHOVER — LOADED ONLY WHEN AN ALERT IS SENT
# ============================================================

import sys
import gc

def pushover(title, message):
    try:
        import pushover_notification
        return pushover_notification.send_notification(title, message)
    except Exception as error:
        print("[Pushover] Error:", error)
        return False
    finally:
        sys.modules.pop("pushover_notification", None)
        try:
            del pushover_notification
        except NameError:
            pass
        gc.collect()


# ============================================================
# OUTPUT CONTROL
# ============================================================

def set_output(pin, state_key, value, upload=True):
    """Change one output and optionally upload its actual state."""
    value = 1 if value else 0
    pin.value(value)
    cloud_state[state_key] = pin.value()

    print("[Output]", state_key, "=", "ON" if value else "OFF")

    if not upload:
        return True

    if save_cloud_state():
        return True

    print("[Cloud] Output changed locally, but status upload failed")
    return False


def normalize_request(value):
    """Accept ON/OFF strings and legacy 1/0 values."""
    if value is True or value == 1:
        return 1
    if value is False or value == 0:
        return 0
    if isinstance(value, str):
        value = value.strip().upper()
        if value == "ON":
            return 1
        if value == "OFF":
            return 0
    return None


# ============================================================
# CLOUD COMMAND PROCESSING
# ============================================================

def read_command_document():
    """Return a command dictionary, or None if cloud read failed."""
    try:
        document = read_json(
            GCS_ACCESS_ID, GCS_SECRET_KEY,
            GCS_BUCKET, GCS_REGION, COMMAND_FILE
        )
    except Exception as error:
        print("[Command] Cloud read error:", error)
        return None

    if not isinstance(document, dict):
        print("[Command] No valid command document")
        return None
    return document


def update_fallback_settings(document):
    """Update polling configuration only when it actually changes."""
    global fallback_enabled, fallback_interval_seconds, last_command_poll

    enabled = document.get("fallback_enabled", fallback_enabled)
    if not isinstance(enabled, bool):
        enabled = fallback_enabled

    try:
        interval = int(document.get("fallback_interval", fallback_interval_seconds))
    except (TypeError, ValueError):
        interval = fallback_interval_seconds

    if interval < MIN_FALLBACK_INTERVAL_SECONDS:
        interval = MIN_FALLBACK_INTERVAL_SECONDS

    if enabled != fallback_enabled or interval != fallback_interval_seconds:
        fallback_enabled = enabled
        fallback_interval_seconds = interval
        last_command_poll = time.ticks_ms()
        print("[Command] Periodic polling:",
              "ENABLED" if fallback_enabled else "DISABLED",
              "-", fallback_interval_seconds, "seconds")


def apply_cloud_command(document):
    """Apply only valid requests; missing/invalid fields leave outputs unchanged."""
    output_settings = (
        ("gpio25_request", gpio25, "gpio25"),
        ("gpio26_request", gpio26, "gpio26"),
        ("gpio27_request", gpio27, "gpio27")
    )

    changed = False
    for request_key, pin, state_key in output_settings:
        if request_key not in document:
            continue

        requested = normalize_request(document.get(request_key))
        if requested is None:
            print("[Command] Invalid request for", state_key, "- unchanged")
            continue

        if pin.value() != requested:
            pin.value(requested)
            cloud_state[state_key] = pin.value()
            print("[Command]", state_key, "set to",
                  "ON" if requested else "OFF")
            changed = True

    return changed


def process_cloud_command():
    """Read requests and then publish actual output/input/sensor status."""
    document = read_command_document()
    if document is None:
        # Crucially, a failed read never changes any output.
        return False

    update_fallback_settings(document)
    apply_cloud_command(document)

    if save_cloud_state():
        print("[Cloud] Command processed; status uploaded")
        return True

    print("[Cloud] Command read, but status upload failed")
    return False


def process_periodic_command_poll():
    """Poll only when the Pythonista command JSON enables fallback polling."""
    global last_command_poll

    if not fallback_enabled:
        return

    now = time.ticks_ms()
    if time.ticks_diff(now, last_command_poll) < fallback_interval_seconds * 1000:
        return

    last_command_poll = now
    print("[Command] Periodic cloud poll")
    process_cloud_command()


# ============================================================
# DOOR/WINDOW ALARM
# ============================================================


def load_alarm_config():
    """Read and validate the manually maintained cloud configuration."""
    global alarm_mode, alarm_start_hour, alarm_end_hour, alarm_config_valid

    data = read_json(
        GCS_ACCESS_ID, GCS_SECRET_KEY,
        GCS_BUCKET, GCS_REGION, ALARM_CONFIG_FILE
    )

    if not isinstance(data, dict):
        print("[Alarm] Config unavailable; retaining previous settings")
        return False

    mode = data.get("mode")
    if mode not in ("auto", "arm", "disarm"):
        print("[Alarm] Invalid mode; retaining previous settings")
        return False

    try:
        start_hour = int(data.get("arm_start"))
        end_hour = int(data.get("arm_end"))
    except (TypeError, ValueError):
        print("[Alarm] Invalid hours; retaining previous settings")
        return False

    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        print("[Alarm] Hours out of range; retaining previous settings")
        return False

    alarm_mode = mode
    alarm_start_hour = start_hour
    alarm_end_hour = end_hour
    alarm_config_valid = True

    print("[Alarm] Config loaded:", alarm_mode, alarm_start_hour, alarm_end_hour)
    return True



def is_alarm_armed():
    """Apply the manually configured mode and time window."""
    if not alarm_config_valid or alarm_mode == "disarm":
        return False
    if alarm_mode == "arm":
        return True

    try:
        time_part = str(clock.get_date_time()).split()[-1]
        current_hour = int(time_part.split(":")[0])
    except (TypeError, ValueError, IndexError):
        return False

    if alarm_start_hour < alarm_end_hour:
        return alarm_start_hour <= current_hour < alarm_end_hour
    return current_hour >= alarm_start_hour or current_hour < alarm_end_hour


def send_alarm_alert(sensor_name):
    message = "{} {} CLINIC Open".format(DEVICE_ID, sensor_name)
    print("[Alarm] ALERT:", message)

    try:
        telegram_notification(message)
    except Exception as error:
        print("[CLINIC Alarm] Telegram alert error:", error)

    try:
        pushover("{} CLINIC ALARM".format(DEVICE_ID), message)
    except Exception as error:
        print("[Alarm] Pushover alert error:", error)


def process_one_alarm_sensor(is_open, sensor_name, now_seconds,
                             alert_sent, alert_sent_time, min_interval):
    if is_open and not alert_sent and is_alarm_armed():
        send_alarm_alert(sensor_name)
        alert_sent = True
        alert_sent_time = now_seconds
    elif not is_open and alert_sent:
        if now_seconds - alert_sent_time > min_interval:
            print("[Alarm]", sensor_name, "closed; alert re-armed")
            alert_sent = False

    return alert_sent, alert_sent_time


def process_alarm():
    """Monitor door and window inputs without cloud calls in the loop."""
    global last_door_open, last_window_open
    global door_alert_sent, door_alert_sent_time
    global window_alert_sent, window_alert_sent_time

    door_open = input13.value() == 1
    window_open = input14.value() == 1

    if door_open != bool(last_door_open):
        print("[Alarm] Door", "OPEN" if door_open else "CLOSED")
        last_door_open = 1 if door_open else 0

    if window_open != bool(last_window_open):
        print("[Alarm] Window", "OPEN" if window_open else "CLOSED")
        last_window_open = 1 if window_open else 0

    now_seconds = time.time()
    door_alert_sent, door_alert_sent_time = process_one_alarm_sensor(
        door_open, "Door", now_seconds, door_alert_sent,
        door_alert_sent_time, DOOR_ALERT_MIN_INTERVAL_SECONDS
    )
    window_alert_sent, window_alert_sent_time = process_one_alarm_sensor(
        window_open, "Window", now_seconds, window_alert_sent,
        window_alert_sent_time, WINDOW_ALERT_MIN_INTERVAL_SECONDS
    )


# ============================================================
# TELEGRAM COMMAND HANDLER
# ============================================================

def handle_telegram():
    global telegram_update_offset, last_telegram_check

    now = time.ticks_ms()
    if time.ticks_diff(now, last_telegram_check) < TELEGRAM_CHECK_INTERVAL_MS:
        return

    last_telegram_check = now

    try:
        command, telegram_update_offset = receive_telegram(
            TELEGRAM_TOKEN, telegram_update_offset
        )
    except Exception as error:
        print("[Telegram] Receive error:", error)
        return

    if command is None:
        return

    command = command.strip().upper()
    print("[Telegram] Received:", command)

    if command == "REFRESH":
        load_alarm_config()
        if process_cloud_command():
            send_message("ACK refreshed")
        else:
            send_message("Refresh incomplete; check cloud connection")

    elif command in ("GPIO25 ON", "GPIO25 OFF"):
        value = 1 if command.endswith("ON") else 0
        if set_output(gpio25, "gpio25", value):
            send_message("ACK " + command)
        else:
            send_message(command + "; cloud update failed")

    elif command in ("GPIO26 ON", "GPIO26 OFF"):
        value = 1 if command.endswith("ON") else 0
        if set_output(gpio26, "gpio26", value):
            send_message("ACK " + command)
        else:
            send_message(command + "; cloud update failed")

    elif command in ("GPIO27 ON", "GPIO27 OFF"):
        value = 1 if command.endswith("ON") else 0
        if set_output(gpio27, "gpio27", value):
            send_message("ACK " + command)
        else:
            send_message(command + "; cloud update failed")

    elif command == "PING":
        telegram_notification("PING OK")
        pushover("{} :".format(DEVICE_ID), " PING OK")


# ============================================================
# INPUT MONITORING
# ============================================================

def handle_inputs():
    """Upload promptly when a button state or potentiometer changes."""
    changed = False

    for pin, key in (
        (input35, "input35"),
        (input13, "input13"),
        (input14, "input14")
    ):
        value = pin.value()
        if value != cloud_state[key]:
            cloud_state[key] = value
            print("[Input]", key, "changed:", value)
            changed = True

    analog_value = pot.read()
    if abs(analog_value - cloud_state["analog34"]) >= ANALOG_CHANGE_THRESHOLD:
        cloud_state["analog34"] = analog_value
        print("[Input] GPIO34 analog changed:", analog_value)
        changed = True

    if changed:
        if save_cloud_state():
            print("[Cloud] Input changes saved")
        else:
            print("[Cloud] Input update failed; periodic retry remains enabled")


# ============================================================
# SYSTEM INITIALIZATION
# ============================================================

print("[System] Connecting to Wi-Fi...")

while not wifi_loop(WIFI_SSID, WIFI_PASSWORD):
    time.sleep_ms(500)

print("[System] Wi-Fi connected!")

# Synchronize time before signed Google Cloud Storage requests.
clock_synced = sync_time()
if not clock_synced:
    print("[Cloud] Clock synchronization failed; cloud requests may fail")

initialize_gpios()

cloud_state["input35"] = input35.value()
cloud_state["input13"] = input13.value()
cloud_state["input14"] = input14.value()
cloud_state["analog34"] = pot.read()

print("[Input] GPIO35:", cloud_state["input35"])
print("[Input] GPIO13:", cloud_state["input13"])
print("[Input] GPIO14:", cloud_state["input14"])
print("[Input] GPIO34 analog:", cloud_state["analog34"])

# Read the manually maintained alarm configuration once at startup.
load_alarm_config()
last_door_open = input13.value()
last_window_open = input14.value()

if save_cloud_state():
    print("[Cloud] Initial ESP3 status saved")
else:
    print("[Cloud] Initial ESP3 status upload failed")

last_cloud_refresh = time.ticks_ms()
last_command_poll = time.ticks_ms()
last_telegram_check = time.ticks_ms()

wdt = WDT(timeout=WATCHDOG_TIMEOUT_MS)

# ============================================================
# MAIN LOOP
# ============================================================

print("[System] ESP3 controller started")

while True:
    wifi_available = wifi_loop(WIFI_SSID, WIFI_PASSWORD)

    if wifi_available:
        handle_telegram()
        process_periodic_command_poll()

    # Keep local inputs monitored even if Wi-Fi/cloud is unavailable.
    handle_inputs()
    process_cloud_refresh()
    process_alarm()

    wdt.feed()
    time.sleep_ms(LOOP_DELAY_MS)
