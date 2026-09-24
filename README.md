# 设备轨迹穿越区域分析服务

Python与FastAPI基础项目。当前只有健康检查，轨迹分析业务待实现。

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

## 开发检查

```bash
.venv/bin/python -m compileall -q app
.venv/bin/python -m pytest
```

当前未实现业务测试，由实现者按业务需求补充。Shapely用于几何计算，pytest与httpx用于本地验证。
