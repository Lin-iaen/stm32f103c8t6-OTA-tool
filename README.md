# STM32F103C8T6 OTA Tool

> 给 STM32F103C8T6（Blue Pill）做**无线固件升级**的命令行工具。
> 插一次线烧好 Bootloader，之后用 BLE 或串口反复换 App，不再需要下载器。

[![tests](https://img.shields.io/badge/tests-19%20passed-brightgreen)](#测试)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)

---

## 这是什么

电脑端工具 + 已编译好的固件。目标是让**一台全新的 Windows 电脑**在几分钟内
完成对一块 F103 开发板的无线 OTA。

- **`fwb` 命令行工具**：扫描设备、读取版本、通过 BLE / 串口升级固件。
- **预编译固件**：`release/bootloader-v0.1.1.bin` + `release/app-v0.1.38.bin`；
  Bootloader 源码在 `firmware/`（同一份源码自动识别 64/128 KB）。
- **自动容量识别**：同一份固件在 64 KB / 128 KB 芯片上分别使用 51 KB / 115 KB App 区。
- **首次烧录脚本**：`tools/flash_initial.py`（唯一需要插线的一步）。

OTA 的核心安全设计：升级中断电不会变砖。Bootloader 常驻，只有在 CRC32
校验通过后才会跳转到新 App；任何异常都会停留在 DFU 模式等待重传。

## 它是怎么工作的

```
┌─────────────┐   BLE / UART    ┌──────────────────────────┐
│  Windows PC │ ◄─────────────► │ STM32F103C8T6            │
│  fwb 工具    │   115200 8N1    │  ┌────────────────────┐  │
└─────────────┘                 │  │ Bootloader 12KB    │  │  常驻，负责收包/写 Flash
                                │  ├────────────────────┤  │
                                │  │ App 51/115KB       │  │  可被 OTA 替换（自动识别）
                                │  ├────────────────────┤  │
                                │  │ Config 1KB         │  │  参数持久化
                                │  └────────────────────┘  │
                                └──────────────────────────┘
```

升级流程（`fwb ota` 内部自动完成）：

```
探测是否已在 Bootloader
  ├─ 否 → 发 APP_OTA_START，App 置标志并复位进入 Bootloader
查询分区信息 (BL_QUERY)
擦除 App 区 (BL_START)
分块写入 512B (BL_DATA × N；BLE 层再按 ≤120B 切包)
CRC32 校验：传输流 == Flash 回读 == 主机计算 (BL_VERIFY)
跳转新 App (BL_JUMP)，重新 PING 确认
```

## 快速开始

### 第 0 步：准备硬件

| 用途 | 推荐 | 说明 |
|---|---|---|
| 首次烧录 | ST-Link V2 或 DAPLink | SWD 接口，只此一次 |
| 无线升级 | BLE 透传模块 | JDY-68A / ECB02H / HC-08 等，接 PA9/PA10 |
| 有线替代 | USB-TTL (CH340/CP2102) | 接 PA9(TX)/PA10(RX)/GND |

接线（BLE 透传模块）：

```
模块 TX  → PA10 (STM32 RX)
模块 RX  → PA9  (STM32 TX)
模块 GND → GND
模块 VCC → 3.3V（按模块规格）
```

> BLE 模块出厂常为 9600 波特率，需先通过 AT 命令改为 **115200**。
> 详见 [docs/01-getting-started.md](docs/01-getting-started.md)。

### 第 1 步：装工具

**方式 A：pip 安装（需要 Python 3.10+）**

```powershell
git clone https://github.com/Lin-iaen/stm32f103c8t6-OTA-tool.git
cd stm32f103c8t6-OTA-tool
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[ble]"        # [ble] 是无线升级必需的
fwb scan-serial                # 出现帮助即安装成功
```

**方式 B：单文件 exe（可选，目标机无需 Python）**

如果 [Releases](https://github.com/Lin-iaen/stm32f103c8t6-OTA-tool/releases)
页面提供了 `fwb.exe`，下载后直接运行；否则在任意有 Python 的机器上构建：

```powershell
pip install -e ".[dev]"
python tools\build_exe.py      # 生成 dist\fwb.exe
```

### 第 2 步：首次烧录（唯一需要插线的一步）

1. 用 ST-Link/DAPLink 连接开发板 SWD（SWDIO / SWCLK / GND / 3.3V）。
2. 安装 [STM32CubeProgrammer](https://www.st.com/en/development-tools/stm32cubeprog.html)。
3. 执行：

```powershell
python tools\flash_initial.py
```

或直接双击 `tools\flash_initial.bat`。

完成后复位板子，**PC13 上的 LED 应每 2 秒双闪一次**，说明 App 已在运行。

### 第 3 步：无线 OTA

```powershell
fwb scan-ble --service 0000ffe0-0000-1000-8000-00805f9b34fb   # 按服务过滤，记下地址
fwb info --ble AA:BB:CC:DD:EE:FF          # 应返回 bootloader v0.1.1, app v0.1.38
fwb ota release\app-v0.1.38.bin --ble AA:BB:CC:DD:EE:FF
```

输出会显示 `probe → erase → write → verify → jump → done` 全过程。

## 常用命令

```powershell
# 无线 OTA（核心功能）
fwb ota app.bin --ble AA:BB:CC:DD:EE:FF        # .bin 或 .hex 都支持
fwb ota app.hex --port COM5                    # 走串口/BT-SPP
fwb info --ble AA:BB:CC:DD:EE:FF               # 读版本
fwb scan-ble --timeout 8                       # 扫描附近 BLE
fwb scan-ble --service 0000ffe0-0000-1000-8000-00805f9b34fb  # 无名字模块按服务过滤
fwb scan-serial                                # 列出串口

# IO 控制台固件附带命令（app v0.1.38）
fwb monitor --ble AA:BB:CC:DD:EE:FF            # 实时遥测
fwb gpio config PB5 out && fwb gpio write PB5 1
fwb adc read 4
fwb pwm set 0 1000 500                         # ch0 1kHz 50%
fwb led on
fwb reboot
```

## 仓库结构

```
stm32f103c8t6-OTA-tool/
├── fwb_tool/                 # Python 包（pip 安装的就是它）
│   ├── protocol.py           #   帧协议 / CRC / 命令码（与固件对齐的单一真相源）
│   ├── transport.py          #   SerialTransport + BleTransport
│   ├── device.py             #   请求-响应层 + 固件镜像加载
│   ├── ota.py                #   OTA 流程编排
│   ├── cli.py                #   fwb 命令
│   └── tests/                #   19 项协议/切包回归
├── firmware/                 # Bootloader 源码（自动识别 64/128KB）
│   ├── common/               #   flash_layout / protocol / crc
│   └── bootloader/           #   DFU 源码 / startup / 链接脚本 / Makefile
├── release/                  # 预编译固件（可直接烧录）
│   ├── bootloader-v0.1.1.bin    # → 0x08000000
│   ├── app-v0.1.38.bin          # → 0x08003000（IO 控制台固件）
│   └── app-v0.1.38.hex
├── tools/
│   ├── flash_initial.py/.bat/.sh   # 首次烧录（需要 STM32CubeProgrammer）
│   ├── ble_probe.py                # BLE 诊断：扫描 / MTU / PING / 包长断崖
│   └── build_exe.py                # PyInstaller 打包
├── docs/
│   ├── 01-getting-started.md
│   ├── 02-wireless-ota.md
│   ├── 03-troubleshooting.md
│   └── 04-protocol.md
├── pyproject.toml
├── LICENSE
└── ATTRIBUTION.md
```

## Flash 分区

Bootloader 启动时读取芯片的 `F_SIZE` 寄存器（`0x1FFFF7E0`），自动选择布局：

| 区域 | 64 KB 芯片 | 128 KB 芯片 | 说明 |
|---|---|---|---|
| Bootloader | `0x08000000`，12 KB | 同左 | 常驻，永不参与 OTA |
| App | `0x08003000`，**51 KB** | `0x08003000`，**115 KB** | OTA 目标 |
| App 最大镜像 | **52,224 B** | **117,760 B** | `BL_QUERY` 报告实际上限 |
| Config | `0x0800FC00`，1 KB | `0x0801FC00`，1 KB | 运行时参数持久化 |

> **不要**把 App 烧到 `0x08000000`，那是 Bootloader 的位置。
>
> 同一份 Bootloader / App 二进制同时支持两种芯片：64 KB 用低 51 KB，
> 128 KB 用满 115 KB。`F_SIZE` 读数不在 64..128 范围（例如某些克隆片
> 返回 `0xFFFF`）时按 64 KB 保守处理，避免写到不存在的 Flash。
>
> 主机工具先按 115 KB 的上限接收镜像，真正的上限由 Bootloader 的
> `BL_QUERY` 在擦除前强制检查；把 100 KB 镜像发到 64 KB 板会被拒绝，
> 不会擦除现有 App，主机随后发 `BL_ABORT` 让设备自动复位回原 App。
>
> **从旧版升级**：只 OTA `app-v0.1.38.bin` 仍可运行，但旧 Bootloader
> 仍按 51 KB 上限；要用满 128 KB，需用 ST-Link/DAPLink 再烧一次
> `release/bootloader-v0.1.1.bin`（地址 `0x08000000`）。

## 从源码编译 Bootloader

`firmware/` 包含自动识别版 Bootloader 源码（`common` + `bootloader`）。
需要 `arm-none-eabi-gcc` 和 `make`：

```bash
make -C firmware/bootloader
# 产物：firmware/bootloader/bl.bin
```

烧到 `0x08000000`。默认构建同时支持 64/128 KB；在 128 KB 板上验证 64 KB
布局时，用同一份源码强制编译：

```bash
make -C firmware/bootloader clean
make -C firmware/bootloader FLASH_SIZE_FORCE_KB=64
```

强制版只用于测试，不要作为正式发布固件。详见
[firmware/README.md](firmware/README.md)。

## 测试

```powershell
pip install -e ".[dev]"
python -m pytest fwb_tool/tests/ -q      # 应 19 passed
```

测试覆盖 CRC 标准向量、帧收发与解析容错、命令码冻结校验、镜像加载与
Intel HEX 解析。它们守护的是**主机与固件之间的协议契约**。

## 为什么断电不变砖

1. **擦除前置标志**：`BL_START` 先写标志再擦除。断电重启后 Bootloader
   看到标志就直接进 DFU，不会跳到半成品镜像。
2. **验证后跳转**：`BL_JUMP` 只在 CRC32 校验成功后执行。
3. **向量表兜底**：跳转前检查 App 首 8 字节（栈指针、复位向量）是否合法。
4. **三重 CRC 一致**：传输流 CRC == Flash 回读 CRC == 主机计算 CRC。

## 兼容性

| 项目 | 要求 |
|---|---|
| 芯片 | STM32F103C8T6（官方 64 KB Flash；部分批次实际 128 KB）。Bootloader 自动识别容量并按 51 / 115 KB 布局运行 |
| 电脑 | Windows 10+ / Linux / macOS |
| Python | 3.10+（仅 pip 安装方式需要） |
| 无线 | BLE 4.0+ 适配器；Windows 需 10 1703+ |
| 固件 | 需烧入本仓库配套 Bootloader（协议版本对齐） |

## 致谢

协议与 Bootloader 架构源自开源项目
[kurui365/smart-robot-car](https://gitee.com/kurui365/smart-robot-car)（MIT）。
详见 [ATTRIBUTION.md](ATTRIBUTION.md)。

## License

MIT，见 [LICENSE](LICENSE)。
