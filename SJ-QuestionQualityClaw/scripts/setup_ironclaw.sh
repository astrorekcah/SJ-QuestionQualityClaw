#!/bin/bash
# Set up IronClaw to work with SJ-QuestionQualityClaw
#
# This configures IRONCLAW_HOME to point to our ironclaw/ directory
# so IronClaw loads our IDENTITY.md and discovers our skills.
#
# Usage: source scripts/setup_ironclaw.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IRONCLAW_DIR="$PROJECT_DIR/ironclaw"

# Check IronClaw is installed
if ! command -v ironclaw &> /dev/null; then
    echo "ERROR: ironclaw not found. Install from https://github.com/nearai/ironclaw"
    exit 1
fi

echo "IronClaw $(ironclaw --version 2>&1 | head -1)"
echo ""

# Set IRONCLAW_HOME
export IRONCLAW_HOME="$IRONCLAW_DIR"
echo "IRONCLAW_HOME=$IRONCLAW_HOME"

# Verify identity loads
if [ -f "$IRONCLAW_DIR/workspace/IDENTITY.md" ]; then
    echo "✅ Identity: $(head -1 "$IRONCLAW_DIR/workspace/IDENTITY.md")"
else
    echo "⚠ No IDENTITY.md found"
fi

# Count skills
SKILL_COUNT=$(find "$IRONCLAW_DIR/skills" -name "SKILL.md" 2>/dev/null | wc -l)
echo "✅ Skills: $SKILL_COUNT discovered"

# List skills
find "$IRONCLAW_DIR/skills" -name "SKILL.md" -exec dirname {} \; | \
    xargs -I {} basename {} | sort | while read skill; do
    echo "   - $skill"
done

echo ""
echo "To use IronClaw backend in SJQQC:"
echo "  export IRONCLAW_HOME=$IRONCLAW_DIR"
echo "  python scripts/run.py process questions/file.json \"feedback\""
echo ""
echo "IronClaw will be auto-detected as the LLM backend."
