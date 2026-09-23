# 01 - 首次使用

本页覆盖从零开始的完整流程：准备电脑 → 首次有线烧录 → 建立无线链路。

## 1. 硬件准备

### 1.1 开发板

STM32F103C8T6 "Blue Pill"。板载 LED 在 **PC13**，低电平点亮。

### 1.2 下载器（仅首次烧录需要）

任选其一：

- **ST-Link V2**（克隆版即可）：SWDIO / SWCLK / GND / 3.3V
- **DAPLink / CMSIS-DAP**

### 1.3 无线模块

推荐 BLE 透传模块（JDY-68A、ECB02H、HC-08 等），也可以使用 USB-TTL
或经典蓝牙 SPP 模块。

**接线（BLE 透传）**：

```
模块 TX  → PA10 (STM32 RX)
模块 RX  → PA9  (STM32 TX)
模块 GND → GND
模块 VCC → 3.3V 或 5V（按模块规格，注意电平）
```

> 串口参数：**115200 8N1**。多数 BLE 模块出厂为 9600，需要先改。

### 1.4 修改 BLE 模块波特率

用 USB-TTL 临时接模块，串口助手 9600 发：

```
AT+BAUD8          # JDY-31A：8 代表 115200
```

不同模块 AT 命令不同，参见模块手册。改完断电重启，再接到 STM32。

## 2. 安装电脑端工具

### 2.1 安装 Python

从 [python.org](https://www.python.org/downloads/) 安装 3.10+，安装时勾选
**Add python.exe to PATH**。

### 2.2 安装 fwb

```powershell
git clone https://github.com/Lin-iaen/stm32f103c8t6-OTA-tool.git
cd stm32f103c8t6-OTA-tool

py -m venv .venv
.venv\Scripts\activate

pip install -e ".[ble]"
```

Linux / macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[ble]"
```

验证：

```powershell
fwb --help
```

### 2.3 安装 STM32CubeProgrammer

用于首次烧录。从
[ST 官网](https://www.st.com/en/development-tools/stm32cubeprog.html)
下载安装。安装后确认 `STM32_Programmer_CLI` 在 PATH 中，或记住完整路径。

## 3. 首次有线烧录

这一步之后，App 的更新就全部走无线了。

### 3.1 连接下载器

把 ST-Link 接到板子的 SWD 接口，并给板子供电。

### 3.2 执行烧录

```powershell
python tools\flash_initial.py
```

脚本会自动寻找 `STM32_Programmer_CLI`。如果没找到：

```powershell
python tools\flash_initial.py --programmer "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"
```

也可以直接双击 `tools\flash_initial.bat`。

脚本会：

1. 全片擦除
2. 写 Bootloader 到 `0x08000000`
3. 写 App 到 `0x08003000`
4. 校验

### 3.3 验证

复位板子，观察 **PC13 LED**：

- **每 2 秒双闪** → App 运行正常（期望结果）
- 常亮 / 常灭 → 可能停在 Bootloader，见故障排查

## 4. 建立无线连接

```powershell
fwb scan-ble
```

输出示例：

```
aa:bb:cc:dd:ee:ff    JDY-68A
```

如果扫描不到，见 [03-troubleshooting.md](03-troubleshooting.md)。

读取设备版本：

```powershell
fwb info --ble AA:BB:CC:DD:EE:FF
```

期望输出：

```
connected. bootloader v0.1.0, app v0.1.25
```

至此无线链路打通，可以进入 [02-wireless-ota.md](02-wireless-ota.md)。
