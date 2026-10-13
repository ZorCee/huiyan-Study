#!/usr/bin/env bash
# 清理回归测试产物。只生成、不自动执行；需要时人工运行：
#   bash backend/scripts/regression/cleanup.sh            # 只列出将删除的内容
#   bash backend/scripts/regression/cleanup.sh --yes      # 真正删除
# 只删除测试产物目录和独立的测试库文件，不碰任何业务数据库。
set -euo pipefail
cd "$(dirname "$0")/../.."

TARGETS=(
  "reports/regression"
  "data/regression_test.db"
)

for t in "${TARGETS[@]}"; do
  [ -e "$t" ] && echo "将删除: backend/$t"
done

if [ "${1:-}" != "--yes" ]; then
  echo "未删除任何内容。确认后加 --yes 重新运行。"
  exit 0
fi

for t in "${TARGETS[@]}"; do
  rm -rf -- "$t"
done
echo "已清理。"
