<a id="reverse-engineering-a-switch-title"></a>
# 对 Switch 标题进行逆向工程

无需解压即可读取零售 Switch 游戏的代码，适用于 Unity/IL2CPP 游戏（BDSP，7.3 GB NSP）和本机 C++ 游戏（剑／盾，13.3 GB XCI）。
<a id="order-of-work"></a>
## 工作顺序

1. 搜索公开的资源以查找现有的常量。代码搜索到达 NintendoClients wiki 内部，包括其摘要表未链接的每个游戏页面：

       gh search code "<a constant, a field name, a class name>" --limit 20
       gh api repos/kinnay/NintendoClientsWiki/contents --jq '.[].name'
       gh api repos/kinnay/NintendoClientsWiki/contents/<Page>.md --jq .content | base64 -d

   汇总表给出了推导值；各游戏、Pia 版本和应用程序数据页面给出了规则。
2. 查找已转储的游戏代码：C# 游戏（BDSP 为 `TeamLumi/opendpr`）读取速度比 IL2CPP 输出更快；游戏键找到第三队客户端（剑／盾的：四个LAN模式客户端）。
3. 获取一次构建的可执行文件和元数据；首先命名一切。
4. 读取二进制文件验证转录并找到未写入的部分（BDSP的`cryptoKeyDataSeed`及其版本规则）。
5. 然后才搜索关键空间：固定错误的一个输入会给出肯定的否定结果。

解密 Pia LDN 标题需要其密码、`cryptoKeyDataSeed`、本地通信版本、广告和每个发送者的 MAC（[Pia 层](pia.md)）。
<a id="getting-the-executable-out"></a>
## 获取可执行文件
<a id="from-an-nsp"></a>
### 来自 NSP

NSP 是 NCA 的 PFS0 档案；可执行文件位于多 GB NCA 的末尾附近。

1. 直接解析PFS0头：hactool的`--listfiles`偏移量是相对于数据库的。
2. 解密`<rights id>.tik`中的标题密钥（权限id是NSP的文件名）：加密密钥在`+0x180`，权限id在`+0x2A0`，绝对。它的最后一个字节是密钥生成 *n*，它使用 `titlekek_{n-1}`。 hactool取`--titlekey`上的加密密钥； `xci_read.py` 自行读取票据。
3. 构建稀疏文件：`dd` NCA 的头部，`truncate -s` 为其实际大小，`dd ... seek_bytes
   conv=notrunc` 所需范围。磁盘上的 109 MB 相当于 2.7 GB，并通过 hactool 的边界检查（`du -h` 显示实际大小，`ls -l` 则不显示）。
<a id="from-an-xci"></a>
### 来自 XCI

`tools/switch/xci_read.py` 遍历 HFS0 分区（或 NSP 的 PFS0），就地解密 NCA 标头（`header_key` 下的 AES-128-XTS，大端扇区调整）并打印标题 id、内容类型、密钥生成以及每个部分的偏移量、计数器和密钥：

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --keys prod.keys --type Program
 盒式NCA具有零权限ID且无票据：主体密钥是密钥区域插槽2下
`key_area_key_application_<max(crypto_type, crypto_type2) - 1>`。更新的 exef 是其程序 NCA 的第 0 部分，即普通的 CTR PartitionFS：

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --nca <id> --exefs 0 --extract main
 陷阱：FS 标头的 `fs_type` 位于 +0x2，哈希类型位于 +0x3（hactool 的结构交换了名称）； 8 字节段计数器的使用方式相反。
<a id="from-a-romfs"></a>
### 来自 RomFS

NCA 部分在标题密钥下是 AES-128-CTR（计数器：该部分的 CTR 值和 `offset >> 4` 大端），因此任何范围都单独解密。 `tools/switch/romfs_read.py` 从容器中的 4.2 GB RomFS 中行走、grep 并提取，除非标头的大小字段读取为 `0x50`，否则首先显示错误的密钥、偏移量或计数器。 hactool 在 34 个十六进制数字的 `prod.keys` 行上中止，并在缺少表的稀疏文件上在 `--listromfs` 上出现段错误。
<a id="naming-everything-first"></a>
## 首先命名所有内容

零售 Unity 游戏有两个独立的命名层：

- IL2CPP 元数据、C# 表面：`global-metadata.dat` (romfs `Data/Managed/Metadata`) 和同一构建的可执行文件为 Il2CppDumper 提供了每个类和方法 RVA。
- C++ RTTI，本机表面：`type_info` 名称指针和 vtable `type_info` 指针是普通重定位。 `tools/switch/rtti_names.py`在BDSP中找到279个`nn::pia`类和2269个虚方法，在剑／盾中找到252个和2036个。

所属类（`LocalProtocol` 或 `LanProtocol`）告诉 LDN 会话密钥源自几乎相同的 LAN 会话密钥。带有孔的 vtable 是一个多重继承组：孔是下一个子对象的顶部偏移量和类型信息。
<a id="a-constant-only-in-the-metadata"></a>
## 仅在元数据中的常量

