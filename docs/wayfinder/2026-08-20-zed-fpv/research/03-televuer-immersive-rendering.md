# 03 · televuer 沉浸式双目渲染机制研究

研究日期：2026-08-20。研究对象：`unitreerobotics/televuer`（commit `766de45`，2026-05-27，v4.0.0）及其依赖 `vuer==0.0.60`（pip wheel 内置的前端 client_build 反混淆核对）。

## 结论摘要

1. **SBS 拆分机制 = 两个全尺寸纹理 + per-eye 相机 layer 掩码**。zmq 路径下 Python 端就把 SBS 帧切成左右两个 `np.ndarray` 视图，分别包成两个 `ImageBackground`（`layers=1` / `layers=2`）；vuer 前端有一个 `XrStereoPatch`，每帧把 XR `ArrayCamera` 的 `cameras[0].layers.mask=3`（左眼：层0+层1）、`cameras[1].layers.mask=5`（右眼：层0+层2）。左眼只看到 layer 1 的 plane，右眼只看到 layer 2 的 plane。**不是** WebXR stereoscopic layer API，也不是把一张 SBS 图在 shader 里拆。
2. **WebRTC 路径才是 shader UV 拆分**：单个 SBS 视频流 → `WebRTCStereoVideoPlane` → 两个 HUDPlane（layer 1/2）各挂一个 `VideoMaterial` 自定义 shader，uniform `texCoordScaleOffset[EYE_INDEX]`，`stereo-left-right` 时左眼取 `[0.5,1,(0,0)]`、右眼取 `[0.5,1,(0.5,0)]`（即 uv.x*0.5 / uv.x*0.5+0.5）。
3. **Plane 是"锁头"公告板**：每帧把 plane 位姿复制为相机位姿，再沿视线前移 `distanceToCamera`，无俯仰滚转、无垂直偏移；尺寸显式给定（`height` × `aspect`），与相机 FOV 无关。
4. **V4.0 "Adjusted the image plane height" 的实际数值**：immersive 保持 `height=1, distanceToCamera=1`（zmq）/ `height=7`（WebRTC，HUDPlane 默认 distance=10）；ego 是新增模式 `height=0.75, distanceToCamera=2`（zmq）/ `height=3`（WebRTC @10m）。
5. **传输格式**：zmq 路径 = 共享内存（BGR）→ 写线程 BGR2RGB → Pillow JPEG quality=80 二进制 → WebSocket `session.upsert`，30fps；WebRTC 路径 = aiortc 类 offer 端点视频流。分辨率约定 `img_shape=(H, W_fullSBS)`，单眼宽 `W_full//2`。
6. **对 Unity**：最直接的等价物是"一张 SBS 纹理 + 一个 quad + Single Pass Instanced shader 用 `unity_StereoEyeIndex` 做半个 UV 偏移"（对应 vuer 的 VideoMaterial 方案）；plane 初值 1m 距离 / 1m 高 / 宽 = 单眼 aspect × 高，锁头不锁世界。

---

## 机制拆解（文件 + 行号）

### televuer 侧（`src/televuer/televuer.py`）

| 位置 | 内容 |
| --- | --- |
| L57-66 | `img_shape=(H,W)` 全 SBS 宽；`binocular=True` 时 `img_width = W//2`（单眼宽），`aspect_ratio = img_width/img_height`（单眼宽高比，不是 SBS 整图比例） |
| L103-136 | 按 `display_mode`（immersive/ego/pass-through）× `binocular` × `zmq/webrtc` 选 8 个 spawn 协程之一；zmq 路径建 `SharedMemory` + 后台写线程 |
| L191-200 | `_xr_render_loop`：`cv2.cvtColor(BGR2RGB)` 后整帧写入共享内存 `img2display` |
| L202-207 | `render_to_xr(image)`：只写 `latest_frame` 并 set event（V3.0 由 `set_display_image` 改名）；webrtc/pass-through 下忽略 |
| L320-373 | `main_image_binocular_zmq`（immersive）：每 `1/display_fps` 秒 upsert 两个 `ImageBackground`：`img2display[:, :img_width]`（左）`layers=1`，`img2display[:, img_width:]`（右）`layers=2`；均 `aspect=单眼比例, height=1, distanceToCamera=1, format="jpeg", quality=80, interpolate=True`。L349-351 有官方注释说明 layer 掩码与左右眼相机的对应关系 |
| L375-413 | `main_image_monocular_zmq`：单 plane 无 layers（双眼同图） |
| L415-450 | `main_image_binocular_webrtc`（immersive）：`WebRTCStereoVideoPlane(src=offer_url, aspect, height=7, layout="stereo-left-right")` |
| L489-542 | `main_image_binocular_zmq_ego`：同 zmq 双 plane，但 `height=0.75, distanceToCamera=2` |
| L584-619 | `main_image_binocular_webrtc_ego`：`WebRTCStereoVideoPlane(height=3, layout="stereo-left-right")`（HUDPlane 默认 `distanceToCamera=10` 未覆盖） |
| L658-681 | `main_pass_through`：不下发任何图像，仅保留手/手柄追踪（画面由头显 AR 透视提供） |

