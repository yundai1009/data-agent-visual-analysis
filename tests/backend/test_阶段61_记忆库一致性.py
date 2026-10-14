# -*- coding: utf-8 -*-
"""阶段 61 · Task 1：embedding 指纹硬闸 + 多 worker 拦截 + /healthz 可观测。

为什么必须硬闸（决策 D4/D5/D8）：
  · 换 embedding 模型后旧向量/新查询不同源——维度不同→查询抛异常被吞（检索恒空）；
    维度相同但换了供应商→**不报错、结果全是噪声**（最难发现的劣化）。
  · chromadb 是嵌入式单进程库，多 worker 并发写会破坏索引，失败一样只记 warning
    （监控全绿，只是记忆慢慢不准）。
  · 记忆故障原来只有 warning，看不见 → /healthz(memory) 段把它变可观测，
    但刻意不拉低 status（记忆是非关键依赖）。

决策修正（预检实证，压过计划原文）：
  [修正4] 指纹必须含「向量化文本模板」——D3 把向量化输入改成只用「需求」，
          老库是旧模板向量，不带这个字段就无闸门。
  [修正5] 校验指纹 必须连「端点」一起比，且端点要归一化尾部斜杠。
"""

from __future__ import annotations

import os
import sys
import threading

import pytest

from api.main import _解析workers, _启动安全自检
from config.settings import EnvConfig
from 后端_核心.agent import memory


@pytest.fixture(autouse=True)
def _隔离环境(monkeypatch, tmp_path):
    """每个用例独立隔离：

    1. 切到 AUTH_ENABLED=false + 钉死回环（同 test_startup_safety.py 的做法）。
    2. 把记忆库重定向到用例级临时目录（本轮不准动 tests/conftest.py，
       这里按用例隔离，不污染项目 data/ 目录）。
    3. 重置 memory 模块级单例（_client / _collection），否则 chroma 单例跨用例泄漏；
       _记忆状态 也换新，保证「最近错误」不串用例。
    """
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr(EnvConfig, "HOST", "127.0.0.1")
    monkeypatch.setattr(memory, "_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(memory, "_client", None)
    monkeypatch.setattr(memory, "_collection", None)
    monkeypatch.setattr(memory, "_记忆状态", {"最近错误": ""})


def _argv(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)


def _有key(monkeypatch):
    """[M2] 让第 6 道防线真的执行指纹校验。

    阶段 61 修复 M2 后：embedding Key 为空（本仓默认值就是空）时第 6 道按
    「记忆链路未启用」**跳过**校验。所以凡是想验证指纹闸门行为的用例，
    都必须先把 Key 配成一个真值，否则测的是「跳过」而不是闸门本身。
    """
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "sk-test-real-looking-key", raising=False)


# ═══════════════════════════════════════════════════════════════
# 一、当前指纹：四项结构[修正4] + 端点归一化[修正5]
# ═══════════════════════════════════════════════════════════════


def test_当前指纹_含模板与归一化端点(monkeypatch):
    """[修正4] 指纹必须含「向量化文本模板」字段——D3 改了向量化输入，
    老库是不同源的旧模板向量，不带这个字段 = 启动闸门对 D3 的改动完全没感觉。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://emb.example.com/v1/", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "text-embedding-v2", raising=False)
    指纹 = memory.当前指纹()
    assert set(指纹) == {"embedding模型", "embedding端点", "向量化文本模板"}
    assert 指纹["embedding模型"] == "text-embedding-v2"
    # [修正5] 端点归一化尾部斜杠：多一个 '/' 不该被算成换了语义空间
    assert 指纹["embedding端点"] == "https://emb.example.com/v1"
    assert 指纹["向量化文本模板"] == "需求"


# ═══════════════════════════════════════════════════════════════
# 二、校验指纹：纯函数，「不一致拒绝、老库放行」
# ═══════════════════════════════════════════════════════════════


def test_指纹一致_放行(monkeypatch):
    """[重写·原审查 Q6] 原用例同义反复：把 当前指纹() 的值赋回自身再比，怎么写都过。

    现在先造一个**确实不同**的库内值证明 校验指纹 真在比（会抛），再把库内值改成
    与当前指纹逐字段相同，断言这时才放行。少任何一半，这个测试都是废的。
    """
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "m1", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://emb.example.com/v1", raising=False)
    当前 = memory.当前指纹()

    # 先证「真在比」：库内值与当前不同 → 必须抛
    库内 = dict(当前)
    库内["embedding模型"] = "m-另一个"
    with pytest.raises(RuntimeError, match="embedding 模型与当前配置不一致"):
        memory.校验指纹(库内, 当前)

    # 再证「相同就放行」：库内值逐字段等于当前指纹 → 不抛、返回 None
    assert memory.校验指纹(dict(当前), 当前) is None


def test_指纹不一致_模型_拒绝(monkeypatch):
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "m2", raising=False)
    with pytest.raises(RuntimeError, match="embedding 模型与当前配置不一致"):
        memory.校验指纹({"embedding模型": "m1"}, memory.当前指纹())


def test_指纹不一致_端点_拒绝(monkeypatch):
    """[修正5] 端点也要比——只比模型，换同模型的另一家端点（不同语义空间）会漏网。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://new.example.com/v1", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "m1", raising=False)
    记录 = {"embedding模型": "m1", "embedding端点": "https://old.example.com/v1"}
    with pytest.raises(RuntimeError, match="embedding 端点与当前配置不一致"):
        memory.校验指纹(记录, memory.当前指纹())


