from time import sleep
from typing import Any, ByteString, Callable, Generic, Tuple, TypeVar
import serial
import struct
import datetime
from threading import Thread
import commands

__VERSION_STRING_LENGTH_IN_BYTES__ = 14
__SERIAL_NUMBER_LENGTH_IN_BYTES__ = 7
__CONFIGURATION_DATA_LENGTH_IN_BYTES__ = 256
__ASCII__ = "ASCII"
__DEFAULT_ACK_BYTE__ = 0xAA


def __string_decoder__(port: serial.Serial, *args, **kwargs):
    return port.read(__VERSION_STRING_LENGTH_IN_BYTES__).decode(__ASCII__)


def __ushort_decoder__(port: serial.Serial, *args, **kwargs):
    return struct.unpack(">H", port.read(2))[0]


def __battery_charge_decoder__(port: serial.Serial, *args, **kwargs):
    """Returns the raw battery value as a byte."""
    return port.read(1)[0]


def __read_fully__(port: serial.Serial, length_in_bytes: int):
    """
    Reads the amount of bytes from the serial port, blocking until the amount of bytes specified by length_in_bytes is received.
    """
    buffer = bytearray()

    remaining = length_in_bytes
    while remaining > 0:
        data = port.read(remaining)
        remaining -= len(data)
        buffer += (data)

    return buffer


def __std_validation_decoder__(port: serial.Serial, *args, **kwargs):
    """
    Listens for the default verification byte of 0xAA.
    """
    val = port.read(1)

    if(val[0] != __DEFAULT_ACK_BYTE__):
        raise Exception(
            f"Acknowledgement byte not received. {val[0]} != {__DEFAULT_ACK_BYTE__}")


__ecfg_verify_decoder__ = __std_validation_decoder__

__wcfg_verify_decoder__ = __std_validation_decoder__

__set_date_decoder__ = __std_validation_decoder__

__cfg_update_verify_decoder__ = __std_validation_decoder__

__factory_reset_verify_decoder__ = __std_validation_decoder__

__setdatetime_decoder__ = __std_validation_decoder__


def __spir_data_decoder__(port: serial.Serial, address: int, length_in_bytes: int, *args, **kwargs):
    """
    Decodes the spir data as returnewd by the device, trying to fill the buffer up to length_in_bytes.
    This will block until enough bytes are read, or the program is interrupted.
    """
    return __read_fully__(port, length_in_bytes)


def __configuration_data_decoder__(port: serial.Serial, *args, **kwargs):
    """
    Reads the configuration data in full. Blocks until enough bytes are read.
    """
    return __read_fully__(port, __CONFIGURATION_DATA_LENGTH_IN_BYTES__)


def __serial_number_decoder__(port: serial.Serial, *args, **kwargs):
    """
    Decodes the serial number read from the serial port and decodes it as ASCII to a python string..
    """
    return port.read(__SERIAL_NUMBER_LENGTH_IN_BYTES__).decode(__ASCII__)


def __getdatetime_decoder__(port: serial.Serial, *args, **kwargs) -> datetime.datetime:
    """
    Reads the datetime from the serial port and decodes it into a datetime object.
    """
    val = port.read(7)
    if(val[6] != 0xAA):
        raise Exception(f"Getting date time data failed. Received: {val}")

    return datetime.datetime(2000 + val[0], val[1], val[2], val[3], val[4], val[5], 0)


def __gettemp_decoder__(port: serial.Serial, *args, **kwargs) -> float:
    """
    Reads the 3 bytes + 1 verification from the serial port and returns the temperature indicated by the unit.
    """
    val = port.read(4)
    if(val[3] != 0xAA):
        raise Exception("Updating configuration data failed.")

    temp = val[0] + (1.0 / val[1])
    if val[2] != 0:
        temp *= -1

    return temp


def __getgyro_decoder__(port: serial.Serial, *args, **kwargs) -> Tuple[int, int, int]:
    """
    Reads the gyro state from the serial port and decodes it as a (x, y, z) tuple.
    """
    val = port.read(8)
    if(val[7] != 0xAA):
        raise Exception("Updating configuration data failed.")

    x = struct.unpack(">H", val[0:2])[0]
    y = struct.unpack(">H", val[2:4])[0]
    z = struct.unpack(">H", val[4:6])[0]

    return (x, y, z)


