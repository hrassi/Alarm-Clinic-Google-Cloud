import ui
import cloud_storage
import telegram_pythonista
import datetime
import threading
import time
# ============================================================
# CONFIGURATION
# ============================================================
DEVICE_ID = "ESP3"
STATUS_FILE = "esp3.json"
COMMAND_FILE = "esp3_command.json"
ALARM_CONFIG_FILE = "esp3_alarm_config.json"
UI_REFRESH_SECONDS = 10
OFFLINE_AFTER_SECONDS = 6 * 60
LCD_FONT = "system"
LCD_FONT_SIZE = 11
LCD_GREEN = "#94c9ff"
#LCD_GREEN = "#00FF55"
DEFAULT_ARM_START = 19
DEFAULT_ARM_END = 9
# ============================================================
# COMMAND STATE
# ============================================================
command_lock = threading.Lock()
command_in_progress = False
ui_busy = False
# ============================================================
# HELPERS
# ============================================================
def load_image(filename):
    try:
        image = ui.Image.named(filename)
        if image is None:
            print("[UI] Image not found:", filename)
        return image
    except Exception as exc:
        print("[UI] Could not load image:", filename, exc)
        return None
def display_state(value):
    if isinstance(value, bool):
        return "OPEN" if value else "CLOSED"
    if isinstance(value, (int, float)):
        return "OPEN" if value else "CLOSED"
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "on", "open", "opened"):
            return "OPEN"
        if text in ("0", "false", "off", "closed", "close"):
            return "CLOSED"
    return "UNKNOWN"
def parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(text)
    except (ValueError, TypeError):
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
    ):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
def timestamp_age_seconds(timestamp):
    if timestamp is None:
        return None
    try:
        if timestamp.tzinfo is None:
            now = datetime.datetime.now()
        else:
            now = datetime.datetime.now(timestamp.tzinfo)
        return (now - timestamp).total_seconds()
    except Exception:
        return None
def format_hour(value):
    try:
        hour = int(value)
        if 0 <= hour <= 23:
            return "{:02d}:00".format(hour)
    except (TypeError, ValueError):
        pass
    return "--:--"
def format_refresh_time(timestamp):
    if timestamp is None:
        return "--:--:--"
    try:
        return timestamp.strftime("%H:%M:%S")
    except Exception:
        return "--:--:--"
# ============================================================
# PROGRESS DISPLAY
# ============================================================
def show_progress(message):
    def update_lcd():
        if root.on_screen:
            label_screen.text = message
    ui.delay(update_lcd, 0)
