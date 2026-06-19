# CompassLevel
[MicroPython]基于ESP32S3的罗盘水平仪（MPU6050+QMC5883L）/Compass and Gradienter Based on ESP32-S3 (MPU6050 + QMC5883L)
罗盘水平仪:开发语言是MicroPython。如果你也想复刻学习这个项目，可以跟着放在下面的步骤操作。

##项目介绍
 具备 3 级菜单系统、罗盘实时显示、水平仪气泡显示、XY 平面校准等功能。
- **罗盘**: 实时方位角检测,椭圆校准消除硬铁误差
- **水平仪**: 双轴倾斜检测,气泡式可视化校准
- **3 级菜单**: 主菜单 → 子菜单 → 功能界面
- **单总线设计**: OLED + 磁力计 + 加速度计共享 I2C

## 硬件目录

 开发板  ESP32-S3 
 显示屏  SSD1306 OLED 128x64
 磁力计  QMC5883L 
 加速度计  MPU6050 
 按键  开发板自带的BOOT 键 (GPIO0) 

## 快速开始

### 1. 准备

- ESP32-S3 开发板 (已烧录 MicroPython v1.20+)
- 上传以下文件到根目录:
  ```
  main.py
  ssd1306.py
  qmc5883l.py
  mpu6050.py
  ```

### 2. 接线

所有 I2C 设备统一接在 **GPIO14 (SDA) / GPIO13 (SCL)**,详见 [技术文档](./TECHNICAL.md#硬件接线)。

## 使用方法

### 按键操作

短按 BOOT  菜单项下移 
长按 BOOT  确认/进入/返回 

### 菜单导航

```
主菜单
├── Compass       →  罗盘 / 校准 / 重置指北
├── Gradienter    →  水平仪
└── Settings      →  About
```

## 文档

- [技术文档](./TECHNICAL.md): 硬件接线、算法细节、故障排查


## 许可证

本项目为课程设计用途,代码仅供学习参考。

## 参考致谢

- [MicroPython](https://micropython.org/)
- [QMC5883L Datasheet](https://www.qstcorp.com/en/product/QMC5883L.html)
- [MPU6050 文档](https://invensense.tdk.com/products/motion-tracking/6-axis/mpu-6050/)
 

 