def __default_request_encoder__(cmd, *args, **kwargs) -> ByteString:
    """
    Encodes a request into a raw ASCII byte string, enclosed by < and >>.
    """
    return f"<{cmd.name}>>".encode(__ASCII__)


def __spir_request_encoder__(cmd, address: int, length_in_bytes: int, *args, **kwargs) -> ByteString:
    """
    Encodes a request into a SPIR request, ensuring minimal address & length validity. It is up to the end user to make sure that the address space of the unit is within bounds.
    """
    if 0 > address or address > 0xFFFFFF:
        raise Exception(f"Address out of bounds: {address}")
    elif 0 > length_in_bytes or length_in_bytes > 0xFFFF:
        raise Exception(
            f"Requested memory read length out of bounds: {length_in_bytes}")

    cmd = f"<{cmd.name}".encode(__ASCII__)
    cmd += bytes([
        (address >> 16) & 0xFF,
        (address >> 8) & 0xFF,
        (address) & 0xFF,
        (length_in_bytes >> 8) & 0xFF,
        (length_in_bytes) & 0xFF,
    ])
    return cmd + ">>".encode(__ASCII__)


def __wcfg_request_encoder__(cmd, address: int, value: int, *args, **kwargs) -> None:
    if 0 > address or address > 0xFF:
        raise Exception(f"Address out of bounds: {address}")
    elif 0 > value or value > 0xFF:
        raise Exception(f"Value for configuration out of bounds: {value}")

    cmd = f"<{cmd.name}".encode(__ASCII__)
    cmd += bytes([address & 0xFF, value & 0xFF])
    return cmd + ">>".encode(__ASCII__)


def __sendkey_encoder__(cmd, key: int, *args, **kwargs) -> None:
    if 0 > key or key > 3:
        raise Exception("Key  must be a value from 0 to 4.")

    cmd = f"<{cmd.name}".encode(__ASCII__)
    cmd += bytes([key])
    return cmd + ">>".encode(__ASCII__)


def __set_date_encoder__(cmd, value: int, *args, **kwargs) -> None:
    """
    Encodes the date value as a byte. This function performs NO VERIFICATION.
    """
    cmd = f"<{cmd.name}".encode(__ASCII__)
    # "{0:0{1}X}".format(value, 2).encode(__ASCII__) # This is a misdocumentation? Value isnt hexadecimal, but the pure byte value apparently.
    cmd += bytes([value])
    return cmd + ">>".encode(__ASCII__)


def __setdatetime_encoder__(cmd, year: int, month: int, day: int, hour: int, minute: int, second: int, *args, **kwargs) -> None:
    """
    Encodes the datetime command and does minimal verification using the datetime api.
    """
    # verify this is a valid date.
    datetime.datetime(year, month, day, hour, minute, second)

    cmd = f"<{cmd.name}".encode(__ASCII__)
    # "{0:0{1}X}".format(value, 2).encode(__ASCII__) # This is a misdocumentation? Value isnt hexadecimal, but the pure byte value apparently.
    cmd += bytes([year, month, day, hour, minute, second])
    return cmd + ">>".encode(__ASCII__)


def __within_bounds_verifier__(lb: int, ub: int) -> None:
    def bounds_checker(x: int):
        if x < lb or x > ub:
            raise Exception(f"Value out of bounds: {lb} <= {x} <= {ub}")

    return bounds_checker


T = TypeVar("T")


class Command(Generic[T]):
    def __init__(self, name, description, firmware, reply_decoder, request_encoder: Callable[[Any], ByteString] = __default_request_encoder__, verifier: Callable[[Any], None] = lambda x: x):
        self.name = name
        self.description = description
        self.firmware = firmware
        self.request_encoder = request_encoder
        self.reply_decoder = reply_decoder
        self.verifier = verifier

    def execute(self, port: serial.Serial, *args, **kwargs) -> T:
        [self.verifier(x) for x in args]
        req = self.request_encoder(self, *args, **kwargs)
        print(f"> {req}")
        port.write(req)
        if self.reply_decoder:
            return self.reply_decoder(port, *args, **kwargs)
        else:
            return None


