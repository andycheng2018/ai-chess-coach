# Chess Buddy × VBOT 演示

[English](README.md) | [中文](README.zh-CN.md)

流程为：**玩家走棋 → 现有 Lichess 对局流 → 现有教练的引擎评价 → 庆祝请求 → VBOT RCP 预设动作**。
复用已有账号、对局流与引擎，不创建另一套棋力判断。目标是 `foot_quadruped`、机器人应用版本 **V1.6.0**。
版本、姿态、动作资源与真机效果必须在目标机器人上确认。

## Chess Buddy 内置控制

打开 **Training Arena → VBOT companion**。面板自动使用当前选择的训练对局，
无需手动复制对局 ID 或切换到独立控制台。**Check robot** 是明确触发的只读
SSH、接口和遥测检查；仅打开页面或刷新状态不会连接机器人。先使用
**Preview without motion**，再检查就绪状态、确认安全场地和现场 Stop 操作，
然后选择 **Enable live reactions**。仍要求 Mac 上现有的 SSH 密钥和已验证的预设记录。

面板显示请求、完成、休息、跳过和暂停状态及具体原因。动作成功但动作后检查未通过时，
保留成功结果并暂停后续动作。结束或切换对局会关闭反应，新对局需要重新明确启用；
不会重放旧走法。关闭反应不能停止正在执行的动作，紧急停止请使用 VBOT 应用的 Stop。
旧的 `/vbot` 控制台仍可用于诊断，日常下棋无需打开它。

成功动作后，辅助程序最多用 12 秒观察头部忙碌或待执行状态恢复，不提交新动作。
每次观察都重新检查全部新鲜遥测。头部故障、电池、系统、姿态异常、缺失或过期遥测、
以及未知动作结果仍会立即停止。持续忙碌将暂停会话。此行为需要部署更新后的辅助程序。

## 在 Mac 上排练

1. 双击项目根目录的 **Open VBOT Chess Demo.command**，保留终端窗口。
   启动器打开棋类应用和 `http://127.0.0.1:8765/vbot`；新后端仅绑定本机回环接口。
   如有旧后端，先在其终端按 Control-C，再启动。自定义 `PORT` / `CHESS_SERVER_PORT` 仍有效。
2. 选择 **Rehearsal**，输入八位对局 ID，然后选择 **Arm rehearsal**。
   合成事件可使用 `AbCd1234`。点击 **Sample good move** 应显示 `rehearsed`，
   点击 **Sample mistake** 应显示 `skipped`；两者均不会连接机器人。
3. 在现有应用中登录 Lichess，与已有训练机器人对弈；也可使用已有 SenseRobot 连接。
   将真实对局 ID 填入演示台，在下一步走棋前启用排练，观察真实评价事件。

现有教练分类只有 `good`、`inaccuracy`、`mistake`、`blunder`，没有单独的 `excellent`。
普通 `good`（包括通常被归为 good 的书本招）随机使用已现场排练的挥手或左右转头。
只有显著时刻可请求 ROCKYOU：预期应手后净材料收益至少 2 分且评价不低于 -0.5；
相对前 5 个本人回合中位数提升至少 2 兵且当前至少 +1；或最近 3 回合相对前 5 回合
持续提升至少 1.5 兵（每个至少高 1 兵、末项比首项高 0.5 兵、单步回落不超过 0.25）。
评价信号还须超过 4 倍稳健噪声估计，搜索深度至少 12；缺失、低深度或将杀哨兵值不触发整段舞蹈。
这些是可调启发式，不是经过校准的统计显著性检验。评分已为走棋者视角，不能把同一局面的最佳/实走评价差误当作局势反转。
快棋（初始时间加 40 次加秒小于 10 分钟）、剩余不足 2 分钟或时限未知时只使用转头。
完整舞蹈至少间隔 3 分钟，短动作完成后休息 10 秒、舞蹈后 20 秒；忙碌时跳过，不补播。
断档、悔棋、分析档位变化、换局或重新启用会重置基线；握手和站起不会在未单独排练时随机调用。
语音表扬独立于动作，合成大事件仅在排练模式演示层级，不代表真实引擎信号。
动作依据已有引擎分类，无需等待 OpenAI/语言模型措辞。
前端与后端必须在演示 Mac 本地运行。生产构建的 `.env.production` 指向 Render，不能控制此 Mac 的机器人。
使用演示启动器与本地开发前端；自定义前端端口需明确加入本地来源白名单。

### SenseRobot 备用连接方式

在 **Connect SenseRobot** 中展开 **Other ways to connect or continue**，可以输入
八字符房间代码并明确选择受邀机器人执棋颜色；确认实体棋盘显示同一对局后，接入当前有效的
训练机器人对局；或者保持同一局并改用屏幕操作。接入现有对局会核对登录账户的进行中对局，
拒绝其他对手以及已经变化的对局或局面。切换输入方式不会另建对局。局面或输入方式变化后，
必须重新确认实体棋子与对局一致。

