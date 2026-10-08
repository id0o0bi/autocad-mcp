# autocad-mcp

让你的 AI 助手真正会画 CAD。

[English](README.md) · 中文

在线介绍页（四张真实图纸的完整效果、功能说明与安装步骤）见仓库的 [`site/`](site/) 目录。

这是一个标准的 MCP 工具（MCP server），不含任何专属定制，任何支持 MCP 的
AI 客户端都能使用。它让助手可以按你的要求生成图纸、成批修改既有图纸、
检查图纸问题，也可以驱动真实的 AutoCAD 引擎完成标注、填充和出图。

---

## 它能做什么

**按参数批量出图** —— 给一张规格表，一次生成整套图纸。零件族、标准件、
孔位阵列、图框、标题栏、明细表都能自动配齐；改一个数字，整张图跟着重画。

**成批修改既有图纸** —— 批量改图层、颜色、线宽、文字；批量替换图块、
更新标题栏；转换版本（例如 2018 降到 2013）；一次处理整个文件夹。

**读图与图纸审查** —— 找出重线、零长度线、看着闭合其实没闭合的轮廓、
放在 0 层的图元、小到印不出来的字、跑出图框的几何。输出问题清单，
并把每个问题在图上圈好编号。

**制造与下料** —— 按物料清单在板材上排版，给出材料利用率，输出可直接
交付的下料图。

**从图纸里取数据** —— 图层结构、图元数量、图纸范围、面积、长度、
块引用统计，整理成表格交给下一步。

**AutoCAD 专属能力** —— 原生 DWG 读写、真正的标注与图案填充、打印与批量发布。

---

## 给 AI 助手看的：安装与配置

> 用户可能会直接对你说「读一下这个目录里的 README.md，帮我配置好」。
> 下面就是你需要的信息，按顺序做完即可。

### 1. 环境要求

- Python 3.10 或更高。先确认一下：`python --version`
- 两个必需包：`mcp`、`ezdxf`
- `Pillow`——生成图纸预览、或跑 `cases/` 里的例子时才需要
- `matplotlib`——可选，只在要输出 PNG（而不是 SVG）预览时需要
- AutoCAD 2013 或更高版本——**只有**用到 `autocad_*` 那几个工具时才需要。
  没装 AutoCAD 也能正常使用生成、修改、审查图纸的全部功能。

### 2. 安装依赖

```
pip install "mcp>=2,<3" ezdxf Pillow
```

`mcp` 和 `ezdxf` 是服务器本身的全部依赖，装这两个工具就能用：

```
pip install "mcp>=2,<3" ezdxf
```

`Pillow` 只有画预览时才需要（例子和 `render.py` 会用到）。
用哪个 Python 解释器，后面 MCP 配置里的 `command` 就要指向哪一个。
在 Windows 上建议写成解释器的完整路径：

```
where python
```

### 3. 写入 MCP 配置

把下面这段加进用户所用客户端的 MCP 配置文件。**三处改成实际路径**：
`command` 是上一步确认的解释器，`args` 里是 `server.py` 的完整路径。

```json
{
  "mcpServers": {
    "autocad": {
      "command": "C:/Python313/python.exe",
      "args": ["D:/tools/autocad-mcp/server.py"],
      "cwd": "D:/tools/autocad-mcp"
    }
  }
}
```

`args` 用完整路径，`cwd` 就只是保险：有些客户端不传工作目录，而 `server.py`
是按自己所在目录去找同目录的模块的，所以完整路径一定能跑起来。
路径里的反斜杠要写成 `/` 或 `\\`，单个 `\` 会被 JSON 当成转义符。

各客户端的配置入口不同，把同样的 `command` / `args` 填到对应位置即可：

| 客户端 | 配置位置 |
|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json`（macOS：`~/Library/Application Support/Claude/`） |
| OpenAI Codex CLI | `~/.codex/config.toml` 里的 `[mcp_servers.autocad]` 表（TOML，见下） |
| 腾讯 WorkBuddy | 客户端内「连接器 → 自定义连接器」，安装 MCP 服务 |
| 腾讯 CodeBuddy | CodeBuddy 设置 → MCP → Add MCP（`mcpServers` JSON，`type: "stdio"`） |
| 字节 Trae | Trae 的 MCP 设置面板（JSON） |
| 阿里 Qoder | Qoder 的 MCP 设置（JSON） |
| 阿里通义灵码 | 灵码的 MCP 设置（JSON） |