注意 zmq 路径每帧 upsert 的是**整个场景元素描述**（vuer 的 diff-patch 协议），图像以 JPEG 字节流内嵌；这在 Unity 里不需要模仿，直接更新 RenderTexture 即可。

### vuer 0.0.60 Python 侧

| 位置 | 内容 |
| --- | --- |
| `vuer/schemas/scene_components.py:351` | `ImageBackground`：仅 schema 声明（"We use a plane that is always facing the camera"），真正几何在前端 |
| `vuer/schemas/scene_components.py:360,386,400` | `HUDPlane` / `WebRTCVideoPlane` / `WebRTCStereoVideoPlane` schema |
| `vuer/schemas/html_components.py:204` | `Image` 基类：ndarray→Pillow 编码，`format="jpeg"` 时调 `IMAGE_FORMATS["jpeg"](data, quality=80)` |
| `vuer/serdes.py:44-55, 94` | `jpeg()`：`pil_image.fromarray(...).save(JPEG, quality)`，输出二进制（非 base64） |

### vuer 前端（wheel 自带 `client_build`，minified；以下为反混淆后语义）

**1) XrStereoPatch —— per-eye 相机层掩码（stereo 分发的核心）**

```js
function XrStereoPatch() {
  const gl = useThree(s => s.gl), camera = useThree(s => s.camera), mode = useXR(s => s.mode);
  useEffect(() => { gl.xr.cameraAutoUpdate = false }, [mode, gl, camera]);
  useFrame(() => {
    gl.xr.updateCamera(camera);
    if (mode === "immersive-ar" || mode === "immersive-vr") {
      if (camera instanceof ArrayCamera) {
        camera.cameras[0].layers.mask = 3;  // 0b011 = layer0(场景) + layer1(左图)
        camera.cameras[1].layers.mask = 5;  // 0b101 = layer0(场景) + layer2(右图)
      }
    }
  });
}
```

**2) ImageBackground / ImagePlane —— zmq 路径的 plane 几何**

- `ImageBackground` 无 depth 时渲染为 `ImagePlane`（`planeGeometry(1,1)` + `meshBasicMaterial`，unlit）。
- 仅在 `immersive-vr/ar` 模式且 `layers` 为数字时执行 `mesh.layers.set(n)`（注意是 `set`：该 mesh 只属于这一层）。
- `useFrame` 每帧：
  - 尺寸：`height`、`aspect` 都显式给出时 `scale.set(height*aspect, height, 1)`；否则 `height = 2·tan(fov/2)·distanceToCamera`（FOV 充满）。
  - 位姿：`mesh.position/quaternion` 复制相机，再加 `(0,0,-distanceToCamera)` 旋到相机朝向 —— **无垂直/水平偏移，正对视线，锁头跟随**。
- `interpolate=True` → 纹理 `LinearFilter`（双线性），否则 `NearestFilter`。

**3) HUDPlane + VideoMaterial —— WebRTC 路径的 SBS shader 拆分**

```js
const StereoVideoPlane = ({src, ...props}) => {
  const video = useVideo(src); const tex = useVuerVideoTexture(video);
  return <>
    <HUDPlane layers={1} {...props}><VideoMaterial map={tex} eyeIndex={0} side={2} toneMapped={false} {...props}/></HUDPlane>
    <HUDPlane layers={2} {...props}><VideoMaterial map={tex} eyeIndex={1} side={2} toneMapped={false} {...props}/></HUDPlane>
  </>;
};
// HUDPlane: 同 ImagePlane 的锁头+尺寸逻辑, 默认 distanceToCamera=10
```

```glsl
// VideoShaderMaterial 顶点着色器（SBS 拆分就在这里）
uniform int EYE_INDEX;
uniform vec4 texCoordScaleOffset[2];
vTexCoord = (uv * scaleOffset.xy) + scaleOffset.zw;
// layout="stereo-left-right": eye0 -> [0.5,1,(0,0)]  左半幅; eye1 -> [0.5,1,(0.5,0)]  右半幅
// layout="stereo-top-bottom": eye0 -> [1,0.5,(0,0)];  eye1 -> [1,0.5,(0,0.5)]
// layout="mono":              [1,1,(0,0)]
```

`toneMapped:false`、unlit 直出；`side=2`（DoubleSide）。

