# 彗尾加载 spinner 的无贴图实现（Unity 2022.3 内置管线 / Android XR）

- 地图：`2026-09-02-1080p-sbs`（服务 t06 Pico 端加载 UI：无贴图资源、非刚体旋转的顺滑彗尾环）
- 日期：2026-09-02 CST
- 方法：Unity 官方 Manual/Scripting API 逐页取证（docs.unity3d.com，2022.3/最新版双查）；无官方"spinner 教程"页，故"标准做法"由文档化的图元反推。
- 标注：【事实】= 文档原文可引；【方案】= 工程建议；【推导】= 算术。

## 0. 四项裁决速答

| # | 问题 | 裁决 |
|---|---|---|
| 1 | N 段切向 quad + 按角滞后驱动顶点 alpha | **推荐主案**：无贴图时空间 alpha 只能来自顶点插值或片元数学两条路，此为前者标准形态；N=48-64 @72-90fps 足够顺滑 |
| 2 | 自定义 shader（径向 alpha + _Time 角度） | 可选副案：每像素绝对顺滑、零逐帧 CPU；但**必须有一个已导入的 .shader 资产**（运行时不能从字符串编译），且 XR 单通道 instanced 需手工加宏 |
| 3 | 头/尾绘制顺序 | 同近 Z 平面下不靠距离排序、不靠 Z 偏移：**material.renderQueue 3000(尾)/3001(头)**，双方 ZWrite Off |
| 4 | XR 陷阱 | 内置 shader（含 Sprites/Default）原生支持单通道 instanced；自写 shader 不加 `UNITY_VERTEX_OUTPUT_STEREO` 等宏会坏；动态网格先 `Mesh.MarkDynamic`，逐帧只重传颜色 |

## 1. 方案 A：N 段固定切向 quad + 顶点 alpha 动画

