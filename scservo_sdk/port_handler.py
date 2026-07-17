#!/usr/bin/env python

import time
import serial
import sys
import platform

DEFAULT_BAUDRATE = 1000000
LATENCY_TIMER = 50 

class PortHandler(object):
    def __init__(self, port_name):
        self.is_open = False
        self.baudrate = DEFAULT_BAUDRATE
        self.packet_start_time = 0.0
        self.packet_timeout = 0.0
        self.tx_time_per_byte = 0.0

        self.is_using = False
        self.port_name = port_name
        self.ser = None

    def openPort(self):
        return self.setBaudRate(self.baudrate)

    def closePort(self):
        if self.ser is not None:
            try:
                if self.ser.is_open:
                    # 清空缓冲区后再关闭，避免 Windows 下句柄未完全释放
                    try:
                        self.ser.reset_input_buffer()
                        self.ser.reset_output_buffer()
                    except Exception:
                        pass
                    self.ser.close()
            except Exception:
                pass
            finally:
                self.ser = None
        self.is_open = False

        # Windows 需要一点时间才能真正释放 COM 端口句柄
        if platform.system() == "Windows":
            time.sleep(0.2)

    def clearPort(self):
        if self.ser is not None and self.ser.is_open:
            self.ser.flush()

    def setPortName(self, port_name):
        self.port_name = port_name

    def getPortName(self):
        return self.port_name

    def setBaudRate(self, baudrate):
        baud = self.getCFlagBaud(baudrate)

        if baud <= 0:
            # self.setupPort(38400)
            # self.baudrate = baudrate
            return False  # TODO: setCustomBaudrate(baudrate)
        else:
            self.baudrate = baudrate
            return self.setupPort(baud)

    def getBaudRate(self):
        return self.baudrate

    def getBytesAvailable(self):
        return self.ser.in_waiting

    def readPort(self, length):
        if (sys.version_info > (3, 0)):
            return self.ser.read(length)
        else:
            return [ord(ch) for ch in self.ser.read(length)]

    def writePort(self, packet):
        return self.ser.write(packet)

    def setPacketTimeout(self, packet_length):
        self.packet_start_time = self.getCurrentTime()
        self.packet_timeout = (self.tx_time_per_byte * packet_length) + (self.tx_time_per_byte * 3.0) + LATENCY_TIMER

    def setPacketTimeoutMillis(self, msec):
        self.packet_start_time = self.getCurrentTime()
        self.packet_timeout = msec

    def isPacketTimeout(self):
        if self.getTimeSinceStart() > self.packet_timeout:
            self.packet_timeout = 0
            return True

        return False

    def getCurrentTime(self):
        return round(time.time() * 1000000000) / 1000000.0

    def getTimeSinceStart(self):
        time_since = self.getCurrentTime() - self.packet_start_time
        if time_since < 0.0:
            self.packet_start_time = self.getCurrentTime()

        return time_since

    def setupPort(self, cflag_baud):
        if self.is_open:
            self.closePort()

        # Windows 下 closePort 已经加了 0.2s 延迟，这里再加一层保险
        if platform.system() == "Windows":
            time.sleep(0.1)

        self.ser = serial.Serial(
            port=self.port_name,
            baudrate=self.baudrate,
            # parity = serial.PARITY_ODD,
            # stopbits = serial.STOPBITS_TWO,
            bytesize=serial.EIGHTBITS,
            timeout=0
        )

        self.is_open = True

        self.ser.reset_input_buffer()

        self.tx_time_per_byte = (1000.0 / self.baudrate) * 10.0

        return True

    def getCFlagBaud(self, baudrate):
        if baudrate in [4800, 9600, 14400, 19200, 38400, 57600, 115200, 128000, 250000, 500000, 1000000]:
            return baudrate
        else:
            return -1          