# ============================================================
# MAIN VIEW
# ============================================================
root = ui.View(frame=(0, 0, 430, 700))
root.name = "ESP3 Alarm Dashboard"
background = ui.ImageView()
background.image = load_image("black_leather.jpg")
background.frame = root.bounds
background.flex = "WH"
background.content_mode = ui.CONTENT_SCALE_TO_FILL
root.add_subview(background)
# ============================================================
# LCD SCREEN
# ============================================================
button90 = ui.Button()
button90.frame = (40, 30, 340, 100)
button90.background_image = load_image("vintage_screen2.jpg")
button90.corner_radius = 15
button90.border_width = 1
button90.border_color = "#9b9ba4"
button90.enabled = False
root.add_subview(button90)
label_screen = ui.Label()
label_screen.frame = button90.frame
label_screen.border_width = 0
label_screen.corner_radius = 12
label_screen.font = (LCD_FONT, LCD_FONT_SIZE)
label_screen.text_color = LCD_GREEN
label_screen.alignment = ui.ALIGN_CENTER
label_screen.background_color = "clear"
label_screen.number_of_lines = 0
label_screen.text = "ESP3\nConnecting to cloud..."
root.add_subview(label_screen)
# ============================================================
# THREE ALARM MODE BUTTONS
# LEFT = ARM
# MIDDLE = DISARM
# RIGHT = AUTO
# ============================================================
button1 = ui.Button()
button1.frame = (60, 160, 70, 70)
button1.background_image = load_image("push_button_black.jpg")
button1.corner_radius = 35
button1.border_width = 1
button1.border_color = "#9b9ba4"
button1.enabled = True
root.add_subview(button1)
button2 = ui.Button()
button2.frame = (175, 160, 70, 70)
button2.background_image = load_image("push_button_black.jpg")
button2.corner_radius = 35
button2.border_width = 1
button2.border_color = "#9b9ba4"
button2.enabled = True
root.add_subview(button2)
button3 = ui.Button()
button3.frame = (290, 160, 70, 70)
button3.background_image = load_image("push_button_black.jpg")
button3.corner_radius = 35
button3.border_width = 1
button3.border_color = "#9b9ba4"
button3.enabled = True
root.add_subview(button3)
# ============================================================
# DOOR / WINDOW PANEL
# ============================================================
panel = ui.View()
panel.frame = (40, 280, 350, 250)
panel.background_color = "clear"
panel.background_image = load_image("dental_chair.jpg")
panel.border_width = 6
panel.border_color = "#b55f43"
root.add_subview(panel)
picture = ui.ImageView()
picture.frame = (0, 0, 350, 250)
picture.image = load_image("dental_chair.JPG")
picture.content_mode = ui.CONTENT_SCALE_TO_FILL
panel.add_subview(picture)
# ============================================================
# DOOR IMAGE BUTTON
# TAP TO SEND PING
# ============================================================
door = ui.Button()
door.frame = (260, 300, 100, 200)
door.background_image = load_image("door_closed.jpg")
door.corner_radius = 1
door.border_width = 1
door.border_color = "#9b9ba4"
door.enabled = True
root.add_subview(door)
# ============================================================
# WINDOW IMAGE
# READ-ONLY
# ============================================================
window = ui.Button()
window.frame = (80, 300, 100, 100)
window.background_image = load_image("window_closed.JPEG")
window.corner_radius = 1
window.border_width = 1
window.border_color = "#9b9ba4"
window.enabled = False
root.add_subview(window)
# ============================================================
# GPIO25 BUTTON
# TAP TO TOGGLE OUTPUT
# ============================================================
gpio25 = ui.Button()
gpio25.frame = (160, 575, 100, 100)
gpio25.background_image = load_image("push_button_black.jpg")
gpio25.corner_radius = 50
gpio25.border_width = 1
gpio25.border_color = "#9b9ba4"
gpio25.enabled = True
root.add_subview(gpio25)
# ============================================================
# UPDATE MODE BUTTON IMAGES
# ============================================================
def update_mode_buttons(mode):
    off_image = load_image("push_button_black.jpg")
    on_image = load_image("black_button_on.JPEG")
    button1.background_image = (
        on_image if mode == "arm" else off_image
    )
    button2.background_image = (
        on_image if mode == "disarm" else off_image
    )
    button3.background_image = (
        on_image if mode == "auto" else off_image
    )
# ============================================================
# UPDATE DOOR AND WINDOW IMAGES
# ============================================================
def update_door_window(status):
    door_state = display_state(status.get("input13"))
    window_state = display_state(status.get("input14"))
    if door_state == "OPEN":
        door.background_image = load_image("door_open.JPEG")
    elif door_state == "CLOSED":
        door.background_image = load_image("door_closed.jpg")
    if window_state == "OPEN":
        window.background_image = load_image("window_open.JPEG")
    elif window_state == "CLOSED":
        window.background_image = load_image("window_closed.JPEG")
    return door_state, window_state
# ============================================================
# UPDATE GPIO25 IMAGE
# ============================================================
def update_gpio25(status):
    state = display_state(status.get("gpio25"))
    if state == "OPEN":
        gpio25.background_image = load_image("black_button_on.JPEG")
    elif state == "CLOSED":
        gpio25.background_image = load_image("push_button_black.jpg")