def test_不一致文案_只给真实可执行的修复路径(monkeypatch):
    """[阶段 61 修复 B3] 报错文案**指向的东西必须真实存在**。

    为什么锁这条：原文案让「指纹不一致 = 拒绝启动 + 唯一修复路径指向一个
    尚不存在的脚本」＝ 运维当场把服务改到起不来，文案却让他跑一条跑不通的命令。
    Task 3 把脚本落地后，禁令就该升级成「提到即必须存在」——否则脚本哪天被
    改名/删掉，文案又会变回一句骗人的话，而这里没有任何东西会红。
    """
    monkeypatch.setattr(memory, "_CHROMA_DIR", str(记忆目录 := "data/chroma_db"))
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "m2", raising=False)
    with pytest.raises(RuntimeError) as 抓:
        memory.校验指纹({"embedding模型": "m1"}, memory.当前指纹())
    文案 = str(抓.value)

    # 文案提到重建脚本 → 脚本必须真的躺在仓库里（不许指向空气）
    if "scripts/重建记忆库.py" in 文案:
        脚本 = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "scripts", "重建记忆库.py",
        )
        assert os.path.isfile(脚本), f"文案让运维跑 {脚本}，但该文件不存在"
    # 真实可执行：给出绝对目录路径 + 明确标注不可逆
    assert os.path.abspath(记忆目录) in 文案
    assert "不可逆" in 文案
    assert "丢失全部长期记忆" in 文案


def test_指纹不一致_模板_拒绝(monkeypatch):
    """[修正4] 旧模板（需求+意图+画像）向量与「只用需求」的查询向量不同源 → 拒绝。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "m1", raising=False)
    记录 = dict(memory.当前指纹())
    记录["向量化文本模板"] = "需求+意图+画像"
    with pytest.raises(RuntimeError, match="向量化文本模板"):
        memory.校验指纹(记录, memory.当前指纹())


def test_端点尾部斜杠_不算不一致():
    """运维把 https://x/v1 改成 https://x/v1/，向量完全可用，不能拦启动。"""
    memory.校验指纹(
        {"embedding模型": "m1", "embedding端点": "https://e.example.com/v1/", "向量化文本模板": "需求"},
        {"embedding模型": "m1", "embedding端点": "https://e.example.com/v1", "向量化文本模板": "需求"},
    )


def test_老库没有指纹字段_放行(monkeypatch):
    """老库没有指纹字段不等于不一致（交给重建脚本处理，不能拦住旧部署启动）。"""
    assert memory.校验指纹(None, memory.当前指纹()) is None
    assert memory.校验指纹({}, memory.当前指纹()) is None
    # 老库只有模型字段（且值相同）、缺端点/模板字段时，缺的字段按「未知」放行
    assert memory.校验指纹({"embedding模型": memory.当前指纹()["embedding模型"]}, memory.当前指纹()) is None


# ═══════════════════════════════════════════════════════════════
# 三、并发硬门槛[修正1] + 异常捕获硬门槛[修正6]
# ═══════════════════════════════════════════════════════════════


