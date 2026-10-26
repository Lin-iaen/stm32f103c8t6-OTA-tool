# 来源声明 (Attribution)

本工具的协议实现与 OTA 编排流程继承自开源项目 **smart-robot-car**
（kurui365，MIT License）及其衍生工程 **f103-workbench**：
https://gitee.com/kurui365/smart-robot-car

| 组件 | 继承程度 | 说明 |
|---|---|---|
| `fwb_tool/protocol.py` | 重写 | 帧格式与命令码沿用原项目协议；代码按独立工具重新组织 |
| `fwb_tool/ota.py` | 重写 | OTA 状态流程照搬原项目 `serial_comm.py` 的设计 |
| `fwb_tool/transport.py` | 重写 | 串口/BLE 双传输抽象 |
| `firmware/common`, `firmware/bootloader` | 移植/改写 | Bootloader 源码；DFU 状态机与启动逻辑源自原项目 |
| `release/*.bin` | 派生 | 由 f103-workbench 的 Bootloader 与 App 编译产物导出 |
| Bootloader 设计 | 移植 | DFU 状态机 / 防砖判定 / 启动逻辑源自原项目 |

原项目及衍生工程 MIT 许可证全文：

```
MIT License

Copyright (c) kurui365

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
