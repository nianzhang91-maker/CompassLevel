from machine import I2C
import time

class QMC5883L:
    def __init__(self, i2c, addr=0x0D):
        self.i2c = i2c
        self.addr = addr
        self.init()
    
    def init(self):
        # ★ 关键: 正确顺序 - 软复位 → 等待 → 配置
        # 否则 0x80 软复位会把 0x09 的配置清掉, 导致读出 0
        try:
            self.i2c.writeto_mem(self.addr, 0x0A, bytes([0x80]))  # 软复位
            time.sleep_ms(100)                                     # 等待复位完成
            self.i2c.writeto_mem(self.addr, 0x0B, bytes([0x01]))  # SET/RESET period
            self.i2c.writeto_mem(self.addr, 0x09, bytes([0x0D]))  # OSR=64, 2G, 200Hz, Continuous
            time.sleep_ms(10)
        except Exception as e:
            print("[QMC5883L] init error:", e)
    
    def read_raw(self):
        data = self.i2c.readfrom_mem(self.addr, 0x00, 6)
        
        x = (data[1] << 8) | data[0]
        y = (data[3] << 8) | data[2]
        z = (data[5] << 8) | data[4]
        
        if x >= 32768:
            x -= 65536
        if y >= 32768:
            y -= 65536
        if z >= 32768:
            z -= 65536
        
        return x, y, z
    
    def read_heading(self, declination_deg=0.0):
        x, y, z = self.read_raw()
        
        import math
        heading = math.atan2(y, x)
        
        heading += declination_deg * (math.pi / 180.0)
        
        if heading < 0:
            heading += 2 * math.pi
        if heading > 2 * math.pi:
            heading -= 2 * math.pi
        
        return heading * (180.0 / math.pi), x, y, z