普通 `[Serializable]` C# 类（不是 `ScriptableObject`）的常量 `byte[]` 默认值由其构造函数使用 `RuntimeHelpers.InitializeArray` 写入静态字段
`<PrivateImplementationDetails>`，其字节仅存在于 `global-metadata.dat` 的字段默认值表中。构造函数的 ADRP/LDR 对命名一个元数据使用槽，解析为
`Field$<PrivateImplementationDetails>.<HEX>`，数据的SHA-1；按字段名称读取值并通过哈希进行验证。 BDSP的16字节游戏密钥种子就是这样存储的。本机 C++ 常量位于 rodata 中，通过交叉引用找到。
<a id="check-which-version-you-dumped"></a>
## 检查你转储的版本

基础游戏和更新是单独的 NSP。 BDSP的基础定义了24个网络消息类别，1.3.0定义了65个； `PosData` 从 `Vector3 pos, short rotY` 变为 `ushort posX, ushort posZ, short rotY`（16 字节到 6），`JoinData` 获得了两个字段并失去了对齐，因此基址转储布局将捕获解码为看似合理的废话。检查：

- `strings global-metadata.dat | grep` 对于只有一个版本的类：BDSP 的基础有 `NetDataTradeStandbyData`（由更新删除）并且缺少 `NetPlayerNameData`（已添加；1.3.0 的元数据为 12,496,504 字节）。
- 将捕获的长度除以结构大小：72 字节的点列表是 6 个点中的 12 个，而不是 16 字节的点。

常量仍然存在（BDSP 的基本元数据密钥种子解密了来自更新游戏机的 674 个数据包中的 674 个）；重新阅读捕获尚未确认的任何结构。
<a id="reading-a-game-updates-romfs"></a>
## 读取游戏更新的 RomFS

更新的 RomFS 是修补基础游戏的 BKTR 部分。最后的两个表，在该节的普通 CTR 下，在由偏移量（hactool `bktr.c`）键控的 0x4000 字节存储桶中，决定每个字节：重定位表将虚拟范围映射到更新的节或基本 RomFS（`is_patch`）；子节表为更新的每个物理范围提供一个计数器值，替换节计数器的字节 4..8。 `tools/switch/bktr_read.py` 将两者组合成一个可查找部分：

    ./.venv/bin/python tools/switch/bktr_read.py UPDATE.nsp --base BASE.nsp \
        --extract /Data/Managed/Metadata/global-metadata.dat

基础内容必须是更新所对应游戏的 Program NCA，且带有 CTR RomFS 分区；XCI 的更新分区包含系统标题的 Program NCA，找到的第一个 Program NCA 可能属于其中之一。

<a id="finding-callers"></a>
## 寻找来电者

扫描 `bl` 的图像字（`100101` 加上带符号的 26 位字偏移量）和尾部调用 `b` (`000101`)，单行 C# 转发器将其编译为：
`ANetData<SelectData>$$SendReliableData` 和 `ANetData<TransitionData>$$SendReliableData` 没有
`bl` 呼叫者和九个 `b` 呼叫者，位于联合房间的上下文菜单中。没有分支的方法可以是通过 ADRP/ADD 对 (`arm64_xref.py`) 注册为 `Action` 的委托，如下所示
`TradeStateModel` 的 `WriteSaveData`、`FirstSave` 和 `SendTradeState`。

陷阱：`arm64_xref.function_start` 通过 `udf` 填充返回，并可以将存储记入前面的函数（检查序言）；将函数限制为“进入后的 N 个字节”，经过其 `ret` 进入下一个函数体； `mov w0, #0x80` 是 ARM64 上的 ORR 立即数，对于字节模式扫描不可见，因此使用反汇编器对常量进行解码。
<a id="calling-into-nnsdk"></a>
## 调用nnSdk

对 nnSdk 的调用会经过一个由 JUMP_SLOT 重定位填充的 GOT 槽，命名该符号：交叉引用槽 (`tools/switch/nso_imports.py`)，然后计算其一个 PLT 存根的调用者。
<a id="the-tools"></a>
## 工具

读取器位于 `pokeldn.switch`（容器与 NCA、RomFS、NSO、Trinity 包）；工具是其命令行入口，需要游戏文件的程序通过它读取用户自行转储的内容。除上述 `xci_read.py`、`romfs_read.py`、`bktr_read.py` 和 `rtti_names.py` 外，全部离线：

    tools/switch/nso_read.py     an NSO's three segments decompressed (pure-Python LZ4) at their
                                 memory offsets: a file offset is an address
    tools/switch/nso_relocs.py   MOD0 -> dynamic -> relative relocations, RELA and RELR. Vtable slots
                                 fill at load time, so "who points here" is a relocation question;
                                 modern titles use RELR, where a RELA-only reader finds nothing
    tools/switch/arm64_xref.py   ADRP(+ADD|+LDR) cross-references, BL call graph, function starts
    tools/switch/arm64_dis.py    capstone window disassembly
