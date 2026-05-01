# 员工配置 DB 化重构

**目标读者**：后端工程师 / DevOps  
**完成日期**：2026-05-01  
**关联**：[refactor_api_registry_db.md](./refactor_api_registry_db.md)（同思路）

---

## 1. 动机

`FF_EMPLOYEE_SOURCE` 原本是个二选一开关：

- `yaml` —— 从 `employees/*.yaml` 读，admin 写入只在内存，重启丢失
- `db` —— 从 `employees` 表读，admin 写入持久化 + version snapshot

实际部署一直走 `db`，但代码里保留了 yaml 模式（含 lifespan DB→YAML 自动 fallback、admin 路由的"yaml mode 拒绝写入"守卫、`update_employee()` in-memory shim 等）。这种双源结构带来三个具体痛点：

1. **DB 出错时悄悄退化到 YAML**，前端拿到的员工列表与运维以为的不一致，定位困难
2. **admin 路由处处守卫 `if manager.source != 'db'`**（8 处），新加路由必须记得加守卫
3. **`update_employee()` in-memory shim 是死代码** —— yaml mode 已无人用，但仍编译进 bundle

跟 [API 注册表清理](./refactor_api_registry_db.md) 同样的处理：**DB 是唯一运行时来源，YAML 退化为出厂 seed 数据**。

---

## 2. 数据流（清理后）

```
employees/*.yaml  +  frontend/src/data/employeeFaq.ts
        │
        ↓ migrations.scripts.seed_employees_from_yaml （UPSERT + version snapshot）
        │
employees + employee_versions 表
        │
        ↓ EmployeeManager.load_from_db()  （lifespan 调用，空表 raise）
        │
in-memory _profiles + _graphs cache
        │
        ↓ admin upsert/archive → manager.upsert_employee/archive_employee
              （写 DB → 创建 version snapshot → 刷新缓存 + 失效 graph）
        │
所有 chat / planning / dryrun 调用方
```

**契约**：
- module import 时 `_profiles` 是空的（不再 import 时读 YAML）
- lifespan 必跑 `load_from_db()`，**空表直接 raise**（强制运维跑过 seed）
- admin 写操作走 `manager.upsert_employee` —— 写 DB + 内存缓存原子刷新
- 测试通过 conftest session-scope fixture 自动 seed + load
- 改动 YAML 后必须再跑一次 seed 才能生效（管理平台改 DB 的不需要）

---

## 3. 关键代码位置

| 文件 | 角色 |
|---|---|
| `employees/*.yaml` | 出厂数据。3 个内置员工：throughput_analyst / customer_insight / asset_investment |
| `frontend/src/data/employeeFaq.ts` | FAQ 出厂数据（与 YAML 配合使用，seed 时合并）|
| `migrations/scripts/seed_employees_from_yaml.py::run` | YAML+FAQ → DB 的 UPSERT 脚本，幂等 |
| `backend/employees/manager.py::EmployeeManager` | 单例，DB→内存装载 + admin 写后刷新 |
| `backend/main.py` lifespan（行 ~38-50）| 启动时调 `load_from_db`，空表 raise |
| `backend/main.py` `/api/employees/*` 路由 | 全部假设 db 模式，无源切换守卫 |
| `tests/conftest.py::_seed_and_load_employees` | session-scope autouse，测试启动 seed + load |

---

## 4. 运维流程

### 首次部署
```bash
uv run alembic upgrade head
uv run python -m tools.seed_api_endpoints
uv run python -m migrations.scripts.seed_admin_tables
uv run python -m migrations.scripts.seed_employees_from_yaml   # ← 必须
uv run uvicorn backend.main:app
```

### YAML 改动后同步
```bash
uv run python -m migrations.scripts.seed_employees_from_yaml          # 默认幂等 UPSERT
uv run python -m migrations.scripts.seed_employees_from_yaml --force  # 同时刷新已有行
# 服务无需重启 — 但需要触发一次 reload：
curl -X POST http://localhost:8000/api/employees/reload
```

### 通过管理平台改
- 直接在 UI 上编辑、保存
- 后端 `manager.upsert_employee` 自动：写 DB → 写 version snapshot → 刷新内存 → 失效 graph 缓存
- 无需 seed、无需 reload、无需重启

---

## 5. 故障排查

### 启动报 `RuntimeError: employees table is empty`
跑 seed：`uv run python -m migrations.scripts.seed_employees_from_yaml`

### 改了 YAML 但运行时没变
1. 跑 seed 把 YAML 写进 DB
2. 触发 reload：`POST /api/employees/reload`
3. 仍不变 → 看后端日志 `[employees]` 行

### 管理平台保存了，刷新页面看到了，但 chat 流程仍用旧配置
- 检查 `EmployeeManager._graphs` 是否被失效（`upsert_employee` 自动 `pop`）
- 用户当前会话已 attach 旧 graph 实例 —— 新会话才生效（设计如此）

### 测试报 `manager.list_employees() returned []`
- 检查 conftest 的 `_seed_and_load_employees` fixture 日志
- 多半是 DB 不可用 —— `mysql -e "SELECT COUNT(*) FROM employees"` 验证
- fresh DB 需要先跑 alembic + seed 才能跑测试

---

## 6. 删了什么

| 项 | 原作用 | 替代 |
|---|---|---|
| `FF_EMPLOYEE_SOURCE` | yaml/db 模式开关 | 永远 db |
| `EmployeeManager._source` / `.source` / `.set_source()` | 暴露当前模式 | 无（永远 db）|
| `EmployeeManager.load_all_profiles(config_dir)` | 从 YAML 装载到内存 | seed 脚本（DB → 内存由 `load_from_db`）|
| `EmployeeManager.update_employee()` | yaml mode 的 in-memory shim | `upsert_employee()`（持久化）|
| `main.py` lifespan 的 try/except YAML fallback | DB 失败回退 YAML | 直接 raise |
| 8 处路由守卫 `if manager.source != "db"` | 拒绝 yaml 模式写入 | 删除 |
| `PUT /api/employees/{id}` 的 yaml 分支（只改 name/description）| YAML mode 简化路径 | 走 db 全字段 patch |

---

## 7. 验收

- ✅ 全套 `tests/contract/` + `tests/integration/` **372 PASSED**
- ✅ 所有员工 admin CRUD 路由通过（前端无需改动，UI 早已假设 db）
- ✅ 启动时 DB 空 → fail-fast 触发 RuntimeError，错误信息指向 seed 命令
- ✅ `EmployeeManager` 公开方法只剩：`load_from_db / get_employee / list_employees / get_graph / run_employee_stream / upsert_employee / archive_employee / validate_all_profiles / get_instance / reset`

---

## 8. 与 api_registry 重构的差异

| 维度 | api_registry | employees |
|---|---|---|
| 内联数据需删除 | 1400 行 | 0（一直是文件源）|
| 新增 admin 路由 | 加 POST/DELETE domain | 已齐全 |
| 写后 reload 钩子 | 路由层显式调 | manager 内部已实现 |
| 前端补 CRUD | 加 DomainsView/Drawer | 已齐全 |
| 净删行数 | ~1900 | ~150 |
| 工时 | 较大 | ~1/4 |

employees 的清理是 api_registry 模式的"轻量复用"，证明同一个清理思路可以稳定复制。
