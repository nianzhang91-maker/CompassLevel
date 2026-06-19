"""MPU6050 简化驱动 (MicroPython)
- 仅支持加速度计读取 (用于水平仪)
- 陀螺仪/温度/DMP 不实现
- 默认地址 0x68 (AD0 接地)
"""
import struct
import math

class MPU6050:
    # 寄存器地址
    REG_PWR_MGMT_1 = 0x6B
    REG_ACCEL_XOUT = 0x3B
    REG_WHO_AM_I   = 0x75

    def __init__(self, i2c, addr=0x68):
        self.i2c = i2c
        self.addr = addr
        # 唤醒 MPU6050 (清除 SLEEP 位)
        try:
            self.i2c.writeto_mem(self.addr, self.REG_PWR_MGMT_1, b'\x00')
        except Exception as e:
            print("[MPU6050] wake error:", e)

    def read_accel(self):
        """读取加速度 (单位: g, 范围 ±2g)
        返回 (ax, ay, az)
        """
        try:
            data = self.i2c.readfrom_mem(self.addr, self.REG_ACCEL_XOUT, 6)
            ax = struct.unpack('>h', data[0:2])[0] / 16384.0
            ay = struct.unpack('>h', data[2:4])[0] / 16384.0
            az = struct.unpack('>h', data[4:6])[0] / 16384.0
            return ax, ay, az
        except Exception as e:
            print("[MPU6050] read error:", e)
            return 0.0, 0.0, 1.0  # 返回默认值 (z=1g 表示水平)

    def read_tilt(self):
        """
        读取倾斜角 (单位: 度)
        返回 (roll, pitch):
          roll  = 左右倾斜 (-90 ~ 90), 0 = 水平
          pitch = 前后倾斜 (-90 ~ 90), 0 = 水平
        """
        ax, ay, az = self.read_accel()
        # Roll: 绕 X 轴旋转 (左右倾斜)
        roll = math.atan2(ay, az) * 180.0 / math.pi
        # Pitch: 绕 Y 轴旋转 (前后倾斜)
        pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az)) * 180.0 / math.pi
        return roll, pitch
