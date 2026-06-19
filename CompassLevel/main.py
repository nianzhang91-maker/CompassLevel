"""
================================================================================
  数字罗盘与水平仪 - SSD1306 OLED 显示版
  平台: ESP32-S3 + QMC5883L + SSD1306 128x64 OLED
  功能: 3级菜单系统 + 罗盘 + 水平仪
================================================================================

【硬件接线表】
+---------------+----------+----------------------+
| SSD1306 OLED  |          | 说明                 |
+---------------+----------+----------------------+
| VCC           | 3.3V     | 电源                 |
| GND           | GND      | 地线                 |
| SDA           | GPIO14   | I2C 数据             |
| SCL           | GPIO13   | I2C 时钟             |
+---------------+----------+----------------------+
| QMC5883L      |          |                      |
+---------------+----------+----------------------+
| VCC           | 3.3V     |                      |
| GND           | GND      |                      |
| SDA           | GPIO14   |                      |
| SCL           | GPIO13   |                      |
+---------------+----------+----------------------+
| MPU6050       |          |                      |
+---------------+----------+----------------------+
| VCC           | 3.3V     |                      |
| GND           | GND      |                      |
| SDA           | GPIO14   |                      |
| SCL           | GPIO13   |                      |
+---------------+----------+----------------------+

【I2C 设备地址】
SSD1306 OLED: 0x3C 
 QMC5883L   : 0x0D
MPU6050     ：0X68 

【3级菜单结构】
Level 1 (主菜单)        Level 2 (子菜单)              Level 3 (功能/显示)
MAIN MENU          →    COMPASS                  →     罗盘实时显示
   Compass         →    ├ Show Compass           →     返回: 长按 BOOT
   Gradienter      →    ├ Plane Calib            →     校准提示
   Settings        →    ├ Reset Heading          →     重置指北
                       └ Back                   →     返回主菜单
                       GRADIENTER               →     水平仪实时显示
                       └ Show Gradienter        →     
                       SETTINGS                 →
                       ├ About                  →     系统硬件信息
                       └ Back

【按键操作】
- 短按 BOOT : 向下移动菜单项
- 长按 BOOT : 确认/进入/返回
================================================================================
"""

from machine import Pin, SoftI2C, I2C
import time
import math
from ssd1306 import SSD1306_I2C
from qmc5883l import QMC5883L

#---------------引脚定义---------------
BOOT_PIN       = 0
I2C_SDA_OLED   = 14   # OLED SDA (SoftI2C)
I2C_SCL_OLED   = 13   # OLED SCL (SoftI2C)
I2C_SDA_MAG    = 8    # 磁力计 SDA
I2C_SCL_MAG    = 9    # 磁力计 SCL

#---------------显示参数---------------
DISP_W = 128
DISP_H = 64
CX, CY = 32, 30
R      = 24

#---------------按键参数---------------
DEBOUNCE_MS   = 50
LONG_PRESS_MS = 500

#---------------3级菜单结构---------------
MENUS = {
    "main": [
        ("Compass",    "menu",   "compass_menu"),
        ("Gradienter", "menu",   "gradienter_menu"),
        ("Settings",   "menu",   "settings_menu"),
    ],
    "compass_menu": [
        ("Compass",   "action", "show_compass"),
        ("Plane Calib", "action", "do_plane_calib"),
        ("Reset Heading",  "action", "do_reset_heading"),
        ("Back",           "back",   None),
    ],
    "gradienter_menu": [
        ("Gradienter", "action", "show_gradienter"),
        ("Back",            "back",   None),
    ],
    "settings_menu": [
        ("About", "action", "show_about"),
        ("Back",  "back",   None),
    ],
}

MENU_TITLES = {
    "main":            "MENU",
    "compass_menu":    "Compass",
    "gradienter_menu": "Gradienter",
    "settings_menu":   "Settings",
}

# ---------------状态机设定---------------
STATE_MAIN    = 0
STATE_SUB     = 1
STATE_DISPLAY = 2

