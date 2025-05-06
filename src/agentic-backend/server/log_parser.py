from pymavlink import mavutil
import structlog

logger = structlog.get_logger()

def parse_log(log_file_path: str) -> dict:
    """
    Parses a .bin (ArduPilot Dataflash) log file and extracts key information.
    Returns a dictionary containing the parsed data.
    """
    # Bind context for this operation
    log = logger.bind(log_file_path=log_file_path) 
    log.info("log_parsing_started")
    data = {
        "timestamps": [], "altitudes": [], "gps_statuses": [],
        "battery_voltages": [], "error_messages": [], "flight_modes": [],
        "duration_seconds": 0, "start_time_us": None, "end_time_us": None,
        # Add more fields as needed
    }
    mlog = None # Initialize mlog to None

    try:
        mlog = mavutil.mavlink_connection(log_file_path)
        start_time_us = None
        end_time_us = None

        while True:
            msg = mlog.recv_match(blocking=False) # Use blocking=False for potentially faster iteration
            if msg is None:
                if mlog.eof:
                    log.info("log_parsing_eof")
                    break
                # If blocking=False, None might just mean no message available *yet*
                # Add a small sleep or use blocking=True if issues arise
                continue

            msg_type = msg.get_type()
            timestamp_us = getattr(msg, 'TimeUS', None)

            if timestamp_us is None: continue # Skip messages without TimeUS

            if start_time_us is None: start_time_us = timestamp_us
            end_time_us = timestamp_us

            # --- Extract specific messages (Add more as needed) ---
            if msg_type == 'VFR_HUD':
                data["timestamps"].append(timestamp_us)
                data["altitudes"].append(msg.alt)
            elif msg_type == 'GPS':
                data["gps_statuses"].append({'time_us': timestamp_us, 'fix_type': msg.Status, 'num_sats': msg.NSats})
            elif msg_type == 'BAT':
                data["battery_voltages"].append({'time_us': timestamp_us, 'voltage': msg.Volt})
            elif msg_type == 'ERR':
                data["error_messages"].append({'time_us': timestamp_us, 'sub_sys': msg.Subsys, 'ecode': msg.ECode})
            elif msg_type == 'MODE':
                 data["flight_modes"].append({'time_us': timestamp_us, 'mode': msg.Mode, 'mode_num': msg.ModeNum})
            # --- End message extraction ---

        if start_time_us is not None and end_time_us is not None:
            data['duration_seconds'] = (end_time_us - start_time_us) / 1_000_000.0
            data['start_time_us'] = start_time_us
            data['end_time_us'] = end_time_us
            log.info("log_parsing_duration_calculated", duration_sec=data['duration_seconds'])
        else:
            log.warning("log_parsing_duration_undetermined")

    except Exception as e:
        log.error("log_parsing_error", error=str(e), exc_info=True) # exc_info adds traceback
        raise # Re-raise the exception to be caught by the endpoint
    finally:
        if mlog:
            mlog.close()
            log.info("log_file_closed")

    return data