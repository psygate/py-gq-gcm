# py-gq-gcm
A python library for communication with GQ Geiger Counters.

## Source

https://www.gqelectronicsllc.com/download/GQ-RFC1201.txt

## Usage

There are 2 ways of using the library. Either by using the provided wrapper class GQGCM1201 or by directly invoking the commands on a serial connection.

### Using the wrapper:
```
import datettime
from time import sleep


with GQGCM1201("/dev/ttyUSB0", 57600) as gq:
    gq.set_datetime(datetime.datetime.now())
    gq.reboot()
    sleep(5)
    gq.send_key(0)
    gq.power_off()
```

### Using Commands:

```
import serial
import struct
import datetime
from threading import Thread


serial = serial.Serial("/dev/ttyUSB0", 57600)
Commands.SETDATETIME.execute(serial, datetime.datetime.now())
COMMANDS.REBOOT.execute(serial)
sleep(5)
COMMANDS.SENDKEY.execute(serial, 0)
COMMANDS.POWEROFF.execute(serial)
```

## Internals

* ### Baudrate guessing
    If no baudrate is supplied to the GQGCM1201 class, it will try to guess the right one, by querying the version string over and over again. This may take a while but is better than nothing.

* ### Datetime API
    The datetime api is as good as it can be, with some validation built in. As far as I can tell the units and devices themselves to not validate date settings (0 month is valid and displayed, but makes no sense). So the commands themselves do some validation.

* ###  Architecture
    The architecture is modular. Commands are just objects that unify some behaviour, with specifics delegated to callbacks.
    