# ============================================================
# UPDATE LCD DISPLAY
# ============================================================
def update_display(status, config, error_message=None):
    if not isinstance(status, dict):
        label_screen.text = (
            "ESP3   STATUS UNKNOWN\n"
            "Waiting for cloud status..."
        )
        return
    updated_value = status.get("updated")
    updated_timestamp = parse_timestamp(updated_value)
    age = timestamp_age_seconds(updated_timestamp)
    if age is None or age < -60:
        connection = "UNKNOWN"
    elif age > OFFLINE_AFTER_SECONDS:
        connection = "OFFLINE"
    else:
        connection = "ONLINE"
    if isinstance(config, dict):
        mode = str(config.get("mode", "unknown")).lower()
    else:
        mode = "unknown"
    if mode not in ("arm", "disarm", "auto"):
        mode = "unknown"
    update_mode_buttons(mode)
    if mode == "auto" and isinstance(config, dict):
        start_text = format_hour(config.get("arm_start"))
        end_text = format_hour(config.get("arm_end"))
        alarm_text = "ALARM: AUTO {}-{}".format(
            start_text,
            end_text
        )
    else:
        alarm_text = "ALARM: {}".format(mode.upper())
    door_state, window_state = update_door_window(status)
    update_gpio25(status)
    if updated_timestamp is not None:
        refresh_text = updated_timestamp.strftime("%d/%m %H:%M:%S")
    else:
        refresh_text = "--/-- --:--:--"
    line1 = "{}  {}  REF: {}".format(
        DEVICE_ID,
        connection,
        refresh_text
    )
    line2 = "DOOR: {}   WINDOW: {}".format(
        door_state,
        window_state
    )
    line3 = alarm_text
    label_screen.text = "\n".join([
        line1,
        line2,
        line3
    ])
    print(
        "[UI] Connection:", connection,
        "| Alarm:", mode,
        "| Door:", door_state,
        "| Window:", window_state,
        "| GPIO25:", status.get("gpio25"),
        "| Updated:", updated_value
    )
# ============================================================
# READ CLOUD DATA
# ============================================================
def read_cloud_data():
    status = None
    config = None
    error_message = None
    try:
        status = cloud_storage.read_json(STATUS_FILE)
    except Exception as exc:
        error_message = str(exc)
        print("[Cloud] Status read failed:", exc)
    try:
        config = cloud_storage.read_json(ALARM_CONFIG_FILE)
    except Exception as exc:
        error_message = str(exc)
        print("[Cloud] Alarm config read failed:", exc)
    if not isinstance(status, dict):
        status = None
    if not isinstance(config, dict):
        config = None
    return status, config, error_message
# ============================================================
# REFRESH DASHBOARD AFTER COMMAND
# ============================================================
def restore_dashboard():
    global ui_busy
    try:
        show_progress("REFRESHING STATUS...\nPlease wait")
        status, config, error_message = read_cloud_data()
        def finish_refresh():
            global ui_busy
            if root.on_screen:
                update_display(
                    status,
                    config,
                    error_message
                )
            ui_busy = False
        ui.delay(finish_refresh, 0)
    except Exception as exc:
        print("[UI] Dashboard refresh failed:", exc)
        def show_error():
            global ui_busy
            if root.on_screen:
                label_screen.text = (
                    "REFRESH FAILED\n"
                    "Check connection"
                )
            ui_busy = False
        ui.delay(show_error, 0)
# ============================================================
# COMMON TELEGRAM REFRESH HELPER
# ============================================================
def send_esp_refresh(message="REFRESH"):
    telegram_ok = False
    telegram_message = ""
    try:
        telegram_ok, telegram_message = (
            telegram_pythonista.send_message(
                "esp3",
                message
            )
        )
        print(
            "[Command] Telegram {} result:".format(message),
            telegram_ok,
            telegram_message
        )
    except Exception as exc:
        telegram_message = str(exc)
        print(
            "[Command] Telegram {} failed:".format(message),
            exc
        )
    return telegram_ok, telegram_message