state             = STATE_MAIN
current_menu_id   = "main"
current_index     = 0
menu_stack        = []
display_type      = None
menu_dirty        = True

"""
状态机 大概原理图
┌─────────────┐    长按菜单项     ┌─────────────┐
│  STATE_MAIN │ ───────────────→ │  STATE_SUB  │
│  (主菜单)    │                  │  (子菜单)   │
└─────────────┘ ←─────────────── └─────────────┘
                  长按 Back
                       │
                       │ 长按 show_*
                       ▼
                ┌───────────── ┐
                │ STATE_DISPLAY│
                │ (功能显示)    │
                └───────────── ┘
                       │
                       │ 长按 (返回)
                       └──────────→ STATE_SUB
"""
#罗盘参数
smooth_angle = 0
first_read   = True

# ---------------XY平面校准参数---------------
# 用户在水平桌面旋转设备采集 360° 数据
# 校准结果:椭圆拟合中心+旋转角度
plane_offset_x = 0    # 椭圆中心 X
plane_offset_y = 0    # 椭圆中心 Y
plane_rotation = 0.0  # 平面旋转补偿 (弧度)
plane_calibrated = False
heading_offset  = 0.0  # 指北偏差 (用户对准真北时记录)
plane_quality   = 0    # 校准质量 (0-100)

#---------------磁力计错误恢复---------------
mag_error_count    = 0
MAX_MAG_ERRORS     = 5     # 连续错误次数阈值
MAG_RETRY_INTERVAL = 3000  # 错误后等待时间 (ms)
last_mag_attempt   = 0
last_good_heading  = (0, 0, 0, 0)  # 缓存上一次有效数据
debug_print_counter = 0  # REPL 调试输出计数器
last_raw_x, last_raw_y, last_raw_z = 0, 0, 0  # 调试用原始值

#---------------硬件初始化与诊断---------------
print("Digital Compass starting...")

# OLED 和 QMC5883L 共用单总线 (GPIO14/13)
i2c = SoftI2C(sda=Pin(I2C_SDA_OLED), scl=Pin(I2C_SCL_OLED), freq=100000)
print("I2C: SoftI2C @ GPIO{},{} (OLED + QMC5883L 共用)".format(I2C_SDA_OLED, I2C_SCL_OLED))

# 总线引用
i2c_oled = i2c
i2c_mag = i2c

def i2c_recover(scl_pin_no, sda_pin_no):
    """软件复位 I2C 总线: 切 SCL 9 次发送 STOP, 释放卡住的从机"""
    try:
        scl = Pin(scl_pin_no, Pin.OPEN_DRAIN, Pin.PULL_UP)
        sda = Pin(sda_pin_no, Pin.OPEN_DRAIN, Pin.PULL_UP)
        for _ in range(9):
            scl.value(0); time.sleep_us(5)
            scl.value(1); time.sleep_us(5)
        # 手动发 STOP: SDA low -> SCL high -> SDA high
        sda.value(0); time.sleep_us(5)
        scl.value(1); time.sleep_us(5)
        sda.value(1); time.sleep_us(5)
    except Exception as e:
        print("[i2c_recover] error:", e)

# 进度条参数 (为了减少设备运行负担，这只是纯时间驱动动画，跑完9s即初始化完毕进入菜单MENU)
# 进度条:  9 秒匀速
LOAD_BAR_DURATION_MS = 9000   # 动画总时长
LOAD_BAR_REFRESH_MS  = 30     # 刷新间隔 (9000/30 = 300 帧)
load_bar_start_ms    = time.ticks_ms()