def test_记忆锁必须是可重入锁():
    """[修正1·P0] _get_collection 持锁内再调 _get_client；普通 Lock 会永久死锁
    （Task 3 fixture 每次置 None → 6 个集成测试 hang）。"""
    assert isinstance(memory._记忆锁, type(threading.RLock())), (
        "_记忆锁 必须是 threading.RLock()，普通 Lock 会在持锁内重入时永久死锁"
    )


def test_持锁内再取库_不挂死():
    """[修正1·行为版] 模拟 _get_collection 的临界区：持锁内再调 _get_collection。

    用工作线程 + join 超时做 watchdog：若是普通 Lock，这里会一直 hang 住；
    daemon=True 保证断言失败也不会把整个测试进程拖死。
    """
    完成 = {}

    def 工作():
        with memory._记忆锁:
            memory._get_collection()  # 内部：再取一次 _记忆锁 + 建 client/collection
        完成["done"] = True

    t = threading.Thread(target=工作, daemon=True)
    t.start()
    t.join(timeout=20)
    assert 完成.get("done", False), "持锁内重入 _记忆锁 死锁了——_记忆锁 必须是 RLock"
    assert memory._collection is not None


def test_库不存在_走创建路径_不捕漏(monkeypatch):
    """[修正6·P1] chromadb 1.5.9 抛 NotFoundError，旧代码只捕 ValueError →
    首次运行永远建不了库（异常直接被 保存记忆 的 except 吞掉，静默无库）。"""
    from chromadb.errors import NotFoundError

    调用 = {}

    class 假client:
        def get_collection(self, name):
            调用["get"] = name
            raise NotFoundError(f"Collection {name} does not exist")

        def create_collection(self, name, metadata=None):
            调用["create"] = (name, metadata)
            return "假collection"

    monkeypatch.setattr(memory, "_client", 假client())
    monkeypatch.setattr(memory, "_collection", None)

    assert memory._get_collection() == "假collection"
    assert 调用["get"] == memory._COLLECTION_NAME
    # 创建时必须一次性写进当前指纹（模型/端点/模板），否则新库就是「无指纹老库」
    assert 调用["create"][1] == memory.当前指纹()


def test_指纹不一致_不得污染全局collection(monkeypatch):
    """[阶段 61 修复 B1·回归] 校验失败后全局 `_collection` 必须仍是 None。

    原缺陷（已实测复现）：`_get_collection` 先把 `get_collection()` 的返回值赋给
    全局 `_collection`，**之后**才校验指纹。校验抛错时全局已被污染，于是函数开头
    的 fast-path 在第二次调用时直接返回那个不一致的库——硬闸只响一次就被绕过，
    之后的读写全部落在不一致的语义空间里，而且 保存记忆/检索相似记忆 的 except
    会把异常吞成 warning，调用方毫无感知。

    三条断言缺一不可：抛错（闸门仍响）／全局仍是 None（没被污染）／
    第二次调用仍然抛（没被 fast-path 绕过）。
    """
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "当前模型", raising=False)
    库内指纹 = dict(memory.当前指纹())
    库内指纹["embedding模型"] = "老模型"

    class 假collection:
        metadata = 库内指纹
        count_calls = 0

        def count(self):
            假collection.count_calls += 1
            return 7

        def modify(self, metadata=None):
            raise AssertionError("指纹不一致时绝不允许 modify（等于默默改写别人的语义空间）")

    class 假client:
        def get_collection(self, name):
            return 假collection()

        def create_collection(self, name, metadata=None):
            raise AssertionError("库已存在（只是指纹不一致），不该走创建路径")

    monkeypatch.setattr(memory, "_client", 假client())
    monkeypatch.setattr(memory, "_collection", None)

    with pytest.raises(RuntimeError, match="embedding 模型与当前配置不一致"):
        memory._get_collection()
    # 【关键断言】全局没被污染
    assert memory._collection is None, (
        "指纹校验失败后全局 _collection 必须保持 None——"
        "被污染会让 fast-path 绕过硬闸（B1）"
    )
    # 第二次调用必须**再抛一次**：证明 fast-path 真的没被用上
    with pytest.raises(RuntimeError, match="embedding 模型与当前配置不一致"):
        memory._get_collection()
    assert memory._collection is None
    assert 假collection.count_calls == 0, "指纹没过就不该再去 count()"  # 短路顺序：校验在前