**4) 入口按钮**：页面自带 `XRButton`——"Virtual Reality"→`enterVR()`（immersive-vr），"Pass-through"→`enterAR()`（immersive-ar，由头显合成器提供透视背景）。televuer 的 `display_mode="pass-through"` 只是 Python 端不再发图。

---

## 可直接抄的参数数值

### plane 几何（v4.0.0 实际值，televuer.py 行号）

| 模式 | 传输 | height（m） | distanceToCamera（m） | 宽（m） | 张角（单眼 4:3，即 640×480/眼） |
| --- | --- | --- | --- | --- | --- |
| immersive 双目 (L344-368) | zmq/JPEG | **1.0** | **1.0** | aspect×1.0 = 1.333 | 水平 2·atan(0.667/1)≈**67.4°**，垂直 2·atan(0.5/1)≈**53.1°** |
| immersive 单目 (L397-412) | zmq | 1.0 | 1.0 | aspect×1.0 | 同上（双眼同图） |
| immersive 双目 (L437-449) | WebRTC | **7** | 10（HUDPlane 默认，未覆盖） | aspect×7 | 水平 2·atan(4.667/10)≈**50.0°**，垂直 2·atan(3.5/10)≈**38.7°** |
| ego 双目 (L510-540) | zmq | **0.75** | **2.0** | aspect×0.75 = 1.0 | 水平 2·atan(0.5/2)≈**28.1°**，垂直 2·atan(0.375/2)≈**21.2°** |
| ego 双目 (L606-618) | WebRTC | **3** | 10（默认） | aspect×3 | 垂直 2·atan(1.5/10)≈**17.1°** |
| pass-through | — | 无 plane | — | — | 头显 AR 透视 |

- **无垂直偏移**：所有 plane 位置偏移均为 `(0, 0, -distance)`，中心正对视线。
- **尺寸与 FOV 解耦**：显式给 `height+aspect` 时 plane 张角恒定，不随头显相机 FOV 变化。
- V4.0 变更核对（git：`562a9ca` 2025-11-12 "[feat] fov, immersive, pass-through mode"）：immersive 数值从 V3.x 原样继承（V3.x 即 height=1@1m / webrtc height=7）；**"调整 plane height"实际指为 ego（当时叫 fov）新配了小窗口几何 0.75@2m（zmq）/ 3（webrtc）**，后在 `6b9aafd` 把模式名 fov→ego。

### 传输参数

| 参数 | 值 |
| --- | --- |
| zmq 图像格式 | JPEG（Pillow），**quality=80**，二进制（非 base64） |
| zmq 帧率 | `display_fps=30.0`（注释：jpeg 编码约 30fps） |
| 颜色序 | `render_to_xr` 收 **BGR**（OpenCV 惯例），内部 BGR2RGB 再 JPEG |
| 分辨率约定 | `img_shape=(H, W_fullSBS)`；示例 `(480, 1280)` → 单眼 640×480；单眼 aspect=4/3 |
| 左右映射 | `[:, :W//2]`=左眼→layers=1；`[:, W//2:]`=右眼→layers=2（**左半=左眼**） |
| 纹理滤波 | `interpolate=True` → LinearFilter 双线性 |
| WebRTC | WHIP 风格 POST `/offer`（recvonly video+audio），`iceServers=[]`（局域网直连，不用 STUN） |
| WS 队列 | `Vuer(..., queue_len=3)`（背压丢帧） |

---

## 对 Unity 沉浸模式的建议

### SBS 拆分放哪一层：shader UV（首选），其次双 quad + culling mask

televuer 两条路径给出两个可抄方案，Unity 里推荐按场景选：

1. **首选：一张 SBS 纹理 + 单个（或每眼一个）quad + 单 pass instanced shader**（对应 vuer 的 `VideoMaterial` 方案）：
   - Unity XR Single Pass Instanced 下，shader 里用 `unity_StereoEyeIndex` 在片元/顶点阶段做 UV 偏移：`uv.x = uv.x * 0.5 + (unity_StereoEyeIndex == 0 ? 0.0 : 0.5)`。这与 vuer 的 `texCoordScaleOffset[EYE_INDEX]` 完全同构，还省掉第二个 quad。
   - 优点：纹理只上传/解码一次；SBS→per-eye 的映射集中在一段 HLSL，改 layout（left-right/top-bottom）只动 scaleOffset 常量。
   - 若用多线程纹理注入（如 `Texture2D.LoadRawTextureData` 或 NV12→RGB compute），仍保持单张 SBS 纹理，shader 拆分零拷贝。
2. **备选：两个 quad + per-eye culling mask**（对应 vuer 的 layers 方案）：
   - Unity 等价物：两个 camera（`stereoTargetEye = Left / Right`）配不同 cullingMask，或 URP 里用 Renderer Feature；quad 放 layer `LeftEye` / `RightEye`。
   - 代价：多一个 draw call 和一次状态切换；好处是左右可用不同纹理（后处理、独立对齐校正时有用）。
   - vuer 的实现证明该方案在 Pico 浏览器 WebXR 下工作正常，Unity 下更无兼容性问题。

