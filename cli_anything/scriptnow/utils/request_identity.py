"""一次提交的**原请求身份**：怎么产生，以及为什么可以这样产生。

问题（2B-1 场次 / 2B-2 章节 / R2-C 蓝图）
-----------------------------------------
服务端按「原请求身份」找回执，身份就是 `idempotency_key`。旧实现每次调用生成
`cli-scene-propose-<time_ns>` / `cli-chapter-propose-<time_ns>` —— 看着像幂等键，
实际上换一次调用就换一个身份。于是"平台已保存、响应丢了再重试"必然拿不到原结果：
要么新建一条内容相同的候选，要么直接撞上已经消费掉的一次性审阅凭证。
**换一次调用就换身份，就不能宣称支持跨调用恢复。**

R2-C 的蓝图是同一个病：`script propose <作品号> blueprint` 的 `idempotency_key` 一直是
`cli-script-propose-blueprint-<time_ns>`，平台侧那条恢复优先的
`POST /script/projects/{pid}/blueprints/propose` 因此**永远命中不了回执** ——
端点有回执表、CLI 却每调一次换一个身份，恢复链在接缝上断掉。

做法
----
身份 = `sha256(规范化(项目, 单元, 提交内容, 审阅凭证))` 的前 40 位十六进制。
每条派生函数各有一个命名空间，规则同形、命名空间不同：

* `scene`（2B-1）→ `cli-scene-propose-`，单元键名 `scene_id`，内容是 `blocks`；
* `chapter`（2B-2）→ `cli-chapter-propose-`，单元键名 `chapter_id`，内容是 `blocks`；
* `script blueprint`（R2-C）→ `cli-script-blueprint-propose-`，**没有单元键** --
  规划候选的作用域是整个项目（`resource_id = project_id`），提交内容是 `anchors`。

为什么是**派生**而不是每次新铸
------------------------------
同一次人工授权的同一次提交，无论调用几次，派生出的是同一个身份 ⇒ 丢响应的重试
自动收敛到同一次提交，服务端把原候选还回来。这与仓库既有先例一致：storyboard
propose 也把 `(project_id, source_id, script)` 一起哈希成稳定身份，而不是用
时间戳（见 `storyboard propose` 的 `proposal_identity`）。

为什么把**审阅凭证**放进哈希 —— 这正是"不靠内容摘要猜请求"的落点
------------------------------------------------------------------
只按正文摘要派生身份会撞上一个分不开的歧义：同一份正文既可能是**这次提交的重试**
（该拿回旧候选），也可能是**一次内容恰好相同的新提交**（必须走新的授权，
V11 §8）。加入审阅凭证就把两者分开了 —— 人工授权凭证本身就是"这是一次提交"的
鉴别符：

* 重试 ⇒ 同内容 + **同一枚**凭证 ⇒ 同一身份 ⇒ 拿回原候选（V11 P06：不因工具
  失败重复索取同一决定）。
* 新提交 ⇒ 新的一次人工授权（新凭证），内容相同也**是另一个身份** ⇒ 走正常
  授权，不会命中旧回执绕过人审。
* 同凭证换内容 ⇒ 身份变了，而且服务端本来就会因摘要不匹配拒收 —— 两道都不放行。

凭证是作为 sha256 的**输入**参与的（明文进、摘要出），摘要不可逆 —— 从派生出的身份串
反推不出凭证。这不是新增暴露面：凭证本来就要随 `X-Review-Token` 发给服务端，服务端
`DecisionTokenModel.token_hash` 存的也是它的哈希。派生身份只是**又一个**单向函数值。

⚠️ 哈希**输入字典的键名**也是被哈希的字节：`scene_id` 与 `chapter_id` 不能互相
替换。把两条派生函数合并成一条"通用 `unit_id`"会**改变场次身份的字节**，让 0.4.10
已发出的 `cli-scene-propose-…` 全部对不上。所以这里是几个薄包装共用同一个
`_derived_request_key`，而不是一个带参数名的通用函数。

⚠️ 蓝图那条**没有单元键**，于是前缀成了唯一命名空间。正因如此它写成
`cli-script-blueprint-propose-`（带领域）而**不是** `cli-blueprint-propose-`：
单元键缺失时，若前缀也不带领域，将来小说侧蓝图身份一旦接入就会与前缀共用同一段
命名空间，"同一条身份换了资源"这条冲突判据就失效了。前两条前缀不带领域是**已发出
的字节**（0.4.10 / 0.4.11），改不得；新的这条没有这个包袱，所以按判据本身要求写。

显式出口
--------
`--request-key` / `SCRIPTNOW_REQUEST_KEY` 优先于派生：调用方（例如 dsh）要把
身份真正"持久保留"在自己的重试状态里时用它，CLI 也会把本次用的身份打进输出，
所以这个引用是可取回、可回传的。
"""

