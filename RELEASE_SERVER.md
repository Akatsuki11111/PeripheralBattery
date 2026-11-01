# v2.6 更新与发布

本次正式版为 v2.6.0，实验版为 v2.6.1-experimental.1。正式版不含电量实验，实验版保留并改为先确认专用状态协议；读取到已验证电量直接结束，全零/填充应答不再启动无意义的长时间观察。

M5 Lite：接收器3151:5045使用RY F7状态与8F型号查询，实机确认型号3090、在线电量100%。共享接收器不静态归属瓦尔基里。插USB时无线字段可能是离线缓存，USB官方代码还直接填100%，均不采信为实时电量。F7没有已验证充电位，因此不虚构充电状态。

## 更新来源

新程序仅向 http://updates.example.invalid:8089 的 VersionHub 请求更新，不回退GitHub。公开 appKey=peripheral-battery，平台windows，正式通道stable、实验通道experimental。两版也继续在GitHub提供源码、标签、EXE及SHA256。旧v2.5客户端的更新地址已编译在旧程序里，需要先手动升级一次，或经其GitHub更新获取本次迁移版；迁移后检查与下载均使用服务器。

服务器目前HTTP且原生仅提供MD5；新版使用内嵌RSA-2048公钥验证发布签名，再核对下载文件SHA256和大小，不跟随重定向。签名绑定应用、平台、通道、版本、版本ID、下载路径及文件；管理口令、登录token与私钥均不打包。签名保护更新完整性，不会把HTTP管理登录变成加密传输；服务器条件允许时仍宜配置HTTPS。

## 后续发布

版本源代码使用Git标签保留；服务器保存对应正式/实验EXE。现有default通道2.5.0保留。当前服务器实测灰度0不会向匿名更新客户端提供版本，发布工具明确使用100（全量）；已发布条目不可直接编辑，因此必须在草稿阶段写好签名与灰度设置。服务器应用配额100MiB，本次三份EXE共约86MB；后续发布需要扩容或明确清理策略，发布脚本不会自动删除旧版本。

`tools/publish_versionhub.py`负责上传草稿、签名、编辑签名说明、发布和读回核对。管理凭据由stdin JSON临时传入，不写参数/源码/发布说明。公钥在assets/update-public-key.json。签名私钥在当前Windows用户的 .peripheral-battery/signing/update-key.dpapi，由DPAPI保护，只能当前用户解密。请妥善保管；不要上传到GitHub或版本服务器，迁移机器前需要规划受保护密钥迁移，不能仅把该DPAPI文件复制给另一个账户。

手动在网页上传一个没有发布签名的EXE不会被新版客户端自动信任。正常发布使用上述签名工具，并保持与客户端内嵌公钥一致。示例（登录JSON由安全输入管道提供）：

```powershell
python tools/publish_versionhub.py --file PeripheralBattery-v2.6.0.exe --version 2.6.0 --version-code 2060000 --channel stable --notes-file notes.txt --credentials-stdin
```

## 约10MB的取舍

原v2.4.1为48.75MB，v2.5约28.6MB，已减41.3%。压缩后的Python、Qt核心库/绑定、SSL和程序归档合计约22.3MB，图标与目录不是主要来源。本次保留现有体积，不再强行裁剪。

| 方案 | 取舍 |
|---|---|
| 保留Python/PySide6独立EXE，约28.6MB | 当前推荐；保留Windows风格界面、DPI、图标、图表、IPC和无需另装运行库的部署方式。 |
| 小启动器或源码包控制在10MB内 | 需要另装/下载Python与Qt；总依赖体积并未真正变小。 |
| 保留Python协议，改用Windows原生GUI | 有机会继续缩小，但需要重做窗口、图表、IPC及高DPI/主题/无障碍验证，不能保证10MB。 |
| 整体换C++/Rust等原生实现 | 更有机会接近目标，但基本属于重写项目，也改变最初Python实现的要求。 |

进一步压缩或更换编译器不能保证从28MB降至10MB；删除运行组件会引入缺功能风险。本次不以牺牲设备识别、更新验签或UI质量换体积。
