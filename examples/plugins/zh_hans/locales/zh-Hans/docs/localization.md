<a id="localization"></a>
# 本地化 API 与资源格式

<a id="interfaces"></a>
## 统一接口

使用 `pokeldn.app.i18n`。英文资源是完整目录，所有显示语言均使用相同接口。
界面调用稳定的语义键，并通过命名参数传值：

```python
i18n.text("core.common.save")
i18n.text("core.gift.egg.description", species=species_name)
i18n.name(EntityKind.MOVE, 94, game=Game.SV)
i18n.name(EntityKind.SPECIES, 128, game=Game.SV, form=1)
i18n.names(EntityKind.MOVE, game=Game.SV).by_id[94]
i18n.document("core.guide.gifts")
```

`NameTable.by_id` 是不可变的稀疏映射。物种名称表还提供
`by_form[(species_id, form_id)]`。指定 `form` 时返回完整形态名称，省略时返回基础物种名。
名称查询不判断可用性；业务服务筛选可用 ID，控件保存这些 ID，并在显示时获取标签。

模块目录保存 `ref("core.some.label")`、`MessageRef(key, params)` 或实体身份。
`TextRef` 为公共目录和命令行兼容保留固定的英文字符串值；界面通过其语义键获取译文，
不能根据英文字符串查找翻译。渲染绑定在 Flet 传输过程中保持有效。

<a id="identity"></a>
## 实体身份

`EntityRef(game, kind, id, form=0)` 支持物种、招式、道具、特性、属性、性格和精灵球枚举。
游戏常量对应稳定字符串标识，插件可以注册额外游戏。
物种使用全国图鉴编号，形态使用对应游戏上下文的编号；招式、特性、属性、性格和精灵球
使用 PKHeX 对应类别的 ID，道具使用对应游戏上下文的道具 ID。精灵球 ID 与道具 ID 分别解释。

火红／叶绿的应用礼物状态使用 `entity_schema = 1`，物种保存全国图鉴编号。
`entity_state()` 转换原生状态，`cartridge_state()` 在编译边界生成使用卡带内部编号的副本。
第三世代道具仍使用对应游戏的道具编号。性格编号零是有效值，未选择状态使用 `None`。

NPC 选择保存稳定的训练家键。其物种、形态、特性、招式和太晶属性均来自生成实际记录的
同一份原生伙伴表。命令行适配层输出启动器需要的固定训练家标识。

<a id="messages"></a>
## 文案与格式化

```toml
[strings]
"core.gift.egg.description" = "赠送{species}的蛋。"

[strings."core.queue.count"]
plural = "count"
other = "已将 {count} 只宝可梦加入队列。"
```

英文条目声明命名参数。翻译的各分支必须保留参数集合与复数选择参数，各语言可按 CLDR
规则提供自己的复数类别，并且必须包含 `other`。Babel 根据实际使用的资源语言选择分支；
回退到英文时使用英文规则。参数不能访问属性、下标或表达式，字面量花括号使用双花括号。
数值格式的宽度和精度均有限制。

英文目录可以通过 `[parameters."key"]` 声明参数及类型：`text`、`literal`、`number`、
`percent`、`date` 和 `datetime`。数值和日期类型使用语言相关格式，数值类型声明不与
Python 数值格式说明符混用。姓名、昵称、路径、网址、连接码和标识符按原值插入，
参数只替换一次，参数内部的花括号不会再次解释为模板。

`MessageRef` 通过 `to_wire()` 和 `from_wire()` 序列化，参数可包含标量、实体引用及嵌套消息。
`message_ref()` 为命令行保留固定诊断文本，同时向界面提供语义引用。
应用错误通过 PKHeX JSON 边界传递消息键和参数。PKHeX 自身的合法性报告及操作系统诊断
作为提供者文本处理。

<a id="packages"></a>
## 语言包与插件命名空间

资源格式版本 1 需要插件 API 1.10：

```toml
id = "community-zh-hans"
name = "简体中文"
version = "2.0.0"
api = "1.10"
localization_format = 1

[locales.zh-Hans]
name = "简体中文"
strings = "locales/zh-Hans/strings.toml"
entities = "locales/zh-Hans/entities.toml"
documents = "locales/zh-Hans/documents.toml"
font_family = "Noto Sans CJK SC"
```

每个包可以提供多种语言，选择时同时保存插件 ID 和语言代码。每次选用一个包，不隐式叠加
多个包。资源路径及符号链接均不能离开插件目录。格式版本、TOML 重复键、未知核心文案键、
不匹配的参数和无效实体类别会在安装前被拒绝。

功能插件通过 `api.register_localization(english, parameters=...)` 注册自身插件 ID 命名空间的
英文目录，通过 `api.register_documents(documents)` 注册文档，通过
`api.register_names(game, provider)` 为自己注册的游戏提供名称服务。
名称提供者返回 `version`、按 ID 索引的 `names` 映射，以及按物种和形态索引的 `forms` 映射。
停用插件时注销其目录。未安装功能插件的翻译命名空间暂不启用，在所有者注册时校验。

示例位于 `examples/plugins/hello_localized`。API 1 语言包的兼容适配位于 `i18n_legacy`，
应用代码统一使用语义接口。

<a id="fallback"></a>
## 回退与诊断

实体名称依次使用：所选语言包覆盖、PKHeX 对应显示语言、PKHeX 英文名称、包含类别和 ID 的
占位文本；形态无法解析时占位文本同时包含形态编号。未知文案键和错误调用参数显示诊断
占位文本；缺少翻译时使用完整英文条目。诊断记录包、语言、修订号及资源键或实体引用，
相同诊断合并记录，默认不记录用户参数值。

名称缓存包含提供者数据版本、语言包身份、语言、资源修订号、游戏和类别。
语言切换使派生缓存失效。名称请求跨越语言切换时，会在发布标签前重新执行只读名称查询。

<a id="documents"></a>
## 文档与实时切换

文档 ID 和父级 ID 保持稳定。元数据声明标题、相对路径，以及包含 `id`、`title`、`level` 的
章节列表。每个 Markdown 标题使用显式 HTML 锚点。阅读器、目录和搜索解析同一个文档，
缺少文档翻译时，其正文、标题和章节元数据一起使用英文版本。

语言切换在完整校验资源后提交，更新已挂载控件及缓存视图，刷新文档搜索，更新 Flet 的语言和
字体，同时保留实体选择、可编辑文本、焦点及运行中的会话。切换失败时保留当前语言。
训练家语言和记录中的文本与显示语言分别管理。

<a id="validation"></a>
## 构建与验证

```bash
python scripts/check_localization.py
python scripts/build_language_pack.py
python scripts/preview_language.py --prepare-only
python scripts/preview_language.py --web 8815
python -m pytest tests/test_semantic_i18n.py
```

简体中文包随程序放在 `pokeldn/app/data/language-packs/zh-Hans`，设置中始终提供此语言。
`build_language_pack.py` 同时生成可安装的 `.pokeplugin` 和 SHA-256 文件。
预览工具将包安装到独立数据目录，并停用无线连接、更新及精灵图下载，不修改用户正常使用的设置。

代码检查禁止应用按英文原文查询翻译、引用未声明的字面量键、传入错误命名参数，或在模块常量中
执行翻译。英文目录是声明源，`extract_strings.py --check` 仅校验目录，不根据调用点覆盖目录。