# ============================================================
# ALARM MODE COMMAND
# ============================================================
def set_alarm_mode(mode):
    global command_in_progress
    if mode not in ("arm", "disarm", "auto"):
        return
    if not command_lock.acquire(False):
        print("[Alarm] Another command is already running.")
        return
    command_in_progress = True
    try:
        print("[Alarm] Requested mode:", mode.upper())
        # ----------------------------------------------------
        # STEP 1: WRITE CONFIGURATION TO CLOUD
        # ----------------------------------------------------
        show_progress(
            "WRITING TO CLOUD...\n"
            "Setting " + mode.upper()
        )
        try:
            config = cloud_storage.read_json(
                ALARM_CONFIG_FILE
            )
        except Exception as exc:
            print("[Alarm] Could not read current config:", exc)
            show_progress(
                "CLOUD READ FAILED\n"
                "Check connection"
            )
            time.sleep(1.5)
            return
        if not isinstance(config, dict):
            print(
                "[Alarm] No valid existing alarm config. "
                "Nothing was changed."
            )
            show_progress(
                "CONFIG NOT FOUND\n"
                "Nothing changed"
            )
            time.sleep(1.5)
            return
        # Preserve the current schedule and other config fields.
        new_config = dict(config)
        new_config["mode"] = mode
        new_config["arm_start"] = config.get(
            "arm_start",
            DEFAULT_ARM_START
        )
        new_config["arm_end"] = config.get(
            "arm_end",
            DEFAULT_ARM_END
        )
        try:
            write_ok = cloud_storage.write_json(
                ALARM_CONFIG_FILE,
                new_config
            )
        except Exception as exc:
            print("[Alarm] Config write failed:", exc)
            show_progress(
                "CLOUD WRITE FAILED\n"
                "Mode not confirmed"
            )
            time.sleep(1.5)
            return
        if not write_ok:
            print("[Alarm] Cloud write was not successful.")
            show_progress(
                "CLOUD WRITE FAILED\n"
                "Mode not confirmed"
            )
            time.sleep(1.5)
            return
        print("[Alarm] Config written:", new_config)
        # ----------------------------------------------------
        # STEP 2: SEND TELEGRAM REFRESH
        # ----------------------------------------------------
        show_progress(
            "SENDING TELEGRAM...\n"
            "REFRESH ESP3"
        )
        telegram_ok, telegram_message = send_esp_refresh("REFRESH")
        # ----------------------------------------------------
        # STEP 3: SHOW RESULT
        # ----------------------------------------------------
        if telegram_ok:
            show_progress(
                "COMMAND SENT\n"
                "REFRESHING STATUS..."
            )
        else:
            show_progress(
                "CLOUD UPDATED\n"
                "TELEGRAM NOT CONFIRMED"
            )
            print(
                "[Alarm] Cloud configuration was written, "
                "but Telegram REFRESH was not confirmed."
            )
        time.sleep(1.0)
    finally:
        command_in_progress = False
        command_lock.release()
        restore_dashboard()