from __future__ import annotations

import hashlib
import json


def _canonical(value: object) -> str:
    """与 `utils/review.canonical_content_digest` 同一套规范化（同源同形）。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _derived_request_key(prefix: str, payload: dict[str, object]) -> str:
    """派生这次提交的原请求身份（幂等：同输入必得同串）。

    唯一被各条派生函数共用的部分。**不要**在这里向 `payload` 补字段、改键名或改前缀
    —— 任何一处改动都会静默改变已发出的身份串，重试就再也拿不回原结果。
    """

    identity = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:40]
    return f"{prefix}-{identity}"


def scoped_candidate_request_key(
    *, project_id: str, medium: str, kind: str, content: object,
    execution_token: str,
) -> str:
    """Stable dsh candidate request scoped to one attempt and exact content.

    The bearer token participates only in a digest; the returned key never
    reveals it. A new attempt is a new request even when the text is identical.
    """
    return _derived_request_key(
        f"cli-dsh-{medium}-{kind}",
        {"project_id": project_id, "content": content, "execution_token": execution_token},
    )


def scene_propose_request_key(
    *,
    project_id: str,
    scene_id: str,
    blocks: object,
    review_token: str,
) -> str:
    """派生这次场次提交的原请求身份（幂等：同输入必得同串）。

    ⚠️ 键名 `scene_id` 与前缀 `cli-scene-propose` 是**已发出的字节**（0.4.10 起），
    改动它们就等价于换一次提交 —— 保留原样，不要在 2B-2 里"顺手统一命名"。
    """

    return _derived_request_key(
        "cli-scene-propose",
        {
            "project_id": project_id,
            "scene_id": scene_id,
            "blocks": blocks,
            "review_token": review_token,
        },
    )


def chapter_propose_request_key(
    *,
    project_id: str,
    chapter_id: str,
    blocks: object,
    review_token: str,
) -> str:
    """派生这次章节提交的原请求身份（幂等：同输入必得同串）。

    与场次版**规则同形、命名空间不同**：服务端两侧各有自己的回执表与候选表，
    身份前缀（`cli-chapter-propose`）与单元键名（`chapter_id`）必须能互相区分，
    否则"同一条身份换了资源"这条冲突判据会失效。
    """

    return _derived_request_key(
        "cli-chapter-propose",
        {
            "project_id": project_id,
            "chapter_id": chapter_id,
            "blocks": blocks,
            "review_token": review_token,
        },
    )


def blueprint_propose_request_key(
    *,
    project_id: str,
    anchors: object,
    review_token: str,
) -> str:
    """派生这次蓝图候选提交的原请求身份（幂等：同输入必得同串）。

    与场次/章节两条**规则同形**，差别是这里**没有单元键**：规划候选的作用域是整个
    项目（服务端 `POST /script/projects/{pid}/blueprints/propose` 消费的凭证是
    `resource_kind="blueprint"` + `resource_id=project_id`），提交内容是 `anchors`。
    于是命名空间全由前缀承担 —— 它必须带领域（见模块 docstring 里那段说明），
    否则会把"哪条身份属于哪个领域"这层信息丢掉。

    ⚠️ 前缀 `cli-script-blueprint-propose` 与键名 `anchors` / `review_token` 从本版起
    就是**已发出的字节**：改动它们等于换一次提交，在途的"丢响应重试"从此对不上。
    """

    return _derived_request_key(
        "cli-script-blueprint-propose",
        {
            "project_id": project_id,
            "anchors": anchors,
            "review_token": review_token,
        },
    )