def test_空库回填指纹_走modify(monkeypatch):
    """[_get_collection 的 else 回填分支·原零覆盖] 已有库 + count()==0 → modify 写指纹。

    为什么这条分支要覆盖：空库直接改写指纹、无数据可损失，是「自动修复」的唯一路径；
    它以前一行测试都没有，改坏了（少写字段 / 不写 / 写错时机）只能等线上空库才暴露。
    这里断言 modify 收到的是**完整**当前指纹（模型+端点+模板三项齐全）。
    """
    调用 = {}

    class 假collection:
        def __init__(self, metadata):
            self.metadata = metadata

        def count(self):
            return 0

        def modify(self, metadata=None):
            调用["modify"] = metadata
            self.metadata = metadata

    class 假client:
        def get_collection(self, name):
            return 假collection({})  # 老库：metadata 里没有任何指纹字段

        def create_collection(self, name, metadata=None):
            raise AssertionError("库已存在，不该走创建路径")

    monkeypatch.setattr(memory, "_client", 假client())
    monkeypatch.setattr(memory, "_collection", None)

    col = memory._get_collection()
    assert 调用["modify"] == memory.当前指纹()
    assert set(调用["modify"]) == {"embedding模型", "embedding端点", "向量化文本模板"}
    # 校验通过后才回填全局（与 B1 同一个不变量）
    assert memory._collection is col