# ============================================================
# GPIO25 ON/OFF COMMAND
# ============================================================
def set_gpio25():
    global command_in_progress
    if not command_lock.acquire(False):
        print("[GPIO25] Another command is already running.")
        return
    command_in_progress = True
    try:
        # ----------------------------------------------------
        # STEP 1: READ CURRENT REPORTED OUTPUT STATE
        # ----------------------------------------------------
        show_progress(
            "READING CLOUD...\n"
            "Checking GPIO25"
        )
        print("[GPIO25] Reading status file:", STATUS_FILE)
        try:
            status = cloud_storage.read_json(STATUS_FILE)
            print(
                "[GPIO25] Cloud read returned:",
                repr(status)
            )
        except Exception as exc:
            import traceback
            print(
                "[GPIO25] Status read exception:",
                repr(exc)
            )
            traceback.print_exc()
            show_progress(
                "STATUS READ ERROR\n"
                "See Pythonista console"
            )
            time.sleep(1.5)
            return
        if not isinstance(status, dict):
            print(
                "[GPIO25] Expected a dictionary but received:",
                type(status).__name__,
                repr(status)
            )
            show_progress(
                "STATUS UNAVAILABLE\n"
                "GPIO25 unchanged"
            )
            time.sleep(1.5)
            return
        # ----------------------------------------------------
        # STEP 2: DETERMINE THE OPPOSITE GPIO25 STATE
        # ----------------------------------------------------
        current_state = status.get("gpio25")
        print(
            "[GPIO25] Current reported state:",
            repr(current_state)
        )
        if current_state in (0, False, "0", "OFF", "off"):
            requested_state = "ON"
        elif current_state in (1, True, "1", "ON", "on"):
            requested_state = "OFF"
        else:
            print(
                "[GPIO25] Unrecognized GPIO25 state:",
                repr(current_state)
            )
            show_progress(
                "GPIO25 STATE UNKNOWN\n"
                "Cannot toggle safely"
            )
            time.sleep(1.5)
            return
        print(
            "[GPIO25] Requested state:",
            requested_state
        )
        # ----------------------------------------------------
        # STEP 3: READ EXISTING COMMAND JSON
        # ----------------------------------------------------
        show_progress(
            "READING COMMAND...\n"
            "Preparing GPIO25"
        )
        print(
            "[GPIO25] Reading command file:",
            COMMAND_FILE
        )
        try:
            command = cloud_storage.read_json(COMMAND_FILE)
            print(
                "[GPIO25] Command read returned:",
                repr(command)
            )
        except Exception as exc:
            import traceback
            print(
                "[GPIO25] Command file read exception:",
                repr(exc)
            )
            traceback.print_exc()
            show_progress(
                "COMMAND READ ERROR\n"
                "GPIO25 unchanged"
            )
            time.sleep(1.5)
            return
        if not isinstance(command, dict):
            print(
                "[GPIO25] Invalid command file:",
                repr(command)
            )
            show_progress(
                "COMMAND FILE INVALID\n"
                "GPIO25 unchanged"
            )
            time.sleep(1.5)
            return
        # Preserve all existing command fields.
        new_command = dict(command)
        new_command["gpio25_request"] = requested_state
        # ----------------------------------------------------
        # STEP 4: WRITE COMMAND JSON TO CLOUD
        # ----------------------------------------------------
        show_progress(
            "WRITING TO CLOUD...\n"
            "GPIO25 " + requested_state
        )
        print(
            "[GPIO25] Writing command JSON:",
            repr(new_command)
        )
        try:
            write_ok = cloud_storage.write_json(
                COMMAND_FILE,
                new_command
            )
            print(
                "[GPIO25] Cloud write result:",
                repr(write_ok)
            )
        except Exception as exc:
            import traceback
            print(
                "[GPIO25] Command write exception:",
                repr(exc)
            )
            traceback.print_exc()
            show_progress(
                "CLOUD WRITE ERROR\n"
                "GPIO25 not confirmed"
            )
            time.sleep(1.5)
            return
        if not write_ok:
            print("[GPIO25] Cloud write returned False.")
            show_progress(
                "CLOUD WRITE FAILED\n"
                "GPIO25 not confirmed"
            )
            time.sleep(1.5)
            return
        print("[GPIO25] Command JSON written successfully.")
        # ----------------------------------------------------
        # STEP 5: SEND TELEGRAM REFRESH
        # ----------------------------------------------------
        show_progress(
            "SENDING TELEGRAM...\n"
            "REFRESH ESP3"
        )
        telegram_ok, telegram_message = send_esp_refresh("REFRESH")
        if telegram_ok:
            show_progress(
                "GPIO25 REQUEST SENT\n"
                "REFRESHING STATUS..."
            )
        else:
            print(
                "[GPIO25] Command was written, but Telegram "
                "REFRESH was not confirmed."
            )
            show_progress(
                "CLOUD UPDATED\n"
                "TELEGRAM NOT CONFIRMED"
            )
        time.sleep(1.0)
    except Exception as exc:
        import traceback
        print("[GPIO25] Unexpected error:", repr(exc))
        traceback.print_exc()
        show_progress(
            "GPIO25 ERROR\n"
            "See Pythonista console"
        )
        time.sleep(1.5)
    finally:
        command_in_progress = False
        command_lock.release()
        # Restore the dashboard using the latest cloud data.
        restore_dashboard()
