# 03 - 故障排查

按现象查找。

## 扫描不到 BLE 设备

- 确认模块已上电，且处于**从机 / 透传模式**（不是主机模式）。
- 确认电脑蓝牙已打开。Windows 需 10 1703 或更新。
- 增加扫描时间：

  ```powershell
  fwb scan-ble --timeout 10
  ```

- 关掉手机蓝牙 App，避免模块已被其他设备占用。
- 模块名可能为空，显示为 `?`，先用模块厂商 App 确认真实地址。

## `fwb info` 超时无响应

1. **波特率**：BLE 模块必须为 115200。出厂 9600 需先改。
2. **接线**：模块 TX ↔ PA10、模块 RX ↔ PA9，交叉连接。
3. **供电与共地**：模块 GND 必须与 STM32 共地。
4. **标志状态**：复位板子看 PC13。若常灭，可能 App 未启动，试
   `fwb info` 多跑几次。
5. 串口方式先验证：用 USB-TTL 直连 PA9/PA10，排除无线问题。

## Windows 上 `fwb ota --ble` 报权限/连接错误

- 关闭可能占用蓝牙的软件（厂商 App、串口助手）。
- 删除系统中已配对的该模块记录，重新连接。
- 首次连接 JDY 系模块可能瞬间断连，工具会自动重连一次；若仍失败，
  重跑命令。

## OTA 卡在 `probe`

- 设备可能已经停在 Bootloader：`fwb info --ble ...` 应能应答。
- 若 App 正在运行，`APP_OTA_START` 后需要约 1.5 秒进入 Bootloader；
  网络慢时可重跑。
- 若一直失败，改用有线 `--port COM5` 排除无线因素。

## OTA 走到 `write` 中途失败

- BLE 丢包：重跑 `fwb ota`。Bootloader 处于 DFU 模式，会从头开始重写。
- 距离过远 / 干扰：靠近模块，或用有线。
- **不要**在升级中途断电——虽然不会变砖，但需要重来。

## `verify failed`

- 镜像超过分区大小：报错会提示 `image XXXB > partition`。检查是否
  误用了 Bootloader 镜像或链接地址错误的 App。
- 传输损坏：重跑一次。

## 升级后设备无响应

- 等待 3-5 秒，设备需要重启并重新建立 BLE 连接。
- `fwb info --ble ...` 再试。仍无响应则断电重插，设备会回到 DFU
  或旧 App（取决于标志）。
- 最坏情况：用下载器重新执行 `tools\flash_initial.py`。

## `fwb` 命令找不到

- Windows：确认 venv 已激活（提示符前有 `(.venv)`）。
- 或直接用模块方式：`python -m fwb_tool ...`
- 或使用打包好的 `fwb.exe`。

## Linux 串口权限

```bash
sudo usermod -aG dialout $USER   # 重新登录生效
```

## ST-Link 烧录失败

- 检查 SWD 接线与供电。
- 尝试降速：在 STM32CubeProgrammer 里把 SWD 频率调低。
- 板子在复位循环时按住复位键，点烧录再松开。
- 检查 udev 规则（Linux）：ST-Link 需要 `plugdev` 权限。

## 收集诊断信息

```powershell
fwb --help
fwb scan-serial
fwb scan-ble --timeout 10
fwb info --ble AA:BB:CC:DD:EE:FF
```

把上述输出（地址可打码）附在 issue 里。
