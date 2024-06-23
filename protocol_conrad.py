#!/usr/bin/env python3
import serial # pip install pyserial
import time
import logging
__author__="Robert Detlof"

log = logging.getLogger("Protocol Conrad")

class CommandCodes:
    NOOP = 0
    SETUP = 1
    GETPORT = 2
    SETPORT = 3
    GETOPTION = 4
    SETOPTION = 5
    SETSINGLE = 6
    DELSINGLE = 7
    TOGGLE = 8

    def get_label(index):
        label_dict = {
            CommandCodes.NOOP: "NOOP",
            CommandCodes.SETUP: "SETUP",
            CommandCodes.GETPORT: "GETPORT",
            CommandCodes.SETPORT: "SETPORT",
            CommandCodes.GETOPTION: "GETOPTION",
            CommandCodes.SETOPTION: "SETOPTION",
            CommandCodes.SETSINGLE: "SETSINGLE",
            CommandCodes.DELSINGLE: "DELSINGLE",
            CommandCodes.TOGGLE: "TOGGLE"
        }

        return label_dict[index]


class ResponseCodes:
    NOOP = 255
    SETUP = 254
    GETPORT = 253
    SETPORT = 252
    GETOPTION = 251
    SETOPTION = 250
    SETSINGLE = 249
    DELSINGLE = 248
    TOGGLE = 247


def byte_to_flags(val: int):

    if val < 0 or val > 255:
        raise Exception("Trued to turn int to flags out of ubyte range")

    flags = [ False, False, False, False, False, False, False, False]

    for i in range(0, 8):
        flags[i] = bool( ( val >> i ) & 0x1 )
    
    return flags

def flags_to_byte(flags: list[bool]):
    res = 0
    for f in reversed(flags):
        res = res << 1
        res |= int(f)
            
    return res

def index_to_flag_mask(index: int):
    flags = [ False, False, False, False, False, False, False, False]
    
    if index < 0 and index > len(flags):
        raise Exception("Tried to create flag mask out of index range")
    
    flags[index] = True

    return flags

def index_to_byte_mask(index: int):
    return flags_to_byte(index_to_flag_mask(index))

class ConradSerialFrame:
    def __init__(self, command: int, address: int, data: int) -> None:
        self.command = bytearray(command.to_bytes(1, 'little'))
        self.address = bytearray(address.to_bytes(1, 'little'))
        self.data = bytearray(data.to_bytes(1, 'little'))

    def get_data(self):
        return self.data[0]
    
    def is_response(self):
        return (self.get_command() & 0xf0) != 0
    
    def get_command(self):
        return self.command[0]
    
    def get_data_flags(self):
        return byte_to_flags(self.data[0])

    def _checksum(self):
        return self.command[0] ^ self.address[0] ^ self.data[0]

    def get_bytes(self):
        return b"" + self.command + self.address + self.data + self._checksum().to_bytes(1, 'little')
    
    def __str__(self) -> str:
        command = self.get_command()
        if self.is_response():
            command = 255 - command

        command_label = CommandCodes.get_label(command)

        return f"{hex(self.get_command())} {command_label} {self.get_data_flags()}"


class ConradRelayCard:

    def __init__(self) -> None:
        self.connection = None


    def hacky_set_relays(self, card_id=0, relay_flags_bool=[]):
        flag_int = flags_to_byte(relay_flags_bool)
        response = self._set_all_relays(card_id=card_id, relay_flags=flag_int)
        
        response_flags = response.get_data_flags()

        return response_flags


    def _set_all_relays(self, card_id=0, relay_flags=0):
        request_frame = ConradSerialFrame(CommandCodes.SETPORT, card_id, relay_flags)
        return self._communicate(request_frame)

    def _enable_single_relay(self, card_id=0, relay_flags=0):
        request_frame = ConradSerialFrame(CommandCodes.SETSINGLE, card_id, relay_flags)
        return self._communicate(request_frame)

    def _disable_single_relay(self, card_id=0, relay_flags=0):
        request_frame = ConradSerialFrame(CommandCodes.DELSINGLE, card_id, relay_flags)
        return self._communicate(request_frame)
    
    def _communicate(self, request_frame):
        if self.connection == None or not self.connection.is_open:
            raise Exception("Could not open serial connection")
        
        self.connection.reset_input_buffer()
        self.connection.reset_output_buffer()

        log.info(f"[REQUEST] {str(request_frame)}")

        self.connection.write(request_frame.get_bytes())


        last_read = bytearray(self.connection.read(size=4))

        while len(last_read) > 0 and last_read[0] < 0xf0:
            log.debug(f"discarding: {last_read}")
            last_read = bytearray(self.connection.read(size=4))

        log.debug(f"last_read: {last_read}")

        response_frame_raw = bytearray(last_read)

        if len(response_frame_raw) < 4:
            raise ConnectionError("Response truncated")
        
        response_frame = ConradSerialFrame(response_frame_raw[0], response_frame_raw[1], response_frame_raw[2])
        
        log.info(f"[RESPONSE] {response_frame}")

        time.sleep(.1)

        return response_frame
    

    def enable_relay_by_index(self, card_id, index):
        flag_int = index_to_byte_mask(index)
        return self._enable_single_relay(card_id, flag_int)

    def disable_relay_by_index(self, card_id, index):
        flag_int = index_to_byte_mask(index)
        return self._disable_single_relay(card_id, flag_int)

    def enable_all_relays(self, card_id=0):
        return self._set_all_relays(card_id, relay_flags=255)

    def disable_all_relays(self, card_id=0):
        return self._set_all_relays(card_id, relay_flags=0)

    def check_relay_state(self, card_id=0):
        request = ConradSerialFrame(CommandCodes.GETPORT, card_id, 0)
        response = self._communicate(request)

        if not response.is_response():
            raise Exception("Received non-response")
        
        if (255 - response.get_command()) != request.get_command():
            raise Exception("Received wrong response for request")
        
        return response.get_data_flags()
    
    def pulse(self, card_id=0):
        state_flags = self.check_relay_state(card_id=card_id)
        time.sleep(0.1)
        
        state_flags[5] = True
        state_flags[6] = True
        state_flags[7] = True
        state_int = flags_to_byte(state_flags)
        self._set_all_relays(card_id=0, relay_flags=state_int)
        
        time.sleep(0.5)

        state_flags[5] = False
        state_flags[6] = False
        state_flags[7] = False
        state_int = flags_to_byte(state_flags)
        self._set_all_relays(card_id=card_id, relay_flags=state_int)

        return state_flags

    def connect(self, com_port):
        #port = "COM5"
        port = com_port

        self.connection = serial.Serial(
            port,
            baudrate=19200,
            parity=serial.PARITY_NONE,
            bytesize=serial.EIGHTBITS,
            stopbits=serial.STOPBITS_ONE,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
            timeout=1,
            )
        
        
        log.debug(f"self.connection.is_open: {self.connection.is_open}")

        if self.connection == None or not self.connection.is_open:
            raise ConnectionError("Could not open serial connection")

        self.connection.reset_input_buffer()
        self.connection.reset_output_buffer()


    def shutdown(self):
        if self.connection != None:
            self.connection.close()