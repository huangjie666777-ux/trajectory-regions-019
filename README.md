# 设备轨迹穿越区域分析服务

基于 FastAPI 0.115 与 Shapely 2 的轨迹/区域穿越分析服务。接收若干多边形区域
（可含孔洞）与一条带时区偏移的 ISO8601 轨迹，计算设备在每个区域内的全部
时间区间与停留时长。坐标为平面米制坐标，不做经纬度换算。

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

- 健康检查：`GET /healthz` → `{"status": "ok"}`
- 分析接口：`POST /api/v1/analyze`
- OpenAPI 文档：`/docs`

## 接口格式

### 请求

```json
{
  "regions": [
    {
      "id": "yard",
      "outer": [[0, 0], [100, 0], [100, 100], [0, 100]],
      "holes": [[[40, 40], [60, 40], [60, 60], [40, 60]]]
    }
  ],
  "trajectory": [
    {"x": -30, "y": 50, "time": "2026-09-24T08:00:00+08:00"},
    {"x": 130, "y": 50, "time": "2026-09-24T08:02:40+08:00"}
  ]
}
```

- `regions[].id`：区域 ID，请求内唯一。
- `regions[].outer` / `regions[].holes[]`：简单多边形环，`[x, y]` 列表，
  至少 3 个不同位置；首尾点可重复（自动闭合）。支持凹多边形与孔洞，
  孔洞内部不属于区域。
- `trajectory[]`：至少 2 个点，`time` 为带时区偏移的 ISO8601 时间戳，
  且必须严格递增。相邻点之间按直线匀速移动；坐标相同的相邻点表示静止，
  静止时间计入停留。

### 响应

```json
{
  "time_precision": "microsecond",
  "details": [
    {
      "region_id": "yard",
      "enter": "2026-09-24T08:00:30.000000+08:00",
      "exit": "2026-09-24T08:01:10.000000+08:00",
      "dwell_seconds": 40.0,
      "truncated_start": false,
      "truncated_end": false
    }
  ],
  "regions": [
    {"region_id": "yard", "total_dwell_seconds": 40.0, "interval_count": 1}
  ]
}
```

- `details`：全部进入/离开区间，按进入时间、区域 ID 稳定排序；
  无经过区域时为空列表。交点时间按线段比例插值。
- `regions`：各区域累计停留秒数与区间数（含未经过的区域，为 0）。
- 时间精度：时间戳输出为微秒级 ISO8601（保留原时区偏移），
  停留秒数保留 6 位小数。
- `truncated_start` / `truncated_end`：轨迹首/末点在区域内时，
  对应区间以轨迹首/末时间截断并标记为 `true`。

### 语义约定

- 区域边界视为区域外：仅接触顶点或沿边界移动不计停留。
- 同一时刻相接的有效区间自动合并；多个区域相互独立，允许重叠。
- 两端均在区域外但中途穿过的线段会被识别（按直线匀速插值）。

### 错误

输入非法时返回 `422`，`detail` 为错误列表，指明对应区域或轨迹点，例如：

```json
{
  "detail": [
    "region 'bowtie': invalid polygon (self-intersecting ring, hole outside outer ring, or overlapping holes)",
    "region 'bowtie': duplicate region id",
    "trajectory point 1: timestamps must be strictly increasing"
  ]
}
```

拒绝的情形包括：自交多边形、孔洞在外环之外或相互重叠、非有限坐标
（NaN/Infinity）、重复区域 ID、轨迹点少于 2 个、时间戳无时区偏移或不严格递增。
请求之间相互独立，失败请求不会留下部分结果（服务无状态）。

## 示例（穿越 + 孔洞 + 静止）

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "regions": [
      {"id": "yard",
       "outer": [[0,0],[100,0],[100,100],[0,100]],
       "holes": [[[40,40],[60,40],[60,60],[40,60]]]},
      {"id": "gate",
       "outer": [[-20,45],[0,45],[0,55],[-20,55]], "holes": []}
    ],
    "trajectory": [
      {"x": -30, "y": 50, "time": "2026-09-24T08:00:00+08:00"},
      {"x": 50,  "y": 50, "time": "2026-09-24T08:01:20+08:00"},
      {"x": 50,  "y": 50, "time": "2026-09-24T08:02:20+08:00"},
      {"x": 50,  "y": 80, "time": "2026-09-24T08:02:50+08:00"},
      {"x": 120, "y": 80, "time": "2026-09-24T08:04:00+08:00"}
    ]
  }'
```

轨迹速度 1 m/s：穿过 gate（20 s），进入 yard 后在孔洞前离开（40 s），
在孔洞内静止 60 s（不计），再离开孔洞穿过 yard 直至走出（70 s）。
yard 累计 110 s、2 个区间，gate 累计 20 s、1 个区间。

## 开发检查

```bash
.venv/bin/python -m compileall -q app
.venv/bin/python -m pytest
```

测试位于 tests/，覆盖穿越插值、孔洞排除、静止计时、边界与顶点接触、
区间合并、凹多边形、多区域重叠及各类输入校验错误。