其他支持 MCP 的客户端同理，在各自「MCP 设置」里填入相同的 `command` / `args`。
Codex 用的是 TOML：

```toml
[mcp_servers.autocad]
command = "C:/Python313/python.exe"
args = ["D:/tools/autocad-mcp/server.py"]
```

如果用户用的客户端不在上面，按该客户端文档里「新增 MCP server」的方式，
填入同样的 `command` / `args` / `cwd` 即可。

### 4. 验证

配置完成后重启客户端（或重新加载 MCP 服务器），然后调用 `autocad_status`：

- 返回 `accoreconsole` 路径 → AutoCAD 部分也能用，功能完整。
- 返回 `accoreconsole: null` 和一段提示 → 图纸生成/修改/审查都可正常使用，
  只有需要真实 AutoCAD 的几个功能不可用。这不是故障，可以直接告诉用户。

如果工具列表里根本看不到 `autocad_*`，先看客户端的 MCP 日志：多半是 `command`
指向的解释器不对，或者 `mcp` 装在了另一个 Python 里。用
`<那个解释器> -c "import mcp, ezdxf"` 验证一下。

也可以不经过客户端直接自检，在目录下跑：

```
python -c "import server; print(server.autocad_status())"
```

### 5. 可选：AutoCAD 装在非默认路径

正常情况下会自动找到。如果用户是绿色版、或者装在非标准位置，在配置里加上：

```json
{
  "mcpServers": {
    "autocad": {
      "command": "C:/Python313/python.exe",
      "args": ["D:/tools/autocad-mcp/server.py"],
      "env": {
        "CAD_ACCORECONSOLE": "D:/AutoCAD/accoreconsole.exe"
      }
    }
  }
}
```

想改临时文件目录（默认在系统临时目录下）就在 `env` 里再加一个
`"CAD_WORKDIR"`。

---

## 工具一览

| 工具 | 用途 | 需要 AutoCAD |
|---|---|---|
| `drawing_run(code, path, save_as, dxfversion)` | 用 Python + ezdxf 生成或修改图纸 | 否 |
| `drawing_summary(path)` | 快速看清一张图：图层、图元统计、范围、块 | 否 |
| `autocad_run_lisp(code, input_dwg, output_dwg, dwg_version, timeout, keep_workdir)` | 在真实 AutoCAD 内核里执行 | 是 |
| `autocad_status()` | 检查 AutoCAD 是否可用 | — |
| `autocad_accoreconsole_switches()` | 查询 accoreconsole 的可用开关 | 是 |

几点使用上的约定：

- `drawing_run` 里可以直接用 `doc`、`msp`、`ezdxf`，以及 `emit(...)` 用来回传信息。
  代码出错时**不会写出半成品文件**，可以放心重试。
- `dxfversion` 默认 `R2010`。可选 `R12 / R2000 / R2004 / R2007 / R2010 / R2013 / R2018`。
- `autocad_run_lisp` 的 `input_dwg` 留空会从一张空白图纸开始；
  `dwg_version` 给年份（如 `"2013"`、`"2018"`）存 DWG，给 `"DXF"` 存 DXF。
- **`output_dwg` 的扩展名要和 `dwg_version` 对上**：给年份就用 `.dwg`，
  给 `"DXF"` 就用 `.dxf`。写成 `dwg_version="2013"` + `output_dwg="x.dxf"`
  不会报错，但 `x.dxf` 里装的其实是 DWG 数据，之后打开时会很困惑。