可选的 **Device IP and MAC** 卡片只在本浏览器保存路由器参考信息，不检查连接、不配置
Wi-Fi、不证明实体棋盘已同步，也不推断直接局域网 API。
[官方 SenseRobot FAQ](https://www.senserobotchess.com/pages/chess-faq) 说明了 Lichess
账户关联；直接局域网对局控制接口尚未验证。

## 仅在本地准备部署包

```bash
python3 vbot-demo/prepare_device.py --sdk-dir /path/to/vbot-lab/artifacts/edu-sdk-2026.9.24
python3 vbot-demo/robot_action.py
```

第一条命令依据已有 `SHA256SUMS` 验证四个 wheel，再复制到被 Git 忽略的 `wheelhouse`；不下载、不部署。
配套版本为 SDK/Aorta 消息 `2026.9.23`、EDU 消息 `2026.9.24`、FlatBuffers `25.12.19`。
部署使用 Linux ARM64 wheel，不能复制 Mac 虚拟环境。第二条命令仅输出离线计划，不加载 SDK 或连接设备。
依据匹配的 VitaDynamics `vbot-lab` 中兼容性、Python SDK、连接、RCP 接口、预设目录和公开 Schema 文档。
舞蹈为 `actions/ROCKYOU.json`；可选 `actions/CHEER_R.json`、`actions/WAVE.json`，安装情况和起始姿态以真机为准。

## 机器人上线后验证与部署

以下为需明确执行的部署步骤。需确认目标机器人、真实地址、公钥 SSH 与现场条件。
公开文档目标为应用 V1.6.0；未知的已安装应用版本必须保持未知。
应用版本不同于系统镜像或 SDK；不要把默认有线地址当作 Wi-Fi 地址，也不要为本指南更改 Mac 网络。

1. 使用已验证的目标确认现有公钥登录、`vbot` 用户、ARM64 与 Python 3.10+：

   ```bash
   export VBOT_TARGET='vbot@YOUR_VERIFIED_ADDRESS'
   ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5 "$VBOT_TARGET" 'whoami; uname -m; python3 --version'
   ```

   超时、认证或主机密钥错误时停止，依厂家连接指南处理，不绕过检查、不嵌入出厂密码。

2. 仅读取 RCP 提供者信息，不提交动作：

   ```bash
   ssh "$VBOT_TARGET" 'ZENOH_SESSION_CONFIG_URI=/opt/vita/aorta/edu/edu_session.json5 timeout 15s /opt/vita/aorta/bin/aorta action info /rcp/execute_task'
   ```

   必须有匹配的动作与取消支持。缺失接口、SDK 或配置是阻塞条件，不能修改权限或服务来绕过。

3. 创建全新专用目录，传输程序和 wheel，离线安装：

   ```bash
   ssh "$VBOT_TARGET" 'test ! -e /userdata/vbot/chess-demo && mkdir -m 700 /userdata/vbot/chess-demo'
   scp vbot-demo/robot_action.py "$VBOT_TARGET:/userdata/vbot/chess-demo/"
   scp -r vbot-demo/wheelhouse "$VBOT_TARGET:/userdata/vbot/chess-demo/"
   ssh "$VBOT_TARGET" 'python3 -m venv /userdata/vbot/chess-demo/.venv && /userdata/vbot/chess-demo/.venv/bin/python -m pip install --no-index --find-links /userdata/vbot/chess-demo/wheelhouse aorta-sdk==2026.9.23 aorta-msgs==2026.9.23 vbot-edu-msgs==2026.9.24 flatbuffers==25.12.19 && /userdata/vbot/chess-demo/.venv/bin/python -m pip check'
   ```

   **如目录已存在，必须在后续传输前停止**，明确检查并复用已有部署，保留请求记录与未解决动作标记。
   不修改系统包、启动文件或服务。

4. 确认空旷场地、合适姿态、无冲突任务，现场操作员持有遥控器并掌握停止方法后，明确测试一次动作：

   ```bash
   ssh "$VBOT_TARGET" '/userdata/vbot/chess-demo/.venv/bin/python -I /userdata/vbot/chess-demo/robot_action.py --execute --confirm-motion --preset actions/ROCKYOU.json'
   ```

   同时验证实际动作与匹配的 `terminal` JSON：`status: SUCCEEDED`、`errorCategory: 0`。
   接收请求不等于完成。确认动作时长适合演示；必要时明确选择其他已验证预设。
5. 在 Mac 演示台选择 **Live**，填写相同目标、应用版本、对局 ID，并确认现场条件后启用。
   走出新的好棋，预期依次显示 `requested`、`completed`。旧评价不自动重播。

### 应用版本未知时，仅使用已单独验证的预设

手机 OTA、`/etc/version`、`aorta --version` 均不能证明机器人应用版本，不要为通过检查填写 V1.6.0。
现场单独测试成功并观察动作后，可在被 Git 忽略的 `device-verification.local.json` 中保存目标、
SSH 主机指纹、精确动作 Schema、匹配的成功终态与人工观察记录；仅该目标和预设可启用。
这不证明应用版本或其他预设兼容。后端在启用和发送前检查已保存指纹，SSH 仍检查实际主机。

每次动作前重新读取电池、系统、身体和头部状态。保守演示条件为电量至少 50%、未充电、
BMS 无报警、FUNCTION 激活且严重度为零、非低功耗、心跳递增、站立静止 RL_TROT，
头部空闲且无待处理动作或故障。这些是演示限制，不是厂商通用运行限值。
部署后可使用只读检查，不提交动作：

```bash
ssh "$VBOT_TARGET" '/userdata/vbot/chess-demo/.venv/bin/python -I /userdata/vbot/chess-demo/robot_action.py --check-ready'
```

准备条件不符时不会提交目标，并停用演示。现场检查，必要时用手机应用站起并确认稳定后重新启用；
程序不自动站起或修改休息策略。动作完成后再次检查；检查失败保留已确认的完成结果，但禁用后续舞蹈。
冷却从动作完成起计算，期间好棋直接跳过。声音验证与动作验证独立。

## 先用 Mac 排练实体棋盘

准备棋盘时让 VBOT 保持关机。启动 **Open VBOT Chess Demo.command**，并在 Mac 上保持
Chess Buddy 对局页面与演示控制台打开。当前庆祝流程由对局页面收到的实时引擎结果触发；
关闭页面后不会独立分析对局。引擎结果先于单独生成的讲解返回，庆祝无需等待语音讲解。

1. 创建新 SenseRobot 房间前，先结束现有训练对局。在 Chess Buddy 打开
   **Connect SenseRobot**，依次确认 Wi-Fi、相同的 Lichess 账户、房间与对局。
   Wi-Fi 与账户关联由操作员确认，实际对局连接通过 Lichess 验证。可以扫描房间二维码
   或粘贴链接；相机失败时可重试或改用链接。
2. 第一次排练使用不限时训练对局。在实体棋盘走一步，确认 Chess Buddy 局面一致，
   并确认 SenseRobot 执行机器人对手的应手。继续前核对执棋颜色与对手。
3. VBOT 仍保持关机，为该对局启用 **Rehearsal** 并检查真实走棋事件。
   示例按钮只运行明确标注的合成事件，不连接机器人，也不证明真实走棋达到庆祝条件。
4. 棋盘同步正常后，再开启 VBOT，在手机应用检查机器人音量，确认平整空旷的场地及
   Stop 停止方式，然后为该对局启用 **Live**。现场观察普通小动作与真实重大时刻的反馈。
   快棋只用短头部动作；完整舞蹈仍需满足已说明的评价或材料收益条件。
5. 结束对局后停用庆祝，明确开始下一局。为新对局重新选择并启用；旧对局不得触发后续动作。

演示前检查刷新与重连、待确认走棋后的悔棋、升变选择、对局结束与新对局。确认棋盘与
Lichess 一致，旧走棋不重放机器人动作。若分析比机器人对局流稍早返回，后端最多等待
1.5 秒确认；超时、局面不符、启用会话变化或机器人忙碌／冷却都不会建立延后动作队列。
原生障碍物检查拒绝时，现场检查并清理空间，保留预设检查。
物理动作和实际声音均需匹配的成功终态与操作员观察共同证明。

## 停止、未知结果与重复请求

- **Disarm future dances** 仅阻止新请求，不是物理急停；进行中的动作需用现场遥控器停止。
- 单次动作最多等待 90 秒；超时或中断会请求取消并等待最多 5 秒终态。SSH 中断仍可能留下未知结果。
  Mac 会停用演示并记录 `unknown`，不会自动重试。
- 设备提交前保存请求 ID，拒绝重复 ID，并通过 `unresolved-action.json` 阻止未确认动作期间的后续请求。
  未确认取消时，现场操作员必须先停止并检查任务，再明确处理标记；不能为了继续运行而直接删除标记。
- 动作运行或冷却期间的好棋直接跳过，不排队。有限历史中同一对局/颜色/半回合仅处理一次；悔棋不重复庆祝。
  后端重启始终停用并丢弃旧资格记录，重新连接后须在新走棋前启用。
- 超过 30 秒、早于启用、其他对局、机器人走棋、局面不符、过时对局流和导入历史不能触发动作。
- 控制接口仅允许回环客户端与本地浏览器来源；不接收凭据、任意 shell 命令、Wi-Fi 配置或 SSH 密钥。
  事件台仅保存本次后端进程的最近事件，明确区分请求与完成。

## 离线检查

```bash
npm test
npm run build
python3 vbot-demo/robot_action.py
```

可在单独 Mac 虚拟环境中使用匹配 SDK 检查编码，不创建 `aorta.Node`。
离线测试、编码与排练不能证明真机兼容性、姿态、实际动作或完整 Lichess 演示已通过。

```bash
/path/to/matching-sdk-venv/bin/python vbot-demo/check_sdk.py
```

该检查替换 `Node`，使用真实 FlatBuffers 类型验证联合体、结果解码、重复请求、准入未知与取消清理，不连接机器人。