def draw_loading_screen():
    
    if oled is None:
        return
    elapsed = time.ticks_diff(time.ticks_ms(), load_bar_start_ms)
    # 裁剪到 [0, 9000] ms 范围
    if elapsed < 0:
        elapsed = 0
    if elapsed > LOAD_BAR_DURATION_MS:
        elapsed = LOAD_BAR_DURATION_MS
    # 匀速: progress = elapsed / 9000 * 100
    progress = int(elapsed * 100 / LOAD_BAR_DURATION_MS)

    oled.fill(0)
    # 标题
    oled.text("Loading", 40, 12, 1)
    # 进度条边框
    bar_x, bar_y = 8, 30
    bar_w, bar_h = 112, 14
    oled.rect(bar_x, bar_y, bar_w, bar_h, 1)
    # 进度条内部填充
    fill_w = int((bar_w - 2) * progress / 100)
    if fill_w > 0:
        oled.fill_rect(bar_x + 1, bar_y + 1, fill_w, bar_h - 2, 1)
    # 百分比文字
    oled.text("{}%".format(progress), 52, 50, 1)
    oled.show()

# 启动进度条动画 (t = 0) 
# 实际加载步骤在动画更新间穿插, 但不影响进度条速度

# I2C 总线扫描
all_devices = []
for retry in range(3):
    all_devices = i2c.scan()
    if all_devices:
        break
    time.sleep_ms(200)
print("I2C scan: {}".format(["0x{:02X}".format(d) for d in all_devices]))

# 自动检测 OLED 地址
oled_addr = None
for addr in [0x3C, 0x3D]:
    if addr in all_devices:
        oled_addr = addr
        break

if oled_addr is None:
    print("OLED not detected, using default 0x3C")
    oled_addr = 0x3C
else:
    print("OLED found at 0x{:02X}".format(oled_addr))

# 初始化 OLED (带重试)
oled = None
for attempt in range(3):
    try:
        oled = SSD1306_I2C(DISP_W, DISP_H, i2c_oled, addr=oled_addr)
        oled.contrast(255)
        print("OLED initialized (attempt {})".format(attempt + 1))
        break
    except Exception as e:
        print("OLED init attempt {} failed: {}".format(attempt + 1, e))
        time.sleep_ms(500)

if oled is None:
    print("OLED init failed, continuing without display")
else:
    draw_loading_screen()

#1: 磁力计初始化 
try:
    if 0x0D in all_devices:
        i2c_recover(I2C_SCL_OLED, I2C_SDA_OLED)
        time.sleep_ms(50)
        mag = QMC5883L(i2c_mag, addr=0x0D)
        time.sleep_ms(100)
        print("Magnetometer initialized at 0x0D")
    elif 0x1E in all_devices:
        i2c_recover(I2C_SCL_OLED, I2C_SDA_OLED)
        time.sleep_ms(50)
        mag = QMC5883L(i2c_mag, addr=0x1E)
        time.sleep_ms(100)
        print("HMC5883L initialized at 0x1E")
    else:
        raise Exception("QMC5883L not found")
except Exception as e:
    print("Magnetometer init failed:", e)
    mag = None

draw_loading_screen()

# 2: MPU6050 初始化
mpu = None

def init_mpu6050():
    """初始化 MPU6050 (用于水平仪), 默认地址 0x68"""
    global mpu
    try:
        from mpu6050 import MPU6050
        mpu = MPU6050(i2c, addr=0x68)
        try:
            who = i2c.readfrom_mem(0x68, 0x75, 1)[0]
            if who == 0x68:
                print("MPU6050 initialized at 0x68")
                return True
            else:
                print("MPU6050 WHO_AM_I = 0x{:02X}, expected 0x68".format(who))
                return False
        except Exception as e:
            print("MPU6050 WHO_AM_I check failed, skipping")
            return True
    except Exception as e:
        print("MPU6050 init failed:", e)
        mpu = None
        return False

init_mpu6050()
draw_loading_screen()

# 3: 磁力计快速测试
def test_magnetometer():
    """
    快速验证磁力计 (5秒, 5个样本)  
    """
    if mag is None:
        return False

    samples = []
    for i in range(5):
        draw_loading_screen()
        try:
            x, y, z = mag.read_raw()
            samples.append((x, y, z))
        except Exception as e:
            print("Mag read error:", e)
        time.sleep_ms(1000)  # 1Hz 采样

    if not samples:
        return False

    xs = [s[0] for s in samples]
    ys = [s[1] for s in samples]
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    return dx > 5 or dy > 5

