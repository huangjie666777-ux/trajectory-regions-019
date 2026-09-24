# 设备轨迹穿越区域分析服务

Python与FastAPI基础项目。当前只有健康检查，轨迹分析业务待实现。

## 环境与安装

Python3.10。系统Python未附带ensurepip，本题已有.venv及pip可直接使用；下方从头安装命令适用于具备venv/ensurepip的Python环境。直接依赖版本见requirements.in，完整依赖版本见requirements.txt。
每份目录已准备独立的.venv，命令显式使用当前目录的解释器，无需修改全局环境。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 启动

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

若端口被其他项目占用，可通过--port指定空闲端口，不停止其他项目进程。
健康检查为GET /healthz，OpenAPI文档为/docs。

## 开发检查

```bash
.venv/bin/python -m compileall -q app
.venv/bin/python -m pytest
```

当前未实现业务测试，由实现者按业务需求补充。Shapely用于几何计算，pytest与httpx用于本地验证。
