# 手柄识别与电池通道

v2.5.0 正式版与 v2.5.1-experimental.1 实验版共用手柄功能。新增 22 个品牌：北通、墨将、Xbox、Sony、Nintendo、八位堂、盖世小鸡、飞智、谷粒、HORI、NACON、PowerA、PDP、Turtle Beach、Hyperkin、Thrustmaster、SCUF、EasySMX、PXN、ipega、机械师和雷神。部分品牌仅支持名称识别；明确型号 ID 的来源记录在 catalog.json。品牌识别不代表全部型号或全部连接模式均可读取电池。

## v2.7 新增与已接入的通道

| 通道 | 行为与限制 |
|---|---|
| XInput 1.4 | 耗尽/低/中/高四档；不换算成百分比。优先扩展能力 VID/PID；同一型号家族的 USB/蓝牙/BLE 差异只在物理设备唯一时关联。没有可靠身份时单独显示 XInput 插槽，禁止跨插拔保留缓存。 |
| Windows.Gaming.Input | 同时枚举 RawGameController 与 Gamepad，即使 hidapi 看不到 Xbox GIP/无线适配器下的手柄也能纳入清单。优先使用有效 BatteryReport 容量和充电状态。原生 NonRoamableId 是不透明 ID，只保存哈希，不当作 PnP 路径。 |
| Windows 蓝牙设备属性 | 读取设备/蓝牙父节点的电池属性及 AEP System.Devices.BatteryLife；必须同时确认当前连接。101/越界/冲突值不采用，不把配对缓存当作在线。驱动可能仅提供分档值，标注“约”。 |
| Xbox 蓝牙报告 0x04 | Microsoft 白名单型号，仅读取电源/电池字段。低/中/高/满四档与 XInput 档位不同；只在有效在线电池模式采用。USB 供电不意味着满电或充电，AA 电池不能据此标注充电。被动收不到时尝试只读 GET_INPUT_REPORT 04；不发送输出、振动或模式切换。 |
| Sony DS4 / DualSense / Edge 白名单 | 被动解析完整 HID 电池字段，蓝牙 CRC 校验；分档值显示“约”。 |
| Nintendo Joy-Con / Switch Pro 白名单 | 已有完整 HID 报告的五档电量与充电位，不主动握手或切模式。 |
| 八位堂部分 SF30/SN30 Pro、Pro 2/Pro 3 | 已有增强报告；普通模式补零不当作 0%，不主动切增强模式。 |

Xbox One、One S、Series X|S、Elite 1/2、Adaptive 的 USB/蓝牙/BLE 明确 ID 已补齐；360 通过 XInput。标为 Xbox 协议或共享 OEM 标识，仍不能证明外壳品牌。目录不是“所有型号电量均已适配”的承诺。

分档值使用分段条及文字，托盘在没有可信百分比时可显示等级和手柄标识；不参与百分比最低值、低电量提醒与续航预测。休眠时百分比或分档均保留最后有效值和原采样时间，最长24小时；接收器物理拔出后隐藏。只能识别活动插槽的设备例外：无法证明插槽重新分配后仍是同一只手柄，因此不持久缓存。

同 VID/PID 的多只手柄：直接 HID 字段绑定各自路径；WGI 原生独立 ID 的设备绑定其各自 BatteryReport。只有 VID/PID 而不能唯一关联时不分配数据，绝不按排列顺序猜测。Windows 若返回非无线、固定1000/1000且无功率/充电证据，保守视为可能的占位满电值。

查询在有超时、可终止的后台进程执行。仅提取电池字段，不保存手柄按键、摇杆或原始输入包。GameInput.GetBatteryState 已在当前API移除，旧版从未实现，不作为可用方案。

