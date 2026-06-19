# 技术文档 (Technical Documentation)

本文档包含项目的详细技术信息,包括硬件规格、算法实现、配置参数、故障排查等内容。

## 目录

- [硬件接线](#硬件接线)
- [软件要求](#软件要求)
- [安装部署](#安装部署)
- [架构设计](#架构设计)
- [算法实现](#算法实现)
- [API 参考](#api-参考)
- [配置参数](#配置参数)
- [故障排查](#故障排查)
- [性能指标](#性能指标)
- [开发调试](#开发调试)

## 硬件接线

### 完整接线表

| 模块 | 引脚 | ESP32-S3 | 说明 |
|------|------|----------|------|
| **SSD1306 OLED** | VCC | 3.3V | 电源 |
|  | GND | GND | 地线 |
|  | SDA | GPIO14 | I2C 数据 |
|  | SCL | GPIO13 | I2C 时钟 |
| **QMC5883L** | VCC | 3.3V | 电源 |
|  | GND | GND | 地线 |
|  | SDA | GPIO14 | 共享 I2C |
|  | SCL | GPIO13 | 共享 I2C |
| **MPU6050** | VCC | 3.3V | 电源 |
|  | GND | GND | 地线 |
|  | SDA | GPIO14 | 共享 I2C |
|  | SCL | GPIO13 | 共享 I2C |
| **BOOT 按键** | 一端 | GPIO0 | 内部上拉 |
|  | 另一端 | GND | 按下时拉低 |

### I2C 设备地址

| 设备 | 地址 | 类型 |
|------|------|------|
| SSD1306 OLED | 0x3C | 默认 |
| QMC5883L | 0x0D | 固定 |
| MPU6050 | 0x68 | AD0 接 GND |

### 上拉电阻

- **建议**: SDA/SCL 各接 **4.7kΩ 上拉到 3.3V**
- **应急**: ESP32-S3 内部上拉可临时使用
- **影响**: 内部上拉可能导致 I2C 通信不稳定

## 软件要求

### 运行环境

| 项目 | 版本要求 |
|------|---------|
| MicroPython 固件 | v1.20.0 或更高 |
| ESP32-S3 通用固件 | 推荐 v1.22+ |
| Python 工具 | Thonny / uPyCraft / rshell |

### 依赖驱动

| 文件 | 用途 |
|------|------|
| `ssd1306.py` | OLED 显示屏 I2C 驱动 |
| `qmc5883l.py` | 三轴磁力计 I2C 驱动 |
| `mpu6050.py` | 加速度计 I2C 驱动 (用于水平仪) |

## 安装部署

### 1. 烧录 MicroPython 固件

```bash
# 擦除 Flash
esptool.py --chip esp32s3 --port COMx erase_flash

# 烧录固件
esptool.py --chip esp32s3 --port COMx \
  write_flash -z 0 \
  ESP32_GENERIC_S3-20240105-v1.22.2.bin
```

### 2. 上传项目文件

使用 Thonny:

1. 连接 ESP32-S3,选择解释器为 "MicroPython (ESP32)"
2. 将以下文件上传到根目录:
   - `main.py`
   - `ssd1306.py`
   - `qmc5883l.py`
   - `mpu6050.py`

使用 rshell:

```bash
rshell -p COMx
> ls /pyboard
> cp main.py /pyboard/
> cp ssd1306.py /pyboard/
> cp qmc5883l.py /pyboard/
> cp mpu6050.py /pyboard/
```

### 3. 验证安装

REPL 串口 (115200 波特率) 应输出:

```
Digital Compass starting...
I2C: SoftI2C @ GPIO14,13 (OLED + QMC5883L 共用)
I2C scan: ['0x0D', '0x3C', '0x68']
OLED found at 0x3C
Magnetometer initialized at 0x0D
MPU6050 initialized at 0x68
Hardware ready, entering main loop
```

## 架构设计

### 状态机模型

系统采用 **3 状态有限状态机**:

```
┌─────────────┐    长按菜单项    ┌─────────────┐
│  STATE_MAIN │ ───────────────→ │  STATE_SUB  │
│  (主菜单)   │                  │  (子菜单)   │
└─────────────┘ ←─────────────── └─────────────┘
                  长按 Back
                       │
                       │ 长按 show_*
                       ▼
                ┌─────────────┐
                │ STATE_DISPLAY│
                │ (功能显示)   │
                └─────────────┘
                       │
                       │ 长按 (返回)
                       └──────────→ STATE_SUB
```

### 状态说明

| 状态 | 短按 BOOT | 长按 BOOT |
|------|----------|----------|
| `STATE_MAIN` | (无效) | 进入子菜单 |
| `STATE_SUB` | 切换菜单项 | 确认/返回/进入显示 |
| `STATE_DISPLAY` | (无效) | 返回子菜单 |

### 目录结构

```
/
├── main.py            # 主程序 (UI、状态机、算法)
├── ssd1306.py         # OLED 驱动
├── qmc5883l.py        # 磁力计驱动
├── mpu6050.py         # MPU6050 驱动
└── TECHNICAL.md       # 本文件
```

## 算法实现

### 罗盘方位角计算

**基本公式** (atan2):

```python
heading_rad = math.atan2(y, x)
heading_deg = heading_rad * (180.0 / math.pi)
```

**椭圆校准后**:

```python
x_cal = x - plane_offset_x
y_cal = y - plane_offset_y
heading_rad = math.atan2(y_cal, x_cal)
```

**EMA 平滑滤波**:

```python
d = heading - smooth_angle
if d > 180:  d -= 360
if d < -180: d += 360
smooth_angle += d * 0.2  # 平滑系数
```

### 水平仪倾斜角计算

**Roll (横轴 / 左右倾斜)**:

```python
roll = math.atan2(ay, az) * 180.0 / math.pi
```

**Pitch (纵轴 / 前后倾斜)**:

```python
pitch = math.atan2(-ax, math.sqrt(ay*ay + az*az)) * 180.0 / math.pi
```

**气泡位置映射**:

```python
bubble_x_offset = int(-roll * TILT_SCALE)   # 1° = 2 像素
bubble_y_offset = int(pitch * TILT_SCALE)
# 限制最大偏移 30 像素
```

### XY 平面校准 (椭圆拟合)

**椭圆中心**:

```python
cx = (min(xs) + max(xs)) / 2
cy = (min(ys) + max(ys)) / 2
```

**椭圆半径**:

```python
rx = (max(xs) - min(xs)) / 2
ry = (max(ys) - min(ys)) / 2
```

**校准质量 Q**:

```python
Q = int(min(rx, ry) / max(rx, ry) * 100)
```

| Q 值 | 含义 | 建议 |
|------|------|------|
| ≥ 90% | 优秀 | 正常使用 |
| 70-89% | 良好 | 可用 |
| < 70% | 较差 | 重新校准 |

### 累积角度检测 (旋转 360°)

```python
ang = math.atan2(y, x)
if last_angle is not None:
    d = ang - last_angle
    if d > math.pi:  d -= 2 * math.pi
    if d < -math.pi: d += 2 * math.pi
    angle_sum += d
last_angle = ang
```

## API 参考

### QMC5883L 类

#### 初始化

```python
from qmc5883l import QMC5883L
mag = QMC5883L(i2c, addr=0x0D)
```

#### 读取原始数据

```python
x, y, z = mag.read_raw()
```

#### 计算方位角

```python
heading = mag.heading()  # 返回 0-360 度
```

### MPU6050 类

#### 初始化

```python
from mpu6050 import MPU6050
mpu = MPU6050(i2c, addr=0x68)
```

#### 读取加速度

```python
ax, ay, az = mpu.read_accel()  # 单位 g
```

#### 读取倾斜角

```python
roll, pitch = mpu.read_tilt()  # 单位度
```

### SSD1306 类

#### 初始化

```python
from ssd1306 import SSD1306_I2C
oled = SSD1306_I2C(128, 64, i2c, addr=0x3C)
```

#### 常用方法

```python
oled.fill(0)              # 清屏
oled.text("Hello", x, y)  # 显示文字
oled.pixel(x, y, 1)       # 画点
oled.line(x1, y1, x2, y2) # 画线
oled.rect(x, y, w, h)     # 画矩形
oled.show()               # 刷新显示
```

## 配置参数

### 系统参数 (main.py)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `BOOT_PIN` | 0 | BOOT 键 GPIO |
| `I2C_SDA_OLED` | 14 | OLED SDA 引脚 |
| `I2C_SCL_OLED` | 13 | OLED SCL 引脚 |
| `DISP_W` | 128 | 屏幕宽度 |
| `DISP_H` | 64 | 屏幕高度 |
| `DEBOUNCE_MS` | 50 | 按键消抖 (ms) |
| `LONG_PRESS_MS` | 500 | 长按阈值 (ms) |

### 加载动画

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `LOAD_BAR_DURATION_MS` | 9000 | 动画总时长 (ms) |
| `LOAD_BAR_REFRESH_MS` | 30 | 刷新间隔 (ms) |

### 水平仪参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `TILT_SCALE` | 2.0 | 倾斜角到像素缩放系数 |
| `TILT_MAX_OFFSET` | 30 | 气泡最大像素偏移 |
| `LEVEL_THRESHOLD` | 2.0 | 水平判定阈值 (度) |

### 磁力计错误恢复

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_MAG_ERRORS` | 5 | 连续错误阈值 |
| `MAG_RETRY_INTERVAL` | 3000 | 错误后等待 (ms) |

## 故障排查

### 启动阶段

| 现象 | 可能原因 | 解决方案 |
|------|---------|---------|
| OLED 不亮 | I2C 无上拉 | 检查 4.7kΩ 上拉电阻 |
| OLED 乱码 | 驱动不匹配 | 验证 ssd1306.py 版本 |
| 找不到 0x3C | 接线错误 | 重新检查 SDA/SCL |
| 磁力计无响应 | 地址错 | 单独扫描 0x0D |
| MPU6050 失败 | WHO_AM_I 异常 | 跳过该检查 |

### 运行阶段

| 现象 | 可能原因 | 解决方案 |
|------|---------|---------|
| 长按无响应 | 按键抖动 | 硬件 RC 滤波 |
| 短按跳多项 | 消抖不够 | 增加 DEBOUNCE_MS |
| 罗盘读数 0 | 磁场干扰 | 远离磁铁/手机 |
| 罗盘无变化 | 椭圆未校准 | 执行 Plane Calib |
| 水平仪卡死 | MPU6050 故障 | 检查 0x68 设备 |
| 气泡不移动 | 倾斜角为 0 | 倾斜设备测试 |

### 校准失败

| Q 值 | 可能原因 | 解决方案 |
|------|---------|---------|
| < 50% | 旋转过快 | 降低速度,稳定旋转 |
| < 70% | 未保持水平 | 桌面校准,水平仪辅助 |
| 偏差大 | 强磁场环境 | 远离金属、扬声器 |
| 数值漂移 | 传感器噪声 | 增加样本数 |

## 性能指标

| 指标 | 数值 |
|------|------|
| 启动时间 | 约 9 秒 |
| 罗盘刷新率 | 5 Hz |
| 水平仪刷新率 | 5 Hz |
| 内存占用 | < 50 KB |
| 工作电流 | < 100 mA |
| 工作电压 | 3.3V |

## 开发调试

### REPL 串口输出

启用方法:连接 USB,打开串口监视器 (115200 8N1)

```
Digital Compass starting...
I2C: SoftI2C @ GPIO14,13
I2C scan: ['0x0D', '0x3C', '0x68']
OLED found at 0x3C
OLED initialized (attempt 1)
Magnetometer initialized at 0x0D
MPU6050 initialized at 0x68
Mag test: PASS
BOOT key initialized
Hardware ready, entering main loop
[mag] x=   123 y=  -456 z=   789 h= 285.0°
[mag] x=   150 y=  -420 z=   812 h= 290.3°
```

### 实时调试命令

REPL 中可输入:

```python
# 查看当前状态
>>> print(state, current_menu_id, current_index)

# 手动读取磁力计
>>> x, y, z = mag.read_raw()
>>> print(x, y, z)

# 手动读取 MPU6050
>>> roll, pitch = mpu.read_tilt()
>>> print(roll, pitch)

# 查看校准参数
>>> print(plane_offset_x, plane_offset_y, plane_quality)
```

### 常见调试场景

**校准验证**:

```python
# 校准前
>>> print(plane_calibrated)
False

# 校准后
>>> print(plane_calibrated, plane_quality)
True 87
```

**传感器测试**:

```python
# 测试磁力计是否响应
>>> for i in range(10):
...     print(mag.read_raw())
```

### 内存监控

```python
import gc
gc.collect()
print("Free memory:", gc.mem_free())
```

## 进阶主题

### 软复位 I2C 总线

```python
def i2c_recover(scl_pin, sda_pin):
    scl = Pin(scl_pin, Pin.OPEN_DRAIN, Pin.PULL_UP)
    sda = Pin(sda_pin, Pin.OPEN_DRAIN, Pin.PULL_UP)
    for _ in range(9):
        scl.value(0); time.sleep_us(5)
        scl.value(1); time.sleep_us(5)
    sda.value(0); time.sleep_us(5)
    scl.value(1); time.sleep_us(5)
    sda.value(1); time.sleep_us(5)
```

### 等待 DRDY 数据就绪

```python
for _ in range(10):
    status = mag.i2c.readfrom_mem(mag.addr, 0x06, 1)
    if status[0] & 0x01:  # DRDY 位
        break
    time.sleep_ms(10)
```

## 参考资料

### 官方文档

- [MicroPython 官方](https://docs.micropython.org/)
- [ESP32-S3 文档](https://www.espressif.com/en/products/socs/esp32-s3)
- [SSD1306 OLED 驱动](https://github.com/micropython/micropython-lib)

### 传感器资料

- [QMC5883L Datasheet](https://www.qstcorp.com/en/product/QMC5883L.html)
- [MPU6050 Register Map](https://invensense.tdk.com/products/motion-tracking/6-axis/mpu-6050/)
- [磁力计校准原理](https://www.vectornav.com/resources/inertial-navigation-articles/magnetometer-calibration)

### 算法参考

- [椭圆拟合算法](https://en.wikipedia.org/wiki/Ellipse_fitting)
- [atan2 三角函数](https://en.wikipedia.org/wiki/Atan2)
- [EMA 滤波](https://en.wikipedia.org/wiki/Exponential_smoothing)

---

**版本**: v1.0
**最后更新**: 2025
**维护者**: 课程设计项目组
