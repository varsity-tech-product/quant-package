"""频繁提交帮助函数。

这个仓库刻意维护**大量小颗粒度的 commit**：每完成一个小步骤（写一个函数、
补一段文档、加一个样例）就调一次 ``commit()``。这样 git 历史能清晰反映
每一步增量，也便于回滚到任意中间状态。

用法::

    from quantkit.git_commit import commit
    commit("feat: add gateway client skeleton")
    commit("docs: explain panel field mapping", paths=["reference/data_service.md"])

也可以直接当脚本用::

    python -m quantkit.git_commit "feat: something" path/to/file
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 仓库根目录 = 本文件上两级（quantkit/git_commit.py -> quant-package/）
REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def commit(message: str, paths: list[str] | None = None, *, allow_empty: bool = False) -> bool:
    """暂存并提交一次改动。

    Args:
        message: commit message。
        paths: 要 add 的路径列表；None 表示 ``git add -A``（全部）。
        allow_empty: 没有改动时是否仍创建一个空 commit。

    Returns:
        True 表示成功创建了 commit；False 表示没有改动且未允许空提交。
    """
    if paths:
        _run(["git", "add", "--", *paths])
    else:
        _run(["git", "add", "-A"])

    # 没有暂存改动时，diff --cached --quiet 返回 0
    staged = _run(["git", "diff", "--cached", "--quiet"])
    if staged.returncode == 0 and not allow_empty:
        return False

    args = ["git", "commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    result = _run(args)
    if result.returncode != 0:
        raise RuntimeError(f"git commit failed: {result.stderr.strip()}")
    return True


def commit_count() -> int:
    """返回当前分支的 commit 总数。"""
    result = _run(["git", "rev-list", "--count", "HEAD"])
    return int(result.stdout.strip() or "0")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m quantkit.git_commit <message> [path ...]", file=sys.stderr)
        return 2
    message = argv[0]
    paths = argv[1:] or None
    created = commit(message, paths)
    print(f"{'committed' if created else 'nothing to commit'} (total={commit_count()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