def test_非空库不回填_也不modify(monkeypatch):
    """对照组：已有指纹且 count()>0 时**不许** modify（那等于偷改语义空间）。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "m1", raising=False)
    指纹 = memory.当前指纹()

    class 假collection:
        metadata = 指纹

        def count(self):
            return 42

        def modify(self, metadata=None):
            raise AssertionError("非空库不许改写指纹")

    class 假client:
        def get_collection(self, name):
            return 假collection()

    monkeypatch.setattr(memory, "_client", 假client())
    monkeypatch.setattr(memory, "_collection", None)

    assert memory._get_collection() is not None
    assert memory._collection is not None
    assert memory._collection.metadata == 指纹


# ═══════════════════════════════════════════════════════════════
# 四、启动硬闸：workers 解析 + 拒绝启动通道
# ═══════════════════════════════════════════════════════════════


def test_解析workers_空格与等号与缺省(monkeypatch):
    _argv(monkeypatch, ["uvicorn", "api.main:app", "--workers", "4"])
    assert _解析workers() == 4
    _argv(monkeypatch, ["uvicorn", "api.main:app", "--workers=8"])
    assert _解析workers() == 8
    _argv(monkeypatch, ["uvicorn", "api.main:app", "--port", "8000"])
    assert _解析workers() == 1
    _argv(monkeypatch, ["uvicorn", "api.main:app", "--workers", "abc"])
    assert _解析workers() == 1  # 非法值保守当 1：宁可少拦也不错拦


def test_解析workers_非uvicorn进程_不当多worker(monkeypatch):
    """[阶段 61 修复 M1·回归] 只有 argv 里真有 uvicorn 启动痕迹才解析 --workers。

    为什么必须锁这条：`sys.argv` 是**进程级**全局量，pytest 进程的 argv 就是 pytest
    的参数。装了 pytest-parallel（它的开关恰好也叫 `--workers`）或手写
    `pytest tests/backend --workers 4` 时，旧实现会误判成「多 worker 启动」，
    于是**每个 TestClient 用例**都在 lifespan 里被「安全拒绝启动」，而且报错指向
    chromadb/向量记忆，跟真实故障毫无关系——排查成本极高（本轮就是从这种
    「测试莫名大面积红」里发现的）。

    对照组：uvicorn 形态（可执行文件或 `python -m uvicorn`）必须照常解析，
    否则第 5 道防线形同虚设。
    """
    # pytest 自己的 argv 里带 --workers → 按 1 处理（= 不拦）
    _argv(monkeypatch, ["pytest", "--workers", "4"])
    assert _解析workers() == 1
    _argv(monkeypatch, ["pytest", "tests/backend", "-n", "4", "--workers=8"])
    assert _解析workers() == 1
    # 普通脚本 argv（无 uvicorn 痕迹）同样按 1 处理
    _argv(monkeypatch, [os.path.join("C:", "Python", "python.exe"), "-m", "pytest", "--workers", "4"])
    assert _解析workers() == 1
    # 对照组：uvicorn 形态照常解析（不能因为门禁把第 5 道防线写废）
    _argv(monkeypatch, [os.path.join("C:", "Python", "Scripts", "uvicorn.exe"), "--workers", "4"])
    assert _解析workers() == 4
    _argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--workers", "4"])
    assert _解析workers() == 4


def test_多worker_拒绝启动_不受门禁影响(monkeypatch):
    """门禁只挡「非 uvicorn 形态」，真 uvicorn 多 worker 仍必须拒绝启动（回归锁）。"""
    _argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--workers", "4"])
    with pytest.raises(RuntimeError, match="向量记忆"):
        _启动安全自检()


def test_多worker_拒绝启动(monkeypatch):
    _argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--workers", "4"])
    with pytest.raises(RuntimeError, match="向量记忆"):
        _启动安全自检()


def test_多worker_文案只敢叫尽力而为(monkeypatch):
    """闸门只能解析 CLI（uvicorn.run(workers=N) / UVICORN_WORKERS / gunicorn 都能绕过）。
    文案必须如实写清楚这三条绕过路径，不许宣称绝对拦截。"""
    _argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--workers", "4"])
    try:
        _启动安全自检()
    except RuntimeError as exc:
        文案 = str(exc)
    else:
        raise AssertionError("--workers 4 必须拒绝启动")
    assert "尽力而为" in 文案
    assert "uvicorn.run(workers=N)" in 文案
    assert "UVICORN_WORKERS" in 文案
    assert "gunicorn" in 文案


def test_单worker_放行(monkeypatch):
    _argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--workers", "1"])
    _启动安全自检()


def test_指纹不一致_走安全拒绝启动通道(monkeypatch):
    """指纹不一致 → 走现有「安全拒绝启动」RuntimeError 通道（与 AUTH 闸门同一条路）。"""
    _argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1"])
    _有key(monkeypatch)  # [M2] Key 为空时第 6 道按「记忆未启用」跳过校验，这里要真的校验

    def 假校验():
        raise RuntimeError("向量记忆库的embedding 模型与当前配置不一致：库内 'a'，当前 'b'。")

    monkeypatch.setattr(memory, "校验记忆库一致性", 假校验)
    with pytest.raises(RuntimeError, match="安全拒绝启动"):
        _启动安全自检()


def test_记忆库打不开_不拦启动(monkeypatch):
    """记忆是可降级依赖：打开库本身失败（OSError 等）要让服务起来，只是记忆不可用。"""
    _argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1"])
    _有key(monkeypatch)

    def 假校验():
        raise OSError("磁盘只读")

    monkeypatch.setattr(memory, "校验记忆库一致性", 假校验)
    _启动安全自检()  # 不应抛


def test_未配置Key_跳过指纹校验_不拦启动(monkeypatch):
    """[阶段 61 修复 M2·回归] embedding Key 为空 → 第 6 道跳过校验，不拒绝启动。

    为什么必须这样：第 5 道防线的自救建议②是「清空 embedding Key 让记忆整体
    不读写」，而指纹里**不含** Key（含 Key 会把轮换密钥误判成换了模型）。
    旧实现下这条建议自相矛盾——清空 Key 后指纹回落到 LLM_BASE_URL + 默认模型，
    用户反而被第 6 道拒绝启动，只能删库。Key 为空时记忆链路 100% 不读写，
    不存在新旧语义空间冲突，硬拦没有意义。
    """
    _argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1"])
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "", raising=False)

    def 假校验():
        raise AssertionError("Key 未配置时不该做指纹校验（记忆链路没启用）")

    monkeypatch.setattr(memory, "校验记忆库一致性", 假校验)
    _启动安全自检()  # 不应抛


def test_未配置Key_占位符_同样跳过指纹校验(monkeypatch):
    """占位符 Key（your_llm_api_key / sk-xxx…）等同未配置——它们在请求时会 401，
    等于记忆不可用；这时硬拦指纹只会让「没配 Key」的人连服务都起不来。"""
    _argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1"])
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "your_llm_api_key", raising=False)

    def 假校验():
        raise AssertionError("占位符 Key 下不该做指纹校验")

    monkeypatch.setattr(memory, "校验记忆库一致性", 假校验)
    _启动安全自检()  # 不应抛


# ═══════════════════════════════════════════════════════════════
# 五、/healthz 可观测：增 memory 段，顶层 status 不变
# ═══════════════════════════════════════════════════════════════


def _取healthz():
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as c:
        响应 = c.get("/healthz")
    assert 响应.status_code == 200
    return 响应.json()


def test_healthz_暴露记忆段(monkeypatch):
    monkeypatch.setattr(memory, "记忆状态", lambda: {"ok": True, "条数": 12, "模型": "m1"})
    响应体 = _取healthz()
    assert 响应体["memory"]["条数"] == 12
    # 顶层旧字段一个不能少（回归锁：healthz 的老契约不能被 memory 段破坏）
    assert 响应体["status"] in ("ok", "degraded")
    assert "db_backend" in 响应体 and "db_ok" in 响应体


def test_healthz_记忆故障不拉低status(monkeypatch):
    """记忆是非关键依赖：坏了要看得见，但不能把整个实例从负载均衡摘掉。"""
    monkeypatch.setattr(memory, "记忆状态", lambda: {"ok": False, "原因": "collection 不存在"})
    响应体 = _取healthz()
    assert 响应体["memory"]["ok"] is False
    assert 响应体["status"] == "ok"


def test_healthz_不是协程_避免阻塞事件循环():
    """[阶段 61 修复 M3·回归锁] /healthz 必须是同步 def（由 Starlette 丢线程池）。

    为什么锁这条：路由体里没有任何 await，却全是阻塞 IO（sqlite/mysql 的
    connect+execute、chroma 的 `col.count()`）。写成 `async def` 就等于让 FastAPI
    在**事件循环线程**里直接执行它们——探活一卡，全站所有接口一起卡。
    本项目已经为此付出过代价：开发日志 docs/开发日志/项目开发日志.md:4536-4537
    记录 /healthz 把接口从 2241ms 拖到 2.7s（:4674、:4716 是同一条线的后续）。

    断言用 inspect：coroutinefunction 为 True 就说明又写回 async def 了。
    """
    import inspect

    import api.main as 主模块

    assert not inspect.iscoroutinefunction(主模块.healthz), (
        "/healthz 不能是 async def：体内无 await 却是纯阻塞 IO，"
        "会在事件循环里同步执行拖垮全站（M3）"
    )


# ═══════════════════════════════════════════════════════════════
# 六、阶段 61 审查修复（B2/B4/M4）：只读语义与 ok 语义定死
# ═══════════════════════════════════════════════════════════════


def test_校验一致性_目录不存在_一个字节都不写盘(monkeypatch):
    """[阶段 61 修复 B2] 启动自检自称「只读不写盘」就真得只读。

    原缺陷（已实测）：函数直接调 `_get_client()`，而 `chromadb.PersistentClient`
    在 rust 层就会创建数据目录——空目录上调用一次就多出 data/chroma_db；桌面版
    cwd=%APPDATA%，等于把启动探活写进用户目录。docstring 写着「只读不写盘」，
    实现却每次启动都写盘。

    这里锁两条：返回「未创建」，且目录**仍然不存在**（连 mkdir 都不能有）。
    """
    不存在的目录 = os.path.join(str(memory._CHROMA_DIR), "还没建过")
    monkeypatch.setattr(memory, "_CHROMA_DIR", 不存在的目录)

    结果 = memory.校验记忆库一致性()

    assert 结果["ok"] is True
    assert 结果["库"] == "未创建"
    assert 结果["条数"] == 0
    assert "尚未创建" in 结果["原因"]
    # 【关键断言】探活没有在磁盘上留任何东西
    assert os.path.isdir(不存在的目录) is False


def test_校验一致性_键集合一致(monkeypatch):
    """[M4] 所有返回分支的键集合必须一致——消费者不该写防御式 .get()。

    做法：真库（目录已存在 + 空 collection）与未创建（目录不存在）两条路径各调一次，
    比键集合。早退/未创建分支少了任何键，/healthz 的序列化就会缺字段。
    """
    未创建键 = set(memory.校验记忆库一致性().keys())

    os.makedirs(memory._CHROMA_DIR, exist_ok=True)  # 目录存在、collection 还没建
    monkeypatch.setattr(memory, "_client", None)
    未建库键 = set(memory.校验记忆库一致性().keys())

    assert 未创建键 == 未建库键
    assert {"ok", "库", "模型", "条数", "指纹一致", "原因"} <= 未建库键


def test_记忆状态_未创建_算可读(monkeypatch):
    """[阶段 61 修复 B4] 全新部署（记忆库还没建）memory.ok 必须是 True。

    为什么：原来这里是 NotFoundError → ok=False + 原因「记忆库不可用：
    Collection [agent_memories] does not exist」。记忆还没建是**正常状态**，
    却让 /healthz.memory.ok=False——① 与 校验记忆库一致性 的 ok=True/未创建
    自相矛盾；② 按 memory.ok 配的告警在全新部署上 100% 永久误报。
    顺带锁「这次调用没建库」：探活不该有磁盘副作用。
    """
    不存在的目录 = os.path.join(str(memory._CHROMA_DIR), "还没建过")
    monkeypatch.setattr(memory, "_CHROMA_DIR", 不存在的目录)

    状态 = memory.记忆状态()

    assert 状态["ok"] is True
    assert 状态["库"] == "未创建"
    assert 状态["条数"] == 0
    assert "首次写入时创建" in 状态["原因"]
    assert 状态["指纹一致"] == "未知（库未创建，无指纹可比）"
    assert os.path.isdir(不存在的目录) is False  # 探活不写盘


def test_记忆状态_目录在但库没建_也算未创建(monkeypatch):
    """B4 的另一条路径：目录在（老数据目录残留）、collection 没建 → 同样未创建。

    这条走的是 chromadb 的 NotFoundError 分支，与上面的「目录都没建」是两码事：
    老部署清空过 collection、或换 chroma 版本后目录结构变了，都会落到这里。
    """
    from chromadb.errors import NotFoundError

    os.makedirs(memory._CHROMA_DIR, exist_ok=True)  # 目录在

    class 假client:
        def get_collection(self, name):
            raise NotFoundError(f"Collection {name} does not exist")

    monkeypatch.setattr(memory, "_client", 假client())

    状态 = memory.记忆状态()
    assert 状态["ok"] is True
    assert 状态["库"] == "未创建"
    assert 状态["条数"] == 0


def test_记忆状态_库真打不开_才ok为False(monkeypatch):
    """反向锁：ok=False 只留给「真打不开」（磁盘满/权限/锁文件/索引损坏）。"""
    os.makedirs(memory._CHROMA_DIR, exist_ok=True)

    class 假client:
        def get_collection(self, name):
            raise OSError("磁盘空间不足")

    monkeypatch.setattr(memory, "_client", 假client())

    状态 = memory.记忆状态()
    assert 状态["ok"] is False
    assert "磁盘空间不足" in 状态["原因"]
    # 键集合与其它分支保持一致（[M4]）
    assert "指纹一致" in 状态


def test_记忆状态_老库缺指纹字段_不许报True(monkeypatch):
    """[M4] 老库没有指纹字段 → 指纹一致 = "未知（…）"，不能报 True。

    为什么：`校验指纹` 对缺字段是「未知放行」的，一个字段都没比过；报 True 等于
    告诉运维「闸门在工作」——这是主动误导（真出事时正是「闸门看起来绿着」）。
    """
    os.makedirs(memory._CHROMA_DIR, exist_ok=True)
    指纹 = memory.当前指纹()

    class 假collection:
        metadata = {"embedding模型": 指纹["embedding模型"]}  # 老库：只有模型，缺端点/模板

        def count(self):
            return 5

    class 假client:
        def get_collection(self, name):
            return 假collection()

    monkeypatch.setattr(memory, "_client", 假client())

    状态 = memory.记忆状态()
    assert 状态["ok"] is True  # 可读 = 健康
    assert 状态["库"] == "已存在"
    assert 状态["条数"] == 5
    assert 状态["指纹一致"] == "未知（老库无指纹，缺字段按未知放行）"
    assert "缺少指纹字段" in 状态["原因"]
    assert 状态["指纹一致"] is not True


def test_记忆状态_指纹不一致_可读但指纹不一致(monkeypatch):
    """ok 与 指纹一致 是两个正交的键：库可读（ok=True）≠ 语义空间同源（指纹一致=False）。"""
    os.makedirs(memory._CHROMA_DIR, exist_ok=True)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "当前模型", raising=False)

    class 假collection:
        metadata = dict(memory.当前指纹(), **{"embedding模型": "老模型"})

        def count(self):
            return 3

    class 假client:
        def get_collection(self, name):
            return 假collection()

    monkeypatch.setattr(memory, "_client", 假client())

    状态 = memory.记忆状态()
    assert 状态["ok"] is True
    assert 状态["指纹一致"] is False
    assert "embedding 模型与当前配置不一致" in 状态["原因"]
