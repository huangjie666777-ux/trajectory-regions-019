# 设备轨迹穿越区域分析服务

基于 FastAPI 0.115 与 Shapely 2 的轨迹穿越区域分析服务。输入多个简单多边形区域（可含孔洞）
和一条带时区偏移的 ISO8601 轨迹，输出轨迹在每个区域内的全部时间区间、停留秒数与各区域
累计停留时间。坐标一律按平面米制处理，不做经纬度换算。

## 环境与安装

Python3.10.12及标准库位于本目录.tools/python，解释器为.tools/python/bin/python3.10。
已安装依赖的独立虚拟环境为.venv，实际运行使用.venv/bin/python，无需修改全局PATH。
完整依赖版本锁定于requirements.txt，运行时来源、版本和校验值见toolchain.json。

```bash
.venv/bin/python --version
.venv/bin/python -m pip install -r requirements.txt
```

虚拟环境不适合直接搬移，复制项目到新绝对路径后，可用.tools/python/bin/python3.10创建该路径下的虚拟环境，再按requirements.txt安装依赖。当前Ubuntu发行版运行时不附带ensurepip，可使用PyPI官方pip25.1.1wheel作为引导；准备好的base、a、b均已完成安装。工具二进制不提交Git，重建时需准备toolchain.json所列相同版本运行时及系统共享库。

## 启动

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

若端口被其他项目占用，可通过--port指定空闲端口，不停止其他项目进程。
健康检查为GET /healthz，OpenAPI文档为/docs。

## 接口

### GET /healthz

返回 `{"status": "ok"}`。

### POST /api/v1/analyze

请求体：

```json
{
  "regions": [
    {
      "id": "yard",
      "outer": [[0, 0], [40, 0], [40, 20], [0, 20]],
      "holes": [[[15, 5], [25, 5], [25, 15], [15, 15]]]
    }
  ],
  "track": [
    {"x": 5, "y": 10, "time": "2026-01-01T08:00:00+08:00"},
    {"x": 5, "y": 10, "time": "2026-01-01T08:00:10+08:00"},
    {"x": 45, "y": 10, "time": "2026-01-01T08:00:50+08:00"}
  ]
}
```

- `regions[].id`：区域 ID，请求内唯一。
- `regions[].outer`：外环 `[x, y]` 列表，至少 3 个不同点，简单多边形（支持凹多边形），首尾点可重复。
- `regions[].holes`：孔洞环列表，可省略；每个孔洞必须是严格位于外环内部、互不重叠的简单多边形。
- `track[]`：至少 2 个轨迹点，`x`/`y` 为有限平面米制坐标，`time` 为带时区偏移的 ISO8601
  时间戳且严格递增。相邻点之间按直线匀速移动。

响应体：

```json
{
  "details": [
    {
      "region_id": "yard",
      "enter": "2026-01-01T08:00:00.000000+08:00",
      "leave": "2026-01-01T08:00:20.000000+08:00",
      "stay_seconds": 20.0,
      "start_truncated": true,
      "end_truncated": false
    }
  ],
  "region_summaries": [
    {"region_id": "yard", "total_stay_seconds": 35.0, "interval_count": 2}
  ]
}
```

- `details`：全部进入/离开区间，按进入时间、区域 ID 稳定排序；无经过区域时为空数组。
- `enter`/`leave`：带时区的 ISO8601 时间戳，微秒精度，时区取轨迹首点的偏移；交点时间按线段比例插值。
- `stay_seconds`：区间停留秒数，微秒精度（6 位小数）。
- `start_truncated`/`end_truncated`：轨迹起点/终点位于区域内时为 true，区间以轨迹首尾时间截断。
- `region_summaries`：每个区域的累计停留秒数与区间数，未经过的区域为 0。

语义约定：

- 区域内部不含边界；仅接触顶点或沿边界移动不计停留；孔洞内部不属于区域。
- 两端采样点均在区域外但线段中途穿过的，仍会识别进入/离开。
- 同一时刻相接的区间自动合并；静止（相邻两点坐标相同）且位于区域内的时间计入停留。
- 多个区域独立计算，允许重叠。
- 请求相互独立，校验或计算失败返回 422 且不留下任何部分结果。

错误响应（422）示例：

```json
{"detail": "region 'bow': outer ring is not a simple polygon (Self-intersection[5 5])"}
{"detail": "track point 1: time must be strictly increasing"}
```

重复区域 ID、自交多边形、无效孔洞、非有限坐标、缺时区或时间非递增均返回 422，
消息中指明对应区域 ID 或轨迹点下标。

## 示例

examples/request.json 包含穿越、孔洞与静止的完整示例（轨迹起点在区域内并静止 10 秒，
随后匀速穿过带孔区域和重叠的 gate 区域）：

```bash
curl -s --noproxy '*' -X POST http://127.0.0.1:8000/api/v1/analyze \
  -H 'Content-Type: application/json' \
  --data-binary @examples/request.json | .venv/bin/python -m json.tool
```

yard 区域得到两个区间 `[08:00:00, 08:00:20]`（起点截断）与 `[08:00:30, 08:00:45]`，
孔洞段 `08:00:20~08:00:30` 不计入；gate 区域得到 `[08:00:43, 08:00:49]`。

## 开发检查

```bash
.venv/bin/python -m compileall -q app
.venv/bin/python -m pytest
```

测试位于 tests/，覆盖直线穿越插值、孔洞、静止、边界接触、凹多边形、截断标记、
重叠区域排序及各类无效输入。