test_result = test_magnetometer()
print("Mag test: {}".format("PASS" if test_result else "FAIL/QUIET"))
draw_loading_screen()

# 4: 初始化按键
boot_key = Pin(BOOT_PIN, Pin.IN, Pin.PULL_UP)
print("BOOT key initialized")
draw_loading_screen()

# 5: 动画完成阶段
# 进度条继续匀速走动直到 100% (即 t = 9000ms)
while time.ticks_diff(time.ticks_ms(), load_bar_start_ms) < LOAD_BAR_DURATION_MS:
    draw_loading_screen()
    time.sleep_ms(LOAD_BAR_REFRESH_MS)

# 动画完成后直接进入主菜单
print("Hardware ready")

# ---------------按键状态机 ---------------
key_state       = 0
key_press_start = 0
last_key_scan   = 0

def key_scan():
    global key_state, key_press_start, last_key_scan
    now = time.ticks_ms()
    if now - last_key_scan < DEBOUNCE_MS:
        return
    last_key_scan = now
    val = boot_key.value()

    if key_state == 0:
        if val == 0:
            key_press_start = now
            key_state = 1
    elif key_state == 1:
        if val == 0:
            if now - key_press_start >= LONG_PRESS_MS:
                key_state = 3
        else:
            key_state = 2
    elif key_state == 2:
        if now - key_press_start >= LONG_PRESS_MS:
            handle_long_press()
        else:
            handle_short_press()
        key_state = 0
    elif key_state == 3:
        if val != 0:
            handle_long_press()
            key_state = 0

def handle_short_press():
    global current_index, menu_dirty
    if state != STATE_DISPLAY:
        menu = MENUS[current_menu_id]
        current_index = (current_index + 1) % len(menu)
        menu_dirty = True

def handle_long_press():
    global state, current_menu_id, current_index
    global display_type, menu_stack, menu_dirty

    if state == STATE_MAIN:
        item = MENUS[current_menu_id][current_index]
        if item[1] == "menu":
            menu_stack.append((current_menu_id, current_index))
            current_menu_id = item[2]
            current_index = 0
            state = STATE_SUB
            menu_dirty = True

    elif state == STATE_SUB:
        item = MENUS[current_menu_id][current_index]
        if item[1] == "back":
            if menu_stack:
                current_menu_id, current_index = menu_stack.pop()
                state = STATE_MAIN
                menu_dirty = True
        elif item[1] == "action":
            action = item[2]
            if action.startswith("show_"):
                display_type = action
                state = STATE_DISPLAY
                menu_dirty = True
            else:
                do_action(action)
                menu_dirty = True

    elif state == STATE_DISPLAY:
        display_type = None
        state = STATE_SUB
        menu_dirty = True

def do_action(action):
    if action == "do_plane_calib":
        # XY 平面校准: 用户水平旋转设备 360°
        plane_calibration_routine()
    elif action == "do_reset_heading":
        # 重置指北偏移, 以当前朝向为北
        global heading_offset
        heading_offset = 0.0
        oled.fill(0)
        oled.text("Heading Reset", 8, 28, 1)
        oled.show()
        time.sleep_ms(800)