### plane 摆位初值（直接映射）

- **immersive**：挂在 XR Origin（头节点）下，local position `(0, 0, 1.0)`（Unity 左手系 +z 前方；vuer/three.js 是 -z 前方，符号取反），local rotation 恒等，**每帧跟随头部**（rigid head-lock，不要 world-lock）。Quad 尺寸：高 1.0m，宽 = 1.0 × 单眼 aspect（ZED 720p 双目即单眼 1280×720 → 1.778m 宽）。材料 unlit（`UNET/Unlit` 或 shader 里直出），bilinear 滤波，关闭 tone mapping。
- **ego/小窗模式**：同样锁头，`(0, 0, 2.0)`，高 0.75m（宽 = 0.75×aspect），四周露出透视——televuer 验证过的"低晕动"形态。
- 起步张角参考：immersive 约 53°（垂直）@4:3 单眼，故意小于头显 FOV（Pico 4 约 96°~105°），边缘留黑形成"面罩式暗角"。

### 舒适性 / 晕动症要点（从他们的选择反推）

1. **锁头不锁世界**：image plane 刚性跟随头部（每帧复制相机位姿），旋转延迟为零；世界锁定会放大视差不适。这是 FPV 机器人视角的标准做法。
2. **面罩暗角（scuba mask）**：plane 张角 < 头显 FOV，四周黑边。比起试图充满全 FOV，暗角显著降低 vection（自主运动错觉），是低成本抗晕手段。immersive 的 67°/53° 就是这么选的。
3. **提供 ego 降级模式**：长时间佩戴或敏感用户切小窗（21° @2m）+ 透视，televuer V4.0 特意加的。
4. **滤波与画质**：低分辨率放大必须 Linear/Bilinear（`interpolate=True`），Nearest 会出像素闪烁；JPEG q80 在 30fps 是他们实测的带宽/画质平衡点——Unity 侧走本地纹理上传无此约束，可用更高码率/原始格式。
5. **延迟优先于帧率**：他们接受 30fps 显示（注释明说 jpeg 编码限速），说明该应用下延迟（teleop 闭环）比帧率更敏感；Unity 侧 pico-bridge 若能拿到低延迟 SBS 流，优先压管线延迟，帧率 30→72 提升是锦上添花。
6. **无垂直偏移、无俯仰**：地平线不因人为偏移而错位，减少视神经冲突。
7. **右侧纹理黑屏坑**（README 版本史）：Pico 上 WebXR 启动瞬间右眼偶发黑屏（vuer 0.0.35~0.0.60 记录）；Unity 原生渲染不走浏览器，无此问题，但启动时先各眼推一帧黑/灰再上真实帧可避免闪烁感。
8. **`toneMapped:false` + unlit**：相机原图直出，不做色彩分级/伽马二次处理，避免与真实世界色彩体系冲突；Unity 里注意 sRGB 解码链路（JPEG 解码→ sRGB 纹理 → unlit 直出）。

### 其他可迁移细节

- 分辨率约定沿用 `img_shape=(H, W_sbs)`、左半=左眼，与 teleimager/televuer 生态互通。
- 背压丢帧：vuer `queue_len=3`；Unity 侧纹理更新环形缓冲同样只留最新帧，丢弃过期帧。
- `render_to_xr` 只做"最新帧指针 + event"的解耦（生产者只写变量，渲染线程取 latest），Unity 侧对应 `Texture2D` 双缓冲 + 原子交换，避免在渲染线程做 BGR2RGB/JPEG 解码。

## 来源

- televuer 源码：https://github.com/unitreerobotics/televuer （commit `766de45`，v4.0.0；`src/televuer/televuer.py`、`README.md` V4.0 Release Note）
- televuer git 历史：`562a9ca`（2025-11-12，fov/immersive/pass-through 三模式与 ego 几何引入）、`6b9aafd`（fov→ego 改名）、`068d26d`（V3.x 旧值 height=1@1m / webrtc height=7）
- vuer 0.0.60 wheel（`pip download vuer[all]==0.0.60 --no-deps`）：`vuer/serdes.py`、`vuer/schemas/scene_components.py`、`vuer/schemas/html_components.py`、`vuer/client_build/assets/chunks/chunk-Dd3xtWba.js`（minified，含 `XrStereoPatch` / `ImageBackground` / `ImagePlane` / `HUDPlane` / `VideoShaderMaterial` / `StereoVideoPlane` / `WebRTCStereoVideoPlane`）
- teleimager（图像源侧，未克隆）：https://github.com/silencht/teleimager
