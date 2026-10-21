# 简体中文语言包

适用于插件 API 1.10、本地化资源格式 1。

程序在“设置 → 应用语言”中提供内置“简体中文”。独立安装包的 ID 为
`community-zh-hans`，与内置包使用相同的本地化资源。

## 构建和安装

在仓库根目录运行：

```bash
python scripts/check_localization.py
python scripts/build_language_pack.py
```

生成 `dist/community-zh-hans-2.0.2.pokeplugin` 和对应 SHA-256 文件。
在程序的“插件”页面安装该文件，然后在“设置 → 应用语言”选择“简体中文”。

通过以下命令将安装包带入独立数据目录并启动界面验证：

```bash
python scripts/preview_language.py --web 8815
```

浏览器打开 `http://127.0.0.1:8815/`。该预览禁用开发板访问、更新检查和精灵图片下载。

## 资源覆盖

- 全部 5,548 个核心文案键，以及 `hello-localized` 插件示例的 4 个文案键。
- 高级参数说明及选项、礼物预设与效果说明、剑盾官方活动标题和分类。
- 游戏实体名称由 PKHeX 简体中文名称表提供，语言包补充指定名称和形态覆盖。
- 39 篇中文文档；其余 7 篇文档的正文、标题和目录整体使用英文。
- 训练家姓名、昵称、文件路径、连接码和导入记录中的原始文本保持原值。

资源格式和插件接口见仓库的 `docs/localization.md`，以及本包的
`locales/zh-Hans/docs/localization.md`。