# ---------------XY 平面校准 (水平旋转 360°)---------------
def plane_calibration_routine():
    """
    水平旋转设备, 采集 360° 磁力计数据
    自动拟合椭圆中心, 计算最佳 XY 平面参数
    短按 BOOT 取消
    """
    global plane_offset_x, plane_offset_y, plane_calibrated, plane_quality

    if mag is None:
        oled.fill(0)
        oled.text("No Mag Sensor", 12, 28, 1)
        oled.show()
        time.sleep_ms(1500)
        return

    samples = []
    angle_sum = 0.0
    last_angle = None
    full_rotations = 0
    start_ms = time.ticks_ms()
    CAL_TIMEOUT_MS = 30000  # 30秒超时

    # 阶段 1: 准备提示
    oled.fill(0)
    oled.text("PLANE CALIB", 20, 0, 1)
    oled.text("Hold flat,", 16, 16, 1)
    oled.text("rotate 360", 16, 26, 1)
    oled.text("slowly", 30, 36, 1)
    oled.hline(0, 46, DISP_W, 1)
    oled.text("S: cancel", 36, 50, 1)
    oled.show()

    # 等待 1.5 秒让用户准备好
    prep_start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), prep_start) < 1500:
        if boot_key.value() == 0:
            time.sleep_ms(20)
            if boot_key.value() == 0:
                oled.fill(0)
                oled.text("Cancelled", 28, 28, 1)
                oled.show()
                time.sleep_ms(800)
                return
        time.sleep_ms(20)

    # 阶段 2: 采集数据
    oled.fill(0)
    oled.text("Rotating...", 24, 4, 1)
    oled.text("0%", 56, 18, 1)
    oled.hline(0, 32, DISP_W, 1)
    oled.show()

    last_show = 0
    user_stopped = False
    while time.ticks_diff(time.ticks_ms(), start_ms) < CAL_TIMEOUT_MS:
        # 短按 BOOT 提前结束采集
        if boot_key.value() == 0:
            time.sleep_ms(20)  # 防抖
            if boot_key.value() == 0:
                user_stopped = True
                break

        # 读取磁力计
        try:
            x, y, z = mag.read_raw()
        except:
            time.sleep_ms(20)
            continue

        # 跳过全 0 数据
        if x == 0 and y == 0:
            time.sleep_ms(20)
            continue

        samples.append((x, y))

        # 计算累积角度 (用于判断是否转过 360°)
        ang = math.atan2(y, x)
        if last_angle is not None:
            d = ang - last_angle
            if d > math.pi:  d -= 2 * math.pi
            if d < -math.pi: d += 2 * math.pi
            angle_sum += d
            if abs(angle_sum) > 2 * math.pi * (full_rotations + 1) - 0.3:
                full_rotations += 1
        last_angle = ang

        # 更新进度
        progress = min(100, int(abs(angle_sum) / (2 * math.pi) * 100))
        now = time.ticks_ms()
        if time.ticks_diff(now, last_show) > 100:
            last_show = now
            oled.fill_rect(0, 18, DISP_W, 14, 0)
            oled.text("{}%".format(progress), 50, 18, 1)
            oled.fill_rect(0, 36, DISP_W, 10, 0)
            bar_w = int(DISP_W * progress / 100)
            oled.fill_rect(0, 38, bar_w, 6, 1)
            oled.show()

        time.sleep_ms(20)  # 50Hz 采样

    # 阶段 3: 椭圆拟合
    if len(samples) < 10:
        oled.fill(0)
        oled.text("CAL FAIL", 30, 20, 1)
        oled.text("Too few samples", 4, 36, 1)
        oled.show()
        time.sleep_ms(1500)
        return

    # 椭圆中心 = (Xmin+Xmax)/2, (Ymin+Ymax)/2
    xs = [s[0] for s in samples]
    ys = [s[1] for s in samples]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2

    # 校准质量评估: 越接近圆越好
    rx = (max(xs) - min(xs)) / 2
    ry = (max(ys) - min(ys)) / 2
    if rx > 0 and ry > 0:
        # 椭圆度 = min(rx,ry)/max(rx,ry) * 100
        plane_quality = int(min(rx, ry) / max(rx, ry) * 100)
    else:
        plane_quality = 0

    plane_offset_x = int(cx)
    plane_offset_y = int(cy)
    plane_calibrated = True

    # 显示结果
    oled.fill(0)
    oled.text("PLANE OK", 28, 0, 1)
    oled.text("cx={}".format(plane_offset_x)[:10], 0, 16, 1)
    oled.text("cy={}".format(plane_offset_y)[:10], 0, 26, 1)
    oled.text("rx={}".format(int(rx))[:10], 0, 36, 1)
    oled.text("ry={}".format(int(ry))[:10], 0, 44, 1)
    oled.text("Q={}%".format(plane_quality), 60, 54, 1)
    oled.show()
    time.sleep_ms(2500)

