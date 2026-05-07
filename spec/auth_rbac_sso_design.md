# Analytica 用户登录、RBAC 与 SSO 单点登录 — 整体设计方案

> 基于对项目全栈架构的全面分析拟定。当前系统无任何认证机制，所有 API 端点公开访问，
> user_id 为自由文本字符串，默认 `"anonymous"`。

---

## 目录

1. [现状分析](#一现状分析)
2. [设计目标](#二设计目标)
3. [整体架构](#三整体架构)
4. [数据库设计](#四数据库设计)
5. [认证流程设计](#五认证流程设计)
6. [RBAC 权限模型](#六rbac-权限模型)
7. [API 授权与员工所有权](#七api-授权与员工所有权)
8. [API 授权审批流程](#八api-授权审批流程)
9. [规划层 API 权限交集机制](#九规划层-api-权限交集机制)
10. [SSO 单点登录 — OIDC 适配](#十sso-单点登录--oidc-适配)
11. [后端实现设计](#十一后端实现设计)
12. [前端实现设计](#十二前端实现设计)
13. [现有代码改造策略](#十三现有代码改造策略)
14. [安全考量](#十四安全考量)
15. [实施阶段](#十五实施阶段)
16. [配置清单](#十六配置清单)

---

## 一、现状分析

### 1.1 认证现状

| 维度 | 现状 |
|------|------|
| **认证机制** | 完全空白 — 无登录、无 Token、无 Session 管理 |
| **user_id** | 自由文本字符串，默认 `"anonymous"`，前端直传 |
| **用户模型** | 数据库中无 `users` 表，无密码哈希 |
| **角色/权限** | 无 role/permission 表，无 RBAC |
| **中间件** | 无任何 FastAPI 中间件（连 CORS 都没有） |
| **Admin 控制台** | 所有 `/api/admin/*` 端点公开可访问 |
| **WebSocket** | 连接无需认证，`user_id` 从消息体中提取 |

### 1.2 涉及 user_id 的现有表和代码

| 位置 | 用途 |
|------|------|
| `sessions` 表 | `user_id` 列（索引），创建会话时写入 |
| `user_preferences` 表 | `user_id` + `key` 唯一约束 |
| `analysis_templates` 表 | `user_id` + domain 复合索引 |
| `tool_notes` 表 | `tool_id` + `user_id` 唯一约束 |
| `audit_logs` 表 | `actor_id` 列 |
| `sessionStore.ts` | `userId: 'anonymous'` 硬编码 |
| `api/client.ts` | `createSession(userId)` 直传字符串 |
| WebSocket handler | `user_id = data.get("user_id", "anonymous")` |

### 1.3 数字员工与 API 关系现状

- 数字员工（employees）**全局共享**，无 `owner_id` 字段，任何用户可选任何员工
- API 端点（api_endpoints）通过 `api_token` 列存储外部数据 API 的认证凭据
- 员工的 `endpoints`/`domains` 字段控制其可用 API 范围
- **无用户级 API 访问控制**：同一员工被不同用户使用时，看到的 API 完全一样

### 1.4 规划层端点过滤链路

```
graph.py:planning_node()
  → profile.get_endpoint_names()          # 仅来自员工
  → engine.generate_plan(allowed_endpoints=...)
    → planning.py: valid_endpoints = set(allowed_endpoints)
      → get_endpoints_description()      # LLM Prompt 硬过滤
      → _validate_tasks()                # 任务验证丢弃
```

### 1.5 Phase5 规划

`spec/Phase5_前端UI与集成测试.md` 第 210-218 行已规划 JWT Bearer Token + httpOnly Cookie + Refresh Token 机制，但未实现。

---

## 二、设计目标

1. **用户认证**：支持用户名+密码登录 + OIDC SSO 单点登录，JWT Token 机制
2. **RBAC 权限控制**：角色-权限模型，粒度到 API 路由/操作级别
3. **API 域授权**：管理员可为用户分配业务域（D1-D7）和逐端点 API 授权
4. **员工所有权**：支持公共员工（admin 创建）+ 私有员工（用户自建），用户自建员工时只能选择已被授权的 API
5. **规划层交集**：公共员工配置的 API + 用户个人的 API 授权，取交集后生效
6. **前端路由守卫**：未登录→登录页，无权限→隐藏功能
7. **向后兼容**：现有 user_id 散落代码平滑迁移，匿名模式保留为兜底
8. **安全最佳实践**：httpOnly Cookie 存 Refresh Token，Access Token 存内存，bcrypt 哈希密码

---

## 三、整体架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Frontend (React 19)                              │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────────────────────┐   │
│  │ LoginPage│  │ AuthProvider  │  │ ProtectedRoute / AdminGuard      │   │
│  │ (新增)   │  │ (新增 Context)│  │ (包装现有路由)                    │   │
│  └──────────┘  └──────────────┘  └──────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  api/client.ts (改造: 自动注入 Bearer Token, 401 自动刷新)        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────────────┤
│                          Nginx (反向代理)                                │
│  /analytica/api/*  →  backend:8000     /analytica/ws/*  →  backend:8000 │
├──────────────────────────────────────────────────────────────────────────┤
│                          Backend (FastAPI)                                │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ backend/auth/                          (认证模块 — 新增)          │    │
│  │  ├── dependencies.py   → get_current_user / require_role /       │    │
│  │  │                        require_permission (FastAPI Depends)   │    │
│  │  ├── jwt.py            → JWT 签发/验证                           │    │
│  │  ├── password.py       → bcrypt 密码哈希                         │    │
│  │  ├── schemas.py        → LoginRequest / TokenResponse / UserInfo │    │
│  │  ├── routes.py         → /api/auth/login /refresh /logout /me    │    │
│  │  ├── api_grants.py     → get_user_authorized_endpoints()         │    │
│  │  └── sso/              → OIDC SSO 适配器                         │    │
│  │      ├── oidc.py       → Authorization Code Flow                 │    │
│  │      ├── routes.py     → /api/auth/sso/login /callback           │    │
│  │      └── user_mapping.py → 外部身份 → 内部用户映射                │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ backend/admin/users.py            (Admin 用户/角色管理 — 新增)    │    │
│  │ backend/admin/users_store.py      (用户管理 DAL)                  │    │
│  │ backend/admin/users_schemas.py    (Pydantic schemas)             │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ backend/main.py                     (现有路由改造)                │    │
│  │  所有路由注入 Depends(get_current_user)                           │    │
│  │  Admin 路由注入 Depends(require_role("admin"))                    │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ backend/agent/graph.py              (规划层改造)                   │    │
│  │  planning_node() 中增加:                                          │    │
│  │  effective = employee_endpoints ∩ user_authorized_endpoints       │    │
│  └─────────────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────────────┤
│                          Database (MySQL)                                 │
│  ┌──────────┐ ┌───────────┐ ┌──────────────┐ ┌──────────────────────┐   │
│  │  users   │ │  roles    │ │ permissions  │ │  role_permissions    │   │
│  │  (新增)  │ │  (新增)   │ │   (新增)     │ │   (新增)             │   │
│  └──────────┘ └───────────┘ └──────────────┘ └──────────────────────┘   │
│  ┌───────────┐ ┌──────────────┐ ┌───────────────────────────────────┐   │
│  │ user_roles│ │refresh_tokens│ │  user_domain_grants                │   │
│  │  (新增)   │ │   (新增)     │ │   (新增 — 用户域授权)              │   │
│  └───────────┘ └──────────────┘ └───────────────────────────────────┘   │
│  ┌──────────────────────┐ ┌──────────────────────┐                     │
│  │  user_api_grants     │ │ api_grant_requests   │                     │
│  │  (新增 — 逐端点授权)  │ │  (新增 — 审批流)     │                     │
│  └──────────────────────┘ └──────────────────────┘                     │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  employees 表扩展:  + owner_id (FK→users) + visibility            │   │
│  │  users 表扩展:       + sso_provider + external_id + 唯一约束      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 四、数据库设计

### 4.1 新增表

#### `users` — 用户表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | VARCHAR(36) | PK | UUID4，即现有系统中的 `user_id` |
| `username` | VARCHAR(64) | UNIQUE, NOT NULL | 登录用户名 |
| `password_hash` | VARCHAR(256) | NULLABLE | bcrypt 哈希（SSO 用户可为空） |
| `display_name` | VARCHAR(128) | NOT NULL | 显示名称 |
| `email` | VARCHAR(255) | NULLABLE | 邮箱 |
| `sso_provider` | VARCHAR(32) | NULLABLE | 最后认证的 SSO 提供商标识 |
| `external_id` | VARCHAR(256) | NULLABLE | SSO 返回的用户唯一标识 |
| `status` | VARCHAR(16) | NOT NULL, DEFAULT 'active' | active / disabled |
| `last_login_at` | DATETIME | NULLABLE | 最后登录时间 |
| `created_at` | DATETIME | NOT NULL | |
| `updated_at` | DATETIME | NOT NULL | |

唯一约束: `uq_users_sso` on (`sso_provider`, `external_id`) — 确保同一外部身份只映射一个内部用户

#### `roles` — 角色表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | VARCHAR(36) | PK | UUID4 |
| `name` | VARCHAR(64) | UNIQUE, NOT NULL | 角色标识（admin / analyst / viewer） |
| `description` | VARCHAR(255) | NULLABLE | |
| `is_system` | SMALLINT | DEFAULT 0 | 系统预置角色，不可删除 |
| `created_at` | DATETIME | NOT NULL | |

#### `permissions` — 权限表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | VARCHAR(36) | PK | UUID4 |
| `code` | VARCHAR(128) | UNIQUE, NOT NULL | 权限代码（如 `sessions:create`） |
| `name` | VARCHAR(128) | NOT NULL | 权限名称 |
| `resource` | VARCHAR(64) | NOT NULL | 资源类型 |
| `action` | VARCHAR(32) | NOT NULL | 操作（create/read/update/delete/manage） |
| `description` | VARCHAR(255) | NULLABLE | |

#### `role_permissions` — 角色-权限关联表

| 列名 | 类型 | 约束 |
|------|------|------|
| `role_id` | VARCHAR(36) | PK, FK → roles.id |
| `permission_id` | VARCHAR(36) | PK, FK → permissions.id |

#### `user_roles` — 用户-角色关联表

| 列名 | 类型 | 约束 |
|------|------|------|
| `user_id` | VARCHAR(36) | PK, FK → users.id |
| `role_id` | VARCHAR(36) | PK, FK → roles.id |

#### `refresh_tokens` — Refresh Token 表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | VARCHAR(36) | PK | UUID4 |
| `user_id` | VARCHAR(36) | FK → users.id, INDEX | |
| `family_id` | VARCHAR(36) | NOT NULL, INDEX | Token 家族 ID（Rotation 轮换用） |
| `token_hash` | VARCHAR(256) | UNIQUE, NOT NULL | Refresh Token 的 SHA256 哈希 |
| `expires_at` | DATETIME | NOT NULL | 过期时间（7 天） |
| `revoked` | SMALLINT | DEFAULT 0 | 是否已撤销 |
| `created_at` | DATETIME | NOT NULL | |

#### `user_domain_grants` — 用户域授权表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | VARCHAR(36) | PK | UUID4 |
| `user_id` | VARCHAR(36) | FK → users.id, NOT NULL | 被授权用户 |
| `domain_code` | VARCHAR(8) | NOT NULL | 授权的业务域（D1-D7） |
| `granted_by` | VARCHAR(36) | NULLABLE | 授权人 |
| `granted_at` | DATETIME | NOT NULL | |

唯一约束: `uq_user_domain` on (`user_id`, `domain_code`)

#### `user_api_grants` — 用户逐端点 API 授权表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | VARCHAR(36) | PK | UUID4 |
| `user_id` | VARCHAR(36) | FK → users.id, NOT NULL | 被授权用户 |
| `endpoint_name` | VARCHAR(128) | NOT NULL | 授权的 API 端点名称 |
| `granted_by` | VARCHAR(36) | NULLABLE | 授权人 |
| `granted_at` | DATETIME | NOT NULL | |

唯一约束: `uq_user_api` on (`user_id`, `endpoint_name`)

#### `api_grant_requests` — API 授权申请/审批表

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | VARCHAR(36) | PK | UUID4 |
| `requester_id` | VARCHAR(36) | FK → users.id, NOT NULL | 申请人 |
| `target_user_id` | VARCHAR(36) | FK → users.id, NOT NULL | 被授权用户（可为自己申请） |
| `grant_type` | VARCHAR(16) | NOT NULL | domain / endpoint |
| `grant_target` | VARCHAR(128) | NOT NULL | 域代码（D1-D7）或端点名称 |
| `reason` | TEXT | NOT NULL | 申请理由 |
| `status` | VARCHAR(16) | NOT NULL, DEFAULT 'pending' | pending / approved / rejected |
| `reviewer_id` | VARCHAR(36) | FK → users.id, NULLABLE | 审批人 |
| `review_comment` | TEXT | NULLABLE | 审批意见 |
| `requested_at` | DATETIME | NOT NULL | |
| `reviewed_at` | DATETIME | NULLABLE | |

索引: `idx_grants_status` on (`status`, `requested_at`)

### 4.2 现有表扩展

#### `employees` 表新增列

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `owner_id` | VARCHAR(36) | FK → users.id, NULLABLE | 所有者用户 ID，NULL = 公共员工 |
| `visibility` | VARCHAR(16) | NOT NULL, DEFAULT 'public' | public / private |

### 4.3 预置数据

**角色和权限分配：**

| 角色 | 权限 |
|------|------|
| `admin` | 所有权限 |
| `analyst` | sessions:create/read/delete/cancel, reports:read/download/convert, employees:read, employees:create/update_own |
| `viewer` | sessions:read, reports:read, employees:read |

**权限清单：**

```
sessions:create, sessions:read, sessions:delete, sessions:cancel
reports:read, reports:download, reports:convert
employees:read, employees:create, employees:update_own, employees:update_all, employees:delete
admin:apis.read, admin:apis.write, admin:apis.test
admin:tools.read, admin:tools.write
admin:skills.read, admin:skills.write
admin:domains.read, admin:domains.write
admin:memories.read, admin:memories.delete
admin:audit.read
admin:users.read, admin:users.write
admin:roles.read, admin:roles.write
admin:api_grants.read, admin:api_grants.write
admin:grants.approve, admin:grants.reject       # 审批操作
```

**初始管理员用户**：username=`admin`，密码通过种子脚本生成随机密码，输出到控制台。角色=admin，所有域授权。

---

## 五、认证流程设计

### 5.1 Token 机制

| Token 类型 | 存储位置 | 有效期 | 用途 |
|------------|----------|--------|------|
| Access Token | 前端内存（Context 状态） | 15 分钟 | API 请求认证（Bearer Token） |
| Refresh Token | httpOnly Cookie | 7 天 | 获取新的 Access Token |

### 5.2 密码登录流程

```
POST /api/auth/login
  Body: { username, password }
  → bcrypt 验证密码
  → 查询用户角色和权限
  → 生成 Access Token (JWT, HS256, 15min)
     payload: { sub, username, display_name, roles, permissions }
  → 生成 Refresh Token (opaque random, 7 days)
  → Refresh Token SHA256 哈希后存入 refresh_tokens 表
  → Set-Cookie: refresh_token=<value>; HttpOnly; Secure; SameSite=Strict; Path=/api/auth
  → Response: { access_token, user: { id, username, display_name, roles } }
```

### 5.3 Token 刷新流程

```
POST /api/auth/refresh
  Cookie: refresh_token=<value>
  → SHA256(refresh_token) 查表
  → 验证未过期、未撤销
  → 如启用 Rotation: 撤销旧 token，签发新 Refresh Token
  → 签发新 Access Token
  → Response: { access_token }
```

### 5.4 登出流程

```
POST /api/auth/logout
  Cookie: refresh_token=<value>
  → 标记该 token family 下所有 token 为 revoked
  → Clear Cookie
```

### 5.5 页面刷新自动恢复流程

```
用户刷新页面
  → AuthProvider 挂载
  → POST /api/auth/refresh (自动携带 Cookie)
  → 成功 → 获取新 Access Token + 用户信息 → 正常使用
  → 失败 → 清除状态 → 显示登录页
```

---

## 六、RBAC 权限模型

### 6.1 模型结构

用户 N:N 角色 → 角色 N:N 权限 → 权限精确到 resource:action

### 6.2 FastAPI Depends 守卫

```python
# backend/auth/dependencies.py

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> UserContext:
    """从 Authorization: Bearer <token> 提取并验证用户身份。"""

async def require_role(*roles: str):
    """工厂函数: require_role("admin", "analyst")"""

async def require_permission(permission: str):
    """工厂函数: require_permission("admin:users.write")"""
```

### 6.3 Admin 用户管理 API

| 端点 | 方法 | 守卫 | 说明 |
|------|------|------|------|
| `/api/admin/users` | GET | require_permission("admin:users.read") | 用户列表 |
| `/api/admin/users` | POST | require_permission("admin:users.write") | 创建用户 |
| `/api/admin/users/{id}` | GET | require_permission("admin:users.read") | 用户详情 |
| `/api/admin/users/{id}` | PUT | require_permission("admin:users.write") | 更新用户 |
| `/api/admin/users/{id}/status` | POST | require_permission("admin:users.write") | 启/禁用用户 |
| `/api/admin/users/{id}/roles` | GET/PUT | require_permission("admin:roles.write") | 用户角色管理 |
| `/api/admin/users/{id}/api-grants` | GET/PUT | require_permission("admin:api_grants.write") | 用户 API 域授权 |
| `/api/admin/roles` | GET | require_permission("admin:roles.read") | 角色列表 |
| `/api/admin/roles` | POST | require_permission("admin:roles.write") | 创建角色 |
| `/api/admin/roles/{id}/permissions` | GET/PUT | require_permission("admin:roles.write") | 角色权限管理 |
| `/api/admin/grant-requests` | GET | require_permission("admin:grants.write") | 审批列表 |
| `/api/admin/grant-requests/{id}` | PUT | require_permission("admin:grants.write") | 批准/驳回 |

---

## 七、API 授权与员工所有权

### 7.1 API 授权模型

采用**域级授权为主 + 逐端点授权为辅**的组合模型：

```
用户可用端点 = {所有授权域下的端点} ∪ {user_api_grants 中单独授权的端点}
```

用户在使用员工时，实际可用 API = `employee.endpoints ∩ 用户可用端点`（交集）。

通过 `get_user_authorized_endpoints(user_id, db)` 函数计算（实现见第八节）。

### 7.2 员工所有权模型

| 员工类型 | owner_id | visibility | 可见范围 | 可编辑者 |
|----------|----------|------------|----------|----------|
| 公共员工 | NULL | public | 所有用户 | Admin |
| 私有员工 | user_id | private | 仅所有者 | 所有者 + Admin |
| 共享员工 | user_id | public | 所有用户 | 所有者 + Admin |

### 7.3 创建员工时的 API 校验

用户创建私有员工时，选择的 `domains` 和 `endpoints` 必须是其授权范围的**子集**：

```
POST /api/employees (创建员工)
  后端校验:
  1. 获取 current_user 的授权域和授权端点
  2. 请求中的 domains ⊆ 授权域
  3. 请求中的 endpoints ⊆ 授权端点
  4. 不满足 → 403: "你未被授权使用域 X / 端点 Y"
```

### 7.4 员工列表按所有权过滤

```
GET /api/employees
  返回逻辑:
  - owner_id IS NULL                    → 所有用户可见
  - owner_id = current_user.id          → 所有者可见
  - owner_id != NULL AND visibility='public' AND owner_id != current_user → 他人共享的员工
  - owner_id != NULL AND visibility='private' AND owner_id != current_user → 不可见
  Admin 角色 → 可见所有员工
```

---

## 八、API 授权审批流程

### 8.1 设计原则

Admin 仍可直接为用户授权（即时生效，用于管理员直配场景），同时提供**审批流**作为细粒度 API 授权时的合规路径。两种模式可并行，状态由 `user_domain_grants` / `user_api_grants` 表统一承载，与授权来源无关。

### 8.2 审批流程

```
普通用户                               Admin
  │                                      │
  │ POST /api/auth/grant-requests        │
  │ { target_user_id, grant_type,        │
  │   grant_target, reason }             │
  │ ────────────────────────────────────→│ 创建审批单，状态=pending
  │                                      │
  │ ←── { id, status: "pending" } ──────│
  │                                      │
  │                                      │ GET /api/admin/grant-requests
  │                                      │ (待审批列表，按时间排序)
  │                                      │
  │                                      │ 查看理由，决定批准或驳回
  │                                      │
  │                                      │ PUT /api/admin/grant-requests/{id}
  │                                      │ { action: "approve"/"reject",
  │                                      │   comment: "审批意见" }
  │                                      │
  │                                      │ approve时自动写入对应授权表:
  │                                      │  grant_type=domain → user_domain_grants
  │                                      │  grant_type=endpoint → user_api_grants
  │                                      │
  │ ←── 通知 (可选: WebSocket / 轮询) ───│
```

### 8.3 审批操作

Admin 审批时包含两个关键动作：

| 操作 | 行为 |
|------|------|
| **批准** | ① 更新 `api_grant_requests.status='approved'` ② 写入对应授权表（`user_domain_grants` 或 `user_api_grants`）③ 更新 `reviewed_at` |
| **驳回** | ① 更新 `api_grant_requests.status='rejected'` ② 记录 `review_comment` 原因 ③ 更新 `reviewed_at` |

批准写入授权表时遵循幂等原则：若授权记录已存在（例如 Admin 之前已直接授权），更新 `granted_by` 和 `granted_at` 而非重复插入。

### 8.4 审批 API

| 端点 | 方法 | 守卫 | 说明 |
|------|------|------|------|
| `POST /api/auth/grant-requests` | POST | get_current_user | 普通用户提交 API 授权申请 |
| `GET /api/auth/grant-requests` | GET | get_current_user | 当前用户自己的申请记录 |
| `GET /api/admin/grant-requests` | GET | require_permission("admin:grants.write") | Admin 查看全部待审批/已审批记录 |
| `PUT /api/admin/grant-requests/{id}` | PUT | require_permission("admin:grants.write") | Admin 批准/驳回 |

### 8.5 申请限制

| 规则 | 说明 |
|------|------|
| 已存在相同授权的待审批申请 | 不允许重复提交，返回 409 |
| 已存在相同授权且已批准 | 直接返回 "该授权已生效"，不创建新申请 |
| 已驳回的申请 | 允许在驳回 24 小时后重新提交 |
| 申请内容不在可授权范围内 | 若 `grant_target` 对应的域/端点不存在 → 400 |

---

## 九、规划层 API 权限交集机制

### 9.1 当前过滤链路

```
graph.py:planning_node()
  → profile.get_endpoint_names()          # 员工端点
  → engine.generate_plan(allowed_endpoints=...)
    → LLM Prompt 硬过滤 (get_endpoints_description)  # LLM 看不到非授权 API
    → 任务验证丢弃 (_validate_tasks)                 # 兜底保护
```

### 9.2 交集插入点

**唯一改动点在 `graph.py:planning_node()`**，员工端点加载后、传递给规划引擎前，与用户授权端点取交集：

```python
# graph.py:planning_node() — 改造后

employee_id = state.get("employee_id")
allowed_endpoints: frozenset[str] | None = None

# 步骤 1: 获取员工端点（现有逻辑）
if employee_id:
    profile = EmployeeManager.get_instance().get_profile(employee_id)
    if profile:
        allowed_endpoints = profile.get_endpoint_names()

# 步骤 2: 获取用户授权端点（新增）
user_id = state.get("user_id")
if user_id and user_id != "anonymous":
    from backend.auth.api_grants import get_user_authorized_endpoints
    user_authorized = get_user_authorized_endpoints(user_id, db_session)

    if allowed_endpoints is not None:
        allowed_endpoints = allowed_endpoints & user_authorized    # 交集
        if not allowed_endpoints:
            state["error"] = (
                f"数字员工「{profile.name}」配置的 API 端点均不在"
                f"您的授权范围内。请联系管理员授权或选择其他员工。"
            )
            return state
    else:
        # 通用模式（无员工）：仅用用户授权端点
        allowed_endpoints = user_authorized

# 步骤 3: 传递给规划引擎（现有逻辑，不变）
plan = await engine.generate_plan(intent, allowed_endpoints=allowed_endpoints, ...)
```

### 9.3 `get_user_authorized_endpoints()` 实现

```python
# backend/auth/api_grants.py (新增)

async def get_user_authorized_endpoints(
    user_id: str,
    db: AsyncSession,
) -> frozenset[str]:
    """计算用户被授权访问的所有 API 端点名称集合。
    来源 = domain_grants 下的端点 ∪ user_api_grants 中单独授权的端点。
    """

    # 1. 查询授权域
    domain_rows = await db.execute(
        text("SELECT domain_code FROM user_domain_grants WHERE user_id = :uid"),
        {"uid": user_id},
    )
    domains = {r[0] for r in domain_rows.fetchall()}

    # 2. 查询单独授权的端点
    api_rows = await db.execute(
        text("SELECT endpoint_name FROM user_api_grants WHERE user_id = :uid"),
        {"uid": user_id},
    )
    direct_endpoints = {r[0] for r in api_rows.fetchall()}

    # 3. 查询这些域下的所有端点
    if domains:
        ep_rows = await db.execute(
            text("SELECT name FROM api_endpoints WHERE domain IN :domains"),
            {"domains": tuple(domains)},
        )
        domain_endpoints = {r[0] for r in ep_rows.fetchall()}
    else:
        domain_endpoints = set()

    # 4. 合并 + 与运行时注册表取交集（去除已删除端点）
    all_authorized = domain_endpoints | direct_endpoints
    from backend.agent.api_registry import VALID_ENDPOINT_IDS
    valid = all_authorized & VALID_ENDPOINT_IDS

    return frozenset(valid)
```

### 9.4 各场景行为矩阵

| 场景 | 结果 |
|------|------|
| 正常使用公共员工 | `员工端点 ∩ 用户授权端点` |
| 用户有所有域授权 | `= 员工端点`（无变化） |
| 通用模式（无员工） | `= 用户授权端点` |
| 交集为空 | 规划中止，返回明确错误消息 |
| 匿名/未认证 | 跳过用户过滤，仅用员工端点（向后兼容） |

### 9.5 感知层处理

感知层不做 API 过滤改动。用户可能查询未授权域的数据，规划层交集为空时返回清晰错误："您的查询涉及 D2 域数据，但您当前未被授权访问该域。请联系管理员。" 这比感知层静默忽略提供更好的 UX。

---

## 十、SSO 单点登录 — OIDC 适配

### 10.1 范围限定

仅支持标准 **OAuth 2.0 Authorization Code Flow + OIDC**，对接企业内部统一认证平台。不支持微信、钉钉、飞书等商业产品。

### 10.2 流程

```
浏览器                   Analytica 后端                 内部 IdP (OIDC)
  │                          │                              │
  │ GET /analytica/           │                              │
  │ ────────────────────────→│ 检测未登录                     │
  │ 302 → /api/auth/sso/login │                              │
  │ ←────────────────────────│                              │
  │                          │                              │
  │ GET /authorize?           │                              │
  │   response_type=code      │                              │
  │   client_id=analytica     │                              │
  │   scope=openid+profile    │                              │
  │   state=<random>          │                              │
  │ ────────────────────────────────────────────────────────→│
  │                          │                         用户登录
  │ 302 → /api/auth/sso/callback?code=xxx&state=xxx         │
  │ ←────────────────────────────────────────────────────────│
  │                          │                              │
  │ GET /api/auth/sso/callback│                              │
  │ ────────────────────────→│                              │
  │                          │ POST /token (code→id_token)   │
  │                          │ ────────────────────────────→│
  │                          │ ←── id_token + claims ───────│
  │                          │                              │
  │                          │ 验签(id_token)                │
  │                          │ 查/建 users 表                │
  │                          │ 签发内部 JWT                  │
  │ 302 → /analytica/         │ Set-Cookie: refresh_token    │
  │ ←────────────────────────│                              │
```

### 10.3 配置

```bash
# 仅四个关键配置项
AUTH_SSO_ENABLED=true
AUTH_OIDC_ISSUER=https://sso.internal.example.com
AUTH_OIDC_CLIENT_ID=analytica
AUTH_OIDC_CLIENT_SECRET=xxx

# 可选配置（使用默认值即可）
AUTH_OIDC_SCOPES=openid profile
AUTH_OIDC_DISCOVERY=true                        # 自动发现 .well-known
AUTH_SSO_USER_CLAIM=preferred_username           # SSO 用户的身份字段
AUTH_SSO_AUTO_CREATE_USER=true                   # 首次登录自动创建用户
AUTH_SSO_DEFAULT_ROLE=viewer                     # 自动创建用户的默认角色
```

### 10.4 用户映射

SSO 回调返回身份后：

1. 按 `(sso_provider='oidc', external_id=<sub claim>)` 查 users 表
2. 找到 → 直接登录（更新 last_login_at）
3. 未找到 → 若 `AUTH_SSO_AUTO_CREATE_USER=true` → 自动创建用户，角色=viewer
4. 未找到 → 若 `AUTH_SSO_AUTO_CREATE_USER=false` → 返回 "请联系管理员开通账号"

### 10.5 安全验证

| 要求 | 实现 |
|------|------|
| state 参数防 CSRF | 每次请求生成随机 state，回调时校验 |
| id_token 签名验证 | 从 `jwks_uri` 获取公钥验证 RS256/HS256 |
| iss 验证 | 确保 token 来自配置的 issuer |
| aud 验证 | 确保 token 是颁发给本 client_id |
| exp 验证 | 拒绝过期 token |
| client_secret 保护 | 仅存后端，从未暴露给浏览器 |
| code 一次性使用 | 交换后 state 立即失效 |

### 10.6 两种登录模式共存

```
AUTH_SSO_ENABLED=false  →  仅支持用户名+密码登录
AUTH_SSO_ENABLED=true   →  SSO 优先 + 用户名+密码备选
```

初期可用本地密码登录跑通 RBAC，后续对接 IdP 时仅填四个环境变量即可启用 SSO。

---

## 十一、后端实现设计

### 10.1 新增文件清单

```
backend/auth/
├── __init__.py              # auth 模块入口
├── jwt.py                   # JWT 生成/验证工具函数
├── password.py              # bcrypt 密码哈希
├── dependencies.py          # FastAPI Depends 守卫
├── schemas.py               # Pydantic: LoginRequest, TokenResponse, UserInfo
├── routes.py                # /api/auth/login /refresh /logout /me
├── api_grants.py            # get_user_authorized_endpoints()
└── sso/
    ├── __init__.py
    ├── oidc.py              # OIDC Authorization Code Flow 适配器
    ├── routes.py            # /api/auth/sso/login /callback
    └── user_mapping.py      # SSO 身份 → 内部用户映射

backend/admin/
├── users.py                 # Admin 用户/角色/授权管理 API
├── users_store.py           # DAL: users/roles/permissions CRUD
└── users_schemas.py          # Pydantic schemas
```

### 10.2 config.py 新增配置

```python
# ── Auth / JWT ──
AUTH_JWT_SECRET: str = Field(..., description="JWT 签名密钥 (HS256, 至少32字符)")
AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15)
AUTH_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)
AUTH_BCRYPT_ROUNDS: int = Field(default=12)

# ── SSO ──
AUTH_SSO_ENABLED: bool = Field(default=False)
AUTH_OIDC_ISSUER: str = Field(default="")
AUTH_OIDC_CLIENT_ID: str = Field(default="")
AUTH_OIDC_CLIENT_SECRET: str = Field(default="")
AUTH_OIDC_SCOPES: str = Field(default="openid profile")
AUTH_OIDC_DISCOVERY: bool = Field(default=True)
AUTH_SSO_USER_CLAIM: str = Field(default="preferred_username")
AUTH_SSO_AUTO_CREATE_USER: bool = Field(default=True)
AUTH_SSO_DEFAULT_ROLE: str = Field(default="viewer")
```

### 10.3 新增路由一览

**认证路由 (无需认证):**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login` | POST | 用户名密码登录 |
| `/api/auth/refresh` | POST | 刷新 Access Token |
| `/api/auth/logout` | POST | 登出 |
| `/api/auth/sso/login` | GET | SSO 登录入口（302 到 IdP） |
| `/api/auth/sso/callback` | GET | SSO 回调处理 |
| `/api/auth/config` | GET | 返回当前认证配置（SSO 是否启用等） |

**需要认证:**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/me` | GET | 当前用户信息 + 权限 |

**Admin 路由 (需 admin 角色):**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/users` | GET/POST | 用户列表/创建 |
| `/api/admin/users/{id}` | GET/PUT/DELETE | 用户详情/更新/禁用 |
| `/api/admin/users/{id}/roles` | GET/PUT | 用户角色管理 |
| `/api/admin/users/{id}/api-grants` | GET/PUT | 用户 API 授权管理 |
| `/api/admin/roles` | GET/POST | 角色列表/创建 |
| `/api/admin/roles/{id}` | GET/PUT/DELETE | 角色详情/更新/删除 |
| `/api/admin/roles/{id}/permissions` | GET/PUT | 角色权限管理 |

---

## 十二、前端实现设计

### 11.1 新增文件清单

```
frontend/src/
├── contexts/
│   └── AuthContext.tsx         # 认证状态 + login/logout/ssoLogin 方法
├── hooks/
│   └── useAuth.ts              # 便捷 Hook: const { user, login, logout } = useAuth()
├── components/auth/
│   ├── LoginPage.tsx           # 登录页（SSO按钮 + 密码表单）
│   ├── ProtectedRoute.tsx      # 路由守卫：未登录 → 登录页
│   └── AdminGuard.tsx          # Admin 角色守卫：非 admin → 403
├── pages/admin/
│   ├── UsersView.tsx           # Admin 用户管理页
│   └── RolesView.tsx           # Admin 角色管理页
├── api/
│   └── auth.ts                 # Auth API: login/logout/refresh/me
└── api/client.ts               # 改造: 自动注入 Bearer Token, 401 自动刷新
```

### 11.2 Token 存储策略

| Token | 存储 | 说明 |
|-------|------|------|
| Access Token | AuthContext 状态（内存） | 页面刷新后走 refresh 恢复 |
| Refresh Token | httpOnly Cookie | JS 不可读写，防 XSS |
| 用户信息 + 权限 | AuthContext 状态（内存） | |

### 11.3 路由改造

```tsx
// App.tsx 改造后
<Routes>
  {/* 公开路由 */}
  <Route path="login" element={<LoginPage />} />

  {/* 受保护路由 */}
  <Route element={<ProtectedRoute />}>
    <Route index element={<ChatPageV2 />} />
    <Route path="employees" element={<EmployeesPage />} />
  </Route>

  {/* Admin 路由（额外角色检查） */}
  <Route element={<ProtectedRoute requiredRole="admin" />}>
    <Route path="admin" element={<AdminLayout />}>
      <Route index element={<AdminHome />} />
      <Route path="employees" element={<EmployeesView />} />
      <Route path="apis" element={<ApisView />} />
      <Route path="tools" element={<ToolsView />} />
      <Route path="skills" element={<SkillsView />} />
      <Route path="domains" element={<DomainsView />} />
      <Route path="memories" element={<MemoriesView />} />
      <Route path="audit" element={<AuditView />} />
      <Route path="users" element={<UsersView />} />
      <Route path="roles" element={<RolesView />} />
    </Route>
  </Route>

  <Route path="*" element={<Navigate to="/" replace />} />
</Routes>
```

### 11.4 API Client 改造

```typescript
// client.ts 改造
let accessToken: string | null = null;
export function setAccessToken(token: string | null) {
  accessToken = token;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }

  const res = await fetch(`${BASE}${path}`, { method, headers, body: JSON.stringify(body) });

  // 401 自动刷新
  if (res.status === 401 && path !== '/api/auth/refresh') {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${accessToken}`;
      return fetch(`${BASE}${path}`, { method, headers, body: JSON.stringify(body) }).then(r => r.json());
    }
    throw new Error('Authentication required');
  }

  if (!res.ok) throw new Error(`API ${method} ${path} → ${res.status}`);
  return res.json();
}
```

### 11.5 状态管理改造

| 组件/Store | 改动 |
|------------|------|
| `sessionStore.ts` | 移除 `userId: 'anonymous'` 默认值，由 AuthContext 注入 |
| `ChatPageV2.tsx` | 从 `useAuth()` 获取用户信息 |
| `Topbar.tsx` | 新增用户头像/姓名 + 退出登录按钮 |
| `AdminLayout.tsx` | 根据权限动态显示/隐藏侧边栏菜单项 |

---

## 十三、现有代码改造策略

### 12.1 改造原则

最小侵入，渐进式：先加守卫，再逐步收紧。先支持未认证回退（向后兼容），稳定后移除回退路径。

### 12.2 后端路由改造

| 端点类别 | 改造方式 |
|----------|----------|
| `POST /api/sessions` | 注入 `current_user`，用认证用户 ID 替换请求体中的 `user_id` |
| `GET /api/sessions` | 注入 `current_user`，强制 `WHERE user_id = current_user.id` |
| `GET /api/sessions/{id}` | 注入 `current_user` + 所有权校验 |
| `DELETE /api/sessions/{id}` | 注入 `current_user` + 所有权校验 |
| `POST /api/sessions/{id}/plan/*` | 注入 `current_user` + 所有权校验 |
| `GET /api/employees` | 注入 `current_user`，按所有权过滤 |
| `POST/PUT/DELETE /api/employees/*` | 注入 `current_user` + 所有权校验 / require_permission |
| `GET/PUT/DELETE /api/admin/*` | 注入 `require_role("admin")` |
| `WS /ws/chat/{session_id}` | URL query string 传 token 进行认证 |
| `/api/reports/*` | 注入 `current_user` + 所有权校验 |

### 12.3 WebSocket 认证

```
ws://host:8000/ws/chat/{session_id}?token=<access_token>
```

后端在 WebSocket 连接建立时校验 token，拒绝未认证连接。

### 12.4 渐进式迁移策略

```
阶段 1: 部署中间件，但未认证请求仍放行（打印警告日志）
阶段 2: 正式启用认证守卫，未认证请求返回 401
阶段 3: 前端全面接入，匿名模式降级为仅测试用
```

---

## 十四、安全考量

| 维度 | 措施 |
|------|------|
| **密码存储** | bcrypt (rounds=12) 哈希，永不明文存储 |
| **JWT 签名** | HS256，密钥≥32 字符，来自环境变量 `AUTH_JWT_SECRET` |
| **Token 刷新** | Refresh Token Family Rotation：整个家族同时撤销（防重放） |
| **CSRF** | SameSite=Strict Cookie + 验证 Origin/Referer |
| **XSS** | Access Token 仅存内存；httpOnly Cookie 不可 JS 访问 |
| **暴力破解** | 登录失败 5 次后锁定 15 分钟 |
| **CORS** | 添加 `CORSMiddleware`，仅允许前端同源或白名单域名 |
| **会话隔离** | 所有业务查询强制附加 `user_id` 条件 |
| **审计日志** | `audit_logs.actor_id` 写入认证用户 ID |
| **SSO 安全** | state/nonce 防 CSRF 和重放；id_token 验签、验 iss/aud/exp；client_secret 仅存后端 |

---

## 十五、实施阶段

| 阶段 | 内容 | 涉及模块 |
|------|------|----------|
| **Phase A** | 数据模型 + 迁移 + 种子脚本 | `database.py`, `migrations/`, `migrations/scripts/seed_auth.py` |
| **Phase B** | 后端 Auth 模块（密码+JWT） | `backend/auth/` (jwt, password, dependencies, schemas, routes) |
| **Phase C** | 后端 SSO OIDC 适配器 | `backend/auth/sso/` (oidc, routes, user_mapping) |
| **Phase D** | Admin 用户/角色/API授权管理 API | `backend/admin/users.py`, `users_store.py`, `users_schemas.py` |
| **Phase E** | 后端 API 授权计算 + 规划层交集 | `backend/auth/api_grants.py`, `backend/agent/graph.py` |
| **Phase F** | 现有路由改造（注入 auth 守卫） | `backend/main.py` 各路由函数 |
| **Phase G** | 前端 Auth 基础设施 | `AuthContext`, `useAuth`, `ProtectedRoute`, `AdminGuard`, `api/auth.ts` |
| **Phase H** | 前端登录页 + Topbar 改造 | `LoginPage.tsx`, `Topbar.tsx`, `api/client.ts` |
| **Phase I** | 前端 Admin 扩展 | `UsersView.tsx`, `RolesView.tsx`, `AdminLayout.tsx` |
| **Phase J** | 安全加固 + 部署适配 | CORS 中间件、暴力破解防护、nginx、docker、.env |
| **Phase K** | 测试 + 文档 | 契约测试、E2E 测试、部署文档 |

### 分阶段切换策略

| 阶段 | 认证状态 |
|------|----------|
| Phase A-F | 后端加守卫但放行未认证请求 + 日志警告 |
| Phase G-K | 启用认证守卫，未认证返回 401，前端全链路接入 |
| 对接 SSO | 填四个环境变量 → 零代码改动启用 |

---

## 十六、配置清单

### 15.1 .env 新增配置项

```bash
# ── Auth / JWT (必填) ──
AUTH_JWT_SECRET=<至少32字符的随机字符串>
# AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=15    # 可选
# AUTH_REFRESH_TOKEN_EXPIRE_DAYS=7       # 可选

# ── SSO (对接内部 IdP 时填写) ──
# AUTH_SSO_ENABLED=false                  # true 启用
# AUTH_OIDC_ISSUER=https://sso.internal.example.com
# AUTH_OIDC_CLIENT_ID=analytica
# AUTH_OIDC_CLIENT_SECRET=
```

### 15.2 新增 Alembic 迁移

```
migrations/versions/YYYYMMDD_0001_auth_tables.py
  ├── CREATE TABLE users
  ├── CREATE TABLE roles
  ├── CREATE TABLE permissions
  ├── CREATE TABLE role_permissions
  ├── CREATE TABLE user_roles
  ├── CREATE TABLE refresh_tokens
  ├── CREATE TABLE user_domain_grants
  ├── CREATE TABLE user_api_grants
  ├── CREATE TABLE api_grant_requests
  ├── ALTER TABLE employees ADD COLUMN owner_id, visibility
  ├── INSERT INTO permissions (预置权限)
  └── INSERT INTO roles (admin/analyst/viewer)
```

### 15.3 种子脚本

```
migrations/scripts/seed_auth.py
  ├── ASSIGN permissions to roles
  ├── CREATE admin user (random password)
  ├── ASSIGN admin role to admin user
  └── GRANT all domains to admin user
  ├── (Admin 首次登入后手动配置审批人角色)
```

启动顺序：
```bash
alembic upgrade head
uv run python -m migrations.scripts.seed_employees_from_yaml  # 已有
uv run python -m migrations.scripts.seed_admin_tables          # 已有
uv run python -m migrations.scripts.seed_auth                  # 新增
```