class Commands:
    """
    A simple container class containing the available commands as a string.
    Some interdependencies with functions in this file (gqrfc1201.py) make it harder to move this to its own file.
    """

    def __init__(self) -> None:
        raise Exception("This class is not constructible.")

    GETVER = Command[str]("GETVER",
                          "Get hardware model and version.",
                          "GMC-280, GMC-300 Re.2.0x, Re.2.10 or later",
                          __string_decoder__
                          )

    GETCPM = Command[int]("GETCPM",
                          "Get current CPM value.",
                          "GMC-280, GMC-300 Re.2.0x, Re.2.10 or later",
                          __ushort_decoder__
                          )

    HEARTBEAT_ON = Command[None]("HEARTBEAT1",
                                 "Get hardware model and version.",
                                 "GMC-280, GMC-300 Re.2.0x, Re.2.10 or later",
                                 None
                                 )

    HEARTBEAT_OFF = Command[None]("HEARTBEAT0",
                                  "Get hardware model and version.",
                                  "GMC-280, GMC-300 Re.2.0x, Re.2.10 or later",
                                  None
                                  )

    GETVOLT = Command[int]("GETVOLT",
                           "one byte voltage value of battery (X 10V)",
                           "GMC-280, GMC-300 Re.2.0x, Re.2.10 or later",
                           __battery_charge_decoder__
                           )

    SPIR = Command("SPIR",
                   "A2,A1,A0 are three bytes address data, from MSB to LSB.  The L1,L0 are the data length requested.  L1 is high byte of 16 bit integer and L0 is low byte.",
                   "MC-300 Re.2.0x, Re.2.10 or later",
                   __spir_data_decoder__,
                   __spir_request_encoder__
                   )

    GETCFG = Command[ByteString]("GETCFG",
                                 "The configuration data.  Total 256 bytes will be returned.",
                                 "GMC-280, GMC-300 Re.2.10 or later",
                                 __configuration_data_decoder__
                                 )

    ECFG = Command[None]("ECFG",
                         "Erase all configuration data.",
                         "GMC-280, GMC-300 Re.2.10 or later",
                         __ecfg_verify_decoder__
                         )

    WCFG = Command("WCFG",
                   "A0 is the address and the D0 is the data byte(hex).",
                   "GMC-280, GMC-300 Re.2.10 or later",
                   __wcfg_verify_decoder__,
                   __wcfg_request_encoder__
                   )

    GETSERIAL = Command[str]("GETSERIAL",
                             "serial number in 7 bytes.",
                             "GMC-280, GMC-300 Re.2.11 or later",
                             __serial_number_decoder__
                             )

    POWEROFF = Command[None]("POWEROFF",
                             "Power off.",
                             "GMC-280, GMC-300 Re.2.11 or later",
                             None
                             )

    CFGUPDATE = Command[None]("CFGUPDATE",
                              "Reload/Update/Refresh Configuration",
                              "GMC-280, GMC-300 Re.2.20 or later",
                              __cfg_update_verify_decoder__
                              )

    FACTORYRESET = Command[None]("FACTORYRESET",
                                 "Reset unit to factory default",
                                 "GMC-280, GMC-300 Re.3.00 or later",
                                 __factory_reset_verify_decoder__
                                 )

    REBOOT = Command[None]("REBOOT",
                           "Reboot unit.",
                           "GMC-280, GMC-300 Re.3.00 or later",
                           None
                           )

    GETDATETIME = Command[datetime.datetime]("GETDATETIME",
                                             "Get year date and time",
                                             "GMC-280, GMC-300 Re.3.00 or later",
                                             __getdatetime_decoder__
                                             )

    GETTEMP = Command("Get temperature",
                      "Get temperature",
                      "GMC-320 Re.3.01 or later",
                      __gettemp_decoder__
                      )

    POWERON = Command[None]("POWERON",
                            "Power ON",
                            "GMC-280, GMC-300, GMC-320 Re.3.10 or later",
                            None
                            )

    GETGYRO = Command("GETGYRO",
                      "Get gyroscope data",
                      "GMC-320 Re.3.01 or later",
                      __getgyro_decoder__
                      )

    SENDKEY = Command("SENDKEY",
                      "Send a key press to the unit.",
                      "GMC-300 Re.2.0x, Re.2.10 or later",
                      None,
                      __sendkey_encoder__
                      )

    SETDATEYY = Command("SETDATEYY",
                        "Set realtime clock year",
                        "GMC-280, GMC-300 Re.2.23 or later",
                        __set_date_decoder__,
                        __set_date_encoder__,
                        __within_bounds_verifier__(0, 255)
                        )

    SETDATEMM = Command("SETDATEMM",
                        "Set realtime clock month",
                        "GMC-280, GMC-300 Re.2.23 or later",
                        __set_date_decoder__,
                        __set_date_encoder__,
                        __within_bounds_verifier__(1, 12)
                        )

    SETDATEDD = Command("SETDATEDD",
                        "Set realtime clock day",
                        "GMC-280, GMC-300 Re.2.23 or later",
                        __set_date_decoder__,
                        __set_date_encoder__,
                        __within_bounds_verifier__(1, 31)
                        )

    SETTIMEHH = Command("SETTIMEHH",
                        "Set realtime clock hour",
                        "GMC-280, GMC-300 Re.2.23 or later",
                        __set_date_decoder__,
                        __set_date_encoder__,
                        __within_bounds_verifier__(0, 23)
                        )

    SETTIMEMM = Command("SETTIMEMM",
                        "Set realtime clock minute",
                        "GMC-280, GMC-300 Re.2.23 or later",
                        __set_date_decoder__,
                        __set_date_encoder__,
                        __within_bounds_verifier__(0, 59)
                        )

    SETTIMESS = Command("SETTIMESS",
                        "Set realtime clock second",
                        "GMC-280, GMC-300 Re.2.23 or later",
                        __set_date_decoder__,
                        __set_date_encoder__,
                        __within_bounds_verifier__(0, 59)
                        )

    SETDATETIME = Command("SETDATETIME",
                          "Set year date and time",
                          "GMC-280, GMC-300 Re.3.00 or later",
                          __setdatetime_decoder__,
                          __setdatetime_encoder__,
                          )