# ---------------磁力计读取 (XY平面校准)---------------
def safe_mag_read():
    """
    读取磁力计方位角,  XY 平面校准
    等待 DRDY 状态位 
    应用 XY 平面校准 
    错误后重新初始化芯片
    返回: (heading_deg, raw_x, raw_y, raw_z) 或 (last_cached, ...)
    """
    global mag_error_count, last_mag_attempt, last_good_heading
    global debug_print_counter, last_raw_x, last_raw_y, last_raw_z

    if mag is None:
        return None, None, None, None

    # 错误过多时, 等待一段时间再重试
    if mag_error_count >= MAX_MAG_ERRORS:
        now = time.ticks_ms()
        if now - last_mag_attempt < MAG_RETRY_INTERVAL:
            return last_good_heading
        try:
            mag.init()
            print("[mag] reinitialized")
        except Exception as e:
            print("[mag] reinit failed:", e)
        mag_error_count = 0
        print("[mag] retrying after", MAG_RETRY_INTERVAL, "ms")

    last_mag_attempt = time.ticks_ms()

    try:
        # 等待 DRDY 数据就绪
        for _ in range(10):
            try:
                status = mag.i2c.readfrom_mem(mag.addr, 0x06, 1)
                if status and len(status) > 0 and (status[0] & 0x01):
                    break
            except:
                pass
            time.sleep_ms(10)

        # 读取原始数据
        x, y, z = mag.read_raw()
        last_raw_x, last_raw_y, last_raw_z = x, y, z

        # 应用 XY 平面校准 (椭圆中心补偿)
        if plane_calibrated:
            x_cal = x - plane_offset_x
            y_cal = y - plane_offset_y
        else:
            x_cal = x
            y_cal = y

        # 内联计算方位角
        heading_rad = math.atan2(y_cal, x_cal)
        if heading_rad < 0:
            heading_rad += 2 * math.pi
        heading_deg = heading_rad * (180.0 / math.pi)

        # 应用指北偏移
        heading_deg = (heading_deg + heading_offset) % 360.0

        if mag_error_count > 0:
            print("[mag] recovered after", mag_error_count, "errors")
        mag_error_count = 0
        last_good_heading = (heading_deg, x, y, z)

        # REPL 调试输出
        debug_print_counter += 1
        if debug_print_counter % 5 == 0:
            print("[mag] x={:6d} y={:6d} z={:6d} h={:5.1f}°".format(
                x, y, z, heading_deg))

        return last_good_heading
    except Exception as e:
        mag_error_count += 1
        print("[mag] error #{}: {}".format(mag_error_count, e))
        return last_good_heading

# ---------------绘制图像 ---------------
def draw_circle(fbuf, x0, y0, r, color=1):
    x, y, err = r, 0, 0
    while x >= y:
        fbuf.pixel(x0 + x, y0 + y, color)
        fbuf.pixel(x0 + y, y0 + x, color)
        fbuf.pixel(x0 - y, y0 + x, color)
        fbuf.pixel(x0 - x, y0 + y, color)
        fbuf.pixel(x0 - x, y0 - y, color)
        fbuf.pixel(x0 - y, y0 - x, color)
        fbuf.pixel(x0 + y, y0 - x, color)
        fbuf.pixel(x0 + x, y0 - y, color)
        y += 1
        err += 1 + 2 * y
        if 2 * (err - x) + 1 > 0:
            x -= 1
            err += 1 - 2 * x

