---
id: 03-televuer-immersive-rendering
title: "televuer immersive 模式渲染机制研究（参考实现）"
labels: [wayfinder:research]
status: closed
assignee: "research-subagent-03"
blocked-by: []
---

## Question

televuer（及底层 vuer）的 immersive 模式如何把 SBS 双目图像送到左右眼？其 image plane 几何参数是什么？可迁移到 Unity 沉浸模式的设计要点有哪些？

需要回答的子问题：

1. 图像分发机制：SBS 纹理如何拆分到左右眼（WebXR stereoscopic layer？两个 plane + 相机分 eye 渲染？vuer 的 scene graph 结构）。
2. Plane 几何数值：距离、宽高、V4.0 note 所说"Adjusted the image plane height"的具体调整值；ego 与 immersive 的差别实现。
3. `render_to_xr` 的数据路径：图像从 teleimager 到 vuer 前端再到 WebXR 显示的完整链路与格式（JPEG？分辨率约定）。
4. 对 Unity 侧的启示：SBS 拆分该在哪层做（texture UV / 双材质 / 双相机）、plane 摆位初值、避免晕动症的注意点。

方法：`git clone --depth 1 https://github.com/unitreerobotics/televuer` 到临时目录读源码；必要时读 vuer（pip 包或 github）对应版本源码；结合 README 版本史交叉验证。

产出：`research/03-televuer-immersive-rendering.md`，含机制描述、可直接抄的参数数值、给 ticket 05 的设计输入、来源链接。

## Resolution

详见 `research/03-televuer-immersive-rendering.md`（基于 televuer commit 766de45 / v4.0.0 + vuer==0.0.60 wheel 前端反混淆）。要点：

1. SBS 分发有两条路径：zmq 路径在 Python 端切成左右两个 ndarray，各包一个 `ImageBackground`（`layers=1`/`layers=2`），vuer 前端 `XrStereoPatch` 每帧设 `cameras[0].layers.mask=3`（左眼）、`cameras[1].layers.mask=5`（右眼）实现 per-eye 分发；WebRTC 路径是单 SBS 视频流 + 两个 HUDPlane 各挂 `VideoMaterial` shader，用 `texCoordScaleOffset[EYE_INDEX]` 做 UV 半幅偏移。
2. Plane 是锁头公告板（每帧复制相机位姿 + 前移 distance，无垂直偏移），尺寸显式给定与 FOV 解耦。V4.0 "调整 plane height" = 新增 ego 模式几何：immersive 维持 height=1@1m（zmq）/ height=7（WebRTC@10m），ego 为 height=0.75@2m（zmq）/ height=3（WebRTC@10m）。
3. 传输：zmq 路径共享内存（BGR）→ BGR2RGB → Pillow JPEG quality=80 二进制，30fps，`img_shape=(H, W_sbs)` 左半=左眼；WebRTC 走 /offer 局域网直连。
4. Unity 建议：首选单张 SBS 纹理 + Single Pass Instanced shader 用 `unity_StereoEyeIndex` 做 UV 偏移（同构 vuer VideoMaterial）；plane 初值锁头 local(0,0,1.0) 高 1m；保留面罩暗角（张角 < 头显 FOV）与 ego 降级模式抗晕动；unlit 直出 + bilinear 滤波。