**验证边界：本次没有 Xbox 实物。** 已进行协议样本、Windows接口模拟、多设备错配、休眠缓存和界面测试，并在本机执行 Windows 枚举。不同固件/连接模式的实机成功率仍待验证；不保证每个 Xbox 或第三方手柄都提供百分比。对无线适配器，优先 WGI，失败后 XInput；对蓝牙，增加系统电池属性与0x04回退；纯有线或驱动不返回电池时保持未知。

## 北通鲲鹏与墨将彩虹 2

控制接口可枚举为 20DD:5134（KP50B DONGLE）与 413D:2106（共享控制接口，型号待确认）。只有 Windows 容器或物理父节点吻合时，才与虚拟 XInput 节点合并，避免重复展示。

新增 20BC:5134（BTP-KP50B XINPUT DONGLE）和 413D:2104（用户确认的彩虹 2；其他同 ID 型号需核对）。实机查询两者均返回 XInput WIRED，Windows 还可能返回 Discharging、1000/1000 容量且无功率信息。这种冲突的固定满容量报告存在驱动占位值风险，当前不当作可信 100%。详情解释原因，主界面显示“电量待适配”。WIRED 不作为无线接收器“无电池”的证明。

公开 BETOP 协议验证的是鲲鹏20、20BC:5191 的厂商 HID 接口与 02 15 查询，不能直接套用到 KP50B。彩虹2当前厂商接口不声明 Feature 报告，Feature GET 也不能直接得到电量。精确适配需要对应型号的查询文档，或官方软件通信与实际电池读数的对照。当前未完成这两款的专用百分比协议适配。

这两个型号完成了接入、去重和标准通道实机验证。其他手柄协议完成了解码、错误包与身份匹配测试，尚未逐一进行实物验证。

## 参考与许可

- [Microsoft XInput 电池结构与档位](https://learn.microsoft.com/en-us/windows/win32/api/xinput/ns-xinput-xinput_battery_information)
- [Microsoft RawGameController.TryGetBatteryReport](https://learn.microsoft.com/en-us/uwp/api/windows.gaming.input.rawgamecontroller.trygetbatteryreport)
- [SDL XInput 扩展结构](https://github.com/libsdl-org/SDL/blob/4bb5020be2a3e3f7a963b84c95f49fe7ef5d35a4/src/core/windows/SDL_xinput.h)
- [SDL 手柄目录](https://github.com/libsdl-org/SDL/blob/4bb5020be2a3e3f7a963b84c95f49fe7ef5d35a4/src/joystick/controller_list.h) 与 [HIDAPI 协议](https://github.com/libsdl-org/SDL/tree/4bb5020be2a3e3f7a963b84c95f49fe7ef5d35a4/src/joystick/hidapi)
- [SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB)
- [HaloBattery Windows 手柄查询](https://github.com/HeyOkay/HaloBattery/tree/2251f0534a8e886c9692ead42056059b4f69d8c0/providers)
- [BETOP 已验证协议的范围](https://github.com/oitsukiii/betop-battery/blob/main/docs/protocol.md)
- [墨将官方支持](https://shop.bigbigwon.com/pages/support)

- [Microsoft IGameControllerBatteryInfo](https://learn.microsoft.com/en-us/uwp/api/windows.gaming.input.igamecontrollerbatteryinfo)
- [Windows System.Devices.BatteryLife 属性及未知值](https://learn.microsoft.com/en-us/windows/win32/properties/props-system-devices-batterylife)
- [Microsoft GameInput 电池接口已移除](https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/input/gameinput/deprecated/interfaces/igameinputdevice/methods/igameinputdevice_getbatterystate)
- [SDL Xbox One 蓝牙报告解析](https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/SDL_hidapi_xboxone.c)
- [SDL Xbox 硬件 ID](https://github.com/libsdl-org/SDL/blob/main/src/joystick/usb_ids.h)
- [xpadneo 电源报告位定义（只参考事实，未复制驱动代码）](https://github.com/atar-axis/xpadneo/blob/master/hid-xpadneo/src/xpadneo/power.c)