1. 【推导】无贴图时，透明度沿轨道的空间变化只有两个来源：(a) 顶点色（含 alpha）经光栅化插值——`Mesh.SetColors` 文档明言"Per-vertex colors"、Color32 每顶点 4 字节（[Mesh.SetColors](https://docs.unity3d.com/ScriptReference/Mesh.SetColors.html)）；(b) 片元着色器程序化计算（见 §2）。方案 A 即 (a) 的标准形态：**几何静止、只动颜色**——环上 N 个固定切向小 quad 拼满轨道，每帧按"该段中心落后头部多少度"改写其 4 个顶点 alpha。相对"让 quad 沿轨道移动"，固定分段不需要逐帧重排顶点/重传位置，只重传颜色，且顶点插值天然把段内 alpha 连成线性坡。
2. 【方案】实现骨架：一个 Mesh、N 个独立 quad（每段 4 顶点，禁止共享角点——各角要有独立颜色）、`SetVertices/SetIndices` 一次性建好；头部位置 `θh = ω·t`，段中心 `θi = i·360/N`，角滞后 `d = Mathf.Repeat(θh - θi, 360)`（[Mathf.Repeat](https://docs.unity3d.com/ScriptReference/Mathf.Repeat.html)："Loops the value t, so that it is never larger than length"，浮点取模正合角度回绕）；每帧仅 `SetColors(Color32[4N])`。绝不旋转整个环的 transform——刚体旋转静态渐变正是要避开的"机械感"来源。
3. 【推导】段数判据：头每帧进程 = ω/fps。1.5 s/圈（240°/s）在 72/90 fps 下为 3.3°/2.7° 每帧；取段宽 Δθ=360/N ≤ 每帧进程的 ~2 倍 → N≥54。又因段内顶点插值补连续，可见阶梯由相邻段 α 差决定：270° 尾 + N=48 时相邻段 α 差 ≈ 7.5/270 ≈ 2.8%，段内已被插值抹平——**工程定值 N=48（7.5°/段，覆盖 ≤1.5 s/圈）；头速提到 ≤1.2 s/圈（ω≥300°/s）时升 N=64；>64 只多耗顶点**。
4. 【方案】彗星手感的非对称缓动（亮起快、消退慢）：令 x = d/D ∈ [0,1]（0=在头处，D=尾弧长 240-270°），`α(x) = rise(x)·(1-x)^p`：
   - 消减 `fade = (1-x)^p`，p≈2（二次幂，头后骤降、尾端趋零的慢衰减感）；文档化替代 `Mathf.SmoothStep(0,1,1-x)`——官方原话"gradually speed up from the start and slow down toward the end. This is useful for creating natural-looking animation, fading and other transitions"（[Mathf.SmoothStep](https://docs.unity3d.com/ScriptReference/Mathf.SmoothStep.html)）。
   - 升亮 `rise = SmoothStep(1-w, 1, x)`，w≈0.15-0.25（头部将至时平滑顶起，避免线性坡的突然起始）；x→1 处 α→0、头部 quad 本身近实心，回绕跳变被头部遮住。
   - `Mathf.PingPong(t, len)` 是三角波（"increments and decrements between zero and the length … triangle wave"，[Mathf.PingPong](https://docs.unity3d.com/ScriptReference/Mathf.PingPong.html)）——升/降对称，读作"呼吸"而非彗尾，只适合对称脉冲；若用于头部亮度呼吸，官方注明 t 须自增（Time.time / **Time.unscaledTime**，加载场景常 timeScale=0）。
5. 【方案】时间基准统一用 `Time.unscaledTime`（加载屏可能 timeScale=0；PingPong 文档同款提示）。CPU 开销：N=48 → 192 顶点 ×4 B = 768 B/帧颜色重传 + N 次 Repeat/SmoothStep，可忽略。

## 2. 方案 B：自定义 shader（径向 alpha 梯度 + _Time 驱动角度）

6. 【事实】"零资源导入"在 B 下不成立：`Shader.Find(name)` 只按名查找**已存在**的 shader 对象，找不到返回 null；官方示例 `new Material(Shader.Find("Transparent/Diffuse"))` 可运行时建材质（[Shader.Find](https://docs.unity3d.com/ScriptReference/Shader.Find.html)）。没有公开的"运行时编译 ShaderLab 字符串"API——自写 shader 必须以 .shader 资产形式在编辑期导入（不占贴图，但占一个文本资产）。且文档警告：无引用的 shader 不会进包，Shader.Find"will work only in the Editor, and will result in the pink error shader in a build"，须三选一保证入包（场景材质引用 / Graphics 设置 Always Included Shaders / 放 Resources）。
7. 【事实】_Time 语义：`_Time = float4 (t/20, t, t*2, t*3)`，"Use for animations inside shaders"；但"Time is measured in seconds, and is **scaled by the Time multiplier** … **There is no built-in variable that provides access to unscaled time**"（[内置 shader 变量表](https://docs.unity3d.com/Manual/SL-UnityShaderVariables.html)）→ **timeScale=0 时 _Time 冻结**，加载屏必踩；对策是 C# 侧用 unscaledTime 每帧写一个自定义 float 属性，别依赖 _Time。
8. 【方案】shader 形态：单个屏幕区 quad，Properties 传环心/半径/角速度，片元 `atan2` 求像素角、与头角之差过 §1 同款 α(x) 曲线；SubShader `Tags { "Queue"="Transparent" }` + `Blend SrcAlpha OneMinusSrcAlpha` + `ZWrite Off`（Transparent 队列的定义即"anything alpha-blended (shaders that don't write to the depth buffer)"，[2022.3 渲染顺序](https://docs.unity3d.com/2022.3/Documentation/Manual/built-in-rendering-order.html)）。
9. 【方案】A/B 取舍：B 每像素无量化、逐帧零 CPU、一个 quad 一刀切；代价是资产+shader 维护、timeScale 陷阱、XR 需手工加 stereo 宏（§4）。A 全脚本可拷贝、用内置 Sprites/Default 即天然 XR 安全，代价是顶点级量化（已证不可见）与逐帧颜色重传。**建议 A 为主**，B 留作 A 调不满意的替代。

## 3. 头（程序化环段）与尾（透明 quad）的绘制顺序

10. 【事实】队列内排序按相机距离："Within each render queue, Unity sorts and draws objects based on their distance from the camera"；索引 ≥2501（Transparent 区）默认 TransparencySortMode（通常 back-to-front）（[2022.3 手册](https://docs.unity3d.com/2022.3/Documentation/Manual/built-in-rendering-order.html)、[RenderQueue 枚举](https://docs.unity3d.com/ScriptReference/Rendering.RenderQueue.html)）。两个几乎共面的网格距离差≈0 → 距离排序不可靠，须显式定序。
11. 【方案】**正解：material.renderQueue 尾=3000、头=3001**。renderQueue 是逐材质覆盖（"-1 用 shader 默认"，[Material.renderQueue](https://docs.unity3d.com/ScriptReference/Material-renderQueue.html)）；枚举页官方示例即用小偏移"Small offset to control order of objects on the same queue"；shader 内等价写法 `"Queue" = "Transparent + 1"`（偏移语法与"透明水先画"示例见 [SubShader Tags](https://docs.unity3d.com/Manual/SL-SubShaderTags.html)）。后画者覆盖先画者 → 头盖尾。
12. 【方案】**不要用 Z 偏移解决**：近共面小 ΔZ 依赖深度缓冲精度（移动端 16/24-bit 易 z-fight），且与 XR 近裁剪面相互作用；ShaderLab `Offset` 命令（"sets the polygon depth offset"，[ShaderLab 命令表](https://docs.unity3d.com/Manual/SL-CullAndDepth.html)）本为共面深度冲突设计，在 ZWrite Off + 队列定序的组合里多余。双方保持 ZWrite Off、深度测试都过，顺序完全交给 renderQueue。
13. 【方案】同队列备选 tie-break：`Renderer.sortingOrder`（"order within a sorting layer"，范围 -32768..32767，[Renderer.sortingOrder](https://docs.unity3d.com/ScriptReference/Renderer-sortingOrder.html)）——主要服务 2D 分层体系；材质级用 renderQueue 更直接。
14. 【事实】Sprites/Default 的颜色通路：`SpriteRenderer.color` 文档原话"The selected **vertex color** becomes the rendering color, and is **accessible in a pixel shader**"（[SpriteRenderer.color](https://docs.unity3d.com/ScriptReference/SpriteRenderer-color.html)）——着色走顶点色；顶点色即 HLSL `COLOR` 语义输入（[顶点输入文档](https://docs.unity3d.com/Manual/SL-VertexProgramInputs.html)，UnityCG.cginc 有预置结构）。【推断】自定义 Mesh + Sprites/Default 时 `Mesh.SetColors` 的逐顶点 alpha 即驱动该通路（内置 shader 源码可从官网下载核对，见 [SinglePassInstancing](https://docs.unity3d.com/Manual/SinglePassInstancing.html) 附注）；**分段动画放顶点色、材质色留白作全局 tint**。另：逐 draw 变色要走 `MaterialPropertyBlock`（"change color of each mesh … use MaterialPropertyBlock"，[Graphics.DrawMesh](https://docs.unity3d.com/ScriptReference/Graphics.DrawMesh.html)），但一次 draw 内无法逐段变色——恰证明"单 Mesh + 顶点色"是正确结构（注意 DrawMesh 在新版本已标 obsolete→RenderMesh）。

## 4. XR 专项

15. 【事实】单通道 instanced（Quest 默认渲染模式）：官方原话 URP/HDRP/Shader Graph/表面 shader/**内置 shader already support** single-pass stereo instanced rendering，"shaders … that you have written yourself **might need updating**"；自写 shader 须在 appdata 加 `UNITY_VERTEX_INPUT_INSTANCE_ID`、v2f 加 `UNITY_VERTEX_OUTPUT_STEREO`、vert 里依次 `UNITY_SETUP_INSTANCE_ID()` / `UNITY_INITIALIZE_OUTPUT(v2f,o)` / `UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o)`（[Single Pass Instanced 手册](https://docs.unity3d.com/Manual/SinglePassInstancing.html)，页内附左右眼红绿调试 shader `XR/StereoEyeIndexColor`）。→ **方案 A 用 Sprites/Default 免检；方案 B 的自写 shader 不加宏在 SPI 下直接坏**。
16. 【事实】动态网格：`Mesh.MarkDynamic()`"Call this **before** assigning vertices … makes the Mesh use dynamic buffers … more efficient when Mesh data changes often"（[Mesh.MarkDynamic](https://docs.unity3d.com/ScriptReference/Mesh.MarkDynamic.html)）；颜色可切片重传（`SetColors(array, start, length, MeshUpdateFlags)` 重载，[Mesh.SetColors](https://docs.unity3d.com/ScriptReference/Mesh.SetColors.html)）→ 初始化时 MarkDynamic + 建全网格，运行时每帧只重传 Color32[4N]。
17. 【方案】72-90 fps HMD 的顺滑红线即 §3 条段数判据（每帧头进程 2.7-3.3° @240°/s）；帧率波动不影响判据成立（按 72 fps 下限取 N）。XR 下不要用 LateUpdate 之外的相位补偿，普通 Update+unscaledTime 已与渲染帧对齐。

## 证据来源索引（均 2026-09-02 抓取）

- [Shader.Find](https://docs.unity3d.com/ScriptReference/Shader.Find.html)・[Material.renderQueue](https://docs.unity3d.com/ScriptReference/Material-renderQueue.html)・[Rendering.RenderQueue](https://docs.unity3d.com/ScriptReference/Rendering.RenderQueue.html)・[Renderer.sortingOrder](https://docs.unity3d.com/ScriptReference/Renderer-sortingOrder.html)・[SpriteRenderer.color](https://docs.unity3d.com/ScriptReference/SpriteRenderer-color.html)・[Graphics.DrawMesh](https://docs.unity3d.com/ScriptReference/Graphics.DrawMesh.html)
- [Mesh.SetColors](https://docs.unity3d.com/ScriptReference/Mesh.SetColors.html)・[Mesh.MarkDynamic](https://docs.unity3d.com/ScriptReference/Mesh.MarkDynamic.html)・[Mathf.SmoothStep](https://docs.unity3d.com/ScriptReference/Mathf.SmoothStep.html)・[Mathf.PingPong](https://docs.unity3d.com/ScriptReference/Mathf.PingPong.html)・[Mathf.Repeat](https://docs.unity3d.com/ScriptReference/Mathf.Repeat.html)
- Manual：[2022.3 Rendering order in the Built-in Render Pipeline](https://docs.unity3d.com/2022.3/Documentation/Manual/built-in-rendering-order.html)・[SubShader Tags](https://docs.unity3d.com/Manual/SL-SubShaderTags.html)・[ShaderLab commands](https://docs.unity3d.com/Manual/SL-CullAndDepth.html)・[Built-in shader variables](https://docs.unity3d.com/Manual/SL-UnityShaderVariables.html)・[Input data into HLSL](https://docs.unity3d.com/Manual/SL-VertexProgramInputs.html)・[Single-pass instanced rendering and custom shaders](https://docs.unity3d.com/Manual/SinglePassInstancing.html)
