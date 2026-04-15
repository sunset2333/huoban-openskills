---
name: hb_tablefelid_analysis
description: 伙伴云表结构字段分析。当用户提到"分析伙伴云字段"、"分析表结构"、"生成数据字典"、"导出字段说明"、"hb_tablefelid_analysis"时触发。接受工作区 ID 和 API Key，拉取所有表格字段配置，AI 按业务分组，以 Markdown 表格形式输出每个字段的说明。
---

# hb_tablefelid_analysis — 伙伴云表结构字段分析

## 触发条件

当用户提到以下任意内容时触发本 Skill：
- "分析伙伴云字段 / 分析表结构 / 导出字段说明"
- "帮我看看伙伴云有哪些表和字段"
- "生成伙伴云数据字典 / 字段文档"
- "hb_tablefelid_analysis" / "hb 字段分析"

---

## 执行流程

### 第一步：获取凭据

检查 `~/.claude/skills/hb_tablefelid_analysis/.credentials.json` 是否存在且包含 `space_id` 和 `api_key`。

**情况 A：凭据文件存在** → 读取后告知用户 space_id，直接进入第二步。

**情况 B：凭据文件不存在** → 询问用户提供：

```
请提供以下信息（可选：保存到凭据文件以后复用）：
1. 工作区 ID (space_id)：
2. API Key（Bearer Token）：

凭据文件路径：~/.claude/skills/hb_tablefelid_analysis/.credentials.json
格式：{ "space_id": "...", "api_key": "..." }
```

---

### 第二步：运行数据拉取脚本

脚本分三个 Phase 执行，进度打印到 stderr，完成后输出 JSON 到 stdout。

**有凭据文件时：**
```bash
python ~/.claude/skills/hb_tablefelid_analysis/analyze.py > /tmp/hb_analyze_data.json
```

**用户临时传入凭据时：**
```bash
python ~/.claude/skills/hb_tablefelid_analysis/analyze.py \
  --space-id "{space_id}" --api-key "{api_key}" \
  > /tmp/hb_analyze_data.json
```

执行过程向用户实时播报进度：
- Phase 1/3：拉取表格列表，发现 N 张表
- Phase 2/3：并发拉取字段配置，逐张显示 ✓ / ✗
- Phase 3/3：清洗字段数据

若报错（HTTP 401/403/超时），读取错误信息向用户说明原因。

---

### 第三步：AI 分析 — 业务分组

读取 `/tmp/hb_analyze_data.json` 中的 `tables`，按业务领域将表格分组。

**分析规则：**

对每张表判断所属业务模块，依据表名和字段名推断：
- 分组名控制在 4 字以内
- 单组超 7 张须细化拆分
- 通用基础数据表（无明确业务归属的，如"单位""币种""部门"）归入"基础数据"分组
- 无法归入任何分组的表放入"其他"分组

**Claude 直接基于表名和字段信息完成分组，无需调用外部 AI API。**

完成后告知用户：识别到系统类型（ERP/CRM/MES/OA/…）及分组情况。

---

### 第四步：输出字段说明文档

按分组生成 Markdown 格式的字段说明文档。

**文档结构：**

```markdown
# 伙伴云工作区字段说明
> space_id：`xxx`　共 N 张表，M 个分组

## 销售管理

### 客户表
> 管理客户基本信息

| 字段名 | 类型 | 必填 | 备注 |
|--------|------|------|------|
| 客户名称 | 文本 | 是 | |
| 客户等级 | 选项 | | 选项：A / B / C |
| 负责人 | 成员 | | |
| 关联合同 | 关联 | | → 合同表（多选）|

### 销售订单
...
```

**备注列规则：**
- `relation` 字段：`→ {目标表名}（单选/多选）`；目标表不在本工作区时显示 `→ 外部表`
- `category` 字段：`选项：A / B / C`
- 其余字段备注留空

---

### 第五步：可选后续操作

分析完成后主动提示：
1. **导出文件** → `python ~/.claude/skills/hb_tablefelid_analysis/analyze.py > ~/Desktop/字段说明.md`（需配合重定向）或直接将输出保存为文件
2. **重新拉取** → 删除 `/tmp/hb_analyze_data.json` 后重新执行第二步
3. **只看某分组** → 用户指定分组名，Claude 仅展示该分组内容

---

## 凭据说明

- 伙伴云后台：设置 → 开放平台 → API Key 管理
- 建议：`chmod 600 ~/.claude/skills/hb_tablefelid_analysis/.credentials.json`

## 参考 API

- `POST https://api.huoban.com/openapi/v1/table/list`（表格列表）
- `POST https://api.huoban.com/openapi/v1/table/{tableId}`（字段配置）
- Header：`Open-Authorization: Bearer {api_key}`
