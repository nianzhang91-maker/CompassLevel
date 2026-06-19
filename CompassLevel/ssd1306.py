"""
SSD1306 OLED 显示屏驱动 (MicroPython)
基于: github.com/micropython/micropython/drivers/display/ssd1306.py
适配: 7 针 I2C 接口的 128x64 / 128x32 OLED
关键修复: 添加 0x8D 0x14 (电荷泵使能) - 解决"屏幕不亮"问题
"""

from micropython import const
import framebuf
import time

# ==================== SSD1306 命令集 ====================
SET_CONTRAST        = const(0x81)
SET_ENTIRE_ON       = const(0xA4)   # 正常: 从 RAM 读取
SET_ENTIRE_ON_FORCE = const(0xA5)   # 强制: 全部像素 ON (测试模式)
SET_NORM_INV        = const(0xA6)   # 正常
SET_NORM_INV_INV    = const(0xA7)   # 反转
SET_DISP            = const(0xAE)   # 0xAE=关, 0xAF=开
SET_MEM_ADDR        = const(0x20)
SET_COL_ADDR        = const(0x21)
SET_PAGE_ADDR       = const(0x22)
SET_DISP_START_LINE = const(0x40)
SET_SEG_REMAP       = const(0xA0)   # 0xA0=正常, 0xA1=重映射
SET_MUX_RATIO       = const(0xA8)
SET_COM_OUT_DIR     = const(0xC0)   # 0xC0=正常, 0xC8=反转
SET_DISP_OFFSET     = const(0xD3)
SET_COM_PIN_CFG     = const(0xDA)
SET_DISP_CLK_DIV    = const(0xD5)
SET_PRECHARGE       = const(0xD9)
SET_VCOM_DESEL      = const(0xDB)
SET_CHARGE_PUMP     = const(0x8D)   # 关键: 电荷泵
SET_DEACT_SCROLL    = const(0x2E)   # 关闭滚动
SET_SOFT_RESET      = const(0xE2)   # 软件复位


class SSD1306(framebuf.FrameBuffer):
    """
    SSD1306 OLED 基础类
    通过 framebuf 提供绘图原语
    """
    def __init__(self, width, height, external_vcc=False):
        self.width = width
        self.height = height
        self.external_vcc = external_vcc
        self.pages = self.height // 8
        self.buffer = bytearray(self.pages * self.width)
        super().__init__(self.buffer, self.width, self.height, framebuf.MONO_VLSB)

    def init_display(self):
        """
        完整初始化序列 - 包含所有关键命令
        关键修复: 添加 SET_CHARGE_PUMP (0x8D 0x14)
        """
        # 1) 软件复位 - 确保从干净状态开始
        self.write_cmd(SET_SOFT_RESET)
        time.sleep_ms(10)

        # 2) 关闭显示 (在配置过程中关闭)
        self.write_cmd(SET_DISP | 0x00)
        time.sleep_ms(10)

        # 3) 主配置序列
        for cmd in (
            SET_MEM_ADDR, 0x00,           # 水平寻址模式
            SET_DISP_START_LINE | 0x00,   # 起始行 0
            SET_SEG_REMAP | 0x01,         # 列 127 -> SEG0
            SET_MUX_RATIO, self.height - 1,
            SET_COM_OUT_DIR | 0x08,       # COM[N-1] -> COM0
            SET_DISP_OFFSET, 0x00,
            SET_COM_PIN_CFG, 0x02 if self.height == 32 else 0x12,
            SET_DISP_CLK_DIV, 0x80,
            SET_PRECHARGE, 0x22 if self.external_vcc else 0xF1,
            SET_VCOM_DESEL, 0x30,
            # ★ 关键修复 ★ 启用电荷泵 (3.3V 供电必需!)
            SET_CHARGE_PUMP, 0x14,
            SET_DEACT_SCROLL,             # 关闭滚动
            SET_CONTRAST, 0xFF,           # 最大对比度
            SET_ENTIRE_ON,                # 0xA4 - 正常显示 RAM
            SET_NORM_INV,                 # 0xA6 - 正常 (非反转)
        ):
            self.write_cmd(cmd)

        # 等待内部电路稳定
        time.sleep_ms(100)

        # 4) 开启显示
        self.write_cmd(SET_DISP | 0x01)
        time.sleep_ms(50)

    def poweroff(self):
        """关闭显示 (省电)"""
        self.write_cmd(SET_DISP | 0x00)

    def poweron(self):
        """开启显示"""
        self.write_cmd(SET_DISP | 0x01)

    def contrast(self, contrast):
        """设置对比度 (0-255)"""
        self.write_cmd(SET_CONTRAST)
        self.write_cmd(contrast)

    def invert(self, invert):
        """反转显示"""
        self.write_cmd(SET_NORM_INV | (invert & 1))

    def force_all_on(self):
        """测试模式: 强制全部像素亮起 (忽略 RAM)"""
        self.write_cmd(SET_ENTIRE_ON_FORCE)  # 0xA5

    def force_all_off(self):
        """测试模式结束: 恢复从 RAM 读取"""
        self.write_cmd(SET_ENTIRE_ON)  # 0xA4

    def show(self):
        """将 framebuffer 推送到 OLED 屏幕"""
        x0, x1 = 0, self.width - 1
        if self.width == 64:
            x0 += 32
            x1 += 32
        self.write_cmd(SET_COL_ADDR)
        self.write_cmd(x0)
        self.write_cmd(x1)
        self.write_cmd(SET_PAGE_ADDR)
        self.write_cmd(0)
        self.write_cmd(self.pages - 1)
        self.write_framebuf()


class SSD1306_I2C(SSD1306):
    """
    SSD1306 I2C 接口驱动
    默认地址 0x3C, 大多数 128x64 OLED 模块都使用此地址
    """
    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False):
        self.i2c = i2c
        self.addr = addr
        # 预分配带控制字节的缓冲区 (优化 I2C 传输)
        self.data = bytearray(1 + width * height // 8)
        super().__init__(width, height, external_vcc)
        self.init_display()
        self.fill(0)
        self.show()

    def write_cmd(self, cmd):
        """写入命令 (Co=1, D/C#=0)"""
        self.data[0] = 0x80
        self.data[1] = cmd
        self.i2c.writeto(self.addr, self.data[:2])

    def write_framebuf(self):
        """写入完整帧缓冲 (单次 I2C 事务)"""
        self.data[0] = 0x40  # Co=0, D/C#=1 (数据)
        self.data[1:] = self.buffer
        self.i2c.writeto(self.addr, self.data)

    def write_data(self, buf):
        """写入数据 (用于部分更新)"""
        self.data[0] = 0x40
        for i, b in enumerate(buf):
            self.data[1 + i] = b
        self.i2c.writeto(self.addr, self.data[:1 + len(buf)])