# ---------------绘制菜单 (Level 1 和 level 2) ---------------
def draw_menu():
    oled.fill(0)
    title = MENU_TITLES.get(current_menu_id, "MENU")
    oled.text(title, 4, 2, 1)
    oled.hline(0, 12, DISP_W, 1)

    menu = MENUS[current_menu_id]
    for i, item in enumerate(menu):
        y = 16 + i * 12
        if y + 8 > DISP_H - 12:
            break
        if i == current_index:
            oled.fill_rect(0, y - 1, DISP_W, 11, 1)
            oled.text("> " + item[0], 4, y, 0)
        else:
            oled.text("  " + item[0], 4, y, 1)

    oled.hline(0, DISP_H - 12, DISP_W, 1)
    oled.text("S:next L:ok", 32, DISP_H - 9, 1)
    oled.show()

# ---------------绘制罗盘 (Level 3)---------------
def draw_compass_screen(angle, raw_x=None, raw_y=None):
    
    oled.fill(0)

    # 刻度圆环
    draw_circle(oled, CX, CY, R, 1)

    # 主刻度: 每 30° 一条短线
    for deg in range(0, 360, 30):
        rad = deg * math.pi / 180.0
        x1 = int(CX + math.cos(rad) * R)
        y1 = int(CY + math.sin(rad) * R)
        x2 = int(CX + math.cos(rad) * (R - 4))
        y2 = int(CY + math.sin(rad) * (R - 4))
        oled.line(x1, y1, x2, y2, 1)

    # 罗盘指针
    rad = angle * math.pi / 180.0
    # 北向指针
    nx = int(CX + math.sin(rad) * (R - 5))
    ny = int(CY - math.cos(rad) * (R - 5))
    oled.line(CX, CY, nx, ny, 1)
    # 中心填充圆点
    oled.fill_rect(CX - 2, CY - 2, 5, 5, 1)

    # 右侧大字角度
    deg_str = "{:3d}".format(int(angle))
    oled.text(deg_str, 70, CY - 4, 1)

    oled.show()

# ---------------绘制水平仪 (Level 3) ---------------
# 倾斜角度 -> 像素偏移的缩放系数
TILT_SCALE = 2.0
TILT_MAX_OFFSET = 30
# "水平" 判定阈值 (度)
LEVEL_THRESHOLD = 2.0

def draw_gradienter_screen():
    """
    水平仪界面:
      - 中央大圆 (校准基准)
      - 圆形中心十字准线
      - 圆形内部气泡 (随设备姿态移动)
      - 右侧显示: 上方 = 横轴 (roll) 角度, 下方 = 纵轴 (pitch) 角度
      - 水平时显示 "AP" 提示（ALL PERFECT）
    运行时完全不用QMC5883L 
    """
    oled.fill(0)

    # 计算圆心和半径
    cx, cy = DISP_W // 2, DISP_H // 2
    radius = min(DISP_W, DISP_H) // 2 - 2

    # 中央大圆
    draw_circle(oled, cx, cy, radius, 1)

    # 中心十字准线
    oled.hline(cx - radius, cy, 2 * radius + 1, 1)
    oled.vline(cx, cy - radius, 2 * radius + 1, 1)

    # 读取 MPU6050 倾斜角
    roll, pitch = 0.0, 0.0
    if mpu is not None:
        try:
            roll, pitch = mpu.read_tilt()
        except:
            roll, pitch = 0.0, 0.0

    # 内部气泡 (随设备姿态移动)
    # roll  -> X 偏移 (左右倾斜)
    # pitch -> Y 偏移 (前后倾斜)
    bubble_x_offset = int(-roll * TILT_SCALE)
    bubble_y_offset = int(pitch * TILT_SCALE)
    # 限制最大偏移
    if abs(bubble_x_offset) > TILT_MAX_OFFSET:
        bubble_x_offset = TILT_MAX_OFFSET * (1 if bubble_x_offset > 0 else -1)
    if abs(bubble_y_offset) > TILT_MAX_OFFSET:
        bubble_y_offset = TILT_MAX_OFFSET * (1 if bubble_y_offset > 0 else -1)

    bx = cx + bubble_x_offset
    by = cy + bubble_y_offset
    bubble_r = 5
    draw_circle(oled, bx, by, bubble_r, 1)
    oled.fill_rect(bx - 1, by - 1, 3, 3, 1)

    # 右侧双轴角度显示 (横轴 roll + 纵轴 pitch)
    FILTERED_ANGLES = {0, 90, 180, 270}

    # 横轴 (horizontal, roll, 左右倾斜) - 显示在右上方
    roll_int = abs(int(roll))
    if roll_int not in FILTERED_ANGLES:
        roll_str = str(roll_int)
        rx = DISP_W - len(roll_str) * 6 - 2
        ry = 2
        oled.text(roll_str, rx, ry, 1)

    # 纵轴 (vertical, pitch, 前后倾斜) - 显示在右下方
    pitch_int = abs(int(pitch))
    if pitch_int not in FILTERED_ANGLES:
        pitch_str = str(pitch_int)
        px = DISP_W - len(pitch_str) * 6 - 2
        py = DISP_H - 8
        oled.text(pitch_str, px, py, 1)

    # "AP" 提示 (水平时显示)
    if abs(roll) < LEVEL_THRESHOLD and abs(pitch) < LEVEL_THRESHOLD:
        ap_x = DISP_W - len("AP") * 6 - 2
        ap_y = 22
        oled.text("AP", ap_x, ap_y, 1)

    oled.show()

