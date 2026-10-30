# 手柄识别与电池通道

v2.5.0 正式版与 v2.5.1-experimental.1 实验版共用手柄功能。新增 22 个品牌：北通、墨将、Xbox、Sony、Nintendo、八位堂、盖世小鸡、飞智、谷粒、HORI、NACON、PowerA、PDP、Turtle Beach、Hyperkin、Thrustmaster、SCUF、EasySMX、PXN、ipega、机械师和雷神。部分品牌仅支持名称识别；明确型号 ID 的来源记录在 catalog.json。品牌识别不代表全部型号或全部连接模式均可读取电池。

## 已接入的通道

| 通道 | 行为与限制 |
|---|---|
| XInput 1.4 | 显示耗尽/低/中/高四档，不换算成百分比。扩展能力提供 VID/PID 时才关联实物，不按槽位顺序猜设备。 |
| Windows.Gaming.Input | 根据 BatteryReport 的剩余容量/满充容量计算百分比、读取充电状态；要求唯一 VID/PID 与有效容量。 |
| Sony DS4 / DualSense / Edge 白名单 | 被动解析已有完整 HID 电池字段。蓝牙包校验 CRC；分档值显示“约”。 |
| Nintendo Joy-Con / Switch Pro 白名单 | 解析已有完整 HID 报告中的五档电量与充电位；不发送 USB 握手、模式切换或振动命令。 |
| 八位堂 SF30/SN30 Pro、Pro 2/Pro 3 白名单 | 仅读取已有增强报告；普通模式补零不当作 0% 电量，不主动切换增强模式。 |

分档读数不参与可信最低电量、低电量提醒与续航预测。查询在可终止的后台进程执行。手柄 Input 报告只在内存中提取电池字段；按键、摇杆、原始报告不保存、不导出。没有完整报告时部分型号只显示已识别，不保证等待后一定能得到电量。

同 VID/PID 的多个物理手柄不直接分配 Windows 标准通道的电量，以防错配；物理 HID 电池字段与其路径直接绑定。共享 OEM 或 Xbox/Switch 模拟标识不能证明原厂品牌，目录排除已知跨品牌冲突，仍可能有未收录的共用 ID。

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