# ============================================================
# DOOR PING COMMAND
# ============================================================
def ping_esp3():
    global command_in_progress
    if not command_lock.acquire(False):
        print("[Door] Another command is already running.")
        return
    command_in_progress = True
    try:
        print("[Door] Sending PING to ESP3.")
        show_progress(
            "SENDING TELEGRAM...\n"
            "PING ESP3"
        )
        telegram_ok, telegram_message = send_esp_refresh("PING")
        if telegram_ok:
            show_progress(
                "PING SENT\n"
                "REFRESHING STATUS..."
            )
        else:
            show_progress(
                "PING NOT CONFIRMED\n"
                "Checking cloud status..."
            )
        time.sleep(1.0)
    finally:
        command_in_progress = False
        command_lock.release()
        restore_dashboard()
# ============================================================
# BUTTON ACTIONS
# ============================================================
def start_alarm_command(mode):
    global ui_busy
    if command_in_progress or ui_busy:
        print("[Alarm] Please wait for the current operation.")
        return
    ui_busy = True
    label_screen.text = (
        "STARTING COMMAND...\n"
        "Please wait"
    )
    threading.Thread(
        target=set_alarm_mode,
        args=(mode,),
        daemon=True
    ).start()
def arm_button_tapped(sender):
    start_alarm_command("arm")
def disarm_button_tapped(sender):
    start_alarm_command("disarm")
def auto_button_tapped(sender):
    start_alarm_command("auto")
def start_gpio25_command(sender):
    global ui_busy
    if command_in_progress or ui_busy:
        print("[GPIO25] Please wait for the current operation.")
        return
    ui_busy = True
    label_screen.text = (
        "GPIO25 COMMAND\n"
        "Please wait"
    )
    threading.Thread(
        target=set_gpio25,
        daemon=True
    ).start()
def start_door_ping(sender):
    global ui_busy
    if command_in_progress or ui_busy:
        print("[Door] Please wait for the current operation.")
        return
    ui_busy = True
    label_screen.text = (
        "DOOR STATUS REQUEST\n"
        "Please wait"
    )
    threading.Thread(
        target=ping_esp3,
        daemon=True
    ).start()
button1.action = arm_button_tapped
button2.action = disarm_button_tapped
button3.action = auto_button_tapped
gpio25.action = start_gpio25_command
door.action = start_door_ping
# ============================================================
# PERIODIC CLOUD READER
# ============================================================
def cloud_worker():
    while root.on_screen:
        # Do not overwrite progress messages while a command runs.
        if not ui_busy:
            status, config, error_message = read_cloud_data()
            if not ui_busy:
                ui.delay(
                    lambda s=status, c=config, e=error_message:
                        update_display(s, c, e)
                        if not ui_busy else None,
                    0
                )
        for _ in range(UI_REFRESH_SECONDS):
            if not root.on_screen:
                break
            time.sleep(1)
# ============================================================
# START DASHBOARD
# ============================================================
root.present("sheet")
threading.Thread(
    target=cloud_worker,
    daemon=True
).start()