# ---------------About (Level 3)---------------
def draw_about_screen():
    
    oled.fill(0)

    # 标题分隔线
    oled.hline(0, 11, DISP_W, 1)

    # "About" 标题水平居中
    title = "About"
    title_w = len(title) * 6
    title_x = (DISP_W - title_w) // 2
    oled.text(title, title_x, 1, 1)

    # 元器件名称展示区
    items = ["QMC5883L", "MPU6050", "SSD1306 OLED"]
    start_y = 16
    line_h = 10
    for i, item in enumerate(items):
        # 水平居中
        item_w = len(item) * 6
        item_x = (DISP_W - item_w) // 2
        oled.text(item, item_x, start_y + i * line_h, 1)

    # 底部装饰线
    oled.hline(0, DISP_H - 9, DISP_W, 1)
    # 底部提示
    hint = "Hold:back"
    hint_w = len(hint) * 6
    hint_x = (DISP_W - hint_w) // 2
    oled.text(hint, hint_x, DISP_H - 7, 1)

    oled.show()

# -------------------------------主循环------------------------------------
def main():
    global smooth_angle, first_read, menu_dirty
    draw_menu()
    last_display_update = 0

    while True:
        # 1) 按键扫描
        key_scan()

        # 2) 状态处理
        if state == STATE_DISPLAY:
            now = time.ticks_ms()
            if now - last_display_update > 200:  # 5Hz 更新
                last_display_update = now
                try:
                    if display_type == "show_compass":
                        # 读取磁力计 (带错误恢复 + XY 校准)
                        heading, mx, my, mz = safe_mag_read()
                        if heading is not None:
                            if first_read:
                                smooth_angle = heading
                                first_read = False
                            else:
                                d = heading - smooth_angle
                                if d > 180:  d -= 360
                                if d < -180: d += 360
                                smooth_angle += d * 0.2
                                if smooth_angle < 0:    smooth_angle += 360
                                if smooth_angle >= 360: smooth_angle -= 360
                            draw_compass_screen(smooth_angle)
                        else:
                            if mag is None:
                                oled.fill(0)
                                oled.text("No Mag", 40, 28, 1)
                                oled.show()
                            else:
                                draw_compass_screen(0)

                    elif display_type == "show_gradienter":
                        # 水平仪: 使用 MPU6050, 不调用 QMC5883L
                        draw_gradienter_screen()

                    elif display_type == "show_about":
                        draw_about_screen()
                except Exception as e:
                    print("[main loop] display error:", e)
        else:
            if menu_dirty:
                try:
                    draw_menu()
                except Exception as e:
                    print("[main loop] menu error:", e)
                menu_dirty = False

        # 3) 让出 CPU 时间
        time.sleep_ms(10)

if __name__ == "__main__":
    main()