- 传大图纸、跑复杂脚本时把 `timeout` 调大一些比较稳妥。
- 排查问题时用 `keep_workdir=True`，工具会保留中间目录，可以看到生成的脚本
  和 AutoCAD 的原始输出。
- `drawing_run` 执行的是你给的 Python 代码，权限等同于运行服务器的用户。
  这正是它灵活的原因，但别把服务器开放给不可信的调用方。

## 实例

`cases/` 里有四个可以直接运行的例子。在目录下执行：

```
python cases/run_all.py
```

跑完会在 `out/` 里生成图纸和预览。整页效果见 `site/index.html`，用浏览器直接
打开即可，图是矢量图，可以放大看细节。

| 例子 | 内容 |
|---|---|
| `01_parts.py` | 按规格表生成法兰零件族图纸，带图框与零件表 |
| `02_nesting.py` | 按 BOM 在板材上排版下料，输出利用率 |
| `03_audit.py` | 审查图纸，输出问题清单与批注图 |
| `04_floorplan.py` | 通用引擎画结构 + 真实 AutoCAD 标注出图，两引擎互相复核 |

`render.py` 可以把任意 DXF 转成 SVG 或 PNG 预览，不需要 AutoCAD：

```
python render.py out/01_flange_family.dxf preview.svg
```

预览会自动把「为黑屏设计」的颜色换成白纸上看得清的对应色。AutoCAD 的
模型空间是黑的，所以青色、绿色、黄色、浅灰这些 ACI 颜色在黑底上很清楚，
画到白纸上却几乎等于空白（青色对白纸的对比度只有 1.25）。

两种配色方式可选：

```
python render.py out/01_flange_family.dxf preview.svg          # 保留图层配色（默认）
python render.py --mono out/01_flange_family.dxf preview.svg   # 全部黑色
```

`--mono` 的效果等同于黑白打印样式表（`monochrome.ctb`，或办公室常见的
`!黑白线型*.ctb`），正式图纸和归档件一般用这种。

**DXF 文件不会被修改**：图层颜色仍是标准 ACI 值，预览的配色只存在于
预览文件里。背景色也是同一个道理——模型空间的深色底色是 AutoCAD 的界面
主题（存在用户配置里），不是图纸数据，DXF 里根本没有记录它。

`check_previews.py` 是配套的质量闸门，逐张检查预览里有没有「看不见的线」：

```
python check_previews.py
```

它同时检查颜色对比度和线宽，任何一项不合格就报错退出，可以放进构建流程。

## 已知限制

- 通用部分（不依赖 AutoCAD）**只能处理 DXF，不能直接读写 DWG**。
  遇到 `.dwg` 会给出明确提示。要转 DWG 需要用真实 AutoCAD 那套工具。
- 由 AutoCAD 保存出来的 DXF 固定为当前版本（AC1032 / R2018）。
  要转成更早的版本，读回来设一下版本号再存：

  ```
  drawing_run("doc.dxfversion = ezdxf.const.DXF2010",
              path="a.dxf", save_as="b.dxf")
  ```

  注意单纯 `save_as` **不会**改变版本，必须设置 `doc.dxfversion`。
  （`ezdxf.const.DXF2010` 就是 R2010，也可以直接写 `"R2000"` 这样的字符串。）
- AutoCAD LT 对 AutoLISP 的支持一直很有限（2024 版起才加入部分支持），
  而 `autocad_*` 这套工具依赖它，用 LT 之前先确认一下。
- 图纸预览是静态图，不含交互式的缩放平移界面。

## 许可说明

CAD 软件是商业软件，请通过正规途径获得。可行的方式包括官方 30 天试用、
Autodesk 教育授权、Flex 令牌，以及 BricsCAD / ZWCAD / nanoCAD 等兼容替代品。