# list of availabe baudrates
__BAUDRATES__ = [1200,
                 2400,
                 4800,
                 9600,
                 14400,
                 19200,
                 28800,
                 38400,
                 57600,
                 115200
                 ]


def __run_heartbeat__(port: serial.Serial, callback: Callable[[int], None], condition: Callable[[], bool]) -> None:
    """
    Runs the callback callable until the condition callable returns false.
    """
    while condition():
        callback(__ushort_decoder__(port) & 0x3FFF)


def __guess_baudrate__(serial_name, self):
    """
    Attempt to guess the baudrate of the device. If none match in __BAUDRATES__, this will throw an exception.
    """
    for baudrate in __BAUDRATES__[::-1]:  # reverse so highest comes first.
        with serial.Serial(serial_name, baudrate) as port:
            port.write(Command.CMD_GETVER)
            sleep(0.1)  # give the unit time to reply
            text = port.read_all()
            if len(text) == 14:
                return baudrate

    raise Exception("Can't determine baudrate.")


class GQGCM1201:
    """
    Wrapper class for command communication with the GQ GCM unit.
    This class implements __enter__ and __exit__ for automatic scoping.
    """
    def __init__(self, serial_name: str, baudrate: int = None):
        """
        serial_name has to be a valid string to pass to the Serial library.
        If baudrate is not specified, the __guess_baudrate__ method is used to guess the baudrate.
        """
        self.serial_name = serial_name
        if baudrate is None:
            self.baudrate = __guess_baudrate__(serial_name, baudrate)
        else:
            self.baudrate = baudrate

        self.serial = serial.Serial(self.serial_name, self.baudrate)
        self.is_locked = False         # Flag whether an ongoing operation like heartbeat listening is locking the class / serial port.
        self.heartbeat_thread = None   # Heartbeat thread reference.
        self.process_heartbeat = False # Flag used to signal to the external thread listening for the serial communication on the serial port whether to keep going or stop.

    def __check_lock__(self):
        if self.is_locked:
            raise Exception("Device locked by another operation.")

    def __check_and_acquire_lock__(self):
        self.__check_lock__()
        self.is_locked = True

    def __release_lock__(self):
        self.is_locked = False

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        self.close()

    def close(self):
        """
        Close the serial port, and clean up the class. After this operation the object will be invalid and any further usage that needs serial communication will result in an error.
        """
        self.disable_heartbeat()
        self.serial.close()

    def get_version(self):
        self.__check_lock__()
        return Commands.GETVER.execute(self.serial)

    def get_counts_per_minute(self):
        self.__check_lock__()
        return Commands.GETCPM.execute(self.serial)

    def get_voltage(self):
        self.__check_lock__()
        return Commands.GETVOLT.execute(self.serial)

    def get_configuration(self):
        self.__check_lock__()
        return Commands.GETCFG.execute(self.serial)

    def get_datetime(self):
        self.__check_lock__()
        return Commands.GETDATETIME.execute(self.serial)

    def erase_configuration(self):
        self.__check_lock__()
        return Commands.ECFG.execute(self.serial)

    def get_serial(self):
        self.__check_lock__()
        return Commands.GETSERIAL.execute(self.serial)

    def power_off(self):
        self.__check_lock__()
        Commands.POWEROFF.execute(self.serial)

    def factory_reset(self):
        self.__check_lock__()
        Commands.FACTORYRESET.execute(self.serial)

    def reboot(self):
        self.__check_lock__()
        Commands.REBOOT.execute(self.serial)

    def get_temperature(self):
        self.__check_lock__()
        return Commands.GETTEMP.execute(self.serial)

    def power_on(self):
        self.__check_lock__()
        return Commands.POWERON.execute(self.serial)

    def get_history_data(self, address, length_in_bytes):
        return Commands.SPIR.execute(self.serial, address, length_in_bytes)

    def enable_heartbeat(self, callback: Callable[[int], None]):
        """
        Enables the heartbeat functionality of the GQ GCM unit. The callback will be called with the provided value of the unit every second.
        """
        self.__check_and_acquire_lock__()
        self.process_heartbeat = True

        def runnable(): return __run_heartbeat__(
            self.serial, callback, lambda: self.process_heartbeat)

        self.heartbeat_thread = Thread(
            target=runnable, name="Heartbeat-Thread", daemon=True)
        Commands.HEARTBEAT_ON.execute(self.serial)
        self.heartbeat_thread.start()

    def disable_heartbeat(self):
        """
        Disables the heartbeat functionality of the GQ GCM unit.
        """
        self.process_heartbeat = False
        if self.heartbeat_thread:
            self.heartbeat_thread.join()
        self.heartbeat_thread = None
        self.__release_lock__()

    def write_configuration(self, address: int, value: int):
        """
        Writes a single byte as configuration to the GQ GCM unit. Address and value have to be within the configuration space. 0 <= address < 256 and 0 <= value < 256
        """
        Commands.WCFG.execute(self.serial, address, value)

    def set_year(self, year: int) -> None:
        Commands.SETDATEYY.execute(self.serial, year)

    def set_month(self, month: int) -> None:
        Commands.SETDATEMM.execute(self.serial, month)

    def set_day(self, day: int) -> None:
        Commands.SETDATEDD.execute(self.serial, day)

    def set_hour(self, hour: int) -> None:
        Commands.SETTIMEYY.execute(self.serial, hour)

    def set_minute(self, minute: int) -> None:
        Commands.SETTIMEMM.execute(self.serial, minute)

    def set_second(self, second: int) -> None:
        Commands.SETTIMESS.execute(self.serial, second)

    def set_datetime(self, dt: datetime.datetime) -> None:
        Commands.SETDATETIME.execute(
            self.serial, dt.year - 2000, dt.month, dt.day, dt.hour, dt.minute, dt.second)

    def update_configuration(self) -> None:
        Commands.CFGUPDATE.execute(self.serial)

    def send_key(self, soft_key_idx: int) -> None:
        Commands.SENDKEY.execute(self.serial, soft_key_idx